"""Due-date reminders: decide which tasks deserve a notification.

Pure, unit-testable logic plus a small ``QSettings``-backed store that remembers
which ``(task, due time)`` pairs were already announced and which were snoozed,
so a task is not announced on every timer tick.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from PySide6.QtCore import QSettings

from todo_snake.config import APP_NAME, ORG_NAME
from todo_snake.domain.todo import Todo

_GROUP = "reminders"
_ANNOUNCED_KEY = "announced"
_SNOOZED_KEY = "snoozed"

SNOOZE_CHOICES_MINUTES = (2, 5, 10)


def reminder_key(todo: Todo) -> str | None:
    """Stable key for one ``(task, due time)`` pair; ``None`` without a due date."""
    if todo.due_at is None:
        return None
    due = todo.due_at.astimezone(timezone.utc).isoformat()
    return f"{todo.uid}@{due}"


def active_keys(todos: list[Todo]) -> set[str]:
    """Keys of all open tasks that currently have a due date."""
    keys: set[str] = set()
    for todo in todos:
        if todo.is_done:
            continue
        key = reminder_key(todo)
        if key is not None:
            keys.add(key)
    return keys


def pending_reminders(
    todos: list[Todo],
    now: datetime,
    announced: set[str],
    snoozed: dict[str, datetime],
) -> list[Todo]:
    """Open tasks whose reminder should fire now.

    A task fires once when its due time passes; after a snooze it fires again
    once the snooze elapses.
    """
    pending: list[Todo] = []
    for todo in todos:
        if todo.is_done or todo.due_at is None or todo.due_at > now:
            continue
        key = reminder_key(todo)
        if key is None:
            continue
        if key in snoozed:
            if snoozed[key] <= now:
                pending.append(todo)
            continue
        if key not in announced:
            pending.append(todo)
    return pending


def next_reminder_moment(
    todos: list[Todo],
    now: datetime,
    announced: set[str],
    snoozed: dict[str, datetime],
) -> datetime | None:
    """The soonest future moment a reminder becomes due, or ``None``."""
    candidates: list[datetime] = []
    for todo in todos:
        if todo.is_done or todo.due_at is None:
            continue
        key = reminder_key(todo)
        if key is None:
            continue
        if key in snoozed:
            if snoozed[key] > now:
                candidates.append(snoozed[key])
            continue
        if key not in announced and todo.due_at > now:
            candidates.append(todo.due_at)
    return min(candidates) if candidates else None


class ReminderStore:
    """Persists announced keys and per-key snooze deadlines in ``QSettings``."""

    def __init__(self, settings: QSettings | None = None):
        self._settings = settings if settings is not None else QSettings(ORG_NAME, APP_NAME)

    def load(self) -> tuple[set[str], dict[str, datetime]]:
        self._settings.beginGroup(_GROUP)
        announced_raw = self._settings.value(_ANNOUNCED_KEY, [])
        snoozed_raw = self._settings.value(_SNOOZED_KEY, "{}")
        self._settings.endGroup()

        if isinstance(announced_raw, str):
            announced = {announced_raw} if announced_raw else set()
        else:
            announced = set(announced_raw or [])

        try:
            parsed = json.loads(snoozed_raw if isinstance(snoozed_raw, str) else "{}")
        except ValueError:
            parsed = {}
        snoozed = {
            key: datetime.fromisoformat(value)
            for key, value in parsed.items()
            if isinstance(value, str)
        }
        return announced, snoozed

    def save(self, announced: set[str], snoozed: dict[str, datetime]) -> None:
        self._settings.beginGroup(_GROUP)
        self._settings.setValue(_ANNOUNCED_KEY, sorted(announced))
        self._settings.setValue(
            _SNOOZED_KEY,
            json.dumps({key: value.isoformat() for key, value in snoozed.items()}),
        )
        self._settings.endGroup()
        self._settings.sync()
