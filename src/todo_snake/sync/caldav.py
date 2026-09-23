"""CalDAV transport for VTODO task collections.

Works with any CalDAV server that exposes tasks: **Baïkal** (sabre/dav),
**Radicale**, **Nextcloud** (Tasks), **fruux** and **Vikunja**'s CalDAV
endpoint. One implementation, many servers — because they all speak the same
open standard (RFC 4791 / RFC 5545 VTODO).

The account's ``server_url`` is the full **calendar collection URL**, e.g.
``https://cloud.example.com/remote.php/dav/calendars/alice/tasks/``. Each todo
maps 1:1 to an ``<uid>.ics`` resource in that collection, so our stable todo
``uid`` doubles as the iCalendar ``UID`` — no separate id mapping needed.

Authentication is HTTP Basic over TLS (username + password / app password).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from urllib.parse import quote

from PySide6.QtCore import QByteArray, QEventLoop, QTimer, QUrl
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from todo_snake.sync.accounts import SyncAccount
from todo_snake.sync.document import SyncDocument, SyncItem
from todo_snake.sync.icalendar import parse_vtodo, to_ical
from todo_snake.sync.webdav import (
    FetchResult,
    SyncTransportError,
    basic_auth_value,
    validate_server_url,
)

_DAV_NS = "DAV:"
_CALDAV_NS = "urn:ietf:params:xml:ns:caldav"
_TIMEOUT_MS = 20_000

_CALENDAR_QUERY = (
    '<?xml version="1.0" encoding="utf-8" ?>'
    f'<c:calendar-query xmlns:d="{_DAV_NS}" xmlns:c="{_CALDAV_NS}">'
    "<d:prop><d:getetag/><c:calendar-data/></d:prop>"
    '<c:filter><c:comp-filter name="VCALENDAR">'
    '<c:comp-filter name="VTODO"/>'
    "</c:comp-filter></c:filter>"
    "</c:calendar-query>"
)


def parse_multistatus(body: bytes) -> list[SyncItem]:
    """Extract the VTODOs from a CalDAV ``multistatus`` response."""
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise SyncTransportError(f"Invalid CalDAV response: {exc}") from exc
    items: list[SyncItem] = []
    for response in root.findall(f"{{{_DAV_NS}}}response"):
        data_el = response.find(f".//{{{_CALDAV_NS}}}calendar-data")
        if data_el is None or not data_el.text:
            continue
        item = parse_vtodo(data_el.text)
        if item is not None:
            items.append(item)
    return items


class CalDAVTransport:
    """Fetches and pushes todos as VTODO resources in one calendar collection."""

    def __init__(self, account: SyncAccount, parent=None):
        self._account = account
        self._nam = QNetworkAccessManager(parent)
        self._fetched: dict[str, SyncItem] = {}

    # -- public API ---------------------------------------------------------

    def fetch(self) -> FetchResult:
        """Download every VTODO in the collection as a sync document."""
        status, body = self._exchange(
            b"REPORT",
            self._collection_url(),
            _CALENDAR_QUERY.encode("utf-8"),
            content_type="application/xml; charset=utf-8",
            depth="1",
        )
        self._require_success(status)
        items = parse_multistatus(body)
        document = SyncDocument(items={item.uid: item for item in items})
        # Remember what the server had, so ``upload`` only sends real changes.
        self._fetched = dict(document.items)
        return FetchResult(True, document.to_json().encode("utf-8"))

    def upload(self, body: bytes) -> None:
        """Write back the merged document, one ``PUT`` per changed todo."""
        document = SyncDocument.from_json(body.decode("utf-8"))
        for item in document.items.values():
            if not item.deleted and self._fetched.get(item.uid) == item:
                continue
            self._put_resource(item)

    # -- URL / request helpers ---------------------------------------------

    def _collection_base(self) -> str:
        url = (self._account.server_url or "").strip()
        if not url:
            raise SyncTransportError("No calendar URL configured.")
        validate_server_url(url)
        return url if url.endswith("/") else url + "/"

    def _collection_url(self) -> QUrl:
        return QUrl(self._collection_base())

    def _resource_url(self, uid: str) -> QUrl:
        return QUrl(f"{self._collection_base()}{quote(uid, safe='')}.ics")

    def _put_resource(self, item: SyncItem) -> None:
        payload = to_ical(item).encode("utf-8")
        status, _ = self._exchange(
            b"PUT",
            self._resource_url(item.uid),
            payload,
            content_type="text/calendar; charset=utf-8",
        )
        self._require_success(status)

    def _request(self, url: QUrl, content_type: str | None, depth: str | None) -> QNetworkRequest:
        request = QNetworkRequest(url)
        username = (self._account.username or "").strip()
        password = (self._account.app_password or "").strip()
        request.setRawHeader(b"Authorization", basic_auth_value(username, password).encode("ascii"))
        request.setRawHeader(b"User-Agent", b"todo-snake-sync")
        if content_type:
            request.setRawHeader(b"Content-Type", content_type.encode("ascii"))
        if depth:
            request.setRawHeader(b"Depth", depth.encode("ascii"))
        return request

    def _exchange(
        self,
        method: bytes,
        url: QUrl,
        body: bytes | None = None,
        content_type: str | None = None,
        depth: str | None = None,
    ) -> tuple[int, bytes]:
        request = self._request(url, content_type, depth)
        payload = QByteArray(body) if body is not None else QByteArray()
        reply = self._nam.sendCustomRequest(request, method, payload)
        self._run(reply)
        status = int(reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute) or 0)
        error = reply.error()
        message = reply.errorString()
        body_out = bytes(reply.readAll())
        reply.deleteLater()
        if status == 401:
            raise SyncTransportError(self._unauthorized_message())
        if error is not QNetworkReply.NetworkError.NoError:
            raise SyncTransportError(f"Request failed: {message} (HTTP {status})")
        return status, body_out

    @staticmethod
    def _unauthorized_message() -> str:
        return (
            "HTTP 401 Unauthorized: the CalDAV server rejected the username or "
            "password. Check the credentials and, on Nextcloud, that you use an "
            "app password (Personal settings → Security)."
        )

    @staticmethod
    def _require_success(status: int) -> None:
        if status >= 400:
            raise SyncTransportError(f"CalDAV server returned HTTP {status}.")

    def _run(self, reply: QNetworkReply) -> None:
        loop = QEventLoop()
        timer = QTimer(self._nam)
        timer.setSingleShot(True)
        timer.setInterval(_TIMEOUT_MS)
        reply.finished.connect(loop.quit)
        timer.timeout.connect(loop.quit)
        timer.timeout.connect(reply.abort)
        timer.start()
        loop.exec()
        timer.stop()
