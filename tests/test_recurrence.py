"""Tests for RRULE parsing, occurrence math and completion semantics."""

from __future__ import annotations

from datetime import datetime, timezone

from todo_snake.domain.todo import TodoStatus
from todo_snake.persistence.sqlite import SqliteTodoRepository
from todo_snake.recurrence import build_rrule, next_occurrence, parse_rrule
from todo_snake.service import TodoService

_DUE = datetime(2026, 10, 7, 9, 0, tzinfo=timezone.utc)


def test_build_rrule():
    assert build_rrule(None) is None
    assert build_rrule("WEEKLY") == "FREQ=WEEKLY"
    assert build_rrule("DAILY", 3) == "FREQ=DAILY;INTERVAL=3"
    assert build_rrule("HOURLY") is None


def test_next_occurrence_daily():
    assert next_occurrence(_DUE, "FREQ=DAILY") == datetime(2026, 10, 8, 9, 0, tzinfo=timezone.utc)


def test_next_occurrence_weekly_interval():
    assert next_occurrence(_DUE, "FREQ=WEEKLY;INTERVAL=2") == datetime(
        2026, 10, 21, 9, 0, tzinfo=timezone.utc
    )


def test_next_occurrence_monthly_clamps_the_day():
    due = datetime(2026, 1, 31, 9, 0, tzinfo=timezone.utc)
    assert next_occurrence(due, "FREQ=MONTHLY") == datetime(2026, 2, 28, 9, 0, tzinfo=timezone.utc)


def test_next_occurrence_respects_until():
    assert next_occurrence(_DUE, "FREQ=DAILY;UNTIL=20261007T090000Z") is None


def test_parse_rrule_ignores_unknown_frequency():
    assert parse_rrule("FREQ=HOURLY") is None
    assert parse_rrule(None) is None


def test_recurring_task_gets_a_start_anchor(tmp_path):
    service = TodoService(SqliteTodoRepository(tmp_path / "t.db"))
    todo = service.add_todo("weekly", due_at=_DUE, recurrence="FREQ=WEEKLY")
    # Nextcloud Tasks needs a start date to treat a task as recurring.
    assert todo.start_at == _DUE


def test_recurring_without_a_due_date_gets_an_anchor(tmp_path):
    """A repeating task with no date at all would produce an unanchored RRULE,
    which the server rejects — it must get a due/start date."""
    service = TodoService(SqliteTodoRepository(tmp_path / "t.db"))
    todo = service.add_todo("weekly", recurrence="FREQ=WEEKLY")
    assert todo.due_at is not None
    assert todo.start_at == todo.due_at


def test_completing_a_recurring_task_advances_it(tmp_path):
    service = TodoService(SqliteTodoRepository(tmp_path / "t.db"))
    todo = service.add_todo("daily", due_at=_DUE, recurrence="FREQ=DAILY")

    advanced = service.toggle_done(todo.id)

    assert advanced.status is TodoStatus.OPEN
    assert advanced.due_at == datetime(2026, 10, 8, 9, 0, tzinfo=timezone.utc)
    assert advanced.start_at == datetime(2026, 10, 8, 9, 0, tzinfo=timezone.utc)
    assert advanced.completed_at is None


def test_completing_a_normal_task_marks_it_done(tmp_path):
    service = TodoService(SqliteTodoRepository(tmp_path / "t.db"))
    todo = service.add_todo("once", due_at=_DUE)

    done = service.toggle_done(todo.id)

    assert done.status is TodoStatus.DONE
    assert done.completed_at is not None
