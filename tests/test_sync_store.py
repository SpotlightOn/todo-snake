"""Tests for the sync account store and deletion journal."""

from datetime import datetime, timezone

from PySide6.QtCore import QSettings

from todo_snake.sync.accounts import AccountStore, SyncAccount, SyncProvider
from todo_snake.sync.behavior import SyncBehavior
from todo_snake.sync.journal import SyncJournal


def make_settings(tmp_path) -> QSettings:
    path = tmp_path / "accounts.ini"
    settings = QSettings(str(path), QSettings.Format.IniFormat)
    settings.clear()
    settings.sync()
    return settings


def test_account_roundtrip(tmp_path):
    settings = make_settings(tmp_path)
    store = AccountStore(settings)
    store.save(
        SyncAccount(
            provider=SyncProvider.NEXTCLOUD,
            label="My Cloud",
            server_url="https://cloud.example.com",
            username="alice",
            app_password="hunter2",
        )
    )
    accounts = store.list_accounts()
    assert len(accounts) == 1
    account = accounts[0]
    assert account.provider == SyncProvider.NEXTCLOUD
    assert account.label == "My Cloud"
    assert account.username == "alice"
    assert account.app_password == "hunter2"
    assert account.enabled is True
    assert account.last_sync_at is None


def test_account_uid_preserved(tmp_path):
    settings = make_settings(tmp_path)
    store = AccountStore(settings)
    account = SyncAccount(uid="fixed-uid", label="Fixed")
    store.save(account)
    assert store.get("fixed-uid").label == "Fixed"


def test_stored_credentials_are_trimmed_on_read(tmp_path):
    """Whitespace sneaking into stored credentials (e.g. a pasted app password)
    must be trimmed, otherwise every sync fails with HTTP 401."""
    settings = make_settings(tmp_path)
    store = AccountStore(settings)
    account = SyncAccount(
        label="Messy",
        server_url="https://cloud.example.com",
        username="  alice  ",
        app_password="  t0ps3cret\n",
    )
    store.save(account)
    loaded = store.get(account.uid)
    assert loaded.username == "alice"
    assert loaded.app_password == "t0ps3cret"


def test_generic_webdav_account_roundtrip(tmp_path):
    settings = make_settings(tmp_path)
    store = AccountStore(settings)
    account = SyncAccount(
        provider=SyncProvider.WEBDAV,
        label="My DAV",
        server_url="https://dav.example.com",
        remote_path="/dav/alice",
        username="alice",
        app_password="hunter2",
    )
    store.save(account)
    loaded = store.get(account.uid)
    assert loaded.provider == SyncProvider.WEBDAV
    assert loaded.remote_path == "/dav/alice"


def test_empty_remote_path_is_stored_as_none(tmp_path):
    settings = make_settings(tmp_path)
    store = AccountStore(settings)
    account = SyncAccount(provider=SyncProvider.NEXTCLOUD, label="NC")
    store.save(account)
    assert store.get(account.uid).remote_path is None


def test_account_delete(tmp_path):
    settings = make_settings(tmp_path)
    store = AccountStore(settings)
    account = SyncAccount(uid="gone", label="Gone")
    store.save(account)
    store.delete("gone")
    assert store.list_accounts() == []


def test_account_multiple(tmp_path):
    settings = make_settings(tmp_path)
    store = AccountStore(settings)
    store.save(SyncAccount(label="z-cloud"))
    store.save(SyncAccount(label="a-cloud"))
    assert [account.label for account in store.list_accounts()] == ["a-cloud", "z-cloud"]


def test_last_sync_at_roundtrip(tmp_path):
    settings = make_settings(tmp_path)
    store = AccountStore(settings)
    stamp = datetime(2026, 9, 18, 14, 30, tzinfo=timezone.utc)
    account = SyncAccount(label="eins", last_sync_at=stamp)
    store.save(account)
    assert store.get(account.uid).last_sync_at == stamp


def test_journal_roundtrip(tmp_path):
    journal = SyncJournal(tmp_path / "sync.db")
    stamp = datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc)
    journal.record_deleted("u1", stamp)
    journal.record_deleted("u2", datetime(2026, 9, 18, 13, 0, tzinfo=timezone.utc))
    tombstones = journal.tombstones()
    assert tombstones == {"u1": stamp, "u2": tombstones["u2"]}


def test_journal_persists_across_instances(tmp_path):
    path = tmp_path / "sync.db"
    SyncJournal(path).record_deleted("u1")
    journal = SyncJournal(path)
    assert "u1" in journal.tombstones()


def test_journal_remove_and_prune(tmp_path):
    journal = SyncJournal(tmp_path / "sync.db")
    journal.record_deleted("u1")
    journal.record_deleted("u2")
    journal.remove("u1")
    assert set(journal.tombstones()) == {"u2"}
    journal.prune_all()
    assert journal.tombstones() == {}


def test_journal_record_twice_updates_stamp(tmp_path):
    journal = SyncJournal(tmp_path / "sync.db")
    earlier = datetime(2026, 1, 1, tzinfo=timezone.utc)
    later = datetime(2026, 1, 2, tzinfo=timezone.utc)
    journal.record_deleted("u1", earlier)
    journal.record_deleted("u1", later)
    assert journal.tombstones()["u1"] == later


def test_behavior_load_has_defaults(tmp_path):
    settings = make_settings(tmp_path)
    behavior = SyncBehavior.load(settings)
    assert behavior.sync_on_startup is False
    assert behavior.periodic_enabled is False
    assert behavior.periodic_minutes == 15
    assert behavior.sync_on_change is False


def test_behavior_save_and_load_roundtrip(tmp_path):
    settings = make_settings(tmp_path)
    SyncBehavior(
        sync_on_startup=True,
        periodic_enabled=True,
        periodic_minutes=30,
        sync_on_change=True,
    ).save(settings)
    behavior = SyncBehavior.load(settings)
    assert behavior == SyncBehavior(
        sync_on_startup=True,
        periodic_enabled=True,
        periodic_minutes=30,
        sync_on_change=True,
    )
