"""Sync document: a server-side snapshot of todos plus merge logic.

The document is a pure-data, device-agnostic representation: every item is
identified by its stable ``uid`` and carries an ``updated_at`` timestamp for
last-write-wins conflict resolution. Tombstones (``deleted: true``) propagate
deletions across devices, preventing the "resurrection" problem where a second
device re-uploads an item that the first device already deleted.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

from todo_snake.domain.todo import Todo, TodoPriority, TodoStatus, todo_content_digest

_FORMAT = "todo-snake-sync"
_SCHEMA_VERSION = 1


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _from_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


@dataclass(frozen=True)
class SyncItem:
    uid: str
    title: str
    priority: TodoPriority
    due_at: datetime | None
    note: str
    status: TodoStatus
    created_at: datetime
    completed_at: datetime | None
    updated_at: datetime
    deleted: bool = False

    @classmethod
    def from_todo(cls, todo: Todo) -> SyncItem:
        if todo.uid is None:
            raise ValueError("Cannot build a sync item from a todo without a uid.")
        return cls(
            uid=todo.uid,
            title=todo.title,
            priority=todo.priority,
            due_at=todo.due_at,
            note=todo.note,
            status=todo.status,
            created_at=todo.created_at,
            completed_at=todo.completed_at,
            updated_at=todo.updated_at or todo.created_at,
        )

    def to_todo(self) -> Todo:
        return Todo(
            uid=self.uid,
            title=self.title,
            priority=self.priority,
            due_at=self.due_at,
            note=self.note,
            status=self.status,
            created_at=self.created_at,
            completed_at=self.completed_at,
            updated_at=self.updated_at,
            content_hash=todo_content_digest(
                Todo(
                    title=self.title,
                    priority=self.priority,
                    due_at=self.due_at,
                )
            ),
        )

    @classmethod
    def tombstone(cls, uid: str, deleted_at: datetime) -> SyncItem:
        """A tombstone: remembers a deletion so other devices propagate it."""
        return cls(
            uid=uid,
            title="",
            priority=TodoPriority.MEDIUM,
            due_at=None,
            note="",
            status=TodoStatus.OPEN,
            created_at=deleted_at,
            completed_at=None,
            updated_at=deleted_at,
            deleted=True,
        )

    # -- serialization ------------------------------------------------------

    def to_dict(self) -> dict[str, object]:
        return {
            "uid": self.uid,
            "title": self.title,
            "priority": self.priority.value,
            "due_at": _iso(self.due_at) if self.due_at else None,
            "note": self.note,
            "status": self.status.value,
            "created_at": _iso(self.created_at),
            "completed_at": _iso(self.completed_at) if self.completed_at else None,
            "updated_at": _iso(self.updated_at),
            "deleted": self.deleted,
        }

    @classmethod
    def from_dict(cls, data: object) -> SyncItem:
        if not isinstance(data, dict):
            raise TypeError(f"Invalid sync item: {data!r}")
        try:
            uid = data["uid"]
            if not isinstance(uid, str) or not uid:
                raise ValueError("Sync item has no valid uid.")
            title = data["title"]
            deleted = bool(data.get("deleted", False))
            if not isinstance(title, str) or (not deleted and not title.strip()):
                raise ValueError("Sync item has no valid title.")
            return cls(
                uid=uid,
                title=title.strip(),
                priority=TodoPriority(data.get("priority", TodoPriority.MEDIUM.value)),
                due_at=(
                    _from_iso(str(data["due_at"]))
                    if data.get("due_at")
                    else _from_iso(str(data["due_date"]))
                    if data.get("due_date")
                    else None
                ),
                note=str(data.get("note", "")),
                status=TodoStatus(data.get("status", TodoStatus.OPEN.value)),
                created_at=_from_iso(str(data["created_at"])),
                completed_at=(
                    _from_iso(str(data["completed_at"])) if data.get("completed_at") else None
                ),
                updated_at=_from_iso(str(data["updated_at"])),
                deleted=deleted,
            )
        except (KeyError, ValueError) as exc:
            raise ValueError(f"Invalid sync item: {data!r}") from exc


@dataclass
class SyncDocument:
    items: dict[str, SyncItem]
    updated_at: datetime | None = None

    @classmethod
    def empty(cls) -> SyncDocument:
        return cls(items={})

    @classmethod
    def from_local(
        cls,
        todos: list[Todo],
        tombstones: dict[str, datetime],
        *,
        updated_at: datetime | None = None,
    ) -> SyncDocument:
        items: dict[str, SyncItem] = {}
        for todo in todos:
            if todo.uid is None:
                continue
            items[todo.uid] = SyncItem.from_todo(todo)
        for uid, stamp in tombstones.items():
            items.setdefault(uid, SyncItem.tombstone(uid, stamp))
        return cls(items=items, updated_at=updated_at)

    # -- serialization ------------------------------------------------------

    def to_json(self) -> str:
        document = {
            "format": _FORMAT,
            "schema_version": _SCHEMA_VERSION,
            "updated_at": _iso(self.updated_at or datetime.now(timezone.utc)),
            "items": sorted(
                (item.to_dict() for item in self.items.values()),
                key=lambda item: item["uid"],
            ),
        }
        return json.dumps(document, ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, payload: str) -> SyncDocument:
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Not a valid sync document: {exc}") from exc
        if not isinstance(data, dict) or data.get("format") != _FORMAT:
            raise ValueError("Not a Todo Snake sync document.")
        items_raw = data.get("items")
        if not isinstance(items_raw, list):
            raise TypeError("Sync document has no valid items list.")
        items = {item.uid: item for item in (SyncItem.from_dict(raw) for raw in items_raw)}
        updated_at_raw = data.get("updated_at")
        return cls(
            items=items,
            updated_at=_from_iso(str(updated_at_raw)) if updated_at_raw else None,
        )


def merge_documents(
    local: SyncDocument,
    remote: SyncDocument | None,
) -> MergePlan:
    """Merge a document built from the local store against the remote one.

    Semantics: per-item last-write-wins on ``updated_at`` (ties favour the
    local side). The returned plan lists the changes to apply locally and the
    document to upload back.
    """
    remote = remote if remote is not None else SyncDocument.empty()
    uids = set(local.items) | set(remote.items)

    local_creates: list[SyncItem] = []
    local_updates: list[SyncItem] = []
    local_deletes: list[str] = []
    uploaded: dict[str, SyncItem] = {}

    for uid in sorted(uids):
        local_item = local.items.get(uid)
        remote_item = remote.items.get(uid)

        if remote_item is None:
            # Only known locally — publish it (including tombstones).
            uploaded[uid] = local_item
            continue

        if local_item is None:
            # Only known remotely. If the remote says "deleted", the local
            # device never had it, so there is nothing to do.
            if remote_item.deleted:
                continue
            local_creates.append(remote_item)
            uploaded[uid] = remote_item
            continue

        remote_wins = remote_item.updated_at > local_item.updated_at
        if not remote_wins:
            # Local is newer or equal — keep local, publish it.
            uploaded[uid] = local_item
            continue

        if remote_item.deleted:
            local_deletes.append(uid)
        elif local_item.deleted:
            # Remote re-created an item that was deleted locally, and it is
            # newer — resurrect it on this device.
            local_creates.append(remote_item)
        else:
            local_updates.append(remote_item)
        uploaded[uid] = remote_item

    changed = sum(1 for uid, item in uploaded.items() if remote.items.get(uid) != item)

    return MergePlan(
        local_creates=local_creates,
        local_updates=local_updates,
        local_deletes=local_deletes,
        uploaded_items=uploaded,
        changed=changed,
    )


@dataclass
class MergePlan:
    local_creates: list[SyncItem]
    local_updates: list[SyncItem]
    local_deletes: list[str]
    uploaded_items: dict[str, SyncItem]
    changed: int

    def to_document(self) -> SyncDocument:
        return SyncDocument(items=dict(self.uploaded_items))
