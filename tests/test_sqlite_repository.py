"""Tests for the SQLite repository."""

from datetime import date

import pytest

from todo_snake.domain import Todo, TodoPriority, TodoStatus
from todo_snake.persistence.sqlite import SqliteTodoRepository


@pytest.fixture()
def repo(tmp_path):
    return SqliteTodoRepository(tmp_path / "todos.db")


def test_create_assigns_id(repo):
    todo = repo.create(Todo(title="first"))
    assert todo.id is not None
    assert repo.get(todo.id).title == "first"


def test_create_roundtrip_all_fields(repo):
    created = repo.create(
        Todo(
            title="high, soon",
            priority=TodoPriority.HIGH,
            due_date=date(2026, 9, 30),
        )
    )
    loaded = repo.get(created.id)
    assert loaded.priority is TodoPriority.HIGH
    assert loaded.due_date == date(2026, 9, 30)
    assert loaded.status is TodoStatus.OPEN
    assert loaded.completed_at is None
    assert loaded.created_at == created.created_at


def test_list_newest_first(repo):
    first = repo.create(Todo(title="a"))
    second = repo.create(Todo(title="b"))
    ids = [todo.id for todo in repo.list()]
    assert ids == [second.id, first.id]


def test_list_empty(repo):
    assert repo.list() == []


def test_update(repo):
    created = repo.create(Todo(title="old", priority=TodoPriority.LOW))
    changed = Todo(
        id=created.id,
        title="new",
        priority=TodoPriority.HIGH,
        due_date=date(2026, 9, 1),
        status=TodoStatus.DONE,
        created_at=created.created_at,
        completed_at=created.completed_at,
    )
    repo.update(changed)
    loaded = repo.get(created.id)
    assert loaded.title == "new"
    assert loaded.priority is TodoPriority.HIGH
    assert loaded.status is TodoStatus.DONE


def test_delete_removes_row(repo):
    created = repo.create(Todo(title="bye"))
    repo.delete(created.id)
    assert repo.get(created.id) is None


def test_delete_missing_is_noop(repo):
    repo.delete(42)  # must not raise


def test_get_missing_returns_none(repo):
    assert repo.get(999) is None


def test_persistence_across_instances(tmp_path):
    path = tmp_path / "todos.db"
    repo_a = SqliteTodoRepository(path)
    todo = repo_a.create(Todo(title="survived"))
    repo_b = SqliteTodoRepository(path)
    assert repo_b.get(todo.id).title == "survived"


def test_note_roundtrip(repo):
    created = repo.create(Todo(title="noted", note="first line\nsecond line"))
    loaded = repo.get(created.id)
    assert loaded.note == "first line\nsecond line"


def test_update_persists_note(repo):
    created = repo.create(Todo(title="x", note="old note"))
    updated = Todo(
        id=created.id,
        title="x",
        priority=created.priority,
        due_date=created.due_date,
        note="new note",
        status=created.status,
        created_at=created.created_at,
        completed_at=created.completed_at,
    )
    repo.update(updated)
    assert repo.get(created.id).note == "new note"


def test_migration_adds_note_column(tmp_path):
    import sqlite3

    path = tmp_path / "old.db"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE todos (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            title        TEXT    NOT NULL,
            priority     TEXT    NOT NULL,
            due_date     TEXT,
            status       TEXT    NOT NULL,
            created_at   TEXT    NOT NULL,
            completed_at TEXT,
            content_hash TEXT
        );
        INSERT INTO todos (title, priority, status, created_at)
        VALUES ('legacy', 'low', 'open', '2026-01-01T00:00:00+00:00');
        """
    )
    connection.commit()
    connection.close()

    repo = SqliteTodoRepository(path)
    assert repo.list()[0].note == ""
    created = repo.create(Todo(title="new", note="hi"))
    assert repo.get(created.id).note == "hi"
