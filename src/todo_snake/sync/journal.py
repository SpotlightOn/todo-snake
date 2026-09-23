"""Tombstone journal for synced deletions.

Deleting a todo locally hard-removes the row. To propagate that deletion to
other devices we must remember the id and the deletion time until the merged
document reached the server. ``SyncJournal`` keeps those tombstones in a small
companion table inside the same SQLite file as the todos.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sync_tombstones (
    uid        TEXT PRIMARY KEY,
    deleted_at TEXT NOT NULL
);
"""


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _from_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


class SyncJournal:
    def __init__(self, db_path: Path):
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(_SCHEMA)

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

    def record_deleted(self, uid: str, deleted_at: datetime | None = None) -> None:
        """Remember that the todo with ``uid`` was deleted locally."""
        stamp = _iso(deleted_at or datetime.now(timezone.utc))
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO sync_tombstones (uid, deleted_at)
                VALUES (?, ?)
                ON CONFLICT(uid) DO UPDATE SET deleted_at = excluded.deleted_at
                """,
                (uid, stamp),
            )

    def tombstones(self) -> dict[str, datetime]:
        """Return ``{uid: deleted_at}`` for all recorded deletions."""
        with self._connect() as connection:
            rows = connection.execute("SELECT uid, deleted_at FROM sync_tombstones").fetchall()
        return {row["uid"]: _from_iso(row["deleted_at"]) for row in rows}

    def remove(self, uid: str) -> None:
        """Forget a tombstone once the server has seen the deletion."""
        with self._connect() as connection:
            connection.execute("DELETE FROM sync_tombstones WHERE uid = ?", (uid,))

    def prune_all(self) -> None:
        """Forget every tombstone (the server document has seen them all)."""
        with self._connect() as connection:
            connection.execute("DELETE FROM sync_tombstones")
