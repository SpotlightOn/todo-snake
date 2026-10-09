"""Modern styling for the ``QCalendarWidget`` date popup.

Qt's stock calendar looks dated next to the rest of the app. This module applies
a light, green-accented stylesheet to the popup calendar of a ``QDateEdit``:
rounded navigation bar, hover states, a visible today/selection, and muted
other-month days. It is pure QSS — no dependency, no behaviour change.

The extra padding on ``QAbstractItemView`` is what turns the year/month arrows
into real buttons; the ``::menu-indicator`` rule removes the default drop-down
arrow next to the month name.
"""

from __future__ import annotations

from PySide6.QtWidgets import QDateEdit

_ACCENT = "#4caf50"
_ACCENT_SOFT = "rgba(76, 175, 80, 0.15)"
_TEXT = "#3c3c43"
_MUTED = "#c5c5c7"


def calendar_stylesheet() -> str:
    """Return the QSS for a modern, green-accented calendar popup."""
    return f"""
QCalendarWidget {{
    background-color: #ffffff;
}}
QCalendarWidget QWidget#qt_calendar_navigationbar {{
    background-color: #f4f4f6;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
}}
QCalendarWidget QToolButton {{
    background: transparent;
    border: none;
    border-radius: 6px;
    padding: 4px 8px;
    font-weight: 600;
    color: {_TEXT};
}}
QCalendarWidget QToolButton:hover {{
    background-color: {_ACCENT_SOFT};
}}
QCalendarWidget QToolButton:disabled {{
    color: {_MUTED};
}}
QCalendarWidget QToolButton::menu-indicator {{
    image: none;
}}
QCalendarWidget QSpinBox#qt_calendar_yearedit {{
    background: transparent;
    border: none;
    font-weight: 600;
    color: {_TEXT};
}}
QCalendarWidget QCalendarModel {{
    background-color: transparent;
    color: {_TEXT};
}}
QCalendarWidget QCalendarModel:disabled {{
    color: {_MUTED};
}}
QCalendarWidget QAbstractItemView {{
    background-color: transparent;
    border: none;
    outline: 0;
    padding: 4px;
    selection-background-color: {_ACCENT};
    selection-color: #ffffff;
}}
"""


def style_date_edit(date_edit: QDateEdit) -> None:
    """Apply the calendar theme to ``date_edit``'s popup calendar."""
    calendar = date_edit.calendarWidget()
    if calendar is not None:
        calendar.setStyleSheet(calendar_stylesheet())


__all__ = ["calendar_stylesheet", "style_date_edit"]
