"""Tests for the Nextcloud Login Flow v2 client (local fake server, no network)."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import ClassVar

import pytest
from PySide6.QtCore import QEventLoop, QTimer

from todo_snake.sync.login_flow import NextcloudLoginFlow


class _LoginFlowHandler(BaseHTTPRequestHandler):
    """A minimal stand-in for Nextcloud's ``/index.php/login/v2`` endpoints."""

    init_status: ClassVar[int] = 200
    init_body: ClassVar[bytes | None] = None
    polls_before_success: ClassVar[int] = 2
    poll_status: ClassVar[int] = 200
    poll_body: ClassVar[bytes | None] = None
    _polls: ClassVar[int] = 0
    _lock: ClassVar[threading.Lock] = threading.Lock()

    def _send(self, code: int, body: bytes = b"") -> None:
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        base = f"http://127.0.0.1:{self.server.server_address[1]}"

        if self.path == "/index.php/login/v2":
            if type(self).init_body is not None:
                self._send(type(self).init_status, type(self).init_body)
                return
            body = json.dumps(
                {
                    "poll": {"token": "tok", "endpoint": f"{base}/login/v2/poll"},
                    "login": f"{base}/login/v2/flow/tok",
                }
            ).encode()
            self._send(type(self).init_status, body)
            return

        if self.path == "/login/v2/poll":
            with type(self)._lock:
                type(self)._polls += 1
                polls = type(self)._polls
            if type(self).poll_body is not None:
                self._send(type(self).poll_status, type(self).poll_body)
                return
            if polls < type(self).polls_before_success:
                self._send(404, b"{}")
                return
            self._send(
                200,
                json.dumps(
                    {
                        "server": "https://cloud.example.com",
                        "loginName": "alice",
                        "appPassword": "s3cret",
                    }
                ).encode(),
            )
            return

        self._send(404, b"{}")

    def log_message(self, *args):  # keep test output clean
        pass


@pytest.fixture()
def login_flow_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _LoginFlowHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    _LoginFlowHandler.init_status = 200
    _LoginFlowHandler.init_body = None
    _LoginFlowHandler.polls_before_success = 2
    _LoginFlowHandler.poll_status = 200
    _LoginFlowHandler.poll_body = None
    _LoginFlowHandler._polls = 0
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def _run_flow(server: str, **kwargs) -> dict:
    """Run one flow to completion (or timeout) and collect the signals."""
    flow = NextcloudLoginFlow(server, poll_interval_ms=10, **kwargs)
    seen: dict = {}
    loop = QEventLoop()
    flow.login_url_ready.connect(lambda url: seen.setdefault("login_url", url))
    flow.credentials_ready.connect(lambda *a: (seen.__setitem__("credentials", a), loop.quit()))
    flow.failed.connect(lambda message: (seen.__setitem__("error", message), loop.quit()))
    flow.start()
    QTimer.singleShot(5000, loop.quit)
    loop.exec()
    return seen


def test_login_flow_provisions_credentials(qapp, login_flow_server):
    seen = _run_flow(login_flow_server)
    assert seen.get("credentials") == ("https://cloud.example.com", "alice", "s3cret")
    assert seen.get("login_url", "").endswith("/login/v2/flow/tok")


def test_login_flow_reports_server_error(qapp, login_flow_server):
    """A server-side rejection must reach the user with the server's message."""
    _LoginFlowHandler.poll_status = 500
    _LoginFlowHandler.poll_body = json.dumps(
        {"message": "Password confirmation is required"}
    ).encode()
    seen = _run_flow(login_flow_server)
    assert "Password confirmation is required" in seen.get("error", "")


def test_login_flow_fails_when_init_is_not_json(qapp, login_flow_server):
    _LoginFlowHandler.init_status = 500
    _LoginFlowHandler.init_body = b"nope"
    seen = _run_flow(login_flow_server)
    assert "500" in seen.get("error", "")


def test_login_flow_rejects_plain_http_remote(qapp):
    flow = NextcloudLoginFlow("http://example.com")
    errors: list[str] = []
    flow.failed.connect(errors.append)
    flow.start()
    assert errors and "localhost" in errors[0]


def test_login_flow_strips_index_php_from_the_server(qapp):
    """A stored base like ``…/index.php`` must not become ``…/index.php/index.php``."""
    flow = NextcloudLoginFlow("https://cloud.example.com/index.php")
    assert flow._server == "https://cloud.example.com"
