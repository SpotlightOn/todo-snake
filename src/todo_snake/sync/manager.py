"""Qt adapter around :class:`todo_snake.sync.engine.SyncEngine`.

The manager adds exactly two things: a QObject so the UI can connect signals,
and the decision how a failure is reported (``sync_failed``). Everything about
*what* a sync does lives in the engine.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from todo_snake.logging_setup import get_sync_logger
from todo_snake.service import TodoService
from todo_snake.sync.accounts import SyncAccount
from todo_snake.sync.engine import SyncEngine, SyncStats
from todo_snake.sync.journal import SyncJournal
from todo_snake.sync.transports import create_transport
from todo_snake.sync.webdav import SyncTransportError

_logger = get_sync_logger()

#: Errors a sync cycle may report to the UI instead of crashing the app.
_REPORTED_ERRORS = (SyncTransportError, NotImplementedError, ValueError)


class SyncManager(QObject):
    """Runs sync cycles and reports the outcome as Qt signals."""

    sync_finished = Signal(str, object)  # account uid, stats dict
    sync_failed = Signal(str, str)  # account uid, error message

    def __init__(
        self,
        service: TodoService,
        journal: SyncJournal,
        parent=None,
        attachments=None,
    ):
        super().__init__(parent)
        self._engine = SyncEngine(service, journal, attachments=attachments)

    # -- hooks for the UI ---------------------------------------------------

    def local_deleted(self, uid: str) -> None:
        """Remember a local deletion so it can be propagated on next sync."""
        self._engine.record_local_deletion(uid)

    # -- sync cycle ---------------------------------------------------------

    def trigger_sync(self, account: SyncAccount) -> dict[str, int] | None:
        """Run a full sync cycle for ``account``.

        Returns the stats dict on success, or ``None`` after emitting
        ``sync_failed``. Raises nothing — errors are reported via the signal.
        """
        try:
            stats = self._engine.sync(account)
        except _REPORTED_ERRORS as exc:
            _logger.error("sync failed: %s: %s", account.display_name, exc)
            self.sync_failed.emit(account.uid, str(exc))
            return None
        reported: dict[str, int] = stats.as_dict()
        self.sync_finished.emit(account.uid, reported)
        return reported


__all__ = ["SyncManager", "SyncStats", "create_transport"]
