"""Business logic for todos.

The service owns all rules that are independent of both the storage backend
and the UI: validation, derive timestamps, toggle semantics. It talks only to
the ``TodoRepository`` interface.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime, timezone

from snake_todo.domain.todo import (
    Todo,
    TodoPriority,
    TodoStatus,
    todo_content_digest,
    utc_now,
)
from snake_todo.persistence.base import TodoRepository


class TodoService:
    def __init__(self, repository: TodoRepository):
        self._repository = repository

    def list_todos(self) -> list[Todo]:
        return self._repository.list()

    def add_todo(
        self,
        title: str,
        priority: TodoPriority = TodoPriority.MEDIUM,
        due_date: date | None = None,
    ) -> Todo:
        title = self._require_title(title)
        return self._repository.create(
            Todo(title=title, priority=priority, due_date=due_date)
        )

    def update_todo(
        self,
        todo_id: int,
        *,
        title: str,
        priority: TodoPriority,
        due_date: date | None,
    ) -> Todo:
        todo = self._get_required(todo_id)
        updated = replace(
            todo,
            title=self._require_title(title),
            priority=priority,
            due_date=due_date,
        )
        return self._repository.update(updated)

    def toggle_done(self, todo_id: int) -> Todo:
        """Flip open <-> done and maintain ``completed_at``."""
        todo = self._get_required(todo_id)
        if todo.is_done:
            updated = replace(todo, status=TodoStatus.OPEN, completed_at=None)
        else:
            updated = replace(todo, status=TodoStatus.DONE, completed_at=utc_now())
        return self._repository.update(updated)

    def delete_todo(self, todo_id: int) -> None:
        self._repository.delete(todo_id)

    # -- json import/export ------------------------------------------------------

    def export_json(self) -> str:
        """Serialize all todos to a JSON string (lossless)."""
        todos = self._repository.list()
        return json.dumps(
            [_todo_to_dict(todo) for todo in todos],
            ensure_ascii=False,
            indent=2,
        ) + "\n"

    def import_json(self, payload: str | bytes) -> int:
        """Import todos from a JSON string; returns the number imported.

        Raises ``ValueError`` on malformed data. Entries whose content hash
        (title, priority, due date) already exists are skipped. Imports keep
        their status, timestamps and due dates; ids are stripped so new
        rows are created.
        """
        text = payload.decode("utf-8") if isinstance(payload, bytes) else payload
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Not a valid JSON document: {exc}") from exc

        if not isinstance(data, list):
            raise ValueError("Expected a list of tasks.")

        imported = 0
        for item in data:
            todo = _todo_from_dict(item)
            digest = todo_content_digest(todo)
            if self._repository.content_hash_exists(digest):
                continue
            self._repository.create(todo)
            imported += 1
        return imported

    def _get_required(self, todo_id: int) -> Todo:
        todo = self._repository.get(todo_id)
        if todo is None:
            raise KeyError(f"Task with id {todo_id} does not exist.")
        return todo

    @staticmethod
    def _require_title(title: str) -> str:
        title = title.strip()
        if not title:
            raise ValueError("The title must not be empty.")
        return title


def _todo_to_dict(todo: Todo) -> dict[str, object]:
    return {
        "title": todo.title,
        "priority": todo.priority.value,
        "due_date": todo.due_date.isoformat() if todo.due_date else None,
        "status": todo.status.value,
        "created_at": todo.created_at.astimezone(timezone.utc).isoformat(),
        "completed_at": (
            todo.completed_at.astimezone(timezone.utc).isoformat()
            if todo.completed_at
            else None
        ),
    }


def _todo_from_dict(item: object) -> Todo:
    if not isinstance(item, dict):
        raise ValueError(f"Invalid entry: {item!r}")
    title = item.get("title")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("An entry has no valid title.")
    try:
        priority = TodoPriority(item.get("priority", TodoPriority.MEDIUM.value))
        status = TodoStatus(item.get("status", TodoStatus.OPEN.value))
        due_date = _parse_date(item.get("due_date"))
        created_at = _parse_dt(item.get("created_at"), default=utc_now())
        completed_at = _parse_dt(item.get("completed_at"))
    except ValueError as exc:
        raise ValueError(f"Invalid entry: {item!r}") from exc
    return Todo(
        title=title.strip(),
        priority=priority,
        due_date=due_date,
        status=status,
        created_at=created_at,
        completed_at=completed_at,
    )


def _parse_date(value: object) -> date | None:
    if value is None:
        return None
    return date.fromisoformat(str(value))


def _parse_dt(value: object, default: datetime | None = None) -> datetime | None:
    if value is None:
        return default
    return datetime.fromisoformat(str(value))