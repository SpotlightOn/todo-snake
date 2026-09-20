"""WebDAV transport for Nextcloud.

Uses ``QNetworkAccessManager`` (part of PySide6, no new dependencies) and a
synchronous event-loop pump so the sync manager can run a fetch/merge/upload
cycle in one straight line while still performing real async I/O underneath.

Authentication is HTTP Basic over TLS with a Nextcloud *app password*. Plain
``http://`` URLs are rejected unless the target is the loopback interface
(useful for a local test server).
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

from PySide6.QtCore import QByteArray, QEventLoop, QTimer, QUrl
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from todo_snake.sync.accounts import SyncAccount

_UPLOAD_TIMEOUT_MS = 15_000


class SyncTransportError(RuntimeError):
    """Raised when talking to the sync server fails."""


@dataclass
class FetchResult:
    found: bool
    body: bytes | None


def basic_auth_value(username: str, password: str) -> str:
    import base64

    token = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
    return f"Basic {token}"


def validate_server_url(server_url: str) -> None:
    """Reject non-TLS servers unless they run on the loopback interface."""
    url = QUrl(server_url)
    if not url.isValid() or url.host() == "":
        raise SyncTransportError("Not a valid server URL.")
    if url.scheme() not in ("https", "http"):
        raise SyncTransportError("Server URL must use http(s).")
    if url.scheme() == "http" and url.host() not in ("localhost", "127.0.0.1", "::1"):
        raise SyncTransportError(
            "Plain http is only allowed for localhost; use https for real servers."
        )


class WebDAVTransport:
    """Sends the sync document to/from a Nextcloud WebDAV endpoint."""

    SYNC_FOLDER = "todo-snake"
    SYNC_FILE = "todos.json"

    def __init__(self, account: SyncAccount, parent=None):
        self._account = account
        self._nam = QNetworkAccessManager(parent)

    # -- public API ---------------------------------------------------------

    def fetch(self) -> FetchResult:
        """Download the sync document. ``found`` is ``False`` when the file
        does not exist yet (first sync)."""
        status, body = self._exchange(b"GET", self._file_url())
        if status == 404:
            return FetchResult(False, None)
        self._require_success(status)
        return FetchResult(True, body)

    def upload(self, body: bytes) -> None:
        """Upload the sync document, creating the parent folder if needed."""
        self._ensure_folder()
        status, _ = self._exchange(b"PUT", self._file_url(), body)
        self._require_success(status)

    # -- URL / request helpers ---------------------------------------------

    def _base(self) -> str:
        server = (self._account.server_url or "").strip().rstrip("/")
        if not server:
            raise SyncTransportError("No server URL configured.")
        validate_server_url(server)
        return server

    def _file_url(self) -> QUrl:
        return QUrl(self._dav_url(f"{self.SYNC_FOLDER}/{self.SYNC_FILE}"))

    def _folder_url(self) -> QUrl:
        return QUrl(self._dav_url(f"{self.SYNC_FOLDER}/"))

    def _dav_url(self, suffix: str) -> str:
        """Build the WebDAV url, percent-encoding the username path segment."""
        username = (self._account.username or "").strip()
        if not username:
            raise SyncTransportError("No username configured.")
        return f"{self._base()}/remote.php/dav/files/{quote(username, safe='')}/{suffix}"

    def _ensure_folder(self) -> None:
        status, _ = self._exchange(b"MKCOL", self._folder_url())
        # 201: created; 405/301/412: already exists.
        if status in (201, 405, 301, 412):
            return
        self._require_success(status)

    def _exchange(
        self,
        method: bytes,
        url: QUrl,
        body: bytes | None = None,
    ) -> tuple[int, bytes]:
        """Run ``method`` against ``url`` to completion; return (status, body).

        Raises ``SyncTransportError`` on transport-level failures; HTTP status
        policy is the caller's job (see ``_require_success``).
        """
        request = self._request(url)
        payload = QByteArray(body) if body is not None else QByteArray()
        reply = self._nam.sendCustomRequest(request, method, payload)
        self._run(reply)
        status = int(reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute) or 0)
        error = reply.error()
        body_out = bytes(reply.readAll())
        reply.deleteLater()
        if status == 401:
            raise SyncTransportError(self._unauthorized_message())
        if error is not QNetworkReply.NetworkError.NoError:
            raise SyncTransportError(self._describe(reply, status))
        return status, body_out

    @staticmethod
    def _unauthorized_message() -> str:
        return (
            "HTTP 401 Unauthorized: the server rejected the username or app password. "
            "Check that the username is your Nextcloud login name (not your email "
            "address or display name) and use an app password created under Personal "
            "settings → Security."
        )

    @staticmethod
    def _require_success(status: int) -> None:
        if status >= 400:
            raise SyncTransportError(f"Server returned HTTP {status}.")

    def _request(self, url: QUrl) -> QNetworkRequest:
        request = QNetworkRequest(url)
        username = (self._account.username or "").strip()
        password = (self._account.app_password or "").strip()
        request.setRawHeader(b"Authorization", basic_auth_value(username, password).encode("ascii"))
        request.setRawHeader(b"User-Agent", b"todo-snake-sync")
        return request

    def _run(self, reply: QNetworkReply) -> None:
        loop = QEventLoop()
        timer = QTimer(self._nam)
        timer.setSingleShot(True)
        timer.setInterval(_UPLOAD_TIMEOUT_MS)
        reply.finished.connect(loop.quit)
        timer.timeout.connect(loop.quit)
        timer.timeout.connect(reply.abort)
        timer.start()
        loop.exec()
        timer.stop()

    @staticmethod
    def _describe(reply: QNetworkReply, status: int) -> str:
        details = f" (HTTP {status})" if status else ""
        return f"Request failed: {reply.errorString()}{details}"
