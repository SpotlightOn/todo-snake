"""Tests for the Nextcloud Tasks integration (URL parsing + auto-create)."""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import ClassVar

import pytest

from todo_snake.sync.accounts import SyncAccount, SyncProvider
from todo_snake.sync.document import SyncDocument
from todo_snake.sync.nextcloud import (
    NextcloudTasksTransport,
    normalize_calendar_name,
    split_calendar_url,
)
from todo_snake.sync.webdav import SyncTransportError


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("tasks", "tasks"),
        ("/remote.php/dav/calendars/alice/tasks/", "tasks"),
        ("https://cloud.example.com/remote.php/dav/calendars/alice/tasks/", "tasks"),
        ("https://dino/apps/tasks/calendars/tasks", "tasks"),
        ("", ""),
        ("https://dino/", ""),
    ],
)
def test_normalize_calendar_name_accepts_any_input(value, expected):
    assert normalize_calendar_name(value) == expected


def test_split_calendar_url_accepts_the_tasks_web_url():
    assert split_calendar_url("https://dino/apps/tasks/calendars/tasks") == (
        "https://dino",
        "tasks",
    )


def test_split_calendar_url_accepts_a_caldav_url():
    assert split_calendar_url(
        "https://cloud.example.com/remote.php/dav/calendars/alice/tasks/"
    ) == ("https://cloud.example.com", "tasks")


def test_split_calendar_url_keeps_a_subpath_server():
    assert split_calendar_url("https://host.example.com/nextcloud/apps/tasks/calendars/tasks") == (
        "https://host.example.com/nextcloud",
        "tasks",
    )


def test_split_calendar_url_bare_name_has_no_base():
    assert split_calendar_url("tasks") == ("", "tasks")


def test_split_calendar_url_strips_index_php():
    assert split_calendar_url("https://host.example.com/index.php/apps/tasks/calendars/tasks") == (
        "https://host.example.com",
        "tasks",
    )


def test_collection_base_strips_index_php_from_the_stored_server(qapp):
    account = SyncAccount(
        provider=SyncProvider.NEXTCLOUD,
        server_url="https://host.example.com/index.php",
        remote_path="tasks",
        username="alice",
    )
    transport = NextcloudTasksTransport(account)
    try:
        assert (
            transport._collection_base()
            == "https://host.example.com/remote.php/dav/calendars/alice/tasks/"
        )
    finally:
        transport.close()


def test_collection_base_is_built_from_the_name(qapp):
    account = SyncAccount(
        provider=SyncProvider.NEXTCLOUD,
        server_url="https://cloud.example.com",
        remote_path="tasks",
        username="alice",
    )
    transport = NextcloudTasksTransport(account)
    try:
        assert (
            transport._collection_base()
            == "https://cloud.example.com/remote.php/dav/calendars/alice/tasks/"
        )
    finally:
        transport.close()


def test_collection_base_accepts_a_pasted_web_url(qapp):
    account = SyncAccount(
        provider=SyncProvider.NEXTCLOUD,
        server_url="https://cloud.example.com",
        remote_path="https://dino/apps/tasks/calendars/tasks",
        username="alice",
    )
    transport = NextcloudTasksTransport(account)
    try:
        assert (
            transport._collection_base()
            == "https://cloud.example.com/remote.php/dav/calendars/alice/tasks/"
        )
    finally:
        transport.close()


def test_collection_base_requires_a_calendar(qapp):
    account = SyncAccount(
        provider=SyncProvider.NEXTCLOUD,
        server_url="https://cloud.example.com",
        username="alice",
    )
    transport = NextcloudTasksTransport(account)
    try:
        with pytest.raises(SyncTransportError):
            transport._collection_base()
    finally:
        transport.close()


# -- live fake server: a missing calendar must be created --------------------


class _TasksHandler(BaseHTTPRequestHandler):
    calls: ClassVar[list[tuple[str, str]]] = []

    def _send(self, code: int, body: bytes = b"") -> None:
        self.send_response(code)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_REPORT(self):
        type(self).calls.append(("REPORT", self.path))
        self._send(404)

    def do_MKCALENDAR(self):
        type(self).calls.append(("MKCALENDAR", self.path))
        self._send(201)

    def log_message(self, *args):  # keep test output clean
        pass


@pytest.fixture()
def tasks_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _TasksHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    _TasksHandler.calls = []
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_fetch_creates_a_missing_calendar(qapp, tasks_server):
    account = SyncAccount(
        provider=SyncProvider.NEXTCLOUD,
        server_url=tasks_server,
        remote_path="tasks",
        username="alice",
        app_password="t0ps3cret",
    )
    transport = NextcloudTasksTransport(account)
    try:
        result = transport.fetch()
        assert result.found is True
        assert SyncDocument.from_json(result.body.decode()).items == {}
        assert ("MKCALENDAR", "/remote.php/dav/calendars/alice/tasks/") in _TasksHandler.calls
    finally:
        transport.close()


def test_create_transport_routes_nextcloud_to_tasks(qapp):
    from todo_snake.sync.manager import create_transport

    transport = create_transport(
        SyncAccount(
            provider=SyncProvider.NEXTCLOUD,
            server_url="https://cloud.example.com",
            remote_path="tasks",
            username="alice",
        )
    )
    try:
        assert isinstance(transport, NextcloudTasksTransport)
    finally:
        transport.close()


# -- attachment upload through a full sync ----------------------------------


class _AttachmentHandler(BaseHTTPRequestHandler):
    calls: ClassVar[list[tuple[str, str]]] = []
    bodies: ClassVar[dict[str, bytes]] = {}

    def _send(self, code: int, body: bytes = b"") -> None:
        self.send_response(code)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _record(self, method: str) -> None:
        type(self).calls.append((method, self.path))

    def do_REPORT(self):
        self._record("REPORT")
        # Calendar does not exist yet -> the transport creates it, starts empty.
        self._send(404)

    def do_MKCALENDAR(self):
        self._record("MKCALENDAR")
        self._send(201)

    def do_MKCOL(self):
        self._record("MKCOL")
        self._send(201)

    def do_PUT(self):
        self._record("PUT")
        length = int(self.headers.get("Content-Length") or 0)
        type(self).bodies[self.path] = self.rfile.read(length)
        self._send(201)

    def do_DELETE(self):
        self._record("DELETE")
        type(self).bodies.pop(self.path, None)
        self._send(204)

    def do_PROPFIND(self):
        """List the folder plus the files stored under it (Depth: 1)."""
        self._record("PROPFIND")
        folder = self.path.rstrip("/")
        entries = [(folder + "/", True)]
        for path in type(self).bodies:
            if path.startswith(folder + "/") and "/" not in path[len(folder) + 1 :]:
                entries.append((path, False))
        self._send(207, _multistatus(*entries))

    def log_message(self, *args):
        pass


@pytest.fixture()
def attachment_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _AttachmentHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    _AttachmentHandler.calls = []
    _AttachmentHandler.bodies = {}
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_sync_uploads_attachment_and_writes_attach_url(qapp, tmp_path, attachment_server):
    from todo_snake.persistence.attachments import SqliteAttachmentRepository
    from todo_snake.persistence.sqlite import SqliteTodoRepository
    from todo_snake.service import TodoService
    from todo_snake.service.attachment_service import AttachmentService
    from todo_snake.sync.journal import SyncJournal
    from todo_snake.sync.manager import SyncManager

    db_path = tmp_path / "todos.db"
    attachments = AttachmentService(SqliteAttachmentRepository(db_path))
    service = TodoService(SqliteTodoRepository(db_path), attachments)
    journal = SyncJournal(db_path)
    manager = SyncManager(service, journal, attachments=attachments)

    todo = service.add_todo("Has a file")
    attachments.add(todo.uid, "note.txt", b"hello attachment")

    account = SyncAccount(
        provider=SyncProvider.NEXTCLOUD,
        server_url=attachment_server,
        remote_path="tasks",
        username="alice",
        app_password="t0ps3cret",
    )
    stats = manager.trigger_sync(account)
    assert stats is not None

    methods = [method for method, _path in _AttachmentHandler.calls]
    assert methods.count("MKCOL") == 3  # folder chain: Todo Snake/Attachments/<uid>
    assert "PUT" in methods

    file_puts = {p: b for p, b in _AttachmentHandler.bodies.items() if p.endswith("note.txt")}
    assert list(file_puts.values()) == [b"hello attachment"]

    ics_puts = [b for p, b in _AttachmentHandler.bodies.items() if p.endswith(".ics")]
    assert len(ics_puts) == 1
    assert "ATTACH:" in ics_puts[0].decode("utf-8")
    assert "note.txt" in ics_puts[0].decode("utf-8")


# -- the same attachment on two accounts ------------------------------------


class _FakeServer:
    """One fake Nextcloud, wrapping its handler's recorded calls."""

    def __init__(self, server, handler, thread):
        self.url = f"http://127.0.0.1:{server.server_address[1]}"
        self._handler = handler
        self._server = server
        self._thread = thread

    @property
    def calls(self) -> list[tuple[str, str]]:
        return self._handler.calls

    @property
    def bodies(self) -> dict[str, bytes]:
        return self._handler.bodies

    def stop(self) -> None:
        self._server.shutdown()
        self._thread.join(timeout=5)


@pytest.fixture()
def attachment_servers():
    """Two independent fake Nextclouds sharing the handler implementation."""
    servers: list[_FakeServer] = []
    for _ in range(2):
        handler = type("Handler", (_AttachmentHandler,), {"calls": [], "bodies": {}})
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        servers.append(_FakeServer(server, handler, thread))
    try:
        yield servers
    finally:
        for fake in servers:
            fake.stop()


def test_attachment_is_uploaded_to_every_account(qapp, tmp_path, attachment_servers):
    """Both servers get their own copy, and each task points at its own file."""
    from todo_snake.persistence.attachments import SqliteAttachmentRepository
    from todo_snake.persistence.sqlite import SqliteTodoRepository
    from todo_snake.service import TodoService
    from todo_snake.service.attachment_service import AttachmentService
    from todo_snake.sync.journal import SyncJournal
    from todo_snake.sync.manager import SyncManager

    db_path = tmp_path / "todos.db"
    attachments = AttachmentService(SqliteAttachmentRepository(db_path))
    service = TodoService(SqliteTodoRepository(db_path), attachments)
    journal = SyncJournal(db_path)
    manager = SyncManager(service, journal, attachments=attachments)

    todo = service.add_todo("Shared task")
    attachment = attachments.add(todo.uid, "note.txt", b"payload")

    def account(server_url: str, uid: str) -> SyncAccount:
        return SyncAccount(
            uid=uid,
            provider=SyncProvider.NEXTCLOUD,
            server_url=server_url,
            remote_path="tasks",
            username="alice",
            app_password="pw",
        )

    assert manager.trigger_sync(account(attachment_servers[0].url, "acc-a")) is not None
    assert manager.trigger_sync(account(attachment_servers[1].url, "acc-b")) is not None

    # The file was uploaded to both servers, remembered per account.
    stored = attachments.read(attachment.id)
    assert stored.url_for("acc-a").startswith(attachment_servers[0].url)
    assert stored.url_for("acc-b").startswith(attachment_servers[1].url)

    for index, fake in enumerate(attachment_servers):
        files = [body for path, body in fake.bodies.items() if path.endswith("note.txt")]
        assert files == [b"payload"], f"server {index} did not receive the file"

        calendars = [body for path, body in fake.bodies.items() if path.endswith(".ics")]
        assert len(calendars) == 1
        # Undo RFC 5545 line folding before checking the (long) ATTACH URL.
        ics = calendars[0].decode("utf-8").replace("\r\n ", "")
        assert "ATTACH:" in ics
        assert f"{fake.url}/remote.php/dav/files/alice/Todo%20Snake/Attachments/" in ics
        # ... and *not* the other server's URL.
        assert attachment_servers[1 - index].url not in ics


def test_removing_an_attachment_deletes_the_file_on_every_account(
    qapp, tmp_path, attachment_servers
):
    from todo_snake.persistence.attachments import SqliteAttachmentRepository
    from todo_snake.persistence.sqlite import SqliteTodoRepository
    from todo_snake.service import TodoService
    from todo_snake.service.attachment_service import AttachmentService
    from todo_snake.sync.journal import SyncJournal
    from todo_snake.sync.manager import SyncManager

    db_path = tmp_path / "todos.db"
    attachments = AttachmentService(SqliteAttachmentRepository(db_path))
    service = TodoService(SqliteTodoRepository(db_path), attachments)
    manager = SyncManager(service, SyncJournal(db_path), attachments=attachments)

    todo = service.add_todo("Shared task")
    attachment = attachments.add(todo.uid, "note.txt", b"payload")

    def account(server_url: str, uid: str) -> SyncAccount:
        return SyncAccount(
            uid=uid,
            provider=SyncProvider.NEXTCLOUD,
            server_url=server_url,
            remote_path="tasks",
            username="alice",
            app_password="pw",
        )

    accounts = [
        account(attachment_servers[0].url, "acc-a"),
        account(attachment_servers[1].url, "acc-b"),
    ]
    for acc in accounts:
        assert manager.trigger_sync(acc) is not None
    assert all(
        any(path.endswith("note.txt") for path in fake.bodies) for fake in attachment_servers
    )

    # Remove the attachment locally, then sync again: the file must go away.
    attachments.remove(attachment.id)
    for acc in accounts:
        assert manager.trigger_sync(acc) is not None

    for index, fake in enumerate(attachment_servers):
        deletes = [path for method, path in fake.calls if method == "DELETE"]
        assert deletes, f"server {index} got no DELETE"
        assert deletes[0].endswith("note.txt")
        assert not any(path.endswith("note.txt") for path in fake.bodies)
    # The queue is drained once the files are gone.
    assert attachments.pending_deletions("acc-a") == []
    assert attachments.pending_deletions("acc-b") == []


# -- the "clean up orphaned files" path against a live server ---------------

_FILES_NS = "DAV:"


def _multistatus(*entries: tuple[str, bool]) -> bytes:
    """A Nextcloud-shaped PROPFIND answer for the given (href, is_folder) pairs."""
    responses = []
    for href, is_folder in entries:
        resourcetype = "<d:collection/>" if is_folder else ""
        responses.append(
            f"<d:response><d:href>{href}</d:href>"
            f"<d:propstat><d:prop><d:resourcetype>{resourcetype}</d:resourcetype></d:prop>"
            f"<d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>"
        )
    return (
        '<?xml version="1.0"?>'
        f'<d:multistatus xmlns:d="{_FILES_NS}">{"".join(responses)}</d:multistatus>'
    ).encode()


class _FilesHandler(BaseHTTPRequestHandler):
    """Fake Nextcloud Files endpoint: PROPFIND listing + DELETE."""

    base = "/remote.php/dav/files/alice/Todo%20Snake/Attachments"
    listings: ClassVar[dict[str, bytes]] = {}
    calls: ClassVar[list[tuple[str, str]]] = []
    depths: ClassVar[list[str]] = []

    def _send(self, code: int, body: bytes = b"") -> None:
        self.send_response(code)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_PROPFIND(self):
        path = self.path.rstrip("/")
        type(self).calls.append(("PROPFIND", path))
        type(self).depths.append(self.headers.get("Depth", ""))
        body = type(self).listings.get(path)
        self._send(207, body) if body is not None else self._send(404)

    def do_DELETE(self):
        type(self).calls.append(("DELETE", self.path))
        self._send(204)

    def log_message(self, *args):
        pass


@pytest.fixture()
def files_server():
    _FilesHandler.listings = {
        _FilesHandler.base: _multistatus(
            (f"{_FilesHandler.base}/", True),
            (f"{_FilesHandler.base}/u-1/", True),
        ),
        f"{_FilesHandler.base}/u-1": _multistatus(
            (f"{_FilesHandler.base}/u-1/", True),
            (f"{_FilesHandler.base}/u-1/kept.txt", False),
            (f"{_FilesHandler.base}/u-1/orphan.txt", False),
        ),
    }
    _FilesHandler.calls = []
    _FilesHandler.depths = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FilesHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_cleanup_finds_and_deletes_only_unreferenced_files(qapp, tmp_path, files_server):
    from todo_snake.persistence.attachments import SqliteAttachmentRepository
    from todo_snake.service.attachment_service import AttachmentService
    from todo_snake.sync.attachments import find_orphans
    from todo_snake.sync.file_store import NextcloudFileStore

    account = SyncAccount(
        uid="acc-a",
        provider=SyncProvider.NEXTCLOUD,
        server_url=files_server,
        remote_path="tasks",
        username="alice",
        app_password="pw",
    )
    attachments = AttachmentService(SqliteAttachmentRepository(tmp_path / "todos.db"))
    kept = attachments.add("u-1", "kept.txt", b"kept")
    attachments.set_remote_url(
        kept.id,
        "acc-a",
        f"{files_server}{_FilesHandler.base}/u-1/kept.txt",
    )

    store = NextcloudFileStore(account)
    orphans = find_orphans(account, attachments, store)
    assert orphans == [f"{files_server}{_FilesHandler.base}/u-1/orphan.txt"]

    # The referenced file must not be touched, the orphan must go.
    assert store.delete(f"{files_server}{_FilesHandler.base}/u-1/kept.txt") is True
    assert store.delete(orphans[0]) is True
    assert [path for method, path in _FilesHandler.calls if method == "DELETE"] == [
        f"{_FilesHandler.base}/u-1/kept.txt",
        f"{_FilesHandler.base}/u-1/orphan.txt",
    ]
    # Every listing used Depth: 1 — without it the server returns only the
    # folder itself and the cleanup would silently find nothing.
    assert _FilesHandler.depths == ["1", "1"]
    store.close()


def test_sync_removes_leftover_files_from_a_task_folder(qapp, tmp_path, attachment_server):
    """A file in the task's folder that no attachment references is cleaned up.

    Reproduces a leftover whose local record was lost (deleted before removals
    were tracked): it is in no document, so the next sync must drop it.
    """
    from todo_snake.persistence.attachments import SqliteAttachmentRepository
    from todo_snake.persistence.sqlite import SqliteTodoRepository
    from todo_snake.service import TodoService
    from todo_snake.service.attachment_service import AttachmentService
    from todo_snake.sync.journal import SyncJournal
    from todo_snake.sync.manager import SyncManager

    db_path = tmp_path / "todos.db"
    attachments = AttachmentService(SqliteAttachmentRepository(db_path))
    service = TodoService(SqliteTodoRepository(db_path), attachments)
    manager = SyncManager(service, SyncJournal(db_path), attachments=attachments)

    todo = service.add_todo("Has a file")
    attachments.add(todo.uid, "note.txt", b"payload")
    account = SyncAccount(
        provider=SyncProvider.NEXTCLOUD,
        server_url=attachment_server,
        remote_path="tasks",
        username="alice",
        app_password="pw",
    )
    assert manager.trigger_sync(account) is not None

    # The folder now holds the referenced file; add an orphan to it.
    uploaded = next(path for path in _AttachmentHandler.bodies if path.endswith("note.txt"))
    folder = uploaded.rsplit("/", 1)[0]
    leftover = f"{folder}/image.webp"
    _AttachmentHandler.bodies[leftover] = b"old leftover"

    assert manager.trigger_sync(account) is not None

    # The leftover is gone, the referenced file stays.
    assert leftover not in _AttachmentHandler.bodies
    assert uploaded in _AttachmentHandler.bodies
    deletes = [path for method, path in _AttachmentHandler.calls if method == "DELETE"]
    assert leftover in deletes
