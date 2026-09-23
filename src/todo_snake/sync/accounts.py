"""Sync account model and ``QSettings``-backed storage."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from PySide6.QtCore import QSettings

from todo_snake.config import APP_NAME, ORG_NAME

_ACCOUNTS_PREFIX = "sync/accounts"


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat() if value else None


def _from_iso(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


class SyncProvider:
    NEXTCLOUD = "nextcloud"
    WEBDAV = "webdav"
    CALDAV = "caldav"
    GOOGLE = "google"

    SUPPORTED = frozenset({NEXTCLOUD, WEBDAV, CALDAV, GOOGLE})


@dataclass
class SyncAccount:
    """One configured sync target (e.g. a Nextcloud or generic WebDAV server).

    ``remote_path`` is only meaningful for the generic ``WEBDAV`` provider: it
    is the base path on the server under which the ``todo-snake`` folder is
    created. Nextcloud derives that path from the username instead.
    """

    uid: str = field(default_factory=lambda: str(uuid.uuid4()))
    provider: str = SyncProvider.NEXTCLOUD
    label: str = "Nextcloud"
    server_url: str | None = None
    remote_path: str | None = None
    username: str | None = None
    app_password: str | None = None
    enabled: bool = True
    last_sync_at: datetime | None = None

    @property
    def display_name(self) -> str:
        return self.label or self.username or self.provider


class AccountStore:
    """Persists ``SyncAccount`` objects in ``QSettings``.

    Credentials (``app_password``) are stored in QSettings for now. A follow-up
    should move them to the OS keyring (SecretService/Keychain).
    """

    def __init__(self, settings: QSettings | None = None):
        self._settings = settings if settings is not None else QSettings(ORG_NAME, APP_NAME)

    def list_accounts(self) -> list[SyncAccount]:
        settings = self._settings
        accounts: list[SyncAccount] = []
        settings.beginGroup(_ACCOUNTS_PREFIX)
        children = settings.childGroups()
        settings.endGroup()
        for uid in children:
            settings.beginGroup(f"{_ACCOUNTS_PREFIX}/{uid}")
            provider = settings.value("provider", SyncProvider.NEXTCLOUD)
            if provider not in SyncProvider.SUPPORTED:
                provider = SyncProvider.NEXTCLOUD
            account = SyncAccount(
                uid=uid,
                provider=provider,
                label=str(settings.value("label", "")),
                server_url=settings.value("server_url") or None,
                remote_path=(settings.value("remote_path") or "").strip() or None,
                # Trim stray whitespace from stored credentials: a copied app
                # password with trailing spaces is a common source of HTTP 401.
                username=(settings.value("username") or "").strip() or None,
                app_password=(settings.value("app_password") or "").strip() or None,
                enabled=bool(settings.value("enabled", True)),
                last_sync_at=_from_iso(settings.value("last_sync_at")),
            )
            settings.endGroup()
            accounts.append(account)
        # Stable order: by creation; uid is a uuid4, so a fresh server list is
        # arbitrarily ordered — sort by label to keep the UI deterministic.
        accounts.sort(key=lambda account: (account.label, account.uid))
        return accounts

    def get(self, uid: str) -> SyncAccount | None:
        for account in self.list_accounts():
            if account.uid == uid:
                return account
        return None

    def save(self, account: SyncAccount) -> None:
        settings = self._settings
        prefix = f"{_ACCOUNTS_PREFIX}/{account.uid}"
        settings.beginGroup(prefix)
        settings.setValue("provider", account.provider)
        settings.setValue("label", account.label)
        settings.setValue("server_url", account.server_url)
        settings.setValue("remote_path", account.remote_path)
        settings.setValue("username", account.username)
        settings.setValue("app_password", account.app_password)
        settings.setValue("enabled", account.enabled)
        settings.setValue("last_sync_at", _iso(account.last_sync_at))
        settings.endGroup()
        settings.sync()

    def delete(self, uid: str) -> None:
        settings = self._settings
        settings.beginGroup(_ACCOUNTS_PREFIX)
        settings.remove(uid)
        settings.endGroup()
        settings.sync()
