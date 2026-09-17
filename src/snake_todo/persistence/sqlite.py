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
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterator

from snake_todo.domain.todo import (
    Todo,
    TodoPriority,
    TodoStatus,
    todo_content_digest,
)
from snake_todo.persistence.base import TodoRepository

_SCHEMA = """
CREATE TABLE IF NOT EXISTS todos (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    title        TEXT    NOT NULL,
    priority     TEXT    NOT NULL,
    due_date     TEXT,
    status       TEXT    NOT NULL,
    created_at   TEXT    NOT NULL,
    completed_at TEXT,
    content_hash TEXT
);
CREATE INDEX IF NOT EXISTS idx_todos_status ON todos (status);
"""


def _datetime_to_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _datetime_from_iso(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value is not None else None


def _date_to_iso(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _date_from_iso(value: str | None) -> date | None:
    return date.fromisoformat(value) if value is not None else None


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
        columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(todos)")
        }
        if "content_hash" not in columns:
            connection.execute(
                "ALTER TABLE todos ADD COLUMN content_hash TEXT"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_todos_content_hash"
                " ON todos (content_hash)"
            )
        backfill = connection.execute(
            "SELECT * FROM todos WHERE content_hash IS NULL"
        ).fetchall()
        for row in backfill:
            connection.execute(
                "UPDATE todos SET content_hash = ? WHERE id = ?",
                (
                    todo_content_digest(SqliteTodoRepository._row_to_todo(row)),
                    row["id"],
                ),
            )

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
        created = dataclasses.replace(todo, content_hash=todo_content_digest(todo))
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO todos
                    (title, priority, due_date, status, created_at, completed_at, content_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    created.title,
                    created.priority.value,
                    _date_to_iso(created.due_date),
                    created.status.value,
                    _datetime_to_iso(created.created_at),
                    _datetime_to_iso(created.completed_at) if created.completed_at else None,
                    created.content_hash,
                ),
            )
        return dataclasses.replace(created, id=cursor.lastrowid)

    def get(self, todo_id: int) -> Todo | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM todos WHERE id = ?", (todo_id,)
            ).fetchone()
        return self._row_to_todo(row) if row is not None else None

    def list(self) -> list[Todo]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM todos ORDER BY id DESC"
            ).fetchall()
        return [self._row_to_todo(row) for row in rows]

    def update(self, todo: Todo) -> Todo:
        if todo.id is None:
            raise ValueError("Cannot update a todo without an id.")
        updated = dataclasses.replace(todo, content_hash=todo_content_digest(todo))
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE todos
                   SET title = ?, priority = ?, due_date = ?, status = ?,
                       created_at = ?, completed_at = ?, content_hash = ?
                 WHERE id = ?
                """,
                (
                    updated.title,
                    updated.priority.value,
                    _date_to_iso(updated.due_date),
                    updated.status.value,
                    _datetime_to_iso(updated.created_at),
                    _datetime_to_iso(updated.completed_at) if updated.completed_at else None,
                    updated.content_hash,
                    updated.id,
                ),
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
            title=row["title"],
            priority=TodoPriority(row["priority"]),
            due_date=_date_from_iso(row["due_date"]),
            status=TodoStatus(row["status"]),
            created_at=_datetime_from_iso(row["created_at"]) or datetime.now(timezone.utc),
            completed_at=_datetime_from_iso(row["completed_at"]),
        )