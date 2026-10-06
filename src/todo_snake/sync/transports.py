"""Which concrete transport serves which provider.

Kept apart from ``manager`` so both the engine (default factory) and the
"Test connection" button can build a transport without pulling in the Qt
adapter.
"""

from __future__ import annotations

from todo_snake.sync.accounts import SyncAccount, SyncProvider
from todo_snake.sync.caldav import CalDAVTransport
from todo_snake.sync.nextcloud import NextcloudTasksTransport
from todo_snake.sync.webdav import SyncTransportError, WebDAVTransport


def create_transport(account: SyncAccount, parent=None, state=None):
    """Build the transport for ``account``'s provider."""
    if account.provider == SyncProvider.NEXTCLOUD:
        return NextcloudTasksTransport(account, parent, state)
    if account.provider == SyncProvider.WEBDAV:
        return WebDAVTransport(account, parent)
    if account.provider == SyncProvider.CALDAV:
        return CalDAVTransport(account, parent, state)
    if account.provider == SyncProvider.GOOGLE:
        raise NotImplementedError("Google sync is not implemented yet.")
    raise SyncTransportError(f"Unknown provider: {account.provider!r}")
