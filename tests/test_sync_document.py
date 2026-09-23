"""Tests for the sync document and its merge logic."""

from datetime import datetime, timezone

import pytest

from todo_snake.domain import Todo, TodoPriority, TodoStatus
from todo_snake.sync.document import (
    SyncDocument,
    SyncItem,
    merge_documents,
)

T1 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
T2 = datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc)
T3 = datetime(2026, 1, 3, 12, 0, tzinfo=timezone.utc)


def item(
    uid: str,
    *,
    title: str = "task",
    updated_at: datetime = T1,
    deleted: bool = False,
    priority: TodoPriority = TodoPriority.MEDIUM,
) -> SyncItem:
    return SyncItem(
        uid=uid,
        title=title,
        priority=priority,
        due_at=None,
        note="",
        status=TodoStatus.OPEN,
        created_at=updated_at,
        completed_at=None,
        updated_at=updated_at,
        deleted=deleted,
    )


def doc(*items: SyncItem) -> SyncDocument:
    return SyncDocument(items={it.uid: it for it in items})


def test_from_local_builds_document():
    todo = Todo(
        uid="u1",
        title="hello",
        priority=TodoPriority.HIGH,
        updated_at=T2,
        created_at=T1,
    )
    document = SyncDocument.from_local([todo], {"gone": datetime(2026, 1, 3, tzinfo=timezone.utc)})
    assert document.items["u1"].title == "hello"
    assert document.items["u1"].deleted is False
    assert document.items["gone"].deleted is True


def test_tombstone_classmethod_builds_deleted_item():
    stamp = datetime(2026, 1, 3, 12, 0, tzinfo=timezone.utc)
    tombstone = SyncItem.tombstone("gone", stamp)
    assert tombstone.deleted is True
    assert tombstone.uid == "gone"
    assert tombstone.updated_at == stamp


def test_json_roundtrip():
    document = SyncDocument.from_local(
        [
            Todo(uid="u1", title="a", updated_at=T1, created_at=T1),
            Todo(uid="u2", title="b", updated_at=T2, created_at=T2),
        ],
        {"gone": T3},
    )
    restored = SyncDocument.from_json(document.to_json())
    assert restored.items == document.items
    assert restored.items["gone"].deleted is True


def test_from_json_rejects_foreign_format():
    with pytest.raises(ValueError):
        SyncDocument.from_json('{"format": "other", "items": []}')


def test_first_sync_publishes_everything():
    plan = merge_documents(doc(item("u1"), item("u2")), None)
    assert plan.local_creates == []
    assert plan.local_updates == []
    assert plan.local_deletes == []
    assert set(plan.uploaded_items) == {"u1", "u2"}
    assert plan.changed == 2


def test_remote_only_creates_locally():
    remote = doc(item("u1", title="remote task"))
    plan = merge_documents(SyncDocument.empty(), remote)
    assert [it.uid for it in plan.local_creates] == ["u1"]
    assert plan.uploaded_items["u1"].title == "remote task"


def test_remote_deleted_item_without_local_is_ignored():
    remote = doc(item("u1", deleted=True))
    plan = merge_documents(SyncDocument.empty(), remote)
    assert plan.local_creates == []
    assert plan.uploaded_items == {}


def test_remote_newer_updates_local():
    local = doc(item("u1", title="old", updated_at=T1))
    remote = doc(item("u1", title="new", updated_at=T2))
    plan = merge_documents(local, remote)
    assert [it.title for it in plan.local_updates] == ["new"]
    assert plan.uploaded_items["u1"].title == "new"


def test_local_newer_wins():
    local = doc(item("u1", title="mine", updated_at=T2))
    remote = doc(item("u1", title="theirs", updated_at=T1))
    plan = merge_documents(local, remote)
    assert plan.local_updates == []
    assert plan.uploaded_items["u1"].title == "mine"


def test_equal_timestamps_keep_local():
    local = doc(item("u1", title="mine", updated_at=T1))
    remote = doc(item("u1", title="theirs", updated_at=T1))
    plan = merge_documents(local, remote)
    assert plan.local_updates == []
    assert plan.uploaded_items["u1"].title == "mine"


def test_remote_deletion_propagated():
    local = doc(item("u1", title="still here", updated_at=T1))
    remote = doc(item("u1", title="", updated_at=T2, deleted=True))
    plan = merge_documents(local, remote)
    assert plan.local_deletes == ["u1"]
    assert plan.uploaded_items["u1"].deleted is True


def test_local_tombstone_wins_over_older_remote():
    local = doc(item("u1", deleted=True, updated_at=T2))
    remote = doc(item("u1", title="zombie", updated_at=T1))
    plan = merge_documents(local, remote)
    assert plan.local_creates == []
    assert plan.local_deletes == []
    assert plan.uploaded_items["u1"].deleted is True


def test_remote_recreation_newer_resurrects():
    local = doc(item("u1", deleted=True, updated_at=T1))
    remote = doc(item("u1", title="reborn", updated_at=T2))
    plan = merge_documents(local, remote)
    assert [it.title for it in plan.local_creates] == ["reborn"]
    assert plan.uploaded_items["u1"].title == "reborn"


def test_unchanged_remote_document_has_zero_changes():
    remote = doc(item("u1", title="same", updated_at=T1))
    local = doc(item("u1", title="same", updated_at=T1))
    plan = merge_documents(local, remote)
    assert plan.changed == 0
    assert set(plan.uploaded_items) == {"u1"}


def test_to_document_builds_upload_payload():
    local = doc(item("u1"))
    plan = merge_documents(local, None)
    payload = plan.to_document()
    assert payload.items == local.items
