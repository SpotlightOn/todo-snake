"""Main window: toolbar, filterable todo table, status bar, tray behavior."""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, Signal
from PySide6.QtGui import QAction, QFont, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFileDialog,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QTableView,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from snake_todo.config import APP_DISPLAY_NAME, APP_VERSION
from snake_todo.domain.todo import Todo, TodoStatus
from snake_todo.service.todo_service import TodoService
from snake_todo.ui.icons import create_pencil_icon, create_plus_icon, create_trash_icon
from snake_todo.ui.model import TodoColumn, TodoFilterProxy, TodoTableModel
from snake_todo.ui.todo_dialog import TodoDialog


class MainWindow(QMainWindow):
    """Composes the todo UI. Business rules live in ``TodoService``; this class
    only maps user gestures to service calls and refreshes the views.
    """

    task_completed = Signal(str, str)
    visibility_changed = Signal(bool)

    def __init__(self, service: TodoService, *, tray_enabled: bool = True):
        super().__init__()
        self._service = service
        self._tray_enabled = tray_enabled
        self._really_quit = False

        self.setWindowTitle(APP_DISPLAY_NAME)
        self.resize(760, 520)

        self._table_model = TodoTableModel(self)
        self._proxy = TodoFilterProxy(self)
        self._proxy.setSourceModel(self._table_model)

        self._build_ui()
        self._build_actions()
        self._build_toolbar()
        self._build_menu_bar()
        self._connect_signals()
        self._reload()

    # -- construction --------------------------------------------------------

    def _build_ui(self) -> None:
        self._table = QTableView(self)
        self._table.setModel(self._proxy)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSortingEnabled(True)
        self._table.setShowGrid(False)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(30)

        header = self._table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(TodoColumn.TITLE, QHeaderView.ResizeMode.Stretch)

        font = QFont(self._table.font())
        font.setStrikeOut(True)
        self._table_model.set_strike_through_font(font)

        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._table)
        self.setCentralWidget(central)

        self._status_label = QLabel("", self)
        self.statusBar().addPermanentWidget(self._status_label)

    def _build_actions(self) -> None:
        self._action_new = QAction(create_plus_icon(), "New Task", self)
        self._action_new.setShortcut(QKeySequence.StandardKey.New)
        self._action_new.setStatusTip("Create a new task")

        self._action_edit = QAction(create_pencil_icon(), "Edit", self)
        self._action_edit.setShortcut(QKeySequence("F2"))
        self._action_edit.setStatusTip("Edit the selected task")

        self._action_delete = QAction(create_trash_icon(), "Delete", self)
        self._action_delete.setShortcut(QKeySequence.StandardKey.Delete)
        self._action_delete.setStatusTip("Delete the selected task")

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Main actions", self)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        toolbar.addAction(self._action_new)
        toolbar.addAction(self._action_edit)
        toolbar.addAction(self._action_delete)
        toolbar.addSeparator()

        self._filter_combo = QComboBox(toolbar)
        self._filter_combo.addItem("All", None)
        self._filter_combo.addItem("Open", TodoStatus.OPEN.value)
        self._filter_combo.addItem("Done", TodoStatus.DONE.value)
        toolbar.addWidget(self._filter_combo)

        self._search_edit = QLineEdit(toolbar)
        self._search_edit.setPlaceholderText("Search…")
        self._search_edit.setClearButtonEnabled(True)
        self._search_edit.setFixedWidth(180)
        toolbar.addWidget(self._search_edit)

    def _build_menu_bar(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        file_menu.addAction(self._action_new)
        file_menu.addSeparator()
        self._action_import = QAction("Import…", self)
        self._action_import.triggered.connect(self._on_import)
        file_menu.addAction(self._action_import)
        self._action_export = QAction("Export…", self)
        self._action_export.triggered.connect(self._on_export)
        file_menu.addAction(self._action_export)
        file_menu.addSeparator()
        quit_action = QAction("Quit", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.quit_app)
        file_menu.addAction(quit_action)

        help_menu = self.menuBar().addMenu("&Help")
        about_action = QAction(f"About {APP_DISPLAY_NAME}", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _connect_signals(self) -> None:
        self._action_new.triggered.connect(self._on_new)
        self._action_edit.triggered.connect(self._on_edit)
        self._action_delete.triggered.connect(self._on_delete)

        self._filter_combo.currentIndexChanged.connect(self._on_filter_changed)
        self._search_edit.textChanged.connect(self._proxy.set_search_text)

        self._table.doubleClicked.connect(self._on_double_clicked)
        self._table_model.done_toggled.connect(self._on_done_toggled)
        self._table.selectionModel().selectionChanged.connect(self._update_actions)

    # -- public API used by the tray -----------------------------------------

    def show_window(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def new_task_from_tray(self) -> None:
        self.show_window()
        self._on_new()

    def quit_app(self) -> None:
        self._really_quit = True
        QApplication.instance().quit()

    # -- event handlers --------------------------------------------------------

    def closeEvent(self, event) -> None:
        if self._really_quit or not self._tray_enabled:
            event.accept()
            if not self._really_quit:
                QApplication.instance().quit()
            return
        event.ignore()
        self.hide()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.visibility_changed.emit(True)

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self.visibility_changed.emit(False)

    def _on_new(self) -> None:
        values = TodoDialog.create(self)
        if values is None:
            return
        self._service.add_todo(values.title, values.priority, values.due_date)
        self._reload()

    def _on_edit(self) -> None:
        todo = self._selected_todo()
        if todo is None:
            return
        values = TodoDialog.create(self, todo)
        if values is None:
            return
        self._service.update_todo(
            todo.id,
            title=values.title,
            priority=values.priority,
            due_date=values.due_date,
        )
        self._reload()

    def _on_delete(self) -> None:
        todos = self._selected_todos()
        if not todos:
            return
        if len(todos) == 1:
            text = f"Really delete „{todos[0].title}“?"
        else:
            text = f"Really delete the {len(todos)} selected tasks?"
        answer = QMessageBox.question(self, "Delete tasks", text)
        if answer == QMessageBox.StandardButton.Yes:
            for todo in todos:
                self._service.delete_todo(todo.id)
            self._reload()
            self._status_label.setText(f"Deleted {len(todos)} tasks")

    def _on_export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export tasks",
            "todos.json",
            "JSON files (*.json)",
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self._service.export_json())
        except OSError as exc:
            QMessageBox.critical(self, "Export failed", str(exc))
            return
        self._status_label.setText(f"Exported ({path})")

    def _on_import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import tasks",
            "",
            "JSON files (*.json)",
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = f.read()
            count = self._service.import_json(payload)
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "Import failed", str(exc))
            return
        self._reload()
        self._status_label.setText(f"Imported {count} tasks")

    def _on_done_toggled(self, todo_id: int, checked: bool) -> None:
        todo = self._service.toggle_done(todo_id)
        self._reload()
        if checked:
            self.task_completed.emit("Task completed", todo.title)
            todos = self._service.list_todos()
            if todos and all(other.is_done for other in todos):
                self.task_completed.emit("All done!", "All tasks are completed.")

    def _on_filter_changed(self, index: int) -> None:
        value = self._filter_combo.itemData(index)
        status = TodoStatus(value) if value is not None else None
        self._proxy.set_status_filter(status)

    def _on_double_clicked(self, index: QModelIndex) -> None:
        if not index.isValid():
            return
        self._on_edit()

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            f"About {APP_DISPLAY_NAME}",
            (
                f"<h3>{APP_DISPLAY_NAME} {APP_VERSION}</h3>"
                "<p>A small, tidy task manager "
                "with system tray support.</p>"
            ),
        )

    # -- view refresh ----------------------------------------------------------

    def _reload(self) -> None:
        selected_id = self._selected_id()
        todos = self._service.list_todos()
        self._table_model.set_todos(todos)
        self._update_status_bar(todos)
        if selected_id is not None:
            self._select_todo_by_id(selected_id)
        self._update_actions()

    def _update_status_bar(self, todos: list[Todo]) -> None:
        if not todos:
            self._status_label.setText("No tasks")
            return
        open_count = sum(1 for todo in todos if not todo.is_done)
        done_count = len(todos) - open_count
        self._status_label.setText(f"{open_count} open · {done_count} done")

    def _update_actions(self) -> None:
        has_selection = self._selected_todo() is not None
        self._action_edit.setEnabled(has_selection)
        self._action_delete.setEnabled(has_selection)

    def _selected_id(self) -> int | None:
        todo = self._selected_todo()
        return todo.id if todo is not None else None

    def _selected_todo(self) -> Todo | None:
        indexes = self._selected_proxy_rows()
        if not indexes:
            return None
        source_index = self._proxy.mapToSource(indexes[0])
        if not source_index.isValid():
            return None
        return self._table_model.todo_at(source_index.row())

    def _selected_todos(self) -> list[Todo]:
        todos: list[Todo] = []
        for index in self._selected_proxy_rows():
            source_index = self._proxy.mapToSource(index)
            if not source_index.isValid():
                continue
            todo = self._table_model.todo_at(source_index.row())
            if todo is not None and all(t.id != todo.id for t in todos):
                todos.append(todo)
        return todos

    def _selected_proxy_rows(self) -> list[QModelIndex]:
        indexes = self._table.selectionModel().selectedIndexes()
        rows: list[QModelIndex] = []
        for index in indexes:
            if index.column() != 0 or any(i.row() == index.row() for i in rows):
                continue
            rows.append(index)
        return rows

    def _select_todo_by_id(self, todo_id: int) -> None:
        row = self._table_model.row_of_todo(todo_id)
        if row < 0:
            return
        proxy_index = self._proxy.mapFromSource(self._table_model.index(row, 0))
        if not proxy_index.isValid():
            return
        self._table.selectRow(proxy_index.row())
        self._table.scrollTo(proxy_index)