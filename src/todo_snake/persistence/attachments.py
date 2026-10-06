"""SQLite storage for task attachments (local-first, bytes as BLOBs).

Lives in the same database file as the todos and sync journal. Each attachment
keeps the URLs of its uploaded copies per sync account (JSON in ``remote_urls``),
so the same file can live on several servers.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from todo_snake.domain.attachment import Attachment
from todo_snake.domain.todo import utc_now

_SCHEMA = """
CREATE TABLE IF NOT EXISTS attachments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    todo_uid    TEXT NOT NULL,
    filename    TEXT NOT NULL,
    mime        TEXT NOT NULL DEFAULT '',
    size        INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    data        BLOB,
    remote_urls TEXT
);
CREATE INDEX IF NOT EXISTS idx_attachments_todo ON attachments (todo_uid);
CREATE TABLE IF NOT EXISTS attachment_deletions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    account_uid TEXT NOT NULL,
    remote_url TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _from_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _encode_urls(urls: dict[str, str]) -> str | None:
    return json.dumps(urls, ensure_ascii=False, sort_keys=True) if urls else None


def _decode_urls(value: object) -> dict[str, str]:
    if not value:
        return {}
    try:
        parsed = json.loads(str(value))
    except ValueError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {str(account): str(url) for account, url in parsed.items() if isinstance(url, str)}


class SqliteAttachmentRepository:
    def __init__(self, db_path: Path):
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(_SCHEMA)
            _migrate(connection)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self._db_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
        except Exception:
            connection.rollback()
            raise
        else:
            connection.commit()
        finally:
            connection.close()

    def add(self, attachment: Attachment) -> Attachment:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO attachments
                    (todo_uid, filename, mime, size, created_at, data, remote_urls)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attachment.todo_uid,
                    attachment.filename,
                    attachment.mime,
                    attachment.size,
                    _iso(attachment.created_at),
                    attachment.data,
                    _encode_urls(attachment.remote_urls),
                ),
            )
        return _replace_id(attachment, cursor.lastrowid)

    def for_todo(self, todo_uid: str, *, with_data: bool = False) -> list[Attachment]:
        if with_data:
            columns = "*, (data IS NOT NULL) AS has_data"
        else:
            columns = (
                "id, todo_uid, filename, mime, size, created_at, remote_urls, "
                "(data IS NOT NULL) AS has_data"
            )
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT {columns} FROM attachments WHERE todo_uid = ? ORDER BY id",
                (todo_uid,),
            ).fetchall()
        return [_row_to_attachment(row) for row in rows]

    def get(self, attachment_id: int) -> Attachment | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM attachments WHERE id = ?", (attachment_id,)
            ).fetchone()
        return _row_to_attachment(row) if row is not None else None

    def set_remote_url(self, attachment_id: int, account_uid: str, remote_url: str) -> None:
        """Remember the uploaded URL of one account's copy."""
        self._update_urls(
            attachment_id, lambda urls: urls | {account_uid: remote_url}, delete_if_empty=False
        )

    def remove_remote_url(self, attachment_id: int, account_uid: str) -> None:
        """Forget one account's copy; drops a link-only row that becomes empty."""

        def drop(urls: dict[str, str]) -> dict[str, str]:
            urls.pop(account_uid, None)
            return urls

        self._update_urls(attachment_id, drop, delete_if_empty=True)

    def _update_urls(self, attachment_id: int, change, *, delete_if_empty: bool) -> None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT remote_urls, (data IS NOT NULL) AS has_data FROM attachments WHERE id = ?",
                (attachment_id,),
            ).fetchone()
            if row is None:
                return
            urls = change(_decode_urls(row["remote_urls"]))
            if delete_if_empty and not urls and not row["has_data"]:
                connection.execute("DELETE FROM attachments WHERE id = ?", (attachment_id,))
                return
            connection.execute(
                "UPDATE attachments SET remote_urls = ? WHERE id = ?",
                (_encode_urls(urls), attachment_id),
            )

    def delete(self, attachment_id: int) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM attachments WHERE id = ?", (attachment_id,))

    def delete_for_todo(self, todo_uid: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM attachments WHERE todo_uid = ?", (todo_uid,))

    def filenames_by_todo(self) -> dict[str, tuple[str, ...]]:
        """File names grouped by task uid, without loading any bytes."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT todo_uid, filename FROM attachments ORDER BY id"
            ).fetchall()
        grouped: dict[str, list[str]] = {}
        for row in rows:
            grouped.setdefault(row["todo_uid"], []).append(row["filename"])
        return {uid: tuple(names) for uid, names in grouped.items()}

    # -- server-side deletion queue ------------------------------------------

    def queue_deletions(self, entries: list[tuple[str, str]]) -> None:
        """Remember uploaded files whose attachment was removed locally."""
        if not entries:
            return
        created = utc_now().isoformat()
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO attachment_deletions (account_uid, remote_url, created_at)
                VALUES (?, ?, ?)
                """,
                [(account_uid, url, created) for account_uid, url in entries],
            )

    def pending_deletions(self, account_uid: str) -> list[tuple[int, str]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, remote_url FROM attachment_deletions WHERE account_uid = ? ORDER BY id",
                (account_uid,),
            ).fetchall()
        return [(int(row["id"]), row["remote_url"]) for row in rows]

    def drop_deletion(self, deletion_id: int) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM attachment_deletions WHERE id = ?", (deletion_id,))

    def remote_urls_for_account(self, account_uid: str) -> set[str]:
        """Every uploaded URL this account currently has for a known attachment."""
        with self._connect() as connection:
            rows = connection.execute("SELECT remote_urls FROM attachments").fetchall()
        urls: set[str] = set()
        for row in rows:
            url = _decode_urls(row["remote_urls"]).get(account_uid)
            if url:
                urls.add(url)
        return urls


def _migrate(connection: sqlite3.Connection) -> None:
    """Bring a database from the pre-multi-account schema up to date."""
    columns = {row[1] for row in connection.execute("PRAGMA table_info(attachments)")}
    if "remote_urls" not in columns:
        connection.execute("ALTER TABLE attachments ADD COLUMN remote_urls TEXT")
    if "remote_url" in columns:
        # The single URL could not be attributed to an account; the file is
        # re-uploaded on the next sync (same path, so it just gets overwritten).
        connection.execute("ALTER TABLE attachments DROP COLUMN remote_url")


def _replace_id(attachment: Attachment, attachment_id: int) -> Attachment:
    return replace(attachment, id=attachment_id)


def _row_to_attachment(row: sqlite3.Row) -> Attachment:
    # ``for_todo`` with ``with_data=False`` intentionally omits the BLOB column.
    columns = row.keys()
    data = row["data"] if "data" in columns else None
    has_data = bool(row["has_data"]) if "has_data" in columns else data is not None
    return Attachment(
        id=row["id"],
        todo_uid=row["todo_uid"],
        filename=row["filename"],
        mime=row["mime"] or "",
        size=int(row["size"] or 0),
        created_at=_from_iso(row["created_at"]),
        data=bytes(data) if data is not None else None,
        remote_urls=_decode_urls(row["remote_urls"]),
        has_data=has_data,
    )
