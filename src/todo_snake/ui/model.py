"""Qt Model/View classes: the todo table model and a filtering proxy."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import IntEnum

from PySide6.QtCore import (
    QAbstractTableModel,
    QCoreApplication,
    QModelIndex,
    QSortFilterProxyModel,
    Qt,
    Signal,
)
from PySide6.QtGui import QBrush, QColor, QFont

from todo_snake.domain.todo import Todo, TodoPriority, TodoStatus
from todo_snake.recurrence import parse_rrule
from todo_snake.ui.icons import create_attachment_icon, recurrence_icon


# Single translation context ("TodoTableModel") for the priority labels so the
# keyword table, the filter search and the dialogs all agree on one wording.
def priority_label(priority: TodoPriority) -> str:
    """Localized display label for ``priority``."""
    if priority is TodoPriority.LOW:
        return QCoreApplication.translate("TodoTableModel", "Low")
    if priority is TodoPriority.MEDIUM:
        return QCoreApplication.translate("TodoTableModel", "Medium")
    return QCoreApplication.translate("TodoTableModel", "High")


def recurrence_label(rrule: str | None) -> str | None:
    """Human-readable summary of an RRULE (e.g. "Weekly"), or ``None``."""
    recurrence = parse_rrule(rrule)
    if recurrence is None:
        return None
    label = {
        "DAILY": QCoreApplication.translate("TodoTableModel", "Daily"),
        "WEEKLY": QCoreApplication.translate("TodoTableModel", "Weekly"),
        "MONTHLY": QCoreApplication.translate("TodoTableModel", "Monthly"),
        "YEARLY": QCoreApplication.translate("TodoTableModel", "Yearly"),
    }[recurrence.freq]
    if recurrence.interval > 1:
        label = QCoreApplication.translate("TodoTableModel", "{label} (every {n})").format(
            label=label, n=recurrence.interval
        )
    return label


_PRIORITY_COLORS: dict[TodoPriority, QColor] = {
    TodoPriority.LOW: QColor("#7a7a7a"),
    TodoPriority.MEDIUM: QColor("#c98a00"),
    TodoPriority.HIGH: QColor("#c62828"),
}

_GRAYED_OUT = QColor("#8a8a8a")
_IN_PROCESS = QColor("#1565c0")
_OVERDUE = QColor("#c62828")
_EMPTY_INDEX = QModelIndex()


class TodoColumn(IntEnum):
    DONE = 0
    TITLE = 1
    PRIORITY = 2
    DUE_DATE = 3
    FILES = 4

    @classmethod
    def count(cls) -> int:
        return len(cls.__members__)


class TodoTableModel(QAbstractTableModel):
    """Holds the list of todos. Emits ``done_toggled`` when the user flips the
    checkbox column; the window orchestrates the actual state change via the
    service.
    """

    done_toggled = Signal(int, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._todos: list[Todo] = []
        #: ``{todo uid: (filename, …)}`` for the attachments column.
        self._attachments: dict[str, tuple[str, ...]] = {}
        self._strike_through_font: QFont | None = None

    def set_strike_through_font(self, font: QFont) -> None:
        self._strike_through_font = font

    def set_todos(
        self,
        todos: list[Todo],
        attachments: dict[str, tuple[str, ...]] | None = None,
    ) -> None:
        self.beginResetModel()
        self._todos = list(todos)
        self._attachments = dict(attachments or {})
        self.endResetModel()

    def attachment_names(self, todo: Todo) -> tuple[str, ...]:
        """File names attached to ``todo`` (empty when it has none)."""
        return self._attachments.get(todo.uid, ()) if todo.uid else ()

    def todo_at(self, row: int) -> Todo:
        return self._todos[row]

    def row_of_todo(self, todo_id: int) -> int:
        for index, todo in enumerate(self._todos):
            if todo.id == todo_id:
                return index
        return -1

    # -- QAbstractItemModel interface -----------------------------------

    def rowCount(self, parent=_EMPTY_INDEX) -> int:
        return 0 if parent.isValid() else len(self._todos)

    def columnCount(self, parent=_EMPTY_INDEX) -> int:
        return 0 if parent.isValid() else TodoColumn.count()

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return {
                TodoColumn.DONE: "",
                TodoColumn.TITLE: self.tr("Task"),
                TodoColumn.PRIORITY: self.tr("Priority"),
                TodoColumn.DUE_DATE: self.tr("Due"),
                TodoColumn.FILES: self.tr("Files"),
            }.get(TodoColumn(section), "")
        return None

    def flags(self, index: QModelIndex):
        flags = super().flags(index)
        if TodoColumn(index.column()) is TodoColumn.DONE:
            flags |= Qt.ItemFlag.ItemIsUserCheckable
        return flags

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        todo = self._todos[index.row()]
        column = TodoColumn(index.column())

        if column is TodoColumn.FILES:
            return self._files_data(todo, role)

        if role == Qt.ItemDataRole.CheckStateRole and column is TodoColumn.DONE:
            return Qt.CheckState.Checked if todo.is_done else Qt.CheckState.Unchecked

        if (
            role == Qt.ItemDataRole.DecorationRole
            and column is TodoColumn.TITLE
            and todo.recurrence
        ):
            return recurrence_icon()

        if role == Qt.ItemDataRole.DisplayRole:
            if column is TodoColumn.TITLE:
                return todo.title
            if column is TodoColumn.PRIORITY:
                return priority_label(todo.priority)
            if column is TodoColumn.DUE_DATE:
                return todo.due_at.astimezone().strftime("%Y-%m-%d %H:%M") if todo.due_at else "—"

        if role == Qt.ItemDataRole.TextAlignmentRole:
            if column is TodoColumn.DONE:
                return Qt.AlignmentFlag.AlignCenter
            return Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft

        if role == Qt.ItemDataRole.ForegroundRole:
            if column is TodoColumn.TITLE and todo.is_done:
                return QBrush(_GRAYED_OUT)
            if column is TodoColumn.TITLE and todo.is_in_process:
                return QBrush(_IN_PROCESS)
            if column is TodoColumn.PRIORITY:
                return QBrush(_PRIORITY_COLORS[todo.priority])
            if column is TodoColumn.DUE_DATE and self._is_overdue(todo):
                return QBrush(_OVERDUE)

        if (
            role == Qt.ItemDataRole.FontRole
            and column is TodoColumn.TITLE
            and todo.is_done
            and self._strike_through_font is not None
        ):
            return self._strike_through_font

        if role == Qt.ItemDataRole.ToolTipRole:
            return self._tooltip(todo)

        return None

    def setData(self, index: QModelIndex, value, role=Qt.ItemDataRole.EditRole) -> bool:
        if role == Qt.ItemDataRole.CheckStateRole and TodoColumn(index.column()) is TodoColumn.DONE:
            self.done_toggled.emit(self._todos[index.row()].id, value == Qt.CheckState.Checked)
            return True
        return False

    # -- helpers ---------------------------------------------------------

    def _files_data(self, todo: Todo, role):
        """The attachments column: a paperclip, the count and the file names."""
        names = self.attachment_names(todo)
        if role == Qt.ItemDataRole.DecorationRole:
            return create_attachment_icon() if names else None
        if role == Qt.ItemDataRole.DisplayRole:
            return str(len(names)) if names else ""
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return Qt.AlignmentFlag.AlignCenter
        if role == Qt.ItemDataRole.ForegroundRole and todo.is_done:
            return QBrush(_GRAYED_OUT)
        if role == Qt.ItemDataRole.ToolTipRole:
            if names:
                return self.tr("Attachments:") + "\n" + "\n".join(f"• {name}" for name in names)
            return self._tooltip(todo)
        return None

    @staticmethod
    def _is_overdue(todo: Todo) -> bool:
        return (
            not todo.is_done
            and todo.due_at is not None
            and todo.due_at < datetime.now(timezone.utc)
        )

    def _tooltip(self, todo: Todo) -> str:
        created = todo.created_at.strftime("%Y-%m-%d %H:%M")
        lines = [self.tr("Created: {time}").format(time=created)]
        if todo.is_in_process:
            lines.append(self.tr("In progress"))
        label = recurrence_label(todo.recurrence)
        if label is not None:
            lines.append(self.tr("Repeats: {label}").format(label=label))
        if todo.completed_at is not None:
            completed = todo.completed_at.strftime("%Y-%m-%d %H:%M")
            lines.append(self.tr("Completed: {time}").format(time=completed))
        if todo.due_at is not None and self._is_overdue(todo):
            lines.append(self.tr("Overdue!"))
        return "\n".join(lines)


class TodoFilterProxy(QSortFilterProxyModel):
    """Filters by status and searches the title/priority text.

    Sorting semantics (ascending): done floats to the bottom of the ``DONE``
    column, priority sorts high-first, due dates soonest-first with unset
    dates last, titles alphabetically.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._status: TodoStatus | None = None
        self._search: str = ""
        self.setDynamicSortFilter(True)

    def set_status_filter(self, status: TodoStatus | None) -> None:
        self.beginFilterChange()
        self._status = status
        self.endFilterChange(QSortFilterProxyModel.Direction.Rows)

    def set_search_text(self, text: str) -> None:
        self.beginFilterChange()
        self._search = text.strip().casefold()
        self.endFilterChange(QSortFilterProxyModel.Direction.Rows)

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        source_model: TodoTableModel = self.sourceModel()
        todo = source_model.todo_at(source_row)
        if self._status is not None and todo.status is not self._status:
            return False
        if self._search:
            haystack = f"{todo.title} {priority_label(todo.priority)}".casefold()
            if self._search not in haystack:
                return False
        return True

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:
        left_todo = self._source_todo(left)
        right_todo = self._source_todo(right)
        column = TodoColumn(left.column())

        if column is TodoColumn.TITLE:
            return left_todo.title.casefold() < right_todo.title.casefold()
        if column is TodoColumn.DONE:
            # Ascending: open tasks first, done tasks float to the bottom.
            return left_todo.is_done < right_todo.is_done
        if column is TodoColumn.PRIORITY:
            return self._priority_rank(left_todo) < self._priority_rank(right_todo)
        if column is TodoColumn.DUE_DATE:
            return self._due_rank(left_todo) < self._due_rank(right_todo)
        if column is TodoColumn.FILES:
            return self._files_rank(left_todo) < self._files_rank(right_todo)
        return super().lessThan(left, right)

    def _source_todo(self, index: QModelIndex) -> Todo:
        # ``lessThan`` receives source-model indexes, not proxy indexes.
        source_model: TodoTableModel = self.sourceModel()
        return source_model.todo_at(index.row())

    @staticmethod
    def _priority_rank(todo: Todo) -> int:
        # Lower rank sorts first on ascending; high priority on top.
        return {TodoPriority.HIGH: 0, TodoPriority.MEDIUM: 1, TodoPriority.LOW: 2}[todo.priority]

    @staticmethod
    def _due_rank(todo: Todo) -> datetime:
        # Missing due dates sort after every real date.
        return todo.due_at or datetime.max.replace(tzinfo=timezone.utc)

    def _files_rank(self, todo: Todo) -> tuple[int, int]:
        # Ascending: tasks with attachments first, more attachments on top.
        source_model: TodoTableModel = self.sourceModel()
        count = len(source_model.attachment_names(todo))
        return (1, 0) if count == 0 else (0, -count)
