"""Unit tests for the domain model."""

import dataclasses

import pytest

from todo_snake.domain import Todo, TodoPriority, TodoStatus


def test_defaults():
    todo = Todo(title="  Task  ")
    assert todo.title == "  Task  "
    assert todo.priority is TodoPriority.MEDIUM
    assert todo.due_date is None
    assert todo.status is TodoStatus.OPEN
    assert todo.is_done is False
    assert todo.id is None


def test_created_at_has_timezone():
    todo = Todo(title="x")
    assert todo.created_at.tzinfo is not None


def test_immutable():
    todo = Todo(title="x")
    with pytest.raises(dataclasses.FrozenInstanceError):
        todo.title = "other"


def test_status_enum_values():
    assert TodoStatus.OPEN.value == "open"
    assert TodoStatus.DONE.value == "done"
    assert TodoPriority.HIGH.value == "high"