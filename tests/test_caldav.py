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

_VTODO_RECURRING = (
    "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//test//EN\r\n"
    "BEGIN:VTODO\r\nUID:u-rec\r\nSUMMARY:Weekly review\r\n"
    "DUE:20261008T090000Z\r\nRRULE:FREQ=WEEKLY;INTERVAL=2\r\n"
    "STATUS:NEEDS-ACTION\r\n"
    "CREATED:20260901T100000Z\r\nLAST-MODIFIED:20260902T100000Z\r\n"
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
    report_body: ClassVar[bytes | None] = None

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
        body = type(self).report_body or _multistatus(_VTODO_OPEN, _VTODO_DONE)
        self._send(type(self).report_status, body)

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
    _CalDAVHandler.report_body = None
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
    transport.close()


def test_request_uses_basic_auth(qapp):
    account = _account("http://127.0.0.1:1")
    transport = CalDAVTransport(account)
    request = transport._dav._request(QUrl("http://127.0.0.1:1/x"), depth="1")
    assert bytes(request.rawHeader("Authorization")) == _CalDAVHandler.expected.encode("ascii")
    assert bytes(request.rawHeader("Depth")) == b"1"
    transport.close()


def test_fetch_reads_vtodos_into_document(qapp, caldav_server):
    transport = CalDAVTransport(_account(caldav_server))
    try:
        result = transport.fetch()
        assert result.found is True
        document = SyncDocument.from_json(result.body.decode("utf-8"))
        assert set(document.items) == {"u-open", "u-done"}
        assert document.items["u-open"].title == "Buy milk"
    finally:
        transport.close()


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
            due_at=changed.items["u-open"].due_at,
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
        transport.close()


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
        transport.close()


def test_wrong_credentials_raise_guidance(qapp, caldav_server):
    transport = CalDAVTransport(_account(caldav_server, password="wrong"))
    try:
        with pytest.raises(SyncTransportError) as excinfo:
            transport.fetch()
        assert "401" in str(excinfo.value)
    finally:
        transport.close()


def test_create_transport_routes_caldav(qapp):
    from todo_snake.sync.manager import create_transport

    transport = create_transport(_account("https://cloud.example.com"))
    assert isinstance(transport, CalDAVTransport)
    transport.close()


def test_sync_pulls_remote_tasks_into_the_local_store(qapp, caldav_server, tmp_path):
    """A task that only exists on the server must end up in Todo Snake."""
    from todo_snake.persistence import create_repository
    from todo_snake.service import TodoService
    from todo_snake.sync.journal import SyncJournal
    from todo_snake.sync.manager import SyncManager

    service = TodoService(create_repository("sqlite", tmp_path / "todos.db"))
    manager = SyncManager(service, SyncJournal(tmp_path / "sync.db"))

    stats = manager.trigger_sync(_account(caldav_server))

    assert stats is not None
    assert stats["created"] == 2
    assert sorted(todo.title for todo in service.list_todos()) == ["Buy milk", "Ship it"]


def test_sync_applies_a_remote_due_date_change(qapp, caldav_server, tmp_path):
    """An edit made in Nextcloud Tasks (newer LAST-MODIFIED, new DUE) must win
    over the local task — the reported "due date did not change" bug."""
    from datetime import datetime, timezone

    from todo_snake.domain.todo import Todo
    from todo_snake.persistence import create_repository
    from todo_snake.service import TodoService
    from todo_snake.sync.journal import SyncJournal
    from todo_snake.sync.manager import SyncManager

    service = TodoService(create_repository("sqlite", tmp_path / "todos.db"))
    service.create_synced(
        Todo(
            uid="u-open",
            title="Buy milk",
            due_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
            updated_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        )
    )
    manager = SyncManager(service, SyncJournal(tmp_path / "sync.db"))
    manager.trigger_sync(_account(caldav_server))

    todo = service.find_by_uid("u-open")
    assert todo is not None
    assert todo.due_at == datetime(2026, 10, 1, tzinfo=timezone.utc)


def test_parse_multistatus_items_reads_etags():
    from todo_snake.sync.caldav import parse_multistatus_items

    body = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
        "<d:response><d:href>/cal/u-open.ics</d:href>"
        '<d:propstat><d:prop><d:getetag>"abc123"</d:getetag>'
        f"<c:calendar-data>{_VTODO_OPEN}</c:calendar-data>"
        "</d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>"
        "</d:multistatus>"
    ).encode()
    items = parse_multistatus_items(body)
    assert len(items) == 1
    item, etag = items[0]
    assert item.uid == "u-open"
    assert etag == "abc123"


def test_sync_propagates_a_remote_deletion(qapp, caldav_server, tmp_path):
    """A task deleted on the server must be removed locally, not re-uploaded."""
    from todo_snake.persistence import create_repository
    from todo_snake.service import TodoService
    from todo_snake.sync.journal import SyncJournal
    from todo_snake.sync.manager import SyncManager

    service = TodoService(create_repository("sqlite", tmp_path / "todos.db"))
    manager = SyncManager(service, SyncJournal(tmp_path / "sync.db"))
    account = _account(caldav_server)

    manager.trigger_sync(account)
    assert {todo.uid for todo in service.list_todos()} == {"u-open", "u-done"}

    # Nextcloud now only has u-done: u-open was deleted there.
    _CalDAVHandler.report_body = _multistatus(_VTODO_DONE)
    manager.trigger_sync(account)
    assert {todo.uid for todo in service.list_todos()} == {"u-done"}


def test_sync_imports_a_recurrence(qapp, caldav_server, tmp_path):
    from todo_snake.persistence import create_repository
    from todo_snake.service import TodoService
    from todo_snake.sync.journal import SyncJournal
    from todo_snake.sync.manager import SyncManager

    _CalDAVHandler.report_body = _multistatus(_VTODO_RECURRING)
    service = TodoService(create_repository("sqlite", tmp_path / "todos.db"))
    manager = SyncManager(service, SyncJournal(tmp_path / "sync.db"))

    manager.trigger_sync(_account(caldav_server))

    todo = service.find_by_uid("u-rec")
    assert todo is not None
    assert todo.recurrence == "FREQ=WEEKLY;INTERVAL=2"


def test_sync_uploads_a_recurrence(qapp, caldav_server, tmp_path):
    from datetime import datetime, timezone

    from todo_snake.persistence import create_repository
    from todo_snake.service import TodoService
    from todo_snake.sync.journal import SyncJournal
    from todo_snake.sync.manager import SyncManager

    service = TodoService(create_repository("sqlite", tmp_path / "todos.db"))
    service.add_todo(
        "weekly",
        due_at=datetime(2026, 10, 8, 9, 0, tzinfo=timezone.utc),
        recurrence="FREQ=WEEKLY",
    )
    manager = SyncManager(service, SyncJournal(tmp_path / "sync.db"))

    manager.trigger_sync(_account(caldav_server))

    bodies = [body for _path, body in _CalDAVHandler.puts]
    assert any("RRULE:FREQ=WEEKLY" in body for body in bodies)


def test_nextcloud_provider_syncs_a_recurrence(qapp, caldav_server, tmp_path):
    """The Nextcloud provider (its own fetch override) must handle RRULE too."""
    from todo_snake.persistence import create_repository
    from todo_snake.service import TodoService
    from todo_snake.sync.accounts import SyncAccount, SyncProvider
    from todo_snake.sync.journal import SyncJournal
    from todo_snake.sync.manager import SyncManager

    _CalDAVHandler.report_body = _multistatus(_VTODO_RECURRING)
    service = TodoService(create_repository("sqlite", tmp_path / "todos.db"))
    manager = SyncManager(service, SyncJournal(tmp_path / "sync.db"))
    account = SyncAccount(
        provider=SyncProvider.NEXTCLOUD,
        server_url=caldav_server,
        remote_path="tasks",
        username="alice",
        app_password="t0ps3cret",
    )

    manager.trigger_sync(account)

    todo = service.find_by_uid("u-rec")
    assert todo is not None
    assert todo.recurrence == "FREQ=WEEKLY;INTERVAL=2"


def test_completing_a_recurring_task_advances_it_and_syncs_the_new_due(
    qapp, caldav_server, tmp_path
):
    from datetime import datetime, timezone

    from todo_snake.persistence import create_repository
    from todo_snake.service import TodoService
    from todo_snake.sync.journal import SyncJournal
    from todo_snake.sync.manager import SyncManager

    service = TodoService(create_repository("sqlite", tmp_path / "todos.db"))
    todo = service.add_todo(
        "weekly",
        due_at=datetime(2026, 10, 8, 9, 0, tzinfo=timezone.utc),
        recurrence="FREQ=WEEKLY",
    )
    manager = SyncManager(service, SyncJournal(tmp_path / "sync.db"))
    account = _account(caldav_server)
    manager.trigger_sync(account)  # upload the first occurrence

    _CalDAVHandler.puts = []
    service.toggle_done(todo.id)  # advance to the next occurrence
    manager.trigger_sync(account)

    bodies = [body for _path, body in _CalDAVHandler.puts]
    assert any("DUE:20261015T090000Z" in body for body in bodies)
    assert any("RRULE:FREQ=WEEKLY" in body for body in bodies)
