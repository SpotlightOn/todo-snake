"""Tests for the minimal iCalendar VTODO reader/writer."""

from datetime import datetime, timezone

from todo_snake.domain.todo import TodoPriority, TodoStatus
from todo_snake.sync.document import SyncItem
from todo_snake.sync.icalendar import parse_vtodo, to_ical

_CREATED = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
_UPDATED = datetime(2026, 9, 2, 11, 30, tzinfo=timezone.utc)
_COMPLETED = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)


def make_item(**overrides) -> SyncItem:
    values = {
        "uid": "u-1",
        "title": "Buy milk",
        "priority": TodoPriority.HIGH,
        "due_at": datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc),
        "note": "two litres",
        "status": TodoStatus.OPEN,
        "created_at": _CREATED,
        "completed_at": None,
        "updated_at": _UPDATED,
    }
    values.update(overrides)
    return SyncItem(**values)


def test_roundtrip_preserves_fields():
    item = make_item()
    parsed = parse_vtodo(to_ical(item))
    assert parsed is not None
    assert parsed.uid == "u-1"
    assert parsed.title == "Buy milk"
    assert parsed.priority is TodoPriority.HIGH
    assert parsed.due_at == datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)
    assert parsed.note == "two litres"
    assert parsed.status is TodoStatus.OPEN
    assert parsed.completed_at is None
    assert parsed.created_at == _CREATED
    assert parsed.updated_at == _UPDATED
    assert parsed.deleted is False


def test_roundtrip_done_task_keeps_completion_time():
    item = make_item(status=TodoStatus.DONE, completed_at=_COMPLETED)
    parsed = parse_vtodo(to_ical(item))
    assert parsed.status is TodoStatus.DONE
    assert parsed.completed_at == _COMPLETED


def test_roundtrip_escapes_special_characters():
    item = make_item(title="A, B; C\\D", note="line1\nline2, with comma")
    parsed = parse_vtodo(to_ical(item))
    assert parsed.title == "A, B; C\\D"
    assert parsed.note == "line1\nline2, with comma"


def test_tombstone_roundtrips_as_cancelled():
    stamp = datetime(2026, 9, 4, 8, 0, tzinfo=timezone.utc)
    parsed = parse_vtodo(to_ical(SyncItem.tombstone("u-gone", stamp)))
    assert parsed is not None
    assert parsed.uid == "u-gone"
    assert parsed.deleted is True


def test_roundtrip_preserves_microsecond_precision():
    """iCalendar itself is second-resolution; our X- extension keeps the full
    timestamp so last-write-wins works within the same second."""
    precise = datetime(2026, 9, 2, 11, 30, 0, 123456, tzinfo=timezone.utc)
    parsed = parse_vtodo(to_ical(make_item(updated_at=precise)))
    assert parsed.updated_at == precise


def test_writes_due_as_utc_date_time():
    """DUE is emitted as a UTC DATE-TIME (not an all-day DATE)."""
    item = make_item(due_at=datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc))
    assert "DUE:20261001T090000Z" in to_ical(item)


def test_priority_scale_maps_both_ways():
    for priority, number in (
        (TodoPriority.HIGH, "1"),
        (TodoPriority.MEDIUM, "5"),
        (TodoPriority.LOW, "9"),
    ):
        parsed = parse_vtodo(to_ical(make_item(priority=priority)))
        assert parsed.priority is priority
        assert f"PRIORITY:{number}" in to_ical(make_item(priority=priority))


def test_parses_external_vtodo_with_parameters_and_tzid():
    raw = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
        "BEGIN:VTODO\r\n"
        "UID:ext-1\r\n"
        "SUMMARY:Call\\, mom\r\n"
        "DESCRIPTION:first\\nsecond\r\n"
        "DUE;VALUE=DATE:20261224\r\n"
        "PRIORITY:3\r\n"
        "STATUS:NEEDS-ACTION\r\n"
        "CREATED:20260101T000000Z\r\n"
        "LAST-MODIFIED:20260102T000000Z\r\n"
        "END:VTODO\r\nEND:VCALENDAR\r\n"
    )
    parsed = parse_vtodo(raw)
    assert parsed.uid == "ext-1"
    assert parsed.title == "Call, mom"
    assert parsed.note == "first\nsecond"
    assert parsed.due_at == datetime(2026, 12, 24, tzinfo=timezone.utc)
    assert parsed.priority is TodoPriority.HIGH


def test_unfolds_long_lines():
    raw = (
        "BEGIN:VCALENDAR\r\nBEGIN:VTODO\r\nUID:fold-1\r\n"
        "SUMMARY:Hello\r\n World\r\n"
        "END:VTODO\r\nEND:VCALENDAR\r\n"
    )
    assert parse_vtodo(raw).title == "HelloWorld"


def test_returns_none_without_vtodo():
    assert parse_vtodo("BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:x\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n") is None
    assert parse_vtodo("BEGIN:VCALENDAR\r\nBEGIN:VTODO\r\nUID:x\r\nEND:VTODO\r\nEND:VCALENDAR\r\n") is None
