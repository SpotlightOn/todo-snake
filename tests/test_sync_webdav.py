"""Tests for the WebDAV transport helpers (no real network)."""

import base64
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from PySide6.QtCore import QUrl

from todo_snake.sync.accounts import SyncAccount, SyncProvider
from todo_snake.sync.webdav import (
    SyncTransportError,
    WebDAVTransport,
    basic_auth_value,
    validate_server_url,
)

VALID_CREDENTIALS = "alice:t0ps3cret"


def test_basic_auth_header():
    assert basic_auth_value("alice", "s3cret") == "Basic YWxpY2U6czNjcmV0"


def test_validate_rejects_plain_http_for_remote_servers():
    with pytest.raises(SyncTransportError):
        validate_server_url("http://example.com")


def test_validate_allows_https_and_localhost_http():
    validate_server_url("https://cloud.example.com")
    validate_server_url("http://localhost:8080")
    validate_server_url("http://127.0.0.1:8000")


def test_validate_rejects_garbage():
    with pytest.raises(SyncTransportError):
        validate_server_url("not-a-url")
    with pytest.raises(SyncTransportError):
        validate_server_url("ftp://example.com")


def test_file_url_building(qapp):
    account = SyncAccount(
        provider=SyncProvider.NEXTCLOUD,
        server_url="https://cloud.example.com/",
        username="alice",
    )
    transport = WebDAVTransport(account)
    assert (
        str(transport._file_url().toEncoded(), "utf-8")
        == "https://cloud.example.com/remote.php/dav/files/alice/todo-snake/todos.json"
    )
    transport._nam.deleteLater()


def test_upload_requires_username(qapp):
    account = SyncAccount(provider=SyncProvider.NEXTCLOUD, server_url="https://x.example.com")
    transport = WebDAVTransport(account)
    with pytest.raises(SyncTransportError):
        transport._file_url()
    transport._nam.deleteLater()


def test_username_is_url_encoded(qapp):
    account = SyncAccount(
        provider=SyncProvider.NEXTCLOUD,
        server_url="https://x.example.com",
        username="alice smith",
    )
    transport = WebDAVTransport(account)
    assert "alice%20smith" in str(transport._file_url().toEncoded(), "utf-8")
    transport._nam.deleteLater()


def test_request_uses_trimmed_credentials():
    account = SyncAccount(username="  alice ", app_password="  t0ps3cret  ")
    transport = WebDAVTransport(account)
    request = transport._request(QUrl("http://127.0.0.1/x"))
    expected = basic_auth_value("alice", "t0ps3cret")
    assert bytes(request.rawHeader("Authorization")) == expected.encode("ascii")
    transport._nam.deleteLater()


# -- live Basic-auth server --------------------------------------------------


class _BasicAuthHandler(BaseHTTPRequestHandler):
    expected = "Basic " + base64.b64encode(VALID_CREDENTIALS.encode()).decode("ascii")

    def _authorized(self) -> bool:
        return self.headers.get("Authorization", "") == self.expected

    def _send(self, code: int, body: bytes = b"") -> None:
        self.send_response(code)
        if code == 401:
            self.send_header("WWW-Authenticate", 'Basic realm="dav"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self):
        if not self._authorized():
            self._send(401)
            return
        self._send(200, b'{"ok": true}')

    def do_PUT(self):
        if not self._authorized():
            self._send(401)
            return
        self._send(201)

    def do_MKCOL(self):
        if not self._authorized():
            self._send(401)
            return
        self._send(201)

    def log_message(self, *args):  # keep test output clean
        pass


@pytest.fixture()
def dav_server():
    """A threaded Basic-auth endpoint on a random localhost port."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _BasicAuthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_sync_with_valid_credentials_succeeds(qapp, dav_server):
    account = SyncAccount(
        provider=SyncProvider.NEXTCLOUD,
        server_url=dav_server,
        username="alice",
        app_password="t0ps3cret",
    )
    transport = WebDAVTransport(account)
    try:
        result = transport.fetch()
        assert result.found is True
        assert result.body == b'{"ok": true}'
        transport.upload(b'{"ok": true}')
    finally:
        transport._nam.deleteLater()


def test_sync_with_invalid_credentials_fails_with_guidance(qapp, dav_server):
    account = SyncAccount(
        provider=SyncProvider.NEXTCLOUD,
        server_url=dav_server,
        username="alice",
        app_password="wrong",
    )
    transport = WebDAVTransport(account)
    try:
        with pytest.raises(SyncTransportError) as excinfo:
            transport.fetch()
        message = str(excinfo.value)
        assert "401" in message
        assert "app password" in message
    finally:
        transport._nam.deleteLater()
