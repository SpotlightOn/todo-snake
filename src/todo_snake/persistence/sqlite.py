"""SQLite backend for ``TodoRepository``.

Design notes:
* Timestamps and dates are stored as ISO 8601 text. This keeps the schema
  portable — a future PostgreSQL backend (NeonDB/Supabase) can reuse the
  same column formats.
* Status/priority are stored as short, self-documenting strings
  (``"open"``, ``"high"``, ...) instead of magic integers.
* One short-lived connection per operation keeps this trivially
  thread-safe and avoids stale-transaction bugs in a single-writer app.
"""

from __future__ import annotations

import dataclasses
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from todo_snake.domain.todo import (
    Todo,
    TodoPriority,
    TodoStatus,
    new_uid,
    todo_content_digest,
    utc_now,
)
from todo_snake.persistence.base import TodoRepository

_SCHEMA = """
CREATE TABLE IF NOT EXISTS todos (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    title        TEXT    NOT NULL,
    priority     TEXT    NOT NULL,
    due_at       TEXT,
    note         TEXT    NOT NULL DEFAULT '',
    status       TEXT    NOT NULL,
    created_at   TEXT    NOT NULL,
    completed_at TEXT,
    content_hash TEXT,
    uid          TEXT,
    updated_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_todos_status ON todos (status);
"""


def _datetime_to_iso(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat() if value is not None else None


def _datetime_from_iso(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value)
    # Legacy values may be date-only ("2026-10-01") or naive; treat as UTC.
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _todo_values(todo: Todo) -> tuple[object, ...]:
    """Column values in the same order as the INSERT/SET column lists."""
    return (
        todo.title,
        todo.priority.value,
        _datetime_to_iso(todo.due_at),
        todo.note,
        todo.status.value,
        _datetime_to_iso(todo.created_at),
        _datetime_to_iso(todo.completed_at) if todo.completed_at else None,
        todo.content_hash,
        todo.uid,
        _datetime_to_iso(todo.updated_at),
    )


class SqliteTodoRepository(TodoRepository):
    def __init__(self, db_path: Path):
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(_SCHEMA)
            self._migrate(connection)

    @staticmethod
    def _migrate(connection: sqlite3.Connection) -> None:
        """Bring older databases up to the current schema."""
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(todos)")}
        if "content_hash" not in columns:
            connection.execute("ALTER TABLE todos ADD COLUMN content_hash TEXT")
        if "note" not in columns:
            connection.execute("ALTER TABLE todos ADD COLUMN note TEXT NOT NULL DEFAULT ''")
        if "updated_at" not in columns:
            connection.execute("ALTER TABLE todos ADD COLUMN updated_at TEXT")
        if "uid" not in columns:
            connection.execute("ALTER TABLE todos ADD COLUMN uid TEXT")
        if "due_at" not in columns and "due_date" in columns:
            connection.execute("ALTER TABLE todos RENAME COLUMN due_date TO due_at")
        for row in connection.execute("SELECT * FROM todos").fetchall():
            updates = {}
            if row["uid"] is None:
                updates["uid"] = new_uid()
            if row["updated_at"] is None:
                updates["updated_at"] = row["created_at"]
            if row["content_hash"] is None:
                updates["content_hash"] = todo_content_digest(
                    SqliteTodoRepository._row_to_todo(row)
                )
            if updates:
                assignments = ", ".join(f"{column} = ?" for column in updates)
                connection.execute(
                    f"UPDATE todos SET {assignments} WHERE id = ?",
                    (*updates.values(), row["id"]),
                )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_todos_content_hash ON todos (content_hash)"
        )
        connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_todos_uid ON todos (uid)")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self._db_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
        except Exception:
            connection.rollback()
            raise
        else:
            connection.commit()
        finally:
            connection.close()

    def create(self, todo: Todo) -> Todo:
        created = dataclasses.replace(
            todo,
            uid=todo.uid or new_uid(),
            updated_at=todo.updated_at or utc_now(),
            content_hash=todo_content_digest(todo),
        )
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO todos
                    (title, priority, due_at, note, status, created_at, completed_at,
                     content_hash, uid, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                _todo_values(created),
            )
        return dataclasses.replace(created, id=cursor.lastrowid)

    def get(self, todo_id: int) -> Todo | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM todos WHERE id = ?", (todo_id,)).fetchone()
        return self._row_to_todo(row) if row is not None else None

    def get_by_uid(self, uid: str) -> Todo | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM todos WHERE uid = ?", (uid,)).fetchone()
        return self._row_to_todo(row) if row is not None else None

    def list(self) -> list[Todo]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM todos ORDER BY id DESC").fetchall()
        return [self._row_to_todo(row) for row in rows]

    def update(self, todo: Todo) -> Todo:
        if todo.id is None:
            raise ValueError("Cannot update a todo without an id.")
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM todos WHERE id = ?", (todo.id,)).fetchone()
            if row is None:
                raise KeyError(f"Task with id {todo.id} does not exist.")
            existing = self._row_to_todo(row)
            updated = dataclasses.replace(
                todo,
                uid=todo.uid or existing.uid,
                updated_at=todo.updated_at or utc_now(),
                content_hash=todo_content_digest(todo),
            )
            connection.execute(
                """
                UPDATE todos
                   SET title = ?, priority = ?, due_at = ?, note = ?, status = ?,
                       created_at = ?, completed_at = ?, content_hash = ?, uid = ?,
                       updated_at = ?
                 WHERE id = ?
                """,
                (*_todo_values(updated), updated.id),
            )
        return updated

    def delete(self, todo_id: int) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM todos WHERE id = ?", (todo_id,))

    def content_hash_exists(self, content_hash: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM todos WHERE content_hash = ? LIMIT 1",
                (content_hash,),
            ).fetchone()
        return row is not None

    @staticmethod
    def _row_to_todo(row: sqlite3.Row) -> Todo:
        return Todo(
            id=row["id"],
            uid=row["uid"],
            title=row["title"],
            priority=TodoPriority(row["priority"]),
            due_at=_datetime_from_iso(row["due_at"]),
            note=row["note"] or "",
            status=TodoStatus(row["status"]),
            created_at=_datetime_from_iso(row["created_at"]) or datetime.now(timezone.utc),
            completed_at=_datetime_from_iso(row["completed_at"]),
            updated_at=_datetime_from_iso(row["updated_at"]),
        )
