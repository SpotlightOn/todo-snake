"""A date field with a calendar popup plus a separate, explicit time field.

Qt's ``QDateTimeEdit`` has a calendar popup that only selects the **date**; the
time has to be edited in the spin sections, which is easy to miss. This widget
splits the two: a ``QDateEdit`` with a calendar popup next to a ``QTimeEdit``,
so picking a date and a time are both obvious.

It mirrors the ``QDateTimeEdit`` API (``dateTime``/``setDateTime``) so callers
do not need to know it is a composite.
"""

from __future__ import annotations

from PySide6.QtCore import QDateTime
from PySide6.QtWidgets import QDateEdit, QHBoxLayout, QPushButton, QTimeEdit, QWidget


class DateTimeEdit(QWidget):
    """Date (calendar popup) + time (spin) + a "Now" shortcut, as one field."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._date = QDateEdit(self)
        self._date.setCalendarPopup(True)
        self._date.setDisplayFormat("yyyy-MM-dd")

        self._time = QTimeEdit(self)
        self._time.setDisplayFormat("HH:mm")

        self._now_button = QPushButton(self.tr("Now"), self)
        self._now_button.setToolTip(self.tr("Set to the current date and time"))
        self._now_button.clicked.connect(self.set_now)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._date, 1)
        layout.addWidget(self._time, 0)
        layout.addWidget(self._now_button, 0)

    # -- QDateTimeEdit-like API ---------------------------------------------

    def dateTime(self) -> QDateTime:
        return QDateTime(self._date.date(), self._time.time())

    def setDateTime(self, value: QDateTime) -> None:
        self._date.setDate(value.date())
        self._time.setTime(value.time())

    def setMinimumDateTime(self, value: QDateTime) -> None:
        self._date.setMinimumDate(value.date())
        self._time.setMinimumTime(value.time())

    def set_now(self) -> None:
        self.setDateTime(QDateTime.currentDateTime())

    # Exposed for tests/introspection.
    @property
    def date_edit(self) -> QDateEdit:
        return self._date

    @property
    def time_edit(self) -> QTimeEdit:
        return self._time

    @property
    def now_button(self) -> QPushButton:
        return self._now_button


__all__ = ["DateTimeEdit"]
