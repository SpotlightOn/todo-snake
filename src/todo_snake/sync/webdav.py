"""WebDAV plumbing: the shared HTTP client, helpers and the generic transport.

``DavClient`` is the one place that knows how to talk HTTP to a server
synchronously: Basic auth, request headers, a timeout, status logging and how
to phrase a 401. Everything protocol-specific builds on it:

* :class:`WebDAVTransport` — stores the sync document as a JSON file (the
  generic ``WEBDAV`` provider, and how Nextcloud files are addressed).
* ``caldav.CalDAVTransport`` — keeps every task as a ``VTODO`` resource.
* ``file_store.NextcloudFileStore`` — uploads attachment files.

Uses ``QNetworkAccessManager`` (part of PySide6, no new dependencies) and an
event-loop pump so a sync runs as one straight line while the I/O underneath is
asynchronous. Plain ``http://`` is rejected unless the target is loopback
(useful for local test servers).
"""

from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from urllib.parse import quote

from PySide6.QtCore import QByteArray, QEventLoop, QTimer, QUrl
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from todo_snake.logging_setup import get_sync_logger
from todo_snake.sync.accounts import SyncAccount, SyncProvider

# Re-exported for the transports and their callers.
from todo_snake.sync.errors import SyncTransportError

_DEFAULT_TIMEOUT_MS = 15_000
_DAV_NS = "DAV:"
_logger = get_sync_logger()

#: Minimal PROPFIND asking only for the resource type (folder vs. file).
_PROPFIND_BODY = (
    '<?xml version="1.0" encoding="utf-8" ?>'
    f'<d:propfind xmlns:d="{_DAV_NS}"><d:prop><d:resourcetype/></d:prop></d:propfind>'
).encode()

#: Hint shown when a server answers 401 (kept in one place; CalDAV replaces it).
UNAUTHORIZED_HINT = (
    "HTTP 401 Unauthorized: the server rejected the username or app password. "
    "Check that the username is your Nextcloud login name (not your email "
    "address or display name) and use a valid device/app password."
)


@dataclass
class FetchResult:
    found: bool
    body: bytes | None


def basic_auth_value(username: str, password: str) -> str:
    import base64

    token = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
    return f"Basic {token}"


def clean_server_url(server_url: str) -> str:
    """Normalise a base URL: drop a trailing slash and a trailing
    ``/index.php`` (Nextcloud web URLs often carry it) so DAV/login paths are
    appended correctly."""
    base = (server_url or "").strip().rstrip("/")
    if base.endswith("/index.php"):
        base = base[: -len("/index.php")].rstrip("/")
    return base


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


def parse_propfind_children(body: bytes) -> list[tuple[str, bool]]:
    """Parse a PROPFIND multistatus into ``(href, is_collection)`` entries."""
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise SyncTransportError(f"Invalid WebDAV response: {exc}") from exc
    children: list[tuple[str, bool]] = []
    for response in root.findall(f"{{{_DAV_NS}}}response"):
        href_el = response.find(f"{{{_DAV_NS}}}href")
        if href_el is None or not href_el.text:
            continue
        is_collection = (
            response.find(f".//{{{_DAV_NS}}}resourcetype/{{{_DAV_NS}}}collection") is not None
        )
        children.append((href_el.text.strip(), is_collection))
    return children


class DavClient:
    """Runs HTTP requests against one account, synchronously.

    A transport owns one client and passes it the account credentials; the
    timeout and the 401 wording are configurable per protocol.
    """

    def __init__(
        self,
        account: SyncAccount,
        parent=None,
        *,
        timeout_ms: int = _DEFAULT_TIMEOUT_MS,
        unauthorized_hint: str | None = None,
    ):
        self._account = account
        self._nam = QNetworkAccessManager(parent)
        self._timeout_ms = timeout_ms
        self._unauthorized_hint = unauthorized_hint or UNAUTHORIZED_HINT

    def base(self) -> str:
        """The account's server URL, validated (never a trailing slash)."""
        server = (self._account.server_url or "").strip().rstrip("/")
        if not server:
            raise SyncTransportError("No server URL configured.")
        validate_server_url(server)
        return server

    def exchange(
        self,
        method: bytes,
        url: QUrl,
        body: bytes | None = None,
        *,
        content_type: str | None = None,
        depth: str | None = None,
        etag: str | None = None,
    ) -> tuple[int, bytes]:
        """Run ``method`` against ``url`` to completion; return (status, body).

        Raises ``SyncTransportError`` on transport-level failures and on 401;
        the HTTP *status* policy is the caller's job (see
        :meth:`require_success`).
        """
        request = self._request(url, content_type=content_type, depth=depth, etag=etag)
        payload = QByteArray(body) if body is not None else QByteArray()
        started = time.monotonic()
        reply = self._nam.sendCustomRequest(request, method, payload)
        self._run(reply)
        status = int(reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute) or 0)
        error = reply.error()
        message = reply.errorString()
        body_out = bytes(reply.readAll())
        reply.deleteLater()
        method_name = method.decode("ascii", "replace")
        _logger.info(
            "%s %s -> %s (%d ms)",
            method_name,
            url.toString(),
            status or "-",
            int((time.monotonic() - started) * 1000),
        )
        if status == 401:
            _logger.warning("401 Unauthorized: %s", url.toString())
            raise SyncTransportError(self._unauthorized_hint)
        # An HTTP error *status* is the caller's business: ``fetch`` treats 404
        # as "no document yet" and MKCOL tolerates 405. Only a missing HTTP
        # status means the request itself failed (DNS, TLS, …).
        if error is not QNetworkReply.NetworkError.NoError and status == 0:
            _logger.error("%s %s failed: %s", method_name, url.toString(), message)
            raise SyncTransportError(f"Request failed: {message}")
        if status >= 400:
            _logger.warning("%s %s -> HTTP %s", method_name, url.toString(), status)
        return status, body_out

    @staticmethod
    def require_success(status: int, what: str = "Server") -> None:
        """Raise unless ``status`` is a success (2xx/3xx)."""
        if status >= 400:
            raise SyncTransportError(f"{what} returned HTTP {status}.")

    def close(self) -> None:
        """Release the network manager (call once the request is done)."""
        self._nam.deleteLater()

    def _request(
        self,
        url: QUrl,
        *,
        content_type: str | None = None,
        depth: str | None = None,
        etag: str | None = None,
    ) -> QNetworkRequest:
        request = QNetworkRequest(url)
        username = (self._account.username or "").strip()
        password = (self._account.app_password or "").strip()
        request.setRawHeader(b"Authorization", basic_auth_value(username, password).encode("ascii"))
        request.setRawHeader(b"User-Agent", b"todo-snake-sync")
        if content_type:
            request.setRawHeader(b"Content-Type", content_type.encode("ascii"))
        if depth is not None:
            request.setRawHeader(b"Depth", depth.encode("ascii"))
        if etag:
            request.setRawHeader(b"If-Match", f'"{etag}"'.encode("ascii"))
        return request

    def _run(self, reply: QNetworkReply) -> None:
        """Pump the event loop until the reply finishes (or the timeout hits)."""
        loop = QEventLoop()
        timer = QTimer(self._nam)
        timer.setSingleShot(True)
        timer.setInterval(self._timeout_ms)
        reply.finished.connect(loop.quit)
        timer.timeout.connect(loop.quit)
        timer.timeout.connect(reply.abort)
        timer.start()
        loop.exec()
        timer.stop()


class WebDAVTransport:
    """Sends the sync document to/from a Nextcloud or generic WebDAV endpoint."""

    SYNC_FOLDER = "todo-snake"
    SYNC_FILE = "todos.json"

    def __init__(self, account: SyncAccount, parent=None):
        self._account = account
        self._dav = DavClient(account, parent)

    # -- public API ---------------------------------------------------------

    def fetch(self) -> FetchResult:
        """Download the sync document. ``found`` is ``False`` when the file
        does not exist yet (first sync)."""
        status, body = self._dav.exchange(b"GET", self._file_url())
        if status == 404:
            return FetchResult(False, None)
        self._dav.require_success(status)
        return FetchResult(True, body)

    def upload(self, body: bytes) -> None:
        """Upload the sync document, creating the parent folder if needed."""
        self._ensure_folder()
        status, _ = self._dav.exchange(b"PUT", self._file_url(), body)
        self._dav.require_success(status)

    def close(self) -> None:
        """Release the network manager."""
        self._dav.close()

    # -- URL helpers --------------------------------------------------------

    def dav_base(self) -> str:
        """Base URL under which the sync folder lives.

        Nextcloud keeps user files under ``/remote.php/dav/files/<user>/`` (with
        the username percent-encoded); a generic server uses the configured
        ``remote_path``, which defaults to the server root.
        """
        base = self._dav.base()
        if self._account.provider == SyncProvider.WEBDAV:
            path = (self._account.remote_path or "").strip().strip("/")
            return f"{base}/{path}" if path else base
        username = (self._account.username or "").strip()
        if not username:
            raise SyncTransportError("No username configured.")
        return f"{base}/remote.php/dav/files/{quote(username, safe='')}"

    # -- internals ----------------------------------------------------------

    def _file_url(self) -> QUrl:
        return QUrl(f"{self.dav_base()}/{self.SYNC_FOLDER}/{self.SYNC_FILE}")

    def _folder_url(self) -> QUrl:
        return QUrl(f"{self.dav_base()}/{self.SYNC_FOLDER}/")

    def _ensure_folder(self) -> None:
        status, _ = self._dav.exchange(b"MKCOL", self._folder_url())
        # 201: created; 405/301/412: already exists.
        if status in (201, 405, 301, 412):
            return
        self._dav.require_success(status)
