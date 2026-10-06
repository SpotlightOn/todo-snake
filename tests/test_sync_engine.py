"""The sync engine is plain Python: no Qt, testable with fakes.

These tests deliberately do *not* use the ``qapp`` fixture — they pin down the
claim that the cycle itself is independent of the UI stack.
"""

from __future__ import annotations

import subprocess
import sys
import types

import pytest

from todo_snake.persistence.sqlite import SqliteTodoRepository
from todo_snake.service import TodoService
from todo_snake.sync.engine import SyncEngine, SyncStats
from todo_snake.sync.errors import SyncTransportError
from todo_snake.sync.journal import SyncJournal


def test_engine_module_imports_without_qt():
    """Importing the cycle must not drag PySide6 into the process."""
    code = (
        "import importlib, sys;"
        " importlib.import_module('todo_snake.sync.engine');"
        " print('PySide6' in sys.modules)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "False", result.stderr


def test_engine_runs_a_cycle_and_reports_stats(tmp_path):
    service, journal = _service(tmp_path)
    service.add_todo("local task")
    transport = _FakeTransport()

    stats = _engine(service, journal, transport).sync(_account())

    assert isinstance(stats, SyncStats)
    assert stats.pushed == 1  # the local task was uploaded
    assert len(transport.uploaded) == 1
    assert "local task" in transport.uploaded[0]["items"][0]["title"]


def test_engine_pulls_remote_tasks_into_the_local_store(tmp_path):
    service, journal = _service(tmp_path)
    transport = _FakeTransport(
        {
            "uid": "remote-1",
            "title": "from the server",
            "priority": "medium",
            "status": "open",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-02T00:00:00+00:00",
        }
    )

    stats = _engine(service, journal, transport).sync(_account())

    assert stats.created == 1
    assert [todo.title for todo in service.list_todos()] == ["from the server"]


def test_engine_removes_leftover_files_but_keeps_referenced_ones(tmp_path):
    """The cycle deletes files in a task's folder that nothing references."""
    service, journal = _service(tmp_path)
    service.add_todo("with files")
    uid = service.list_todos()[0].uid
    store = _FakeFileStore(["https://files/keep.txt", "https://files/leftover.webp"])
    attachments = _FakeAttachments([uid], known={"https://files/keep.txt"})

    engine = SyncEngine(
        service,
        journal,
        attachments=attachments,
        transport_factory=lambda *a, **k: _FakeTransport(),
        file_store_factory=lambda account: store,
    )
    engine.sync(_account())

    assert store.deleted == ["https://files/leftover.webp"]
    assert store.files == ["https://files/keep.txt"]


def test_engine_lets_errors_through(tmp_path):
    """The engine reports nothing itself — the caller decides (see manager)."""
    service, journal = _service(tmp_path)

    class _Broken(_FakeTransport):
        def fetch(self):
            raise SyncTransportError("HTTP 503 Service Unavailable")

    with pytest.raises(SyncTransportError):
        _engine(service, journal, _Broken()).sync(_account())


# -- helpers -----------------------------------------------------------------


def _service(tmp_path):
    database = tmp_path / "todos.db"
    return TodoService(SqliteTodoRepository(database)), SyncJournal(database)


def _engine(service, journal, transport) -> SyncEngine:
    return SyncEngine(service, journal, transport_factory=lambda *args, **kwargs: transport)


def _account():
    """Duck-typed account: the engine only needs uid, provider and a label."""
    return types.SimpleNamespace(uid="acc-1", provider="nextcloud", display_name="Test")


class _FakeFileStore:
    """Records deletions; pretends the given URLs live in the task's folder."""

    def __init__(self, files):
        self.files = list(files)
        self.deleted: list[str] = []

    def delete(self, url):
        self.deleted.append(url)
        self.files.remove(url)
        return True

    def files_of_task(self, todo_uid):
        return list(self.files)

    def close(self):
        pass


class _FakeAttachments:
    """The bits of AttachmentService the cycle uses."""

    def __init__(self, todo_uids, known=()):
        self._todo_uids = list(todo_uids)
        self._known = set(known)

    def list_for(self, todo_uid, *, with_data=False):
        return []

    def names_by_todo(self):
        return {uid: ("file",) for uid in self._todo_uids}

    def remote_urls_for_account(self, account_uid):
        return set(self._known)

    def pending_deletions(self, account_uid):
        return []

    def drop_deletion(self, deletion_id):
        pass


class _FakeTransport:
    """Stands in for a real transport: returns a fixed document, records uploads."""

    def __init__(self, *remote_items):
        self._items = list(remote_items)
        self.uploaded: list[dict] = []
        self.remote_deleted_uids: set[str] = set()

    def fetch(self):
        import json

        body = json.dumps(
            {
                "format": "todo-snake-sync",
                "schema_version": 1,
                "items": self._items,
            }
        ).encode("utf-8")
        return types.SimpleNamespace(found=True, body=body)

    def upload(self, body: bytes) -> None:
        import json

        self.uploaded.append(json.loads(body.decode("utf-8")))

    def close(self) -> None:
        pass
