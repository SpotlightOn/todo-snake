"""Domain model for todos — pure Python, no Qt or storage dependencies."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum


def utc_now() -> datetime:
    """Timezone-aware UTC timestamp for ISO storage."""
    return datetime.now(timezone.utc)


class TodoStatus(Enum):
    OPEN = "open"
    DONE = "done"


class TodoPriority(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class Todo:
    title: str
    priority: TodoPriority = TodoPriority.MEDIUM
    due_date: date | None = None
    status: TodoStatus = TodoStatus.OPEN
    created_at: datetime = field(default_factory=utc_now)
    completed_at: datetime | None = None
    id: int | None = None
    content_hash: str | None = None

    @property
    def is_done(self) -> bool:
        return self.status is TodoStatus.DONE


def todo_content_digest(todo: Todo) -> str:
    """Stable identity digest over title, priority and due date.

    Status and timestamps are intentionally excluded: toggling done does not
    change a task's identity, so re-importing an older export still dedupes.
    """
    payload = json.dumps(
        [
            todo.title.strip().casefold(),
            todo.priority.value,
            todo.due_date.isoformat() if todo.due_date else None,
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()