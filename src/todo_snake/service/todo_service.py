"""Business logic for todos.

The service owns all rules that are independent of both the storage backend
and the UI: validation, derive timestamps, toggle semantics. It talks only to
the ``TodoRepository`` interface.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone

from todo_snake.domain.todo import (
    Todo,
    TodoPriority,
    TodoStatus,
    todo_content_digest,
    utc_now,
)
from todo_snake.persistence.base import TodoRepository
from todo_snake.recurrence import next_occurrence


def _anchor_recurrence(
    recurrence: str | None,
    due_at: datetime | None,
    start_at: datetime | None,
) -> tuple[datetime | None, datetime | None]:
    """A recurring VTODO needs an anchor (DTSTART/DUE); without one the server
    rejects it and Nextcloud Tasks cannot show the repetition. Ensure both are
    present and equal by falling back on each other (or "now")."""
    if not recurrence:
        return due_at, start_at
    if due_at is None and start_at is not None:
        due_at = start_at
    if start_at is None and due_at is not None:
        start_at = due_at
    if due_at is None:
        due_at = utc_now()
        start_at = due_at
    return due_at, start_at


class TodoService:
    def __init__(self, repository: TodoRepository, attachments=None):
        self._repository = repository
        # Optional AttachmentService: purged alongside a deleted task.
        self._attachments = attachments

    def list_todos(self) -> list[Todo]:
        return self._repository.list()

    def add_todo(
        self,
        title: str,
        priority: TodoPriority = TodoPriority.MEDIUM,
        due_at: datetime | None = None,
        note: str = "",
        *,
        start_at: datetime | None = None,
        due_all_day: bool = False,
        remind_before: int = 0,
        status: TodoStatus = TodoStatus.OPEN,
        recurrence: str | None = None,
    ) -> Todo:
        title = self._require_title(title)
        due_at, start_at = _anchor_recurrence(recurrence, due_at, start_at)
        return self._repository.create(
            Todo(
                title=title,
                priority=priority,
                due_at=due_at,
                note=note.strip(),
                start_at=start_at,
                due_all_day=due_all_day,
                remind_before=max(0, int(remind_before)),
                status=status,
                completed_at=utc_now() if status is TodoStatus.DONE else None,
                recurrence=recurrence,
            )
        )

    def update_todo(
        self,
        todo_id: int,
        *,
        title: str,
        priority: TodoPriority,
        due_at: datetime | None,
        note: str,
        start_at: datetime | None = None,
        due_all_day: bool = False,
        remind_before: int = 0,
        status: TodoStatus | None = None,
        recurrence: str | None = None,
    ) -> Todo:
        todo = self._get_required(todo_id)
        due_at, start_at = _anchor_recurrence(recurrence, due_at, start_at)
        updated = replace(
            todo,
            title=self._require_title(title),
            priority=priority,
            due_at=due_at,
            note=note.strip(),
            start_at=start_at,
            due_all_day=due_all_day,
            remind_before=max(0, int(remind_before)),
            status=status if status is not None else todo.status,
            updated_at=utc_now(),
            recurrence=recurrence,
        )
        return self._repository.update(updated)

    def set_status(self, todo_id: int, status: TodoStatus) -> Todo:
        """Set a task's status explicitly (open / in progress / done).

        Completing a *recurring* task does not mark it done: it advances to the
        next occurrence instead."""
        todo = self._get_required(todo_id)
        if status is TodoStatus.DONE:
            advanced = self._advance_recurrence(todo)
            if advanced is not None:
                return self._repository.update(advanced)
        completed_at = todo.completed_at
        if status is TodoStatus.DONE:
            completed_at = todo.completed_at or utc_now()
        else:
            completed_at = None
        return self._repository.update(
            replace(todo, status=status, completed_at=completed_at, updated_at=utc_now())
        )

    def _advance_recurrence(self, todo: Todo) -> Todo | None:
        """Return the same task moved to its next occurrence, or ``None`` when
        it does not repeat (any longer)."""
        nxt = next_occurrence(todo.due_at, todo.recurrence)
        if nxt is None:
            return None
        next_start = next_occurrence(todo.start_at, todo.recurrence) if todo.start_at else None
        return replace(
            todo,
            due_at=nxt,
            start_at=next_start,
            status=TodoStatus.OPEN,
            completed_at=None,
            updated_at=utc_now(),
        )

    def toggle_done(self, todo_id: int) -> Todo:
        """Flip open <-> done. Completing a *recurring* task advances it to the
        next occurrence instead of marking it done (maintains ``completed_at``
        for normal tasks)."""
        todo = self._get_required(todo_id)
        if todo.is_done:
            updated = replace(todo, status=TodoStatus.OPEN, completed_at=None, updated_at=utc_now())
        else:
            advanced = self._advance_recurrence(todo)
            if advanced is not None:
                return self._repository.update(advanced)
            updated = replace(
                todo,
                status=TodoStatus.DONE,
                completed_at=utc_now(),
                updated_at=utc_now(),
            )
        return self._repository.update(updated)

    def delete_todo(self, todo_id: int) -> None:
        todo = self._repository.get(todo_id)
        self._repository.delete(todo_id)
        if todo is not None and todo.uid and self._attachments is not None:
            self._attachments.delete_for_todo(todo.uid)

    # -- sync support ------------------------------------------------...

    def create_synced(self, todo: Todo) -> Todo:
        """Persist a todo coming from a remote device, keeping its uid and
        timestamps intact."""
        return self._repository.create(todo)

    def update_synced(self, todo: Todo) -> Todo:
        """Persist a remote update, keeping uid and remote timestamps."""
        return self._repository.update(todo)

    def find_by_uid(self, uid: str) -> Todo | None:
        """Look up a todo by its device-stable uid."""
        return self._repository.get_by_uid(uid)

    def delete_by_uid(self, uid: str) -> None:
        """Delete the todo with the given uid (no-op if it does not exist)."""
        todo = self._repository.get_by_uid(uid)
        if todo is not None and todo.id is not None:
            self._repository.delete(todo.id)
        if self._attachments is not None:
            self._attachments.delete_for_todo(uid)

    # -- json import/export ------------------------------------------------------

    def export_json(self) -> str:
        """Serialize all todos to a JSON string (lossless)."""
        todos = self._repository.list()
        return (
            json.dumps(
                [_todo_to_dict(todo) for todo in todos],
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )

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
            raise TypeError("Expected a list of tasks.")

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
        "due_at": (todo.due_at.astimezone(timezone.utc).isoformat() if todo.due_at else None),
        "note": todo.note,
        "status": todo.status.value,
        "created_at": todo.created_at.astimezone(timezone.utc).isoformat(),
        "completed_at": (
            todo.completed_at.astimezone(timezone.utc).isoformat() if todo.completed_at else None
        ),
        "start_at": (todo.start_at.astimezone(timezone.utc).isoformat() if todo.start_at else None),
        "due_all_day": todo.due_all_day,
        "remind_before": todo.remind_before,
        "recurrence": todo.recurrence,
    }


def _todo_from_dict(item: object) -> Todo:
    if not isinstance(item, dict):
        raise TypeError(f"Invalid entry: {item!r}")
    title = item.get("title")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("An entry has no valid title.")
    try:
        priority = TodoPriority(item.get("priority", TodoPriority.MEDIUM.value))
        status = TodoStatus(item.get("status", TodoStatus.OPEN.value))
        due_at = _parse_dt(item.get("due_at") or item.get("due_date"))
        start_at = _parse_dt(item.get("start_at"))
        created_at = _parse_dt(item.get("created_at"), default=utc_now())
        completed_at = _parse_dt(item.get("completed_at"))
    except ValueError as exc:
        raise ValueError(f"Invalid entry: {item!r}") from exc
    return Todo(
        title=title.strip(),
        priority=priority,
        due_at=due_at,
        note=_parse_note(item.get("note")),
        status=status,
        created_at=created_at,
        completed_at=completed_at,
        start_at=start_at,
        due_all_day=bool(item.get("due_all_day", False)),
        remind_before=max(0, int(item.get("remind_before") or 0)),
        recurrence=item.get("recurrence") or None,
    )


def _parse_note(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()


def _parse_dt(value: object, default: datetime | None = None) -> datetime | None:
    if value is None or value == "":
        return default
    parsed = datetime.fromisoformat(str(value))
    # Legacy values may be date-only ("2026-10-01") or naive; treat as UTC.
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
