"""Minimal iCalendar (RFC 5545) reader/writer for VTODO resources.

Only what the CalDAV sync needs: one ``VTODO`` per resource, mapped to and from
``SyncItem``. Deletions are represented as ``STATUS:CANCELLED`` so a tombstone
survives on the server and propagates to other devices (a deleted CalDAV
resource would simply be gone, causing "resurrection" on the next merge).

Owned fields are rewritten; everything else in a foreign VTODO (categories,
recurrence, attachments, custom properties, …) is preserved by
:func:`patch_vtodo`, so editing a task in Todo Snake does not strip properties
set by other clients.

``LAST-MODIFIED``/``CREATED`` only carry **second** resolution, which is too
coarse for last-write-wins when two devices change a task within the same
second. We therefore also write our own full-precision timestamps into the
``X-TODO-SNAKE-*`` extension properties; foreign clients ignore them.

Pure standard library — no external dependency.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from todo_snake.domain.todo import TodoPriority, TodoStatus
from todo_snake.sync.document import SyncItem

_UPDATED_EXT = "X-TODO-SNAKE-UPDATED"
_CREATED_EXT = "X-TODO-SNAKE-CREATED"

_PRIORITY_TO_ICAL = {
    TodoPriority.HIGH: "1",
    TodoPriority.MEDIUM: "5",
    TodoPriority.LOW: "9",
}

_STATUS_TO_ICAL = {
    TodoStatus.OPEN: "NEEDS-ACTION",
    TodoStatus.IN_PROCESS: "IN-PROCESS",
    TodoStatus.DONE: "COMPLETED",
}

# Properties Todo Snake owns and rewrites; anything else is left untouched.
_OWNED_PROPERTIES = frozenset(
    {
        "UID",
        "SUMMARY",
        "DESCRIPTION",
        "STATUS",
        "DUE",
        "DTSTART",
        "PRIORITY",
        "COMPLETED",
        "CREATED",
        "DTSTAMP",
        "LAST-MODIFIED",
        "RRULE",
        _CREATED_EXT,
        _UPDATED_EXT,
    }
)

_TRIGGER_RE = re.compile(
    r"^TRIGGER[^:]*:([+-])?P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?\s*$",
    re.IGNORECASE,
)


def _priority_from_ical(value: str) -> TodoPriority:
    """Map iCalendar ``PRIORITY`` (0 = undefined, 1 = highest) to our scale."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return TodoPriority.MEDIUM
    if number <= 0:
        return TodoPriority.MEDIUM
    if number <= 3:
        return TodoPriority.HIGH
    if number <= 6:
        return TodoPriority.MEDIUM
    return TodoPriority.LOW


def _status_from_ical(value: str) -> tuple[TodoStatus, bool]:
    """Return ``(status, deleted)`` for an iCalendar ``STATUS``."""
    upper = value.upper()
    if upper == "COMPLETED":
        return TodoStatus.DONE, False
    if upper == "IN-PROCESS":
        return TodoStatus.IN_PROCESS, False
    if upper == "CANCELLED":
        return TodoStatus.OPEN, True
    return TodoStatus.OPEN, False


def _escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def _unescape(text: str) -> str:
    out: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char == "\\" and index + 1 < len(text):
            following = text[index + 1]
            out.append("\n" if following in ("n", "N") else following)
            index += 2
            continue
        out.append(char)
        index += 1
    return "".join(out)


def _format_datetime(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _parse_datetime(value: str) -> datetime | None:
    value = value.strip()
    if not value:
        return None
    try:
        if value.endswith("Z") and "T" in value:
            return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        if "T" in value:
            return datetime.strptime(value, "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
        return datetime.strptime(value, "%Y%m%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _parse_iso(value: str) -> datetime | None:
    """Parse one of our full-precision ``X-TODO-SNAKE-*`` timestamps."""
    try:
        parsed = datetime.fromisoformat(value.strip())
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


# -- content-line handling ---------------------------------------------------


def _unfold(data: str) -> list[str]:
    """Split into logical lines, undoing RFC 5545 line folding."""
    normalized = data.replace("\r\n", "\n").replace("\r", "\n")
    lines: list[str] = []
    for line in normalized.split("\n"):
        if line[:1] in (" ", "\t") and lines:
            lines[-1] += line[1:]
        elif line:
            lines.append(line)
    return lines


def _split_content_line(line: str) -> tuple[str, str] | None:
    """Return ``(NAME, value)``; parameters are stripped from the name."""
    in_quotes = False
    for index, char in enumerate(line):
        if char == '"':
            in_quotes = not in_quotes
        elif char == ":" and not in_quotes:
            head = line[:index]
            value = line[index + 1 :]
            return head.split(";", 1)[0].upper(), value
    return None


def _extract_vtodo_props(data: str) -> dict[str, str] | None:
    """Collect the properties of the first ``VTODO`` component (its own
    properties only — nested ``VALARM`` properties are skipped)."""
    inside = False
    in_alarm = False
    props: dict[str, str] = {}
    for line in _unfold(data):
        upper = line.upper()
        if upper == "BEGIN:VTODO":
            inside = True
            in_alarm = False
            props = {}
            continue
        if upper == "END:VTODO":
            return props
        if not inside:
            continue
        if upper == "BEGIN:VALARM":
            in_alarm = True
            continue
        if upper == "END:VALARM":
            in_alarm = False
            continue
        if in_alarm:
            continue
        parsed = _split_content_line(line)
        if parsed is not None:
            name, value = parsed
            props.setdefault(name, value)
    return None


def _parse_alarm_trigger(data: str) -> int:
    """Minutes before the due time for the first relative ``TRIGGER``."""
    for line in _unfold(data):
        match = _TRIGGER_RE.match(line.strip())
        if match is None:
            continue
        sign, weeks, days, hours, minutes, seconds = match.groups()
        total = (
            int(weeks or 0) * 7 * 1440
            + int(days or 0) * 1440
            + int(hours or 0) * 60
            + int(minutes or 0)
            + int(seconds or 0) // 60
        )
        return total if sign != "+" else 0
    return 0


def _parse_due(value: str) -> tuple[datetime | None, bool]:
    """Return ``(due, all_day)`` — a date-only value is an all-day due date."""
    value = (value or "").strip()
    if not value:
        return None, False
    if "T" in value:
        return _parse_datetime(value), False
    return _parse_datetime(value), True


# -- public API --------------------------------------------------------------


def parse_vtodo(data: str) -> SyncItem | None:
    """Parse calendar data into a ``SyncItem``; ``None`` if it has no usable
    ``VTODO`` (e.g. a ``VEVENT`` or a summary-less task)."""
    props = _extract_vtodo_props(data)
    if props is None:
        return None
    uid = (props.get("UID") or "").strip()
    if not uid:
        return None

    status, deleted = _status_from_ical(props.get("STATUS") or "")
    # Another client (e.g. the Nextcloud Tasks app) bumps LAST-MODIFIED but
    # leaves our own X-TODO-SNAKE-UPDATED untouched, so the real change time is
    # the *maximum* of both — the extension only adds sub-second precision.
    stamps = (
        _parse_iso(props.get(_UPDATED_EXT, "")),
        _parse_datetime(props.get("LAST-MODIFIED", "")),
        _parse_datetime(props.get("DTSTAMP", "")),
    )
    updated_at = max((stamp for stamp in stamps if stamp is not None), default=None)
    if updated_at is None:
        updated_at = datetime.now(timezone.utc)
    created_at = (
        _parse_iso(props.get(_CREATED_EXT, ""))
        or _parse_datetime(props.get("CREATED", ""))
        or updated_at
    )
    due_at, due_all_day = _parse_due(props.get("DUE", ""))
    title = _unescape(props.get("SUMMARY", "")).strip()
    if not deleted and not title:
        return None

    return SyncItem(
        uid=uid,
        title=title,
        priority=_priority_from_ical(props.get("PRIORITY", "0")),
        due_at=due_at,
        note=_unescape(props.get("DESCRIPTION", "")).strip(),
        status=status,
        created_at=created_at,
        completed_at=_parse_datetime(props.get("COMPLETED", "")),
        updated_at=updated_at,
        deleted=deleted,
        start_at=_parse_datetime(props.get("DTSTART", "")),
        due_all_day=due_all_day,
        remind_before=_parse_alarm_trigger(data),
        recurrence=props.get("RRULE") or None,
    )


def _owned_lines(item: SyncItem) -> list[str]:
    """The VTODO properties Todo Snake owns, as unfolded content lines."""
    lines = [
        f"UID:{item.uid}",
        f"DTSTAMP:{_format_datetime(item.updated_at)}",
        f"CREATED:{_format_datetime(item.created_at)}",
        f"LAST-MODIFIED:{_format_datetime(item.updated_at)}",
        f"{_CREATED_EXT}:{item.created_at.isoformat()}",
        f"{_UPDATED_EXT}:{item.updated_at.isoformat()}",
    ]
    if item.deleted:
        lines.append("STATUS:CANCELLED")
        return lines
    lines.append(f"SUMMARY:{_escape(item.title)}")
    if item.note:
        lines.append(f"DESCRIPTION:{_escape(item.note)}")
    lines.append(f"STATUS:{_STATUS_TO_ICAL.get(item.status, 'NEEDS-ACTION')}")
    if item.completed_at is not None:
        lines.append(f"COMPLETED:{_format_datetime(item.completed_at)}")
    start = item.start_at
    if start is None and item.recurrence and item.due_at is not None:
        # Recurrence needs an anchor (DTSTART); Nextcloud Tasks only exposes it
        # when a start date exists, so fall back to the due date.
        start = item.due_at
    if start is not None:
        if item.due_all_day and start is item.due_at:
            day = start.astimezone(timezone.utc).strftime("%Y%m%d")
            lines.append(f"DTSTART;VALUE=DATE:{day}")
        else:
            lines.append(f"DTSTART:{_format_datetime(start)}")
    if item.due_at is not None:
        if item.due_all_day:
            day = item.due_at.astimezone(timezone.utc).strftime("%Y%m%d")
            lines.append(f"DUE;VALUE=DATE:{day}")
        else:
            lines.append(f"DUE:{_format_datetime(item.due_at)}")
    lines.append(f"PRIORITY:{_PRIORITY_TO_ICAL.get(item.priority, '5')}")
    if item.recurrence:
        lines.append(f"RRULE:{item.recurrence}")
    lines.extend(_alarm_lines(item))
    return lines


def _alarm_lines(item: SyncItem) -> list[str]:
    if item.remind_before <= 0 or item.due_at is None:
        return []
    return [
        "BEGIN:VALARM",
        "ACTION:DISPLAY",
        f"DESCRIPTION:{_escape(item.title)}",
        f"TRIGGER:-PT{int(item.remind_before)}M",
        "END:VALARM",
    ]


def to_ical(item: SyncItem) -> str:
    """Serialize a ``SyncItem`` to a single-VTODO calendar."""
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//todo-snake//sync//EN",
        "BEGIN:VTODO",
        *_owned_lines(item),
        "END:VTODO",
        "END:VCALENDAR",
    ]
    return _fold(lines)


def patch_vtodo(raw: str, item: SyncItem) -> str:
    """Rewrite only the owned properties of an existing VTODO, keeping every
    other line (categories, recurrence, attachments, custom fields, …)."""
    out: list[str] = []
    in_todo = False
    in_alarm = False
    for line in _unfold(raw):
        upper = line.upper()
        if upper == "BEGIN:VTODO":
            in_todo = True
            out.append(line)
            out.extend(_owned_lines(item))
            continue
        if upper == "END:VTODO":
            in_todo = False
            out.append(line)
            continue
        if not in_todo:
            out.append(line)
            continue
        if upper == "BEGIN:VALARM":
            in_alarm = True
            continue
        if upper == "END:VALARM":
            in_alarm = False
            continue
        if in_alarm:
            continue
        name = line.split(":", 1)[0].split(";", 1)[0].upper()
        if name in _OWNED_PROPERTIES:
            continue
        out.append(line)
    return _fold(out)


def _fold(lines: list[str]) -> str:
    """Join lines with CRLF, folding any line longer than 75 octets."""
    folded: list[str] = []
    for line in lines:
        current = ""
        for char in line:
            if len((current + char).encode("utf-8")) > 75:
                folded.append(current)
                current = " " + char
            else:
                current += char
        folded.append(current)
    return "\r\n".join(folded) + "\r\n"
