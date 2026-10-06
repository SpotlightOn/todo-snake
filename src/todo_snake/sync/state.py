"""Per-account CalDAV/Nextcloud sync state.

CalDAV has no tombstones: deleting a task removes its resource. To tell a
*local* new task from one that was *deleted on the server*, the last known set
of server resources (their UIDs and ETags) is kept per account. A UID that was
known before and is gone now was deleted remotely.

This store lives in the same SQLite file as the todos/journal.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sync_resources (
    account TEXT NOT NULL,
    uid     TEXT NOT NULL,
    etag    TEXT NOT NULL,
    PRIMARY KEY (account, uid)
);
"""


class SyncStateStore:
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

    def etags(self, account: str) -> dict[str, str]:
        """Return ``{uid: etag}`` for the resources the server had last time."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT uid, etag FROM sync_resources WHERE account = ?", (account,)
            ).fetchall()
        return {row["uid"]: row["etag"] for row in rows}

    def known_uids(self, account: str) -> set[str]:
        return set(self.etags(account))

    def replace(self, account: str, etags: dict[str, str]) -> None:
        """Store the current server resource set for ``account``."""
        with self._connect() as connection:
            connection.execute("DELETE FROM sync_resources WHERE account = ?", (account,))
            connection.executemany(
                "INSERT INTO sync_resources (account, uid, etag) VALUES (?, ?, ?)",
                [(account, uid, etag) for uid, etag in etags.items()],
            )

    def clear(self, account: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM sync_resources WHERE account = ?", (account,))
