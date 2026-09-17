"""Repository factory — the single place where a storage backend is chosen.

Adding NeonDB or Supabase later means:
1. implement ``TodoRepository`` on top of Postgres,
2. register it here under a new key,
3. pass ``backend="postgres"`` (e.g. via env var) — nothing else changes.
"""

from __future__ import annotations

from pathlib import Path

from snake_todo.persistence.base import TodoRepository
from snake_todo.persistence.sqlite import SqliteTodoRepository

SUPPORTED_BACKENDS = frozenset({"sqlite"})


def create_repository(backend: str, db_path: Path) -> TodoRepository:
    """Build the repository for the requested backend."""
    if backend == "sqlite":
        return SqliteTodoRepository(db_path)
    raise ValueError(
        f"Unknown backend: {backend!r}. Available: {', '.join(sorted(SUPPORTED_BACKENDS))}"
    )