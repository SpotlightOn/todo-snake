"""Main window: toolbar, filterable todo table, status bar, tray behavior."""

from __future__ import annotations

import math
from datetime import timedelta

from PySide6.QtCore import QModelIndex, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QFont, QIcon, QKeySequence, QPainter, QPixmap
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
    QSizePolicy,
    QTableView,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from todo_snake.config import APP_DISPLAY_NAME, APP_VERSION
from todo_snake.domain.todo import Todo, TodoStatus, utc_now
from todo_snake.reminders import (
    ReminderStore,
    active_keys,
    next_reminder_moment,
    pending_reminders,
    reminder_key,
)
from todo_snake.service.todo_service import TodoService
from todo_snake.sync.accounts import AccountStore
from todo_snake.sync.behavior import SyncBehavior
from todo_snake.ui.attachments_dialog import AttachmentsDialog
from todo_snake.ui.icons import (
    create_attachment_icon,
    create_pencil_icon,
    create_plus_icon,
    create_sync_active_icon,
    create_sync_error_icon,
    create_sync_icon,
    create_trash_icon,
)
from todo_snake.ui.model import TodoColumn, TodoFilterProxy, TodoTableModel
from todo_snake.ui.reminder_dialog import ReminderDialog
from todo_snake.ui.settings_dialog import SettingsDialog
from todo_snake.ui.switch import SwitchDelegate
from todo_snake.ui.todo_dialog import TodoDialog


class MainWindow(QMainWindow):
    """Composes the todo UI. Business rules live in ``TodoService``; this class
    only maps user gestures to service calls and refreshes the views.
    """

    task_completed = Signal(str, str)
    reminders_active = Signal(bool)
    visibility_changed = Signal(bool)

    def __init__(
        self,
        service: TodoService,
        *,
        tray_enabled: bool = True,
        sync_manager=None,
        account_store: AccountStore | None = None,
        reminder_store: ReminderStore | None = None,
        attachment_service=None,
    ):
        super().__init__()
        self._service = service
        self._tray_enabled = tray_enabled
        self._really_quit = False
        self._sync_manager = sync_manager
        self._account_store = account_store if account_store is not None else AccountStore()
        self._reminders = reminder_store if reminder_store is not None else ReminderStore()
        self._attachments = attachment_service

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
        self._connect_sync()
        self._connect_reminders()
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
        self._table.setItemDelegateForColumn(TodoColumn.DONE, SwitchDelegate(self._table))
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(30)

        header = self._table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(TodoColumn.TITLE, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(TodoColumn.DONE, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(TodoColumn.DONE, 58)
        header.setSectionResizeMode(TodoColumn.FILES, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(TodoColumn.FILES, 64)

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
        self._action_new = QAction(create_plus_icon(), self.tr("New Task"), self)
        self._action_new.setShortcut(QKeySequence.StandardKey.New)
        self._action_new.setStatusTip(self.tr("Create a new task"))

        self._action_edit = QAction(create_pencil_icon(), self.tr("Edit"), self)
        self._action_edit.setShortcut(QKeySequence("F2"))
        self._action_edit.setStatusTip(self.tr("Edit the selected task"))

        self._action_delete = QAction(create_trash_icon(), self.tr("Delete"), self)
        self._action_delete.setShortcut(QKeySequence.StandardKey.Delete)
        self._action_delete.setStatusTip(self.tr("Delete the selected task"))

        self._action_attachments = QAction(create_attachment_icon(), self.tr("Attachments…"), self)
        self._action_attachments.setStatusTip(
            self.tr("Manage the files attached to the selected task")
        )

        self._sync_icon = create_sync_icon()
        self._sync_icon_active = create_sync_active_icon()
        self._sync_icon_error = create_sync_error_icon()
        self._sync_errors: list[str] = []
        self._sync_frames = self._build_sync_frames()
        self._sync_frame = 0
        self._sync_anim_timer = QTimer(self)
        self._sync_anim_timer.setInterval(80)
        self._sync_anim_timer.timeout.connect(self._advance_sync_frame)

        self._action_sync = QAction(self._sync_icon, self.tr("Sync now"), self)
        self._action_sync.setStatusTip(self.tr("Synchronize all enabled accounts now"))
        self._action_sync.triggered.connect(self._on_sync)

    def _build_toolbar(self) -> None:
        toolbar = QToolBar(self.tr("Main actions"), self)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        self._toolbar = toolbar

        toolbar.addAction(self._action_new)
        toolbar.addAction(self._action_edit)
        toolbar.addAction(self._action_attachments)
        toolbar.addAction(self._action_delete)
        toolbar.addSeparator()

        self._filter_combo = QComboBox(toolbar)
        self._filter_combo.addItem(self.tr("All"), None)
        self._filter_combo.addItem(self.tr("Open"), TodoStatus.OPEN.value)
        self._filter_combo.addItem(self.tr("In progress"), TodoStatus.IN_PROCESS.value)
        self._filter_combo.addItem(self.tr("Done"), TodoStatus.DONE.value)
        toolbar.addWidget(self._filter_combo)

        self._search_edit = QLineEdit(toolbar)
        self._search_edit.setPlaceholderText(self.tr("Search…"))
        self._search_edit.setClearButtonEnabled(True)
        self._search_edit.setFixedWidth(180)
        toolbar.addWidget(self._search_edit)

        # Push "Sync now" to the far right.
        spacer = QWidget(toolbar)
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)
        toolbar.addAction(self._action_sync)

    def _build_menu_bar(self) -> None:
        file_menu = self.menuBar().addMenu(self.tr("&File"))
        file_menu.addAction(self._action_new)
        file_menu.addAction(self._action_attachments)
        file_menu.addSeparator()
        self._action_import = QAction(self.tr("Import…"), self)
        self._action_import.triggered.connect(self._on_import)
        file_menu.addAction(self._action_import)
        self._action_export = QAction(self.tr("Export…"), self)
        self._action_export.triggered.connect(self._on_export)
        file_menu.addAction(self._action_export)
        self._action_settings = QAction(self.tr("Settings…"), self)
        self._action_settings.triggered.connect(self._on_settings)
        file_menu.addSeparator()
        file_menu.addAction(self._action_settings)
        file_menu.addSeparator()
        quit_action = QAction(self.tr("Quit"), self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.quit_app)
        file_menu.addAction(quit_action)

        help_menu = self.menuBar().addMenu(self.tr("&Help"))
        about_action = QAction(self.tr("About {name}").format(name=APP_DISPLAY_NAME), self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _connect_signals(self) -> None:
        self._action_new.triggered.connect(self._on_new)
        self._action_edit.triggered.connect(self._on_edit)
        self._action_delete.triggered.connect(self._on_delete)
        self._action_attachments.triggered.connect(self._on_attachments)

        self._filter_combo.currentIndexChanged.connect(self._on_filter_changed)
        self._search_edit.textChanged.connect(self._proxy.set_search_text)

        self._table.doubleClicked.connect(self._on_double_clicked)
        self._table_model.done_toggled.connect(self._on_done_toggled)
        self._table.selectionModel().selectionChanged.connect(self._update_actions)

    def _connect_sync(self) -> None:
        if self._sync_manager is None:
            return
        self._sync_manager.sync_finished.connect(self._on_sync_finished)
        self._sync_manager.sync_failed.connect(self._on_sync_failed)

        self._periodic_sync_timer = QTimer(self)
        self._periodic_sync_timer.timeout.connect(self.sync_all)
        behavior = SyncBehavior.load()
        if behavior.sync_on_startup:
            QTimer.singleShot(2000, self.sync_all)
        self._apply_sync_behavior(behavior)

    def _apply_sync_behavior(self, behavior: SyncBehavior | None = None) -> None:
        """(Re)configure periodic sync from the current settings."""
        if self._sync_manager is None:
            return
        behavior = behavior if behavior is not None else SyncBehavior.load()
        if behavior.periodic_enabled and behavior.periodic_minutes > 0:
            self._periodic_sync_timer.setInterval(behavior.periodic_minutes * 60_000)
            self._periodic_sync_timer.start()
        else:
            self._periodic_sync_timer.stop()

    def _connect_reminders(self) -> None:
        self._reminder_dialogs: dict[str, ReminderDialog] = {}
        # Fires exactly when the next task becomes due.
        self._next_reminder_timer = QTimer(self)
        self._next_reminder_timer.setSingleShot(True)
        self._next_reminder_timer.timeout.connect(self.check_reminders)
        # Safety net for clock jumps and newly created tasks.
        self._reminder_timer = QTimer(self)
        self._reminder_timer.setInterval(30_000)
        self._reminder_timer.timeout.connect(self.check_reminders)
        self._reminder_timer.start()

    # -- public API used by the tray -----------------------------------------

    def show_window(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def check_reminders(self) -> None:
        """Show a persistent reminder for every open task that is now due.

        Runs on a timer, exactly when the next task becomes due, and once on
        startup (wired in ``app.py``) so tasks that came due while the app was
        closed are still announced. Each task/due time is announced once; a
        snooze re-announces it later.
        """
        now = utc_now()
        todos = self._service.list_todos()
        announced, snoozed = self._reminders.load()
        for todo in pending_reminders(todos, now, announced, snoozed):
            key = reminder_key(todo)
            if key is None:
                continue
            announced.add(key)
            snoozed.pop(key, None)
            self._show_reminder(todo, key)
        # Keep only keys that still refer to an open task with this due time, so
        # rescheduling (or reopening) a task can announce again later.
        active = active_keys(todos)
        self._reminders.save(
            announced & active,
            {key: when for key, when in snoozed.items() if key in active},
        )
        self._schedule_next_reminder()

    def _schedule_next_reminder(self) -> None:
        """Arm a single-shot timer for the exact moment the next task is due."""
        now = utc_now()
        todos = self._service.list_todos()
        announced, snoozed = self._reminders.load()
        moment = next_reminder_moment(todos, now, announced, snoozed)
        if moment is None:
            self._next_reminder_timer.stop()
            return
        # Round up plus a small buffer so the timer never fires a fraction of a
        # second *before* the due moment — that would find nothing due and wait
        # for the next tick (visible as a late reminder).
        delay_ms = math.ceil((moment - now).total_seconds() * 1000) + 100
        self._next_reminder_timer.start(max(100, min(delay_ms, 3_600_000)))

    def _show_reminder(self, todo: Todo, key: str) -> None:
        if key in self._reminder_dialogs:
            return
        due_text = self.tr("Due: {time}").format(
            time=todo.due_at.astimezone().strftime("%Y-%m-%d %H:%M")
        )
        dialog = ReminderDialog(todo.title, due_text)
        dialog.snoozed.connect(lambda minutes, k=key: self._snooze_reminder(k, minutes))
        dialog.dismissed.connect(lambda k=key: self._dismiss_reminder(k))
        self._reminder_dialogs[key] = dialog
        dialog.show()
        self.reminders_active.emit(True)

    def _snooze_reminder(self, key: str, minutes: int) -> None:
        self._reminder_dialogs.pop(key, None)
        announced, snoozed = self._reminders.load()
        announced.discard(key)
        snoozed[key] = utc_now() + timedelta(minutes=minutes)
        self._reminders.save(announced, snoozed)
        self.reminders_active.emit(bool(self._reminder_dialogs))
        self._schedule_next_reminder()

    def _dismiss_reminder(self, key: str) -> None:
        self._reminder_dialogs.pop(key, None)
        self.reminders_active.emit(bool(self._reminder_dialogs))

    def new_task_from_tray(self) -> None:
        self.show_window()
        self._on_new()

    def quit_app(self) -> None:
        self._really_quit = True
        QApplication.instance().quit()

    def sync_all(self) -> None:
        """Synchronize every enabled account."""
        if self._sync_manager is None:
            return
        for account in self._account_store.list_accounts():
            if account.enabled:
                self._sync_manager.trigger_sync(account)
        self._reload()

    def _build_sync_frames(self, count: int = 12, extent: int = 64) -> list[QIcon]:
        """Pre-render rotation frames at a fixed pixel size; ``QIcon`` then
        scales/DPR-handles them correctly for the toolbar button."""
        frames: list[QIcon] = []
        for index in range(count):
            pixmap = QPixmap(extent, extent)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.translate(extent / 2, extent / 2)
            painter.rotate(360 * index / count)
            painter.translate(-extent / 2, -extent / 2)
            self._sync_icon_active.paint(painter, QRect(0, 0, extent, extent))
            painter.end()
            frames.append(QIcon(pixmap))
        return frames

    def _on_sync(self) -> None:
        """Toolbar button: show activity (green, spinning), then synchronize."""
        if self._sync_manager is None:
            return
        self._sync_errors = []
        self._sync_frame = 0
        self._action_sync.setIcon(self._sync_frames[0])
        self._sync_anim_timer.start()
        # Let the icon repaint before the (synchronous) sync blocks the loop.
        QTimer.singleShot(0, self._run_sync)

    def _run_sync(self) -> None:
        try:
            self.sync_all()
        finally:
            self._sync_anim_timer.stop()
        if self._sync_errors:
            self._action_sync.setIcon(self._sync_icon_error)
            self._status_label.setText(
                self.tr("Sync failed: {message}").format(message=self._sync_errors[0])
            )
            QMessageBox.warning(self, self.tr("Sync failed"), "\n".join(self._sync_errors))
        else:
            self._action_sync.setIcon(self._sync_icon)

    def _advance_sync_frame(self) -> None:
        self._sync_frame = (self._sync_frame + 1) % len(self._sync_frames)
        self._action_sync.setIcon(self._sync_frames[self._sync_frame])

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
        self._service.add_todo(
            values.title,
            values.priority,
            values.due_at,
            note=values.note,
            start_at=values.start_at,
            due_all_day=values.due_all_day,
            remind_before=values.remind_before,
            status=values.status,
            recurrence=values.recurrence,
        )
        self._reload()

    def _on_edit(self) -> None:
        todo = self._selected_todo()
        if todo is None:
            return
        values = TodoDialog.create(self, todo, attachments=self._attachments)
        if values is None:
            return
        self._service.update_todo(
            todo.id,
            title=values.title,
            priority=values.priority,
            due_at=values.due_at,
            note=values.note,
            start_at=values.start_at,
            due_all_day=values.due_all_day,
            remind_before=values.remind_before,
            status=values.status,
            recurrence=values.recurrence,
        )
        self._reload()

    def _on_attachments(self) -> None:
        todo = self._selected_todo()
        if todo is None or self._attachments is None:
            return
        AttachmentsDialog(self, todo, self._attachments).exec()
        self._reload()

    def _on_delete(self) -> None:
        todos = self._selected_todos()
        if not todos:
            return
        if len(todos) == 1:
            text = self.tr("Really delete „{title}“?").format(title=todos[0].title)
        else:
            text = self.tr("Really delete the {count} selected tasks?").format(count=len(todos))
        answer = QMessageBox.question(self, self.tr("Delete tasks"), text)
        if answer == QMessageBox.StandardButton.Yes:
            for todo in todos:
                self._service.delete_todo(todo.id)
                if self._sync_manager is not None and todo.uid is not None:
                    self._sync_manager.local_deleted(todo.uid)
            self._reload()
            self._status_label.setText(self.tr("Deleted {count} tasks").format(count=len(todos)))

    def _on_export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            self.tr("Export tasks"),
            "todos.json",
            self.tr("JSON files (*.json)"),
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self._service.export_json())
        except OSError as exc:
            QMessageBox.critical(self, self.tr("Export failed"), str(exc))
            return
        self._status_label.setText(self.tr("Exported ({path})").format(path=path))

    def _on_import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            self.tr("Import tasks"),
            "",
            self.tr("JSON files (*.json)"),
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = f.read()
            count = self._service.import_json(payload)
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, self.tr("Import failed"), str(exc))
            return
        self._reload()
        self._status_label.setText(self.tr("Imported {count} tasks").format(count=count))

    def _on_done_toggled(self, todo_id: int, checked: bool) -> None:
        todo = self._service.toggle_done(todo_id)
        self._reload()
        if checked:
            self.task_completed.emit(self.tr("Task completed"), todo.title)
            todos = self._service.list_todos()
            if todos and all(other.is_done for other in todos):
                self.task_completed.emit(self.tr("All done!"), self.tr("All tasks are completed."))

    def _on_filter_changed(self, index: int) -> None:
        value = self._filter_combo.itemData(index)
        status = TodoStatus(value) if value is not None else None
        self._proxy.set_status_filter(status)

    def _on_double_clicked(self, index: QModelIndex) -> None:
        if not index.isValid():
            return
        self._on_edit()

    # -- settings / sync -----------------------------------------------------

    def _on_settings(self) -> None:
        dialog = SettingsDialog(self, self._account_store, self._sync_manager, self._attachments)
        dialog.reload_requested.connect(self._reload)
        dialog.exec()
        self._apply_sync_behavior()
        self._reload()

    def _on_sync_finished(self, uid: str, stats: dict) -> None:
        self._status_label.setText(
            self.tr(
                "Synced: {created} created, {updated} updated, {deleted} deleted, {pushed} pushed"
            ).format(**stats)
        )

    def _on_sync_failed(self, uid: str, message: str) -> None:
        account = self._account_store.get(uid)
        name = account.display_name if account is not None else uid
        text = f"{name}: {message}"
        self._sync_errors.append(text)
        # Mark the failure immediately (also for periodic/auto sync), and keep
        # the message visible in the status bar.
        self._action_sync.setIcon(self._sync_icon_error)
        self._status_label.setText(self.tr("Sync failed: {message}").format(message=text))

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            self.tr("About {name}").format(name=APP_DISPLAY_NAME),
            (
                f"<h3>{APP_DISPLAY_NAME} {APP_VERSION}</h3>"
                + self.tr("<p>A small, tidy task manager with system tray support.</p>")
            ),
        )

    # -- view refresh ----------------------------------------------------------

    def _reload(self) -> None:
        selected_id = self._selected_id()
        todos = self._service.list_todos()
        attachment_names = (
            self._attachments.names_by_todo() if self._attachments is not None else {}
        )
        self._table_model.set_todos(todos, attachment_names)
        self._update_status_bar(todos)
        if selected_id is not None:
            self._select_todo_by_id(selected_id)
        self._update_actions()
        # A task added/edited with a due time close to now must arm the precise
        # reminder timer immediately, not on the next 60s safety tick.
        self._schedule_next_reminder()

    def _update_status_bar(self, todos: list[Todo]) -> None:
        if not todos:
            self._status_label.setText(self.tr("No tasks"))
            return
        open_count = sum(1 for todo in todos if not todo.is_done)
        done_count = len(todos) - open_count
        self._status_label.setText(
            self.tr("{open_count} open · {done_count} done").format(
                open_count=open_count, done_count=done_count
            )
        )

    def _update_actions(self) -> None:
        has_selection = self._selected_todo() is not None
        self._action_edit.setEnabled(has_selection)
        self._action_delete.setEnabled(has_selection)
        self._action_attachments.setEnabled(has_selection and self._attachments is not None)
        # "Sync now" is only meaningful with at least one enabled account.
        self._action_sync.setEnabled(
            self._sync_manager is not None
            and any(account.enabled for account in self._account_store.list_accounts())
        )

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
