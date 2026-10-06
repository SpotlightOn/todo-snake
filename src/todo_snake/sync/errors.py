"""Errors of the sync layer.

Deliberately dependency-free (no Qt), so the sync *core* — ``engine``,
``document``, ``icalendar`` — keeps its error handling without pulling in the
UI stack. ``todo_snake.sync.webdav`` re-exports this for the transports.
"""

from __future__ import annotations


class SyncTransportError(RuntimeError):
    """Raised when talking to the sync server fails."""
