"""Tests for the todo service (business logic)."""

from datetime import date

import pytest

from todo_snake.domain import TodoPriority, TodoStatus
from todo_snake.persistence.sqlite import SqliteTodoRepository
from todo_snake.service import TodoService


@pytest.fixture()
def service(tmp_path):
    return TodoService(SqliteTodoRepository(tmp_path / "todos.db"))


def test_add_trims_title(service):
    todo = service.add_todo("  shopping  ")
    assert todo.title == "shopping"


def test_add_rejects_empty_title(service):
    with pytest.raises(ValueError):
        service.add_todo("   ")


def test_add_sets_defaults(service):
    todo = service.add_todo("no details")
    assert todo.priority is TodoPriority.MEDIUM
    assert todo.due_date is None
    assert todo.status is TodoStatus.OPEN
    assert todo.note == ""


def test_add_and_update_note(service):
    created = service.add_todo("noted", note="  remember the milk  ")
    assert created.note == "remember the milk"
    updated = service.update_todo(
        created.id,
        title="noted",
        priority=TodoPriority.MEDIUM,
        due_date=None,
        note="multi\nline note",
    )
    assert updated.note == "multi\nline note"
    assert service.list_todos()[0].note == "multi\nline note"


def test_toggle_done_sets_and_clears_completed_at(service):
    todo = service.add_todo("remember this")
    assert todo.completed_at is None

    done = service.toggle_done(todo.id)
    assert done.is_done
    assert done.completed_at is not None

    reopened = service.toggle_done(todo.id)
    assert not reopened.is_done
    assert reopened.completed_at is None


def test_update_changes_fields(service):
    todo = service.add_todo("old", TodoPriority.LOW)
    updated = service.update_todo(
        todo.id,
        title=" new ",
        priority=TodoPriority.HIGH,
        due_date=date(2026, 9, 30),
        note="details",
    )
    assert updated.title == "new"
    assert updated.priority is TodoPriority.HIGH
    assert updated.due_date == date(2026, 9, 30)
    assert updated.note == "details"


def test_update_rejects_empty_title(service):
    todo = service.add_todo("stays")
    with pytest.raises(ValueError):
        service.update_todo(todo.id, title="  ", priority=TodoPriority.LOW, due_date=None, note="")
    assert service.list_todos()[0].title == "stays"


def test_update_missing_raises(service):
    with pytest.raises(KeyError):
        service.update_todo(42, title="x", priority=TodoPriority.LOW, due_date=None, note="")


def test_toggle_missing_raises(service):
    with pytest.raises(KeyError):
        service.toggle_done(42)


def test_delete(service):
    todo = service.add_todo("get rid of this")
    service.delete_todo(todo.id)
    assert service.list_todos() == []


def test_synced_create_preserves_uid_and_timestamps(service):
    from datetime import datetime, timezone

    from todo_snake.domain import Todo

    stamp = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    created = service.create_synced(
        Todo(uid="remote-uid", title="from cloud", updated_at=stamp, created_at=stamp)
    )
    assert created.uid == "remote-uid"
    assert created.updated_at == stamp
    assert service.find_by_uid("remote-uid").title == "from cloud"


def test_delete_by_uid(service):
    from todo_snake.domain import Todo

    created = service.create_synced(Todo(uid="to-remove", title="gone soon"))
    service.delete_by_uid("to-remove")
    assert service.find_by_uid("to-remove") is None
    assert created.id not in [t.id for t in service.list_todos()]


def test_delete_by_uid_missing_is_noop(service):
    service.delete_by_uid("missing")


def test_update_synced_keeps_remote_timestamp(service):
    from datetime import datetime, timezone

    from todo_snake.domain import Todo, TodoPriority

    service.create_synced(
        Todo(
            uid="sync-uid",
            title="before",
            updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
    )
    local = service.find_by_uid("sync-uid")
    remote_stamp = datetime(2026, 1, 2, tzinfo=timezone.utc)
    imported_as_local = Todo(
        id=local.id,
        uid="sync-uid",
        title="after",
        priority=TodoPriority.HIGH,
        note="remote note",
        status=local.status,
        created_at=local.created_at,
        completed_at=local.completed_at,
        updated_at=remote_stamp,
    )
    service.update_synced(imported_as_local)
    loaded = service.find_by_uid("sync-uid")
    assert loaded.title == "after"
    assert loaded.updated_at == remote_stamp


def test_list_order(service):
    service.add_todo("a")
    service.add_todo("b")
    assert [t.title for t in service.list_todos()] == ["b", "a"]


def test_added_todo_is_persisted(service):
    service.add_todo("something")
    todo = service.list_todos()[0]
    assert service.list_todos()[0].title == "something"
    assert todo.id is not None


def test_export_import_roundtrip(service, tmp_path):
    created = service.add_todo(
        "shopping", TodoPriority.HIGH, date(2026, 10, 1), note="two lines\nof text"
    )
    service.toggle_done(created.id)
    payload = service.export_json()

    other = TodoService(SqliteTodoRepository(tmp_path / "other.db"))
    existing = other.add_todo("stock")
    imported = other.import_json(payload)
    assert imported == 1
    todos = {t.title: t for t in other.list_todos()}
    assert set(todos) == {"stock", "shopping"}
    todo = todos["shopping"]
    assert todo.id != existing.id
    assert todo.priority is TodoPriority.HIGH
    assert todo.due_date == date(2026, 10, 1)
    assert todo.note == "two lines\nof text"
    assert todo.is_done
    assert todo.completed_at is not None


def test_export_empty_is_valid_json(service, tmp_path):
    payload = service.export_json()
    other = TodoService(SqliteTodoRepository(tmp_path / "empty.db"))
    assert other.import_json(payload) == 0


def test_import_missing_note_defaults_empty(service, tmp_path):
    payload = '[{"title": "bare"}]'
    other = TodoService(SqliteTodoRepository(tmp_path / "bare.db"))
    assert other.import_json(payload) == 1
    assert other.list_todos()[0].note == ""


def test_import_rejects_invalid_json(service):
    with pytest.raises(ValueError):
        service.import_json("{ kaputt")


def test_import_rejects_missing_title(service):
    with pytest.raises(ValueError):
        service.import_json('[{"title": ""}]')


def test_import_multiple_and_order(service, tmp_path):
    payload = '[{"title": "a"}, {"title": "b"}, {"title": "c"}]'
    other = TodoService(SqliteTodoRepository(tmp_path / "multi.db"))
    assert other.import_json(payload) == 3
    assert [t.title for t in other.list_todos()] == ["c", "b", "a"]


def test_import_skips_duplicates(service, tmp_path):
    payload = '[{"title": "Shopping"}, {"title": "  shopping  "}, {"title": "new"}]'
    other = TodoService(SqliteTodoRepository(tmp_path / "dedup.db"))
    assert other.import_json(payload) == 2
    assert [t.title for t in other.list_todos()] == ["new", "Shopping"]


def test_import_second_run_skips_all(service, tmp_path):
    other = TodoService(SqliteTodoRepository(tmp_path / "twice.db"))
    payload = '[{"title": "a"}, {"title": "b"}]'
    assert other.import_json(payload) == 2
    assert other.import_json(payload) == 0
    assert len(other.list_todos()) == 2
