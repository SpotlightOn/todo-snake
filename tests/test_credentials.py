"""Tests for credential storage (keyring abstraction and its fallback)."""

from __future__ import annotations

from PySide6.QtCore import QSettings

from todo_snake.sync.accounts import AccountStore, SyncAccount, SyncProvider
from todo_snake.sync.credentials import Credentials, QSettingsBackend


class _FakeBackend:
    def __init__(self):
        self.data: dict[str, str] = {}

    def get(self, uid):
        return self.data.get(uid)

    def set(self, uid, password):
        self.data[uid] = password
        return True

    def delete(self, uid):
        self.data.pop(uid, None)


def _settings(tmp_path) -> QSettings:
    return QSettings(str(tmp_path / "accounts.ini"), QSettings.Format.IniFormat)


def test_credentials_delegates_to_the_backend(tmp_path):
    backend = _FakeBackend()
    credentials = Credentials(_settings(tmp_path), backend)

    credentials.set("u1", "secret")
    assert backend.data["u1"] == "secret"
    assert credentials.get("u1") == "secret"

    credentials.set("u1", None)  # empty clears the entry
    assert credentials.get("u1") is None


def test_qsettings_backend_roundtrip(tmp_path):
    settings = _settings(tmp_path)
    backend = QSettingsBackend(settings)
    backend.set("u1", "hunter2")
    assert backend.get("u1") == "hunter2"
    backend.delete("u1")
    assert backend.get("u1") is None


def test_credentials_reads_legacy_qsettings_when_the_keyring_is_empty(tmp_path):
    """An account whose password predates the keyring must still work — this
    was the "rejected: username/password" regression."""
    settings = _settings(tmp_path)
    QSettingsBackend(settings).set("u1", "legacy")

    credentials = Credentials(settings, _FakeBackend())  # keyring has nothing

    assert credentials.get("u1") == "legacy"


def test_credentials_migrates_to_the_keyring_and_drops_the_plaintext(tmp_path):
    settings = _settings(tmp_path)
    QSettingsBackend(settings).set("u1", "legacy")
    backend = _FakeBackend()
    credentials = Credentials(settings, backend)

    credentials.set("u1", "fresh")

    assert backend.data["u1"] == "fresh"
    assert QSettingsBackend(settings).get("u1") is None


def test_credentials_keeps_qsettings_when_the_keyring_write_fails(tmp_path):
    settings = _settings(tmp_path)

    class _BrokenBackend(_FakeBackend):
        def set(self, uid, password):
            return False  # e.g. locked keyring

    credentials = Credentials(settings, _BrokenBackend())
    credentials.set("u1", "fresh")

    assert QSettingsBackend(settings).get("u1") == "fresh"


def test_account_store_roundtrips_the_password_via_the_fallback(tmp_path):
    settings = _settings(tmp_path)
    store = AccountStore(settings)
    account = SyncAccount(
        provider=SyncProvider.NEXTCLOUD,
        label="NC",
        server_url="https://cloud.example.com",
        username="alice",
        app_password="hunter2",
    )
    store.save(account)

    assert store.get(account.uid).app_password == "hunter2"

    store.delete(account.uid)
    assert store.get(account.uid) is None
