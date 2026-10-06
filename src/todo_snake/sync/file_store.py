"""Attachment files in a Nextcloud account's Files area (WebDAV).

Attachments are local-first (bytes in the database). For a Nextcloud account
they are additionally pushed to the user's Files so other clients can open
them; the task then carries an ``ATTACH`` URL pointing at the uploaded file.

Files are stored per task under ``Todo Snake/Attachments/<task uid>/``, which
avoids name collisions between tasks. The returned URL is the WebDAV file URL
(``<server>/remote.php/dav/files/<user>/…``); opening it in a browser prompts
for the account credentials.

Uses :class:`todo_snake.sync.webdav.DavClient` for the HTTP work — this class
only knows *which* URLs and *which* bodies.
"""

from __future__ import annotations

from urllib.parse import quote

from PySide6.QtCore import QUrl

from todo_snake.sync.accounts import SyncAccount, SyncProvider
from todo_snake.sync.webdav import (
    _PROPFIND_BODY,
    DavClient,
    SyncTransportError,
    parse_propfind_children,
)

#: Folder (below the user's files root) that holds all uploaded attachments.
ATTACHMENT_FOLDER = ("Todo Snake", "Attachments")


class NextcloudFileStore:
    """Pushes attachment bytes into the account's Nextcloud Files."""

    def __init__(self, account: SyncAccount, parent=None):
        self._account = account
        self._dav = DavClient(account, parent)

    # -- public API ---------------------------------------------------------

    def upload(self, todo_uid: str, filename: str, data: bytes) -> str:
        """Create the folder chain if needed, ``PUT`` the file, return its URL."""
        folder = self._ensure_folders((*ATTACHMENT_FOLDER, todo_uid))
        file_url = f"{folder}/{quote(filename, safe='')}"
        status, _ = self._dav.exchange(b"PUT", QUrl(file_url), data)
        self._dav.require_success(status)
        return file_url

    def delete(self, url: str) -> bool:
        """Delete an uploaded file; ``False`` when ``url`` is not ours to delete.

        Only files inside the ``Todo Snake/Attachments`` folder are removed — a
        URL that another client attached elsewhere is left alone.
        """
        if not self.owns(url):
            return False
        status, _ = self._dav.exchange(b"DELETE", QUrl(url))
        if status not in (200, 202, 204, 404):  # 404: already gone
            self._dav.require_success(status)
        return True

    def owns(self, url: str) -> bool:
        """Whether ``url`` points into this account's attachment folder."""
        return url.startswith(f"{self._attachments_base()}/")

    def files_of_task(self, todo_uid: str) -> list[str]:
        """Absolute URLs of the files uploaded for one task."""
        return self._files_in(self._task_folder(todo_uid))

    def list_attachment_files(self) -> list[str]:
        """Absolute URLs of every file below ``Todo Snake/Attachments``."""
        base = self._attachments_base()
        files: list[str] = []
        folders: list[str] = []
        for href, is_collection in self._propfind(base):
            url = self._absolute(href)
            if is_collection:
                if url.rstrip("/") != base:
                    folders.append(url)
            else:
                files.append(url)
        for folder in folders:
            files.extend(self._files_in(folder))
        return _unique(files)

    def close(self) -> None:
        """Release the network manager."""
        self._dav.close()

    # -- URL helpers --------------------------------------------------------

    def _files_root(self) -> str:
        """``<server>/remote.php/dav/files/<user>`` for this account."""
        username = (self._account.username or "").strip()
        if not username:
            raise SyncTransportError("No username configured.")
        return f"{self._dav.base()}/remote.php/dav/files/{quote(username, safe='')}"

    def _attachments_base(self) -> str:
        segments = "/".join(quote(segment, safe="") for segment in ATTACHMENT_FOLDER)
        return f"{self._files_root()}/{segments}"

    def _task_folder(self, todo_uid: str) -> str:
        return f"{self._attachments_base()}/{quote(todo_uid, safe='')}"

    def _absolute(self, href: str) -> str:
        """Turn a server ``href`` (usually a path) into an absolute URL."""
        if href.startswith(("http://", "https://")):
            return href
        scheme, _, rest = self._dav.base().partition("://")
        host = rest.split("/", 1)[0]
        return f"{scheme}://{host}{href}"

    # -- folder listing -----------------------------------------------------

    def _ensure_folders(self, segments) -> str:
        """``MKCOL`` each path segment in turn; return the deepest URL."""
        url = self._files_root()
        for segment in segments:
            url = f"{url}/{quote(segment, safe='')}"
            status, _ = self._dav.exchange(b"MKCOL", QUrl(url))
            # 201: created; 405/301/412: already exists (or a race).
            if status not in (201, 405, 301, 412):
                self._dav.require_success(status)
        return url

    def _files_in(self, folder_url: str) -> list[str]:
        """Absolute URLs of the files directly inside one folder."""
        return _unique(
            self._absolute(href)
            for href, is_collection in self._propfind(folder_url)
            if not is_collection
        )

    def _propfind(self, url: str) -> list[tuple[str, bool]]:
        status, body = self._dav.exchange(b"PROPFIND", QUrl(url), _PROPFIND_BODY, depth="1")
        if status == 404:  # nothing uploaded yet
            return []
        self._dav.require_success(status)
        return parse_propfind_children(body)


def _unique(urls) -> list[str]:
    """De-duplicate, keeping the order (the server may list a folder twice)."""
    seen: set[str] = set()
    unique: list[str] = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            unique.append(url)
    return unique


def make_file_store(account: SyncAccount, parent=None):
    """Return a file store for ``account``, or ``None`` when its provider does
    not support uploading attachment files."""
    if account.provider != SyncProvider.NEXTCLOUD:
        return None
    return NextcloudFileStore(account, parent)
