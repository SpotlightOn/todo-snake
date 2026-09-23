"""A persistent reminder window with snooze options.

Unlike a transient tray balloon, this window stays until it is dismissed (or
snoozed), so a due task cannot be missed. It offers to be reminded again in a
few minutes.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from todo_snake.reminders import SNOOZE_CHOICES_MINUTES


class ReminderDialog(QDialog):
    """Shows a due task and lets the user snooze or dismiss it."""

    snoozed = Signal(int)  # minutes
    dismissed = Signal()

    def __init__(self, title: str, due_text: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._resolved = False
        self.setWindowTitle(self.tr("Task due"))
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setModal(False)
        self.setMinimumWidth(340)

        heading = QLabel(self.tr("Task due"))
        heading_font = heading.font()
        heading_font.setBold(True)
        heading_font.setPointSize(heading_font.pointSize() + 2)
        heading.setFont(heading_font)

        task = QLabel(title)
        task.setWordWrap(True)
        task.setTextFormat(Qt.TextFormat.PlainText)

        due = QLabel(due_text)
        due.setTextFormat(Qt.TextFormat.PlainText)

        buttons = QHBoxLayout()
        for minutes in SNOOZE_CHOICES_MINUTES:
            button = QPushButton(self.tr("Snooze {minutes} min").format(minutes=minutes))
            button.clicked.connect(lambda _=False, m=minutes: self._on_snooze(m))
            buttons.addWidget(button)
        dismiss = QPushButton(self.tr("Dismiss"))
        dismiss.clicked.connect(self._on_dismiss)
        buttons.addWidget(dismiss)

        layout = QVBoxLayout(self)
        layout.addWidget(heading)
        layout.addWidget(task)
        layout.addWidget(due)
        layout.addLayout(buttons)

    # -- actions ------------------------------------------------------------

    def _on_snooze(self, minutes: int) -> None:
        self._resolved = True
        self.snoozed.emit(minutes)
        self.close()

    def _on_dismiss(self) -> None:
        self._resolved = True
        self.dismissed.emit()
        self.close()

    def closeEvent(self, event) -> None:
        # Closing via the window button counts as dismissing.
        if not self._resolved:
            self._resolved = True
            self.dismissed.emit()
        super().closeEvent(event)


__all__ = ["ReminderDialog"]
