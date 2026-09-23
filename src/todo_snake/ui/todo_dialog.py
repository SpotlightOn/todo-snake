"""Dialog for creating and editing a todo."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from PySide6.QtCore import QDateTime
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from todo_snake.domain.todo import Todo, TodoPriority
from todo_snake.ui.datetime_edit import DateTimeEdit
from todo_snake.ui.model import priority_label
from todo_snake.ui.switch import apply_switch_style

_PRIORITY_ORDER: list[TodoPriority] = [
    TodoPriority.LOW,
    TodoPriority.MEDIUM,
    TodoPriority.HIGH,
]


@dataclass(frozen=True)
class TodoFormData:
    """Result of a successfully accepted dialog."""

    title: str
    priority: TodoPriority
    due_at: datetime | None
    note: str


class TodoDialog(QDialog):
    def __init__(self, parent: QWidget | None = None, todo: Todo | None = None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Edit task") if todo is not None else self.tr("New task"))
        self.setModal(True)
        self.setMinimumWidth(380)

        self._title_edit = QLineEdit(self)
        self._title_edit.setPlaceholderText(self.tr("What needs to be done?"))
        self._todo = todo

        self._note_edit = QPlainTextEdit(self)
        self._note_edit.setPlaceholderText(self.tr("Additional note…"))
        self._note_edit.setFixedHeight(72)

        self._priority_combo = QComboBox(self)
        for priority in _PRIORITY_ORDER:
            self._priority_combo.addItem(priority_label(priority), priority.value)

        self._due_switch = QCheckBox(self.tr("Set due date/time"), self)
        apply_switch_style(self._due_switch)
        self._due_at_edit = DateTimeEdit(self)
        self._due_at_edit.setDateTime(QDateTime.currentDateTime())
        self._due_at_edit.setEnabled(False)

        if todo is not None:
            self._title_edit.setText(todo.title)
            self._note_edit.setPlainText(todo.note)
            self._priority_combo.setCurrentIndex(self._priority_combo.findData(todo.priority.value))
            if todo.due_at is not None:
                self._due_switch.setChecked(True)
                self._due_at_edit.setEnabled(True)
                local = todo.due_at.astimezone().replace(tzinfo=None)
                self._due_at_edit.setDateTime(QDateTime(local))

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        self._ok_button: QPushButton = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._ok_button.setText(self.tr("Save"))

        form = QFormLayout()
        form.addRow(self.tr("Task:"), self._title_edit)
        form.addRow(self.tr("Priority:"), self._priority_combo)
        form.addRow(self.tr("Note:"), self._note_edit)
        form.addRow("", self._due_switch)
        form.addRow(self.tr("Due:"), self._due_at_edit)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self._buttons)

        self._due_switch.toggled.connect(self._on_due_toggled)
        self._title_edit.textChanged.connect(self._update_ok_state)
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)

        self._update_ok_state()

    def accept(self) -> None:
        if not self._title_edit.text().strip():
            return
        super().accept()

    @classmethod
    def create(cls, parent: QWidget | None, todo: Todo | None = None) -> TodoFormData | None:
        """Run the dialog; return form data or ``None`` when cancelled."""
        dialog = cls(parent, todo)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return TodoFormData(
            title=dialog._title_edit.text().strip(),
            priority=TodoPriority(dialog._priority_combo.currentData()),
            due_at=(
                dialog._due_at_edit.dateTime().toPython().astimezone(timezone.utc)
                if dialog._due_switch.isChecked()
                else None
            ),
            note=dialog._note_edit.toPlainText().strip(),
        )

    def _update_ok_state(self) -> None:
        self._ok_button.setEnabled(bool(self._title_edit.text().strip()))

    def _on_due_toggled(self, checked: bool) -> None:
        self._due_at_edit.setEnabled(checked)
        if checked:
            # Turning the switch on means "due from now", not the stale date
            # that happened to sit in the field.
            self._due_at_edit.set_now()
