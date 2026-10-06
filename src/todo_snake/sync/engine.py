"""The sync cycle itself: fetch -> merge -> apply -> upload, once per account.

``SyncEngine`` is a plain Python class — no Qt, no signals, no UI. It talks to
the ``TodoService`` (local data) and to a *transport* plus a *file store* (the
two seams that do the I/O). ``todo_snake.sync.manager.SyncManager`` wraps it for
Qt; tests wrap it with fakes.

Failures propagate to the caller (``SyncTransportError``, ``ValueError``, …):
the engine does not decide how an error is reported.

The cycle, step by step (:meth:`SyncEngine.sync`):

1. :meth:`_local_document` — read the local tasks and upload the attachment
   files this account is still missing.
2. :meth:`_fetch` — download the server state and drop tasks the server deleted.
3. :meth:`_merge` — last-write-wins per task (see ``document.merge_documents``).
4. :meth:`_apply` — write the winning version back into the local store.
5. :meth:`_mirror_attachments` — remember the server's ``ATTACH`` URLs.
6. :meth:`_upload` — push the merged document (only if something changed).
7. :meth:`_delete_removed_files` — remove files of locally deleted attachments.
8. :meth:`_remove_leftover_files` — sweep the task folders for files nothing
   references any more (self-healing; see ``sync/attachments.py``).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from todo_snake.logging_setup import get_sync_logger
from todo_snake.sync.attachments import (
    remove_unreferenced_files,
    upload_local_attachments,
)
from todo_snake.sync.document import MergePlan, SyncDocument, merge_documents
from todo_snake.sync.errors import SyncTransportError
from todo_snake.sync.state import SyncStateStore

if TYPE_CHECKING:  # keep this module importable without Qt (and without accounts)
    from todo_snake.service import TodoService
    from todo_snake.sync.accounts import SyncAccount
    from todo_snake.sync.journal import SyncJournal

_logger = get_sync_logger()


@dataclass(frozen=True)
class SyncStats:
    """What one sync cycle changed."""

    created: int = 0
    updated: int = 0
    deleted: int = 0
    pushed: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "created": self.created,
            "updated": self.updated,
            "deleted": self.deleted,
            "pushed": self.pushed,
        }


class SyncEngine:
    """Runs one account's sync cycle; usable without a Qt application."""

    def __init__(
        self,
        service: TodoService,
        journal: SyncJournal,
        *,
        attachments=None,
        transport_factory=None,
        file_store_factory=None,
    ):
        self._service = service
        self._journal = journal
        self._state = SyncStateStore(journal.db_path)
        #: Optional ``AttachmentService``: local files are uploaded on sync.
        self._attachments = attachments
        # Factories are injected (and defaulted lazily) so tests can use fakes
        # and this module stays free of transport/Qt imports.
        self._transport_factory = transport_factory or _create_transport
        self._file_store_factory = file_store_factory or _make_file_store

    # -- public API ---------------------------------------------------------

    def sync(self, account: SyncAccount) -> SyncStats:
        """Run one full cycle; raises on failure instead of swallowing it."""
        _logger.info("sync start: %s (%s)", account.display_name, account.provider)
        file_store = self._file_store(account)
        try:
            transport = self._transport_factory(account, None, self._state)
            local = self._local_document(account, file_store)
            remote = self._fetch(transport, local)
            plan = self._merge(local, remote)
            self._apply(plan)
            self._mirror_attachments(plan, account.uid)
            self._upload(transport, plan, remote)
            self._delete_removed_files(file_store, account.uid)
            self._remove_leftover_files(file_store, local, remote, account.uid)
            self._journal.prune_all()
        finally:
            if file_store is not None:
                file_store.close()

        stats = SyncStats(
            created=len(plan.local_creates),
            updated=len(plan.local_updates),
            deleted=len(plan.local_deletes),
            pushed=plan.changed,
        )
        _logger.info("sync done: %s %s", account.display_name, stats.as_dict())
        return stats

    def record_local_deletion(self, uid: str) -> None:
        """Remember a local deletion so the next sync propagates it."""
        self._journal.record_deleted(uid)

    # -- steps --------------------------------------------------------------

    def _file_store(self, account: SyncAccount):
        """A file store for the account, or ``None`` if files are not synced."""
        if self._attachments is None:
            return None
        return self._file_store_factory(account)

    def _local_document(self, account: SyncAccount, file_store) -> SyncDocument:
        """Local tasks, plus the attachment URLs already uploaded for this account."""
        todos = self._service.list_todos()
        attachment_urls: dict[str, tuple[str, ...]] = {}
        if file_store is not None:
            attachment_urls = upload_local_attachments(
                todos, self._attachments, file_store, account.uid
            )
        return SyncDocument.from_local(
            todos, self._journal.tombstones(), attachments=attachment_urls
        )

    def _fetch(self, transport, local: SyncDocument) -> SyncDocument | None:
        """The server's document (``None`` when it does not exist yet)."""
        result = transport.fetch()
        remote = SyncDocument.from_json(result.body.decode("utf-8")) if result.found else None
        self._drop_server_deletions(local, getattr(transport, "remote_deleted_uids", set()))
        return remote

    def _drop_server_deletions(self, local: SyncDocument, deleted: set[str]) -> None:
        """Tasks gone from the server are removed locally, not re-uploaded."""
        for uid in deleted:
            self._service.delete_by_uid(uid)
            self._journal.remove(uid)
            local.items.pop(uid, None)

    def _merge(self, local: SyncDocument, remote: SyncDocument | None) -> MergePlan:
        return merge_documents(local, remote)

    def _apply(self, plan: MergePlan) -> None:
        """Write the winning version of every changed task into the local store."""
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
                    start_at=item.start_at,
                    due_all_day=item.due_all_day,
                    remind_before=item.remind_before,
                    recurrence=item.recurrence,
                )
            )
        for uid in plan.local_deletes:
            self._service.delete_by_uid(uid)
            self._journal.remove(uid)

    def _mirror_attachments(self, plan: MergePlan, account_uid: str) -> None:
        """Record this account's server-side ``ATTACH`` URLs as link-only files."""
        if self._attachments is None:
            return
        for item in (*plan.local_creates, *plan.local_updates):
            self._attachments.sync_remote_urls(item.uid, account_uid, item.attachments)

    def _upload(self, transport, plan: MergePlan, remote: SyncDocument | None) -> None:
        """Push the merged document, but only when something actually changed."""
        if remote is not None and not plan.changed:
            return
        transport.upload(plan.to_document().to_json().encode("utf-8"))

    def _remove_leftover_files(
        self,
        file_store,
        local: SyncDocument,
        remote: SyncDocument | None,
        account_uid: str,
    ) -> None:
        """Self-healing: drop files in the tasks' folders that nothing references.

        Covers files whose local record was lost (deleted before removals were
        tracked, or a lost upload record) without any manual action. Everything
        the account is known to use is protected: the recorded uploads plus every
        ``ATTACH`` URL of the local and the fetched document.
        """
        if file_store is None or self._attachments is None:
            return
        todo_uids = list(self._attachments.names_by_todo())
        if not todo_uids:
            return
        protected = set(self._attachments.remote_urls_for_account(account_uid))
        for document in (local, remote):
            if document is not None:
                for item in document.items.values():
                    protected.update(item.attachments)

        removed = remove_unreferenced_files(file_store, todo_uids, protected)
        if removed:
            _logger.info(
                "removed %d unreferenced attachment file(s): %s",
                len(removed),
                ", ".join(removed),
            )

    def _delete_removed_files(self, file_store, account_uid: str) -> None:
        """Delete the server files of attachments removed locally (best effort).

        A failure is logged and retried on the next sync — the task updates
        themselves already succeeded, so this must not fail the whole sync.
        """
        if file_store is None or self._attachments is None:
            return
        for deletion_id, url in self._attachments.pending_deletions(account_uid):
            try:
                file_store.delete(url)
            except SyncTransportError as exc:
                _logger.warning("could not delete attachment file %s: %s", url, exc)
                continue
            self._attachments.drop_deletion(deletion_id)


def _create_transport(*args, **kwargs):
    from todo_snake.sync.transports import create_transport

    return create_transport(*args, **kwargs)


def _make_file_store(*args, **kwargs):
    from todo_snake.sync.file_store import make_file_store

    return make_file_store(*args, **kwargs)
