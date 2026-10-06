"""Attachment model: a file attached to a task.

Local-first: the bytes live in the database (BLOB). When an account is synced to
Nextcloud, the file is uploaded to that account's Files and the task's ``ATTACH``
property points at the account-specific URL (:attr:`Attachment.remote_urls`); a
remote-only attachment (pulled from the server) has no local bytes and is opened
via such a URL.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import unquote

from todo_snake.domain.todo import utc_now

#: Per-file size cap (the bytes live in the database).
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024


@dataclass(frozen=True)
class Attachment:
    todo_uid: str
    filename: str
    size: int = 0
    mime: str = ""
    created_at: datetime = field(default_factory=utc_now)
    #: The bytes themselves — only populated when explicitly requested.
    data: bytes | None = None
    #: Uploaded copy per sync account: ``{account uid: file URL}``. One file can
    #: live on several servers, each task carrying its own server's URL.
    remote_urls: dict[str, str] = field(default_factory=dict)
    #: Whether the bytes are stored locally (``data`` is loaded on demand only).
    has_data: bool = False
    id: int | None = None

    def url_for(self, account_uid: str) -> str | None:
        """The uploaded URL on ``account_uid``'s server, if any."""
        return self.remote_urls.get(account_uid)

    @property
    def any_remote_url(self) -> str | None:
        """Some uploaded URL (used by the UI, which is account-agnostic)."""
        return next(iter(self.remote_urls.values()), None)


def filename_from_url(url: str) -> str:
    """Best-effort file name for a remote attachment URL."""
    tail = url.rstrip("/").rsplit("/", 1)[-1]
    return unquote(tail) or "attachment"


def remote_only_attachment(todo_uid: str, account_uid: str, url: str) -> Attachment:
    """A link-only attachment (no local bytes) for one account's ``ATTACH`` URL."""
    return Attachment(
        todo_uid=todo_uid,
        filename=filename_from_url(url),
        remote_urls={account_uid: url},
    )
