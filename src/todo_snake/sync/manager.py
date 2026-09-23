"""Sync orchestrator.

``SyncManager`` runs one fetch -> merge -> apply -> upload cycle per account and
emits Qt signals afterwards. It talks only to the service (via ``TodoService``)
and the sync layer — no UI knowledge.
"""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QObject, Signal

from todo_snake.service import TodoService
from todo_snake.sync.accounts import SyncAccount, SyncProvider
from todo_snake.sync.caldav import CalDAVTransport
from todo_snake.sync.document import MergePlan, SyncDocument, merge_documents
from todo_snake.sync.journal import SyncJournal
from todo_snake.sync.webdav import FetchResult, SyncTransportError, WebDAVTransport


def create_transport(account: SyncAccount, parent=None):
    if account.provider in (SyncProvider.NEXTCLOUD, SyncProvider.WEBDAV):
        return WebDAVTransport(account, parent)
    if account.provider == SyncProvider.CALDAV:
        return CalDAVTransport(account, parent)
    if account.provider == SyncProvider.GOOGLE:
        raise NotImplementedError("Google sync is not implemented yet.")
    raise SyncTransportError(f"Unknown provider: {account.provider!r}")


class SyncManager(QObject):
    """Coordination point for on-demand and future automatic sync."""

    sync_finished = Signal(str, object)  # account uid, stats dict
    sync_failed = Signal(str, str)  # account uid, error message

    def __init__(self, service: TodoService, journal: SyncJournal, parent=None):
        super().__init__(parent)
        self._service = service
        self._journal = journal

    # -- hooks for the UI ---------------------------------------------------

    def local_deleted(self, uid: str) -> None:
        """Remember a local deletion so it can be propagated on next sync."""
        self._journal.record_deleted(uid)

    # -- sync cycle ---------------------------------------------------------

    def trigger_sync(self, account: SyncAccount) -> dict[str, int] | None:
        """Run a full sync cycle for ``account``.

        Returns a stats dict on success, or ``None`` after emitting
        ``sync_failed``. Raises nothing — errors are reported via the signal.
        """
        try:
            transport = create_transport(account, self)
            local = SyncDocument.from_local(
                self._service.list_todos(),
                self._journal.tombstones(),
            )

            result: FetchResult = transport.fetch()
            remote = SyncDocument.from_json(result.body.decode("utf-8")) if result.found else None

            plan = merge_documents(local, remote)
            self._apply(plan)

            upload_needed = remote is None or plan.changed
            if upload_needed:
                transport.upload(plan.to_document().to_json().encode("utf-8"))

            # Everything relevant is now in the server document.
            self._journal.prune_all()

            stats = {
                "created": len(plan.local_creates),
                "updated": len(plan.local_updates),
                "deleted": len(plan.local_deletes),
                "pushed": plan.changed,
            }
            self.sync_finished.emit(account.uid, stats)
            return stats
        except (SyncTransportError, NotImplementedError, ValueError) as exc:
            self.sync_failed.emit(account.uid, str(exc))
            return None

    # -- internals ----------------------------------------------------------

    def _apply(self, plan: MergePlan) -> None:
        for item in plan.local_creates:
            self._service.create_synced(item.to_todo())
        for item in plan.local_updates:
            local = self._service.find_by_uid(item.uid)
            if local is None:
                self._service.create_synced(item.to_todo())
                continue
            self._service.update_synced(
                replace(
                    local,
                    title=item.title,
                    priority=item.priority,
                    due_at=item.due_at,
                    note=item.note,
                    status=item.status,
                    completed_at=item.completed_at,
                    updated_at=item.updated_at,
                )
            )
        for uid in plan.local_deletes:
            self._service.delete_by_uid(uid)
            self._journal.remove(uid)
