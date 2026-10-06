"""Dialog for creating and editing a todo."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

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
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from todo_snake.domain.todo import Todo, TodoPriority, TodoStatus
from todo_snake.recurrence import build_rrule, parse_rrule
from todo_snake.ui.attachments_dialog import AttachmentsDialog
from todo_snake.ui.datetime_edit import DateTimeEdit
from todo_snake.ui.icons import create_attachment_icon
from todo_snake.ui.model import priority_label
from todo_snake.ui.switch import apply_switch_style

if TYPE_CHECKING:
    from todo_snake.service.attachment_service import AttachmentService

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
    status: TodoStatus
    start_at: datetime | None
    due_all_day: bool
    remind_before: int
    recurrence: str | None


class TodoDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None = None,
        todo: Todo | None = None,
        attachments: AttachmentService | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Edit task") if todo is not None else self.tr("New task"))
        self.setModal(True)
        self.setMinimumWidth(400)

        self._title_edit = QLineEdit(self)
        self._title_edit.setPlaceholderText(self.tr("What needs to be done?"))
        self._todo = todo
        self._attachments_service = attachments

        self._note_edit = QPlainTextEdit(self)
        self._note_edit.setPlaceholderText(self.tr("Additional note…"))
        self._note_edit.setFixedHeight(72)

        # Attachments need a saved task (a uid), so this only shows when editing.
        self._attachments_button = QPushButton(self.tr("Attachments…"), self)
        self._attachments_button.setIcon(create_attachment_icon())
        self._attachments_button.clicked.connect(self._on_attachments)
        self._can_attach = attachments is not None and todo is not None and bool(todo.uid)
        self._attachments_button.setVisible(self._can_attach)
        self._update_attachments_button()

        self._status_combo = QComboBox(self)
        self._status_combo.addItem(self.tr("Open"), TodoStatus.OPEN.value)
        self._status_combo.addItem(self.tr("In progress"), TodoStatus.IN_PROCESS.value)
        self._status_combo.addItem(self.tr("Done"), TodoStatus.DONE.value)

        self._priority_combo = QComboBox(self)
        for priority in _PRIORITY_ORDER:
            self._priority_combo.addItem(priority_label(priority), priority.value)

        self._start_switch = QCheckBox(self.tr("Set start date/time"), self)
        apply_switch_style(self._start_switch)
        self._start_at_edit = DateTimeEdit(self)
        self._start_at_edit.setDateTime(QDateTime.currentDateTime())
        self._start_at_edit.setEnabled(False)

        self._due_switch = QCheckBox(self.tr("Set due date/time"), self)
        apply_switch_style(self._due_switch)
        self._due_at_edit = DateTimeEdit(self)
        self._due_at_edit.setDateTime(QDateTime.currentDateTime())
        self._due_at_edit.setEnabled(False)
        self._due_all_day_check = QCheckBox(self.tr("All day (no time)"), self)
        self._due_all_day_check.setEnabled(False)

        self._remind_combo = QComboBox(self)
        for label, minutes in (
            (self.tr("At due time"), 0),
            (self.tr("5 minutes before"), 5),
            (self.tr("15 minutes before"), 15),
            (self.tr("30 minutes before"), 30),
            (self.tr("1 hour before"), 60),
            (self.tr("1 day before"), 1440),
        ):
            self._remind_combo.addItem(label, minutes)
        self._remind_combo.setEnabled(False)

        self._recurrence_combo = QComboBox(self)
        self._recurrence_combo.addItem(self.tr("Does not repeat"), "")
        self._recurrence_combo.addItem(self.tr("Daily"), "DAILY")
        self._recurrence_combo.addItem(self.tr("Weekly"), "WEEKLY")
        self._recurrence_combo.addItem(self.tr("Monthly"), "MONTHLY")
        self._recurrence_combo.addItem(self.tr("Yearly"), "YEARLY")
        self._recurrence_interval = QSpinBox(self)
        self._recurrence_interval.setRange(1, 99)
        self._recurrence_interval.setSuffix(self.tr("×"))
        self._recurrence_interval.setEnabled(False)

        if todo is not None:
            self._title_edit.setText(todo.title)
            self._note_edit.setPlainText(todo.note)
            self._status_combo.setCurrentIndex(self._status_combo.findData(todo.status.value))
            self._priority_combo.setCurrentIndex(self._priority_combo.findData(todo.priority.value))
            if todo.start_at is not None:
                self._start_switch.setChecked(True)
                self._start_at_edit.setEnabled(True)
                self._start_at_edit.setDateTime(QDateTime(_to_local(todo.start_at)))
            if todo.due_at is not None:
                self._due_switch.setChecked(True)
                self._due_at_edit.setEnabled(True)
                self._due_at_edit.setDateTime(QDateTime(_to_local(todo.due_at)))
                self._due_all_day_check.setChecked(todo.due_all_day)
            self._remind_combo.setCurrentIndex(
                max(0, self._remind_combo.findData(todo.remind_before))
            )
            recurrence = parse_rrule(todo.recurrence)
            if recurrence is not None:
                index = self._recurrence_combo.findData(recurrence.freq)
                if index >= 0:
                    self._recurrence_combo.setCurrentIndex(index)
                    self._recurrence_interval.setValue(recurrence.interval)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        self._ok_button: QPushButton = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._ok_button.setText(self.tr("Save"))

        form = QFormLayout()
        form.addRow(self.tr("Task:"), self._title_edit)
        form.addRow(self.tr("Status:"), self._status_combo)
        form.addRow(self.tr("Priority:"), self._priority_combo)
        form.addRow(self.tr("Note:"), self._note_edit)
        form.addRow("", self._attachments_button)
        form.addRow("", self._start_switch)
        form.addRow(self.tr("Start:"), self._start_at_edit)
        form.addRow("", self._due_switch)
        form.addRow(self.tr("Due:"), self._due_at_edit)
        form.addRow("", self._due_all_day_check)
        form.addRow(self.tr("Reminder:"), self._remind_combo)
        form.addRow(self.tr("Repeat:"), self._recurrence_combo)
        form.addRow(self.tr("Every:"), self._recurrence_interval)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self._buttons)

        self._start_switch.toggled.connect(self._on_start_toggled)
        self._due_switch.toggled.connect(self._on_due_toggled)
        self._recurrence_combo.currentIndexChanged.connect(self._on_recurrence_changed)
        self._title_edit.textChanged.connect(self._update_ok_state)
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)

        self._recurrence_interval.setEnabled(self._recurrence_combo.currentData() != "")

        self._start_at_edit.setEnabled(self._start_switch.isChecked())
        self._due_at_edit.setEnabled(self._due_switch.isChecked())
        self._due_all_day_check.setEnabled(self._due_switch.isChecked())
        self._remind_combo.setEnabled(self._due_switch.isChecked())
        self._update_ok_state()

    def accept(self) -> None:
        if not self._title_edit.text().strip():
            return
        super().accept()

    @classmethod
    def create(
        cls,
        parent: QWidget | None,
        todo: Todo | None = None,
        attachments: AttachmentService | None = None,
    ) -> TodoFormData | None:
        """Run the dialog; return form data or ``None`` when cancelled."""
        dialog = cls(parent, todo, attachments)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return dialog.form_data()

    def _update_attachments_button(self) -> None:
        if not self._can_attach:
            return
        count = len(self._attachments_service.list_for(self._todo.uid))
        if count:
            self._attachments_button.setText(self.tr("Attachments ({count})…").format(count=count))
        else:
            self._attachments_button.setText(self.tr("Attachments…"))

    def _on_attachments(self) -> None:
        if self._attachments_service is None or self._todo is None:
            return
        AttachmentsDialog(self, self._todo, self._attachments_service).exec()
        self._update_attachments_button()

    def form_data(self) -> TodoFormData:
        """Collect the current widget values (used by ``create`` and tests)."""
        return TodoFormData(
            title=self._title_edit.text().strip(),
            priority=TodoPriority(self._priority_combo.currentData()),
            due_at=self._collect_due(),
            note=self._note_edit.toPlainText().strip(),
            status=TodoStatus(self._status_combo.currentData()),
            start_at=(
                self._start_at_edit.dateTime().toPython().astimezone(timezone.utc)
                if self._start_switch.isChecked()
                else None
            ),
            due_all_day=(
                self._due_all_day_check.isChecked() if self._due_switch.isChecked() else False
            ),
            remind_before=(
                int(self._remind_combo.currentData()) if self._due_switch.isChecked() else 0
            ),
            recurrence=build_rrule(
                self._recurrence_combo.currentData(),
                self._recurrence_interval.value(),
            ),
        )

    def _collect_due(self) -> datetime | None:
        if not self._due_switch.isChecked():
            return None
        due = self._due_at_edit.dateTime().toPython().astimezone(timezone.utc)
        if self._due_all_day_check.isChecked():
            # All-day means midnight UTC of the picked calendar date.
            local = self._due_at_edit.dateTime().toPython()
            due = datetime(local.year, local.month, local.day, tzinfo=timezone.utc)
        return due

    def _update_ok_state(self) -> None:
        self._ok_button.setEnabled(bool(self._title_edit.text().strip()))

    def _on_start_toggled(self, checked: bool) -> None:
        self._start_at_edit.setEnabled(checked)
        if checked:
            self._start_at_edit.set_now()

    def _on_recurrence_changed(self) -> None:
        recurring = self._recurrence_combo.currentData() != ""
        self._recurrence_interval.setEnabled(recurring)
        # A repeat needs an anchor; make the due date explicit for the user.
        if recurring and not self._due_switch.isChecked():
            self._due_switch.setChecked(True)

    def _on_due_toggled(self, checked: bool) -> None:
        self._due_at_edit.setEnabled(checked)
        self._due_all_day_check.setEnabled(checked)
        self._remind_combo.setEnabled(checked)
        if checked:
            # Turning the switch on means "due from now", not the stale date
            # that happened to sit in the field.
            self._due_at_edit.set_now()


def _to_local(value: datetime) -> datetime:
    return value.astimezone().replace(tzinfo=None)
