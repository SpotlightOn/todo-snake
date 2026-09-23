"""Tests for the CalDAV transport (local fake CalDAV server, no real network)."""

import base64
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import ClassVar

import pytest
from PySide6.QtCore import QUrl

from todo_snake.sync.accounts import SyncAccount, SyncProvider
from todo_snake.sync.caldav import CalDAVTransport, parse_multistatus
from todo_snake.sync.document import SyncDocument, SyncItem
from todo_snake.sync.webdav import SyncTransportError

VALID_CREDENTIALS = "alice:t0ps3cret"

_VTODO_OPEN = (
    "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//test//EN\r\n"
    "BEGIN:VTODO\r\nUID:u-open\r\nSUMMARY:Buy milk\r\n"
    "STATUS:NEEDS-ACTION\r\nPRIORITY:1\r\nDUE;VALUE=DATE:20261001\r\n"
    "CREATED:20260901T100000Z\r\nLAST-MODIFIED:20260902T100000Z\r\n"
    "END:VTODO\r\nEND:VCALENDAR\r\n"
)
_VTODO_DONE = (
    "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//test//EN\r\n"
    "BEGIN:VTODO\r\nUID:u-done\r\nSUMMARY:Ship it\r\n"
    "STATUS:COMPLETED\r\nCOMPLETED:20260903T120000Z\r\n"
    "CREATED:20260901T090000Z\r\nLAST-MODIFIED:20260903T120000Z\r\n"
    "END:VTODO\r\nEND:VCALENDAR\r\n"
)


def _multistatus(*calendars: str) -> bytes:
    responses = "".join(
        "<d:response><d:href>/cal/{i}.ics</d:href><d:propstat><d:prop>"
        f"<c:calendar-data>{data}</c:calendar-data>"
        "</d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>"
        for i, data in enumerate(calendars)
    )
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
        f"{responses}</d:multistatus>"
    ).encode()


def test_parse_multistatus_extracts_vtodos():
    items = parse_multistatus(_multistatus(_VTODO_OPEN, _VTODO_DONE))
    assert {item.uid for item in items} == {"u-open", "u-done"}


def test_parse_multistatus_rejects_garbage():
    with pytest.raises(SyncTransportError):
        parse_multistatus(b"<not-xml")


# -- live fake CalDAV server -------------------------------------------------


class _CalDAVHandler(BaseHTTPRequestHandler):
    expected = "Basic " + base64.b64encode(VALID_CREDENTIALS.encode()).decode("ascii")
    puts: ClassVar[list[tuple[str, str]]] = []
    report_status = 207

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

    def do_REPORT(self):
        if not self._authorized():
            self._send(401)
            return
        self._send(type(self).report_status, _multistatus(_VTODO_OPEN, _VTODO_DONE))

    def do_PUT(self):
        if not self._authorized():
            self._send(401)
            return
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8")
        type(self).puts.append((self.path, body))
        self._send(201)

    def log_message(self, *args):  # keep test output clean
        pass


@pytest.fixture()
def caldav_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _CalDAVHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    _CalDAVHandler.puts = []
    _CalDAVHandler.report_status = 207
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def _account(server: str, password: str = "t0ps3cret") -> SyncAccount:
    return SyncAccount(
        provider=SyncProvider.CALDAV,
        server_url=f"{server}/calendars/alice/tasks/",
        username="alice",
        app_password=password,
    )


def test_resource_url_appends_ics_to_collection(qapp):
    account = SyncAccount(
        provider=SyncProvider.CALDAV,
        server_url="https://cloud.example.com/remote.php/dav/calendars/alice/tasks",
        username="alice",
    )
    transport = CalDAVTransport(account)
    assert (
        str(transport._resource_url("u-1").toEncoded(), "utf-8")
        == "https://cloud.example.com/remote.php/dav/calendars/alice/tasks/u-1.ics"
    )
    transport._nam.deleteLater()


def test_request_uses_basic_auth(qapp):
    account = _account("http://127.0.0.1:1")
    transport = CalDAVTransport(account)
    request = transport._request(QUrl("http://127.0.0.1:1/x"), None, "1")
    assert bytes(request.rawHeader("Authorization")) == _CalDAVHandler.expected.encode("ascii")
    assert bytes(request.rawHeader("Depth")) == b"1"
    transport._nam.deleteLater()


def test_fetch_reads_vtodos_into_document(qapp, caldav_server):
    transport = CalDAVTransport(_account(caldav_server))
    try:
        result = transport.fetch()
        assert result.found is True
        document = SyncDocument.from_json(result.body.decode("utf-8"))
        assert set(document.items) == {"u-open", "u-done"}
        assert document.items["u-open"].title == "Buy milk"
    finally:
        transport._nam.deleteLater()


def test_upload_sends_only_changed_todos(qapp, caldav_server):
    transport = CalDAVTransport(_account(caldav_server))
    try:
        fetched = transport.fetch()
        # Re-uploading the untouched document must not issue any PUT.
        transport.upload(fetched.body)
        assert _CalDAVHandler.puts == []

        changed = SyncDocument.from_json(fetched.body.decode("utf-8"))
        changed.items["u-open"] = SyncItem(
            uid="u-open",
            title="Buy oat milk",
            priority=changed.items["u-open"].priority,
            due_date=changed.items["u-open"].due_date,
            note="",
            status=changed.items["u-open"].status,
            created_at=changed.items["u-open"].created_at,
            completed_at=None,
            updated_at=datetime(2026, 9, 5, 8, 0, tzinfo=timezone.utc),
        )
        transport.upload(changed.to_json().encode("utf-8"))

        paths = [path for path, _ in _CalDAVHandler.puts]
        assert paths == ["/calendars/alice/tasks/u-open.ics"]
        assert "SUMMARY:Buy oat milk" in _CalDAVHandler.puts[0][1]
    finally:
        transport._nam.deleteLater()


def test_upload_writes_tombstone_as_cancelled(qapp, caldav_server):
    transport = CalDAVTransport(_account(caldav_server))
    try:
        transport.fetch()
        document = SyncDocument(
            items={
                "u-open": SyncItem.tombstone(
                    "u-open", datetime(2026, 9, 6, 8, 0, tzinfo=timezone.utc)
                )
            }
        )
        transport.upload(document.to_json().encode("utf-8"))
        assert len(_CalDAVHandler.puts) == 1
        assert "STATUS:CANCELLED" in _CalDAVHandler.puts[0][1]
    finally:
        transport._nam.deleteLater()


def test_wrong_credentials_raise_guidance(qapp, caldav_server):
    transport = CalDAVTransport(_account(caldav_server, password="wrong"))
    try:
        with pytest.raises(SyncTransportError) as excinfo:
            transport.fetch()
        assert "401" in str(excinfo.value)
    finally:
        transport._nam.deleteLater()


def test_create_transport_routes_caldav(qapp):
    from todo_snake.sync.manager import create_transport

    transport = create_transport(_account("https://cloud.example.com"))
    assert isinstance(transport, CalDAVTransport)
    transport._nam.deleteLater()
