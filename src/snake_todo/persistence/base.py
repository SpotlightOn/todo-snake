"""Abstract repository interface for ``Todo`` persistence."""

from __future__ import annotations

from abc import ABC, abstractmethod

from snake_todo.domain.todo import Todo


class TodoRepository(ABC):
    """Storage-agnostic contract. Implementations must be fully deterministic
    in ordering: ``list`` returns newest-first.
    """

    @abstractmethod
    def create(self, todo: Todo) -> Todo:
        """Persist a new todo and return it with its assigned id."""

    @abstractmethod
    def get(self, todo_id: int) -> Todo | None:
        """Return the todo with the given id, or ``None``."""

    @abstractmethod
    def list(self) -> list[Todo]:
        """Return all todos, newest first."""

    @abstractmethod
    def update(self, todo: Todo) -> Todo:
        """Persist changes to an existing todo."""

    @abstractmethod
    def delete(self, todo_id: int) -> None:
        """Remove the todo with the given id (no-op if absent)."""

    @abstractmethod
    def content_hash_exists(self, content_hash: str) -> bool:
        """Return ``True`` if a todo with the given content hash exists."""