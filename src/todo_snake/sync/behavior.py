"""Sync behavior settings persisted in ``QSettings``.

Holds the *when to sync* flags that both the settings dialog (edit) and the
main window (apply) need, so the ``sync/behavior`` keys live in one place.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QSettings

from todo_snake.config import APP_NAME, ORG_NAME

BEHAVIOR_GROUP = "sync/behavior"

_PERIODIC_MINUTES_DEFAULT = 15


@dataclass(frozen=True)
class SyncBehavior:
    sync_on_startup: bool = False
    periodic_enabled: bool = False
    periodic_minutes: int = _PERIODIC_MINUTES_DEFAULT
    sync_on_change: bool = False

    @classmethod
    def load(cls, settings: QSettings | None = None) -> SyncBehavior:
        store = settings if settings is not None else QSettings(ORG_NAME, APP_NAME)
        store.beginGroup(BEHAVIOR_GROUP)
        behavior = cls(
            sync_on_startup=bool(store.value("sync_on_startup", False)),
            periodic_enabled=bool(store.value("periodic_enabled", False)),
            periodic_minutes=int(store.value("periodic_minutes", _PERIODIC_MINUTES_DEFAULT)),
            sync_on_change=bool(store.value("sync_on_change", False)),
        )
        store.endGroup()
        return behavior

    def save(self, settings: QSettings | None = None) -> None:
        store = settings if settings is not None else QSettings(ORG_NAME, APP_NAME)
        store.beginGroup(BEHAVIOR_GROUP)
        store.setValue("sync_on_startup", self.sync_on_startup)
        store.setValue("periodic_enabled", self.periodic_enabled)
        store.setValue("periodic_minutes", self.periodic_minutes)
        store.setValue("sync_on_change", self.sync_on_change)
        store.endGroup()
        store.sync()
