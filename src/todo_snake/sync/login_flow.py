"""Nextcloud Login Flow v2 — browser-based app-password provisioning.

Requiring users to create an app password by hand makes the project unusable
for normal accounts on a hosted Nextcloud (no shell, no ``occ``). Login Flow
v2 is Nextcloud's standard client API for this: the user signs in in the
browser (SSO and 2FA included) and grants access; the server then hands the
client its own fresh app password. The credentials feed the existing HTTP
Basic transport, so nothing else changes.

Flow (developer manual, "Login Flow" → "Login flow v2"):

1. ``POST <server>/index.php/login/v2`` returns a poll token/endpoint and a
   login URL.
2. The login URL is opened in the default browser; the user signs in and
   clicks "Grant access".
3. ``POST <poll endpoint>`` with the token answers ``404`` while the user has
   not finished and ``200`` once it has, carrying
   ``{server, loginName, appPassword}``. The token is valid for 20 minutes and
   the ``200`` is returned exactly once.
"""

from __future__ import annotations

import json
import time

from PySide6.QtCore import QByteArray, QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from todo_snake.sync.webdav import SyncTransportError, clean_server_url, validate_server_url

POLL_INTERVAL_MS = 1000
FLOW_TIMEOUT_S = 20 * 60


class NextcloudLoginFlow(QObject):
    """Drives one Login Flow v2 conversation and emits the resulting token."""

    login_url_ready = Signal(str)
    credentials_ready = Signal(str, str, str)  # server, login name, app password
    failed = Signal(str)

    def __init__(
        self,
        server_url: str,
        parent: QObject | None = None,
        *,
        poll_interval_ms: int = POLL_INTERVAL_MS,
        timeout_s: int = FLOW_TIMEOUT_S,
    ):
        super().__init__(parent)
        self._server = clean_server_url(server_url)
        self._poll_interval_ms = poll_interval_ms
        self._timeout_s = timeout_s
        self._nam = QNetworkAccessManager(self)
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(poll_interval_ms)
        self._poll_timer.timeout.connect(self._poll)
        self._poll_endpoint: str | None = None
        self._poll_token: str | None = None
        self._deadline = 0.0
        self._running = False
        self._reply: QNetworkReply | None = None

    # -- public API ---------------------------------------------------------

    def start(self) -> None:
        """Kick off the flow; failures are reported via ``failed``."""
        try:
            validate_server_url(self._server)
        except SyncTransportError as exc:
            self.failed.emit(str(exc))
            return
        self._running = True
        self._deadline = time.monotonic() + self._timeout_s
        self._reply = self._nam.post(
            self._request(QUrl(f"{self._server}/index.php/login/v2")),
            QByteArray(),
        )
        self._reply.finished.connect(self._on_init_finished)

    def cancel(self) -> None:
        """Stop polling (e.g. the dialog was closed)."""
        self._running = False
        self._poll_timer.stop()
        if self._reply is not None:
            self._reply.abort()

    # -- request/response plumbing ------------------------------------------

    @staticmethod
    def _request(url: QUrl) -> QNetworkRequest:
        request = QNetworkRequest(url)
        request.setRawHeader(b"OCS-APIRequest", b"true")
        request.setRawHeader(b"User-Agent", b"todo-snake-sync")
        request.setRawHeader(b"Content-Type", b"application/x-www-form-urlencoded")
        return request

    def _on_init_finished(self) -> None:
        reply, self._reply = self._reply, None
        if reply is None:
            return
        status = int(reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute) or 0)
        body = bytes(reply.readAll())
        reply.deleteLater()
        if not self._running:
            return
        if status != 200:
            self._fail_from_body(body, status, "Nextcloud did not start the login flow")
            return
        try:
            data = json.loads(body.decode("utf-8"))
            poll = data["poll"]
            self._poll_endpoint = str(poll["endpoint"])
            self._poll_token = str(poll["token"])
            login_url = str(data["login"])
        except (KeyError, TypeError, ValueError) as exc:
            self._failed(f"Unexpected response from Nextcloud: {exc}")
            return
        self.login_url_ready.emit(login_url)
        self._poll_timer.start()

    def _poll(self) -> None:
        if not self._running or self._reply is not None:
            return
        if time.monotonic() > self._deadline:
            self._failed("The Nextcloud login timed out. Please try again.")
            return
        payload = QByteArray(f"token={self._poll_token}".encode())
        self._reply = self._nam.post(self._request(QUrl(self._poll_endpoint)), payload)
        self._reply.finished.connect(self._on_poll_finished)

    def _on_poll_finished(self) -> None:
        reply, self._reply = self._reply, None
        if reply is None:
            return
        status = int(reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute) or 0)
        body = bytes(reply.readAll())
        reply.deleteLater()
        if not self._running:
            return
        if status == 404:
            return  # still waiting for the user to grant access
        if status != 200:
            self._fail_from_body(body, status, "Nextcloud rejected the login flow")
            return
        try:
            data = json.loads(body.decode("utf-8"))
            server = str(data["server"])
            login_name = str(data["loginName"])
            app_password = str(data["appPassword"])
        except (KeyError, TypeError, ValueError) as exc:
            self._failed(f"Unexpected response from Nextcloud: {exc}")
            return
        self._running = False
        self._poll_timer.stop()
        self.credentials_ready.emit(server, login_name, app_password)

    # -- helpers ------------------------------------------------------------

    def _failed(self, message: str) -> None:
        self._running = False
        self._poll_timer.stop()
        self.failed.emit(message)

    def _fail_from_body(self, body: bytes, status: int, prefix: str) -> None:
        """Turn an error response into a readable message for the user."""
        message = ""
        try:
            data = json.loads(body.decode("utf-8"))
            if isinstance(data, dict):
                message = str(data.get("message") or "")
        except ValueError:
            message = ""
        detail = f" (HTTP {status})" if status else ""
        suffix = f": {message}" if message else ""
        self._failed(f"{prefix}{detail}{suffix}")
