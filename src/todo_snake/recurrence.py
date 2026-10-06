"""Minimal RRULE support for recurring tasks.

Covers what the UI offers and what server-side rules we must not break:
``FREQ`` (DAILY/WEEKLY/MONTHLY/YEARLY), ``INTERVAL``, and ``UNTIL`` (``COUNT``
is parsed but not enforced). Not a full RFC 5545 recurrence engine — ``BYDAY``
and the like are ignored.

Pure standard library.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

FREQUENCIES = ("DAILY", "WEEKLY", "MONTHLY", "YEARLY")


@dataclass(frozen=True)
class Recurrence:
    freq: str
    interval: int = 1
    until: datetime | None = None
    count: int | None = None


def parse_rrule(value: str | None) -> Recurrence | None:
    if not value:
        return None
    parts: dict[str, str] = {}
    for chunk in value.split(";"):
        if "=" in chunk:
            key, val = chunk.split("=", 1)
            parts[key.strip().upper()] = val.strip()
    freq = parts.get("FREQ", "").upper()
    if freq not in FREQUENCIES:
        return None
    try:
        interval = max(1, int(parts.get("INTERVAL", "1")))
    except ValueError:
        interval = 1
    count = None
    if parts.get("COUNT"):
        try:
            count = int(parts["COUNT"])
        except ValueError:
            count = None
    return Recurrence(
        freq=freq,
        interval=interval,
        until=_parse_until(parts.get("UNTIL", "")),
        count=count,
    )


def build_rrule(freq: str | None, interval: int = 1) -> str | None:
    if not freq:
        return None
    freq = freq.upper()
    if freq not in FREQUENCIES:
        return None
    interval = max(1, int(interval))
    return f"FREQ={freq}" + (f";INTERVAL={interval}" if interval != 1 else "")


def next_occurrence(due_at: datetime | None, rrule: str | None) -> datetime | None:
    """The next due moment after ``due_at``, or ``None`` when the rule has
    ended or is unusable."""
    if due_at is None:
        return None
    recurrence = parse_rrule(rrule)
    if recurrence is None:
        return None
    nxt = _add(due_at, recurrence)
    if nxt is not None and recurrence.until is not None and nxt > recurrence.until:
        return None
    return nxt


def _add(value: datetime, recurrence: Recurrence) -> datetime | None:
    if recurrence.freq == "DAILY":
        return value + timedelta(days=recurrence.interval)
    if recurrence.freq == "WEEKLY":
        return value + timedelta(weeks=recurrence.interval)
    if recurrence.freq == "MONTHLY":
        return _add_months(value, recurrence.interval)
    if recurrence.freq == "YEARLY":
        return _add_months(value, 12 * recurrence.interval)
    return None


def _add_months(value: datetime, months: int) -> datetime:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def _parse_until(value: str) -> datetime | None:
    value = value.strip()
    for fmt in ("%Y%m%dT%H%M%SZ", "%Y%m%dT%H%M%S", "%Y%m%d"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None
