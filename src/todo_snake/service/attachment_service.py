"""Business logic for task attachments (local-first)."""

from __future__ import annotations

from todo_snake.domain.attachment import (
    MAX_ATTACHMENT_BYTES,
    Attachment,
    remote_only_attachment,
)
from todo_snake.persistence.attachments import SqliteAttachmentRepository


class AttachmentTooLargeError(ValueError):
    """Raised when a file exceeds :data:`MAX_ATTACHMENT_BYTES`."""


class AttachmentService:
    def __init__(self, repository: SqliteAttachmentRepository):
        self._repository = repository

    def list_for(self, todo_uid: str, *, with_data: bool = False) -> list[Attachment]:
        """Attachments of a task (metadata only unless ``with_data``)."""
        return self._repository.for_todo(todo_uid, with_data=with_data)

    def add(self, todo_uid: str, filename: str, data: bytes, mime: str = "") -> Attachment:
        payload = bytes(data)
        if len(payload) > MAX_ATTACHMENT_BYTES:
            raise AttachmentTooLargeError(
                f"Attachment exceeds the {MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB limit."
            )
        return self._repository.add(
            Attachment(
                todo_uid=todo_uid,
                filename=filename.strip() or "attachment",
                size=len(payload),
                mime=mime,
                data=payload,
                has_data=True,
            )
        )

    def read(self, attachment_id: int) -> Attachment | None:
        """Attachment including its bytes (when stored locally)."""
        return self._repository.get(attachment_id)

    def remove(self, attachment_id: int) -> None:
        attachment = self._repository.get(attachment_id)
        if attachment is None:
            return
        self._repository.delete(attachment_id)
        self._queue_deletions([attachment])

    def delete_for_todo(self, todo_uid: str) -> None:
        attachments = self._repository.for_todo(todo_uid)
        self._repository.delete_for_todo(todo_uid)
        self._queue_deletions(attachments)

    def _queue_deletions(self, attachments: list[Attachment]) -> None:
        """Queue the uploaded copies of removed *local* files for deletion.

        Only files we uploaded ourselves (local bytes) are queued: link-only
        rows mirror files owned by another client and must not be touched.
        """
        self._repository.queue_deletions(
            [
                (account_uid, url)
                for attachment in attachments
                if attachment.has_data
                for account_uid, url in attachment.remote_urls.items()
            ]
        )

    def pending_deletions(self, account_uid: str) -> list[tuple[int, str]]:
        """Uploaded files to delete on ``account_uid``'s server (id, url)."""
        return self._repository.pending_deletions(account_uid)

    def drop_deletion(self, deletion_id: int) -> None:
        self._repository.drop_deletion(deletion_id)

    def remote_urls_for_account(self, account_uid: str) -> set[str]:
        """URLs of files this account should still have (for orphan cleanup)."""
        return self._repository.remote_urls_for_account(account_uid)

    def names_by_todo(self) -> dict[str, tuple[str, ...]]:
        """Attached file names per task uid (no bytes) — for the task list."""
        return self._repository.filenames_by_todo()

    def set_remote_url(self, attachment_id: int, account_uid: str, remote_url: str) -> None:
        self._repository.set_remote_url(attachment_id, account_uid, remote_url)

    def sync_remote_urls(self, todo_uid: str, account_uid: str, urls: tuple[str, ...]) -> None:
        """Reconcile ``account_uid``'s copies of a task with the URLs the server
        now reports: unknown URLs become link-only attachments, stale ones are
        dropped (locally stored files are never touched)."""
        wanted = set(urls)
        for attachment in self._repository.for_todo(todo_uid):
            known = attachment.url_for(account_uid)
            if known is None:
                continue
            if known in wanted:
                wanted.discard(known)
            elif attachment.id is not None:
                self._repository.remove_remote_url(attachment.id, account_uid)
        for url in wanted:
            self._repository.add(remote_only_attachment(todo_uid, account_uid, url))
