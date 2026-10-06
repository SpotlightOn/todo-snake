"""Tests for the per-account CalDAV sync state store."""

from __future__ import annotations

from todo_snake.sync.state import SyncStateStore


def test_state_store_roundtrip(tmp_path):
    store = SyncStateStore(tmp_path / "sync.db")
    store.replace("acc-1", {"a": "e1", "b": "e2"})
    assert store.known_uids("acc-1") == {"a", "b"}
    assert store.etags("acc-1") == {"a": "e1", "b": "e2"}


def test_state_store_is_per_account(tmp_path):
    store = SyncStateStore(tmp_path / "sync.db")
    store.replace("acc-1", {"a": "e1"})
    store.replace("acc-2", {"b": "e2"})
    assert store.known_uids("acc-1") == {"a"}
    assert store.known_uids("acc-2") == {"b"}


def test_state_store_replace_drops_removed_resources(tmp_path):
    store = SyncStateStore(tmp_path / "sync.db")
    store.replace("acc-1", {"a": "e1", "b": "e2"})
    store.replace("acc-1", {"b": "e2b"})
    assert store.known_uids("acc-1") == {"b"}
    assert store.etags("acc-1") == {"b": "e2b"}


def test_state_store_clear(tmp_path):
    store = SyncStateStore(tmp_path / "sync.db")
    store.replace("acc-1", {"a": "e1"})
    store.clear("acc-1")
    assert store.known_uids("acc-1") == set()
