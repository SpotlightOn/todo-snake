"""Dialog for creating and editing a todo."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QPushButton,
    QWidget,
    QVBoxLayout,
)

from snake_todo.domain.todo import Todo, TodoPriority

_PRIORITY_ITEMS: list[tuple[str, TodoPriority]] = [
    ("Low", TodoPriority.LOW),
    ("Medium", TodoPriority.MEDIUM),
    ("High", TodoPriority.HIGH),
]


@dataclass(frozen=True)
class TodoFormData:
    """Result of a successfully accepted dialog."""

    title: str
    priority: TodoPriority
    due_date: date | None


class TodoDialog(QDialog):
    def __init__(self, parent: QWidget | None = None, todo: Todo | None = None):
        super().__init__(parent)
        self.setWindowTitle("Edit task" if todo is not None else "New task")
        self.setModal(True)
        self.setMinimumWidth(380)

        self._title_edit = QLineEdit(self)
        self._title_edit.setPlaceholderText("What needs to be done?")
        self._todo = todo
        if todo is not None:
            self._title_edit.setText(todo.title)

        self._priority_combo = QComboBox(self)
        for label, priority in _PRIORITY_ITEMS:
            self._priority_combo.addItem(label, priority.value)
        if todo is not None:
            self._priority_combo.setCurrentIndex(
                self._priority_combo.findData(todo.priority.value)
            )

        self._due_checkbox = QCheckBox("Set due date", self)
        self._due_date_edit = QDateEdit(self)
        self._due_date_edit.setCalendarPopup(True)
        self._due_date_edit.setDisplayFormat("yyyy-MM-dd")
        self._due_date_edit.setDate(QDate.currentDate())
        self._due_date_edit.setEnabled(False)
        if todo is not None and todo.due_date is not None:
            self._due_checkbox.setChecked(True)
            self._due_date_edit.setEnabled(True)
            self._due_date_edit.setDate(
                QDate(todo.due_date.year, todo.due_date.month, todo.due_date.day)
            )

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        self._ok_button: QPushButton = self._buttons.button(
            QDialogButtonBox.StandardButton.Ok
        )
        self._ok_button.setText("Save")

        form = QFormLayout()
        form.addRow("Task:", self._title_edit)
        form.addRow("Priority:", self._priority_combo)
        form.addRow("", self._due_checkbox)
        form.addRow("Due on:", self._due_date_edit)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self._buttons)

        self._due_checkbox.toggled.connect(self._due_date_edit.setEnabled)
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
            due_date=(
                dialog._due_date_edit.date().toPython()
                if dialog._due_checkbox.isChecked()
                else None
            ),
        )

    def _update_ok_state(self) -> None:
        self._ok_button.setEnabled(bool(self._title_edit.text().strip()))