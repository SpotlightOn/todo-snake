"""Persistence layer — repository pattern.

The abstract ``TodoRepository`` is the seam that lets us swap storage
backends (SQLite today, PostgreSQL for NeonDB/Supabase later) without
touching UI or service code.
"""

from .base import TodoRepository
from .factory import create_repository

__all__ = ["TodoRepository", "create_repository"]
