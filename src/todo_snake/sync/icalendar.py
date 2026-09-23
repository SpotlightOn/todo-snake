"""Minimal iCalendar (RFC 5545) reader/writer for VTODO resources.

Only what the CalDAV sync needs: one ``VTODO`` per resource, mapped to and from
``SyncItem``. Deletions are represented as ``STATUS:CANCELLED`` so a tombstone
survives on the server and propagates to other devices (a deleted CalDAV
resource would simply be gone, causing "resurrection" on the next merge).

``LAST-MODIFIED``/``CREATED`` only carry **second** resolution, which is too
coarse for last-write-wins when two devices change a task within the same
second. We therefore also write our own full-precision timestamps into the
``X-TODO-SNAKE-*`` extension properties; foreign CalDAV clients ignore them,
our own devices use them to converge correctly.

Pure standard library — no external dependency.
"""

from __future__ import annotations

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
    """Collect the properties of the first ``VTODO`` component."""
    inside = False
    props: dict[str, str] = {}
    for line in _unfold(data):
        upper = line.upper()
        if upper == "BEGIN:VTODO":
            inside = True
            props = {}
            continue
        if upper == "END:VTODO":
            return props
        if not inside:
            continue
        parsed = _split_content_line(line)
        if parsed is not None:
            name, value = parsed
            props.setdefault(name, value)
    return None


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

    status = (props.get("STATUS") or "").upper()
    deleted = status == "CANCELLED"
    updated_at = (
        _parse_iso(props.get(_UPDATED_EXT, ""))
        or _parse_datetime(props.get("LAST-MODIFIED", ""))
        or _parse_datetime(props.get("DTSTAMP", ""))
        or datetime.now(timezone.utc)
    )
    created_at = (
        _parse_iso(props.get(_CREATED_EXT, ""))
        or _parse_datetime(props.get("CREATED", ""))
        or updated_at
    )
    title = _unescape(props.get("SUMMARY", "")).strip()
    if not deleted and not title:
        return None

    return SyncItem(
        uid=uid,
        title=title,
        priority=_priority_from_ical(props.get("PRIORITY", "0")),
        due_at=_parse_datetime(props.get("DUE", "")),
        note=_unescape(props.get("DESCRIPTION", "")).strip(),
        status=TodoStatus.DONE if status == "COMPLETED" else TodoStatus.OPEN,
        created_at=created_at,
        completed_at=_parse_datetime(props.get("COMPLETED", "")),
        updated_at=updated_at,
        deleted=deleted,
    )


def to_ical(item: SyncItem) -> str:
    """Serialize a ``SyncItem`` to a single-VTODO calendar."""
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//todo-snake//sync//EN",
        "BEGIN:VTODO",
        f"UID:{item.uid}",
        f"DTSTAMP:{_format_datetime(item.updated_at)}",
        f"CREATED:{_format_datetime(item.created_at)}",
        f"LAST-MODIFIED:{_format_datetime(item.updated_at)}",
        f"{_CREATED_EXT}:{item.created_at.isoformat()}",
        f"{_UPDATED_EXT}:{item.updated_at.isoformat()}",
    ]
    if item.deleted:
        lines.append("STATUS:CANCELLED")
    else:
        lines.append(f"SUMMARY:{_escape(item.title)}")
        if item.note:
            lines.append(f"DESCRIPTION:{_escape(item.note)}")
        lines.append(
            "STATUS:COMPLETED" if item.status is TodoStatus.DONE else "STATUS:NEEDS-ACTION"
        )
        if item.completed_at is not None:
            lines.append(f"COMPLETED:{_format_datetime(item.completed_at)}")
        if item.due_at is not None:
            lines.append(f"DUE:{_format_datetime(item.due_at)}")
        lines.append(f"PRIORITY:{_PRIORITY_TO_ICAL.get(item.priority, '5')}")
    lines += ["END:VTODO", "END:VCALENDAR"]
    return _fold(lines)


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
