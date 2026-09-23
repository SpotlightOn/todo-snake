"""Tests for due-date reminder logic, snooze state and the reminder dialog."""

from datetime import datetime, timedelta, timezone

from PySide6.QtCore import QSettings

from todo_snake.domain.todo import Todo, TodoStatus, utc_now
from todo_snake.persistence.sqlite import SqliteTodoRepository
from todo_snake.reminders import (
    ReminderStore,
    active_keys,
    next_reminder_moment,
    pending_reminders,
    reminder_key,
)
from todo_snake.service import TodoService
from todo_snake.ui.main_window import MainWindow
from todo_snake.ui.reminder_dialog import ReminderDialog

_NOW = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
_PAST = datetime(2026, 9, 23, 11, 0, tzinfo=timezone.utc)
_FUTURE = datetime(2026, 9, 23, 13, 0, tzinfo=timezone.utc)


def make_todo(title: str, due_at: datetime | None = None, done: bool = False) -> Todo:
    return Todo(
        title=title,
        uid=title,
        due_at=due_at,
        status=TodoStatus.DONE if done else TodoStatus.OPEN,
    )


def store_at(tmp_path) -> ReminderStore:
    return ReminderStore(QSettings(str(tmp_path / "reminders.ini"), QSettings.Format.IniFormat))


# -- pure logic --------------------------------------------------------------


def test_reminder_key_none_without_due():
    assert reminder_key(make_todo("a")) is None
    assert reminder_key(make_todo("a", _PAST)) == f"a@{_PAST.isoformat()}"


def test_pending_reminders_selects_due_unannounced():
    todos = [
        make_todo("past", _PAST),
        make_todo("future", _FUTURE),
        make_todo("done", _PAST, done=True),
        make_todo("undated"),
    ]
    assert [t.title for t in pending_reminders(todos, _NOW, set(), {})] == ["past"]


def test_pending_reminders_skips_already_announced():
    past = make_todo("past", _PAST)
    assert pending_reminders([past], _NOW, {reminder_key(past)}, {}) == []


def test_pending_reminders_respects_snooze():
    past = make_todo("past", _PAST)
    key = reminder_key(past)
    snoozed = {key: _NOW + timedelta(minutes=5)}
    assert pending_reminders([past], _NOW, set(), snoozed) == []
    assert pending_reminders([past], _NOW + timedelta(minutes=6), set(), snoozed) == [past]


def test_next_reminder_moment_picks_soonest():
    soon = make_todo("soon", _FUTURE)
    late = make_todo("late", _FUTURE + timedelta(hours=1))
    assert next_reminder_moment([soon, late], _NOW, set(), {}) == _FUTURE
    assert next_reminder_moment([soon, late], _NOW, {reminder_key(soon)}, {}) == (
        _FUTURE + timedelta(hours=1)
    )
    assert next_reminder_moment([make_todo("past", _PAST)], _NOW, set(), {}) is None


def test_active_keys_only_open_with_due():
    past = make_todo("past", _PAST)
    done = make_todo("done", _PAST, done=True)
    undated = make_todo("undated")
    assert active_keys([past, done, undated]) == {reminder_key(past)}


def test_reminder_store_roundtrip(tmp_path):
    store = store_at(tmp_path)
    assert store.load() == (set(), {})
    when = datetime(2026, 9, 23, 12, 30, tzinfo=timezone.utc)
    store.save({"a@x"}, {"b@y": when})
    announced, snoozed = store.load()
    assert announced == {"a@x"}
    assert snoozed == {"b@y": when}


# -- dialog integration ------------------------------------------------------


def test_check_reminders_shows_persistent_dialog_and_blinks(qapp, tmp_path):
    service = TodoService(SqliteTodoRepository(tmp_path / "todos.db"))
    service.add_todo("overdue", due_at=utc_now() - timedelta(hours=1))
    service.add_todo("later", due_at=utc_now() + timedelta(hours=1))

    window = MainWindow(service, reminder_store=store_at(tmp_path))
    active: list[bool] = []
    window.reminders_active.connect(active.append)

    window.check_reminders()

    assert len(window._reminder_dialogs) == 1
    dialog = next(iter(window._reminder_dialogs.values()))
    assert isinstance(dialog, ReminderDialog)
    assert dialog.isVisible()
    assert active[-1] is True

    dialog._on_dismiss()
    assert window._reminder_dialogs == {}
    assert active[-1] is False
    window.close()


def test_snooze_reannounces_after_delay(qapp, tmp_path):
    service = TodoService(SqliteTodoRepository(tmp_path / "todos.db"))
    service.add_todo("overdue", due_at=utc_now() - timedelta(hours=1))
    store = store_at(tmp_path)

    window = MainWindow(service, reminder_store=store)
    window.check_reminders()
    key = next(iter(window._reminder_dialogs))
    next(iter(window._reminder_dialogs.values()))._on_snooze(5)

    announced, snoozed = store.load()
    assert key in snoozed
    assert key not in announced
    todos = service.list_todos()
    assert pending_reminders(todos, utc_now(), announced, snoozed) == []
    assert pending_reminders(todos, utc_now() + timedelta(minutes=6), announced, snoozed)
    window.close()
