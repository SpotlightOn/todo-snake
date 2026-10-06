"""UI smoke tests — run fully offscreen."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QCheckBox

from todo_snake.domain import TodoPriority, TodoStatus
from todo_snake.domain.todo import Todo
from todo_snake.persistence.sqlite import SqliteTodoRepository
from todo_snake.service import TodoService
from todo_snake.ui.main_window import MainWindow
from todo_snake.ui.switch import apply_switch_style
from todo_snake.ui.todo_dialog import TodoDialog
from todo_snake.ui.tray import TrayIcon


@pytest.fixture()
def wired(qapp, tmp_path):
    """Return (service, window, tray) wired to a temporary database."""
    service = TodoService(SqliteTodoRepository(tmp_path / "test.db"))
    window = MainWindow(service)
    window.show()
    tray = TrayIcon(window)
    tray.setVisible(False)
    yield service, window, tray
    window.close()


def test_model_shows_added_todos(wired):
    service, window, _ = wired
    service.add_todo("something to do")
    window._reload()
    assert window._table_model.rowCount() == 1


def test_filter_open(wired):
    service, window, _ = wired
    t = service.add_todo("finish me")
    service.toggle_done(t.id)
    window._reload()
    window._proxy.set_status_filter(TodoStatus.OPEN)
    assert window._proxy.rowCount() == 0
    window._proxy.set_status_filter(TodoStatus.DONE)
    assert window._proxy.rowCount() == 1
    window._proxy.set_status_filter(None)


def test_search(wired):
    service, window, _ = wired
    service.add_todo("take out trash")
    service.add_todo("brush teeth")
    window._reload()
    window._proxy.set_search_text("teeth")
    assert window._proxy.rowCount() == 1
    window._proxy.set_search_text("")


def test_done_toggled_emits_signal(wired):
    service, window, _ = wired
    todo = service.add_todo("foobar")
    window._reload()
    signals: list[tuple[str, str]] = []
    window.task_completed.connect(lambda t, b: signals.append((t, b)))
    window._on_done_toggled(todo.id, True)
    QApplication.instance().processEvents()
    assert signals[0][1] == "foobar"
    assert signals[0][0] == "Task completed"


def test_celebrate_when_all_done(wired):
    service, window, _ = wired
    t1 = service.add_todo("eins")
    t2 = service.add_todo("zwei")
    window._reload()
    signals: list[tuple[str, str]] = []
    window.task_completed.connect(lambda t, b: signals.append((t, b)))
    window._on_done_toggled(t1.id, True)
    window._on_done_toggled(t2.id, True)
    QApplication.instance().processEvents()
    assert ("All done!", "All tasks are completed.") in signals


def test_dialog_button_enables_on_non_empty_title(qapp):
    d = TodoDialog(None)
    assert not d._ok_button.isEnabled()
    d._title_edit.setText("Title")
    assert d._ok_button.isEnabled()
    d._title_edit.setText("   ")
    assert not d._ok_button.isEnabled()
    d.close()


def test_switch_toggles_and_controls_due_date(qapp):
    d = TodoDialog(None)
    switch = d._due_switch
    assert isinstance(switch, QCheckBox)
    assert switch.styleSheet()  # switch styling applied
    assert not switch.isChecked()
    assert not d._due_at_edit.isEnabled()

    switch.setChecked(True)
    assert switch.isChecked()
    assert d._due_at_edit.isEnabled()

    d._title_edit.setText("Title")
    d._buttons.button(d._buttons.StandardButton.Ok).click()
    QApplication.instance().processEvents()
    assert d.result() == d.DialogCode.Accepted
    d.close()


def test_due_editor_has_separate_date_and_time(qapp):
    """The due editor must not hide the time behind a date-only calendar popup:
    the date (calendar) and the time are two visible fields."""
    from PySide6.QtWidgets import QDateEdit, QTimeEdit

    d = TodoDialog(None)
    editor = d._due_at_edit
    assert isinstance(editor.date_edit, QDateEdit)
    assert editor.date_edit.calendarPopup()
    assert isinstance(editor.time_edit, QTimeEdit)
    d.close()


def test_now_button_sets_current_time(qapp):
    from PySide6.QtCore import QDate, QDateTime, QTime

    d = TodoDialog(None)
    d._due_switch.setChecked(True)  # the editor (and its Now button) is only active then
    d._due_at_edit.setDateTime(QDateTime(QDate(2000, 1, 1), QTime(0, 0)))
    d._due_at_edit.now_button.click()
    assert abs(d._due_at_edit.dateTime().secsTo(QDateTime.currentDateTime())) < 5
    d.close()


def test_enabling_due_switch_defaults_to_now(qapp):
    from PySide6.QtCore import QDate, QDateTime, QTime

    d = TodoDialog(None)
    d._due_at_edit.setDateTime(QDateTime(QDate(2000, 1, 1), QTime(0, 0)))
    d._due_switch.setChecked(True)
    assert abs(d._due_at_edit.dateTime().secsTo(QDateTime.currentDateTime())) < 5
    d.close()


def test_switch_styling_renders_indicator(qapp):
    """The switch SVGs must actually load and be drawn: the off/on tracks have
    distinct colors (#9aa0a6 / #4c9fff). A blank or native-looking indicator
    would mean the ``image:`` url is broken (e.g. a mangled path)."""
    from PySide6.QtGui import QColor

    cb = QCheckBox("Set due date")
    apply_switch_style(cb)
    cb.resize(200, 34)
    cb.show()

    def track_color(img) -> tuple[int, int, int] | None:
        # Sample the track region (indicator area at the left edge); return
        # the most frequent non-background color there.
        from collections import Counter

        counts: Counter[tuple[int, int, int]] = Counter()
        for x in range(46):
            for y in range(4, 30):
                c = QColor(img.pixel(x, y))
                if c.alpha() > 0:
                    counts[(c.red(), c.green(), c.blue())] += 1
        return counts.most_common(1)[0][0] if counts else None

    cb.setChecked(False)
    QApplication.instance().processEvents()
    off = track_color(cb.grab().toImage())
    cb.setChecked(True)
    QApplication.instance().processEvents()
    on = track_color(cb.grab().toImage())
    cb.close()

    # #9aa0a6 and #4c9fff within a tolerance for any scaling/filtering.
    assert off is not None and abs(off[0] - 0x9A) + abs(off[1] - 0xA0) + abs(off[2] - 0xA6) < 24, (
        f"off track wrong: {off}"
    )
    assert on is not None and abs(on[0] - 0x4C) + abs(on[1] - 0x9F) + abs(on[2] - 0xFF) < 24, (
        f"on track wrong: {on}"
    )
    assert on != off


def test_switch_checked_when_editing_todo_with_due_date(qapp):
    from datetime import datetime, timezone

    todo = Todo(
        title="With due date",
        priority=TodoPriority.MEDIUM,
        due_at=datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc),
    )
    d = TodoDialog(None, todo)
    assert d._due_switch.isChecked()
    assert d._due_at_edit.isEnabled()
    assert d._due_at_edit.dateTime().toPython() == todo.due_at.astimezone().replace(tzinfo=None)
    d.close()


def test_todo_dialog_roundtrips_status_start_all_day_reminder(qapp):
    from datetime import datetime, timezone

    from todo_snake.domain.todo import TodoStatus
    from todo_snake.ui.todo_dialog import TodoDialog

    todo = Todo(
        title="x",
        status=TodoStatus.IN_PROCESS,
        start_at=datetime(2026, 9, 20, 8, 0, tzinfo=timezone.utc),
        due_at=datetime(2026, 10, 7, tzinfo=timezone.utc),
        due_all_day=True,
        remind_before=15,
    )
    dialog = TodoDialog(None, todo)
    assert dialog._status_combo.currentData() == TodoStatus.IN_PROCESS.value
    assert dialog._start_switch.isChecked()
    assert dialog._due_switch.isChecked()
    assert dialog._due_all_day_check.isChecked()
    assert dialog._remind_combo.currentData() == 15
    dialog.close()


def test_recurring_task_shows_decoration_and_tooltip(qapp):
    from PySide6.QtCore import Qt

    from todo_snake.ui.model import TodoColumn, TodoTableModel, recurrence_label

    model = TodoTableModel()
    model.set_todos([Todo(title="weekly", recurrence="FREQ=WEEKLY;INTERVAL=2")])
    title = model.index(0, TodoColumn.TITLE)
    assert model.data(title, Qt.ItemDataRole.DecorationRole) is not None
    assert "Weekly (every 2)" in model.data(title, Qt.ItemDataRole.ToolTipRole)

    model.set_todos([Todo(title="once")])
    title = model.index(0, TodoColumn.TITLE)
    assert model.data(title, Qt.ItemDataRole.DecorationRole) is None
    assert "Repeats" not in model.data(title, Qt.ItemDataRole.ToolTipRole)

    assert recurrence_label(None) is None
    assert recurrence_label("FREQ=DAILY") == "Daily"


def test_todo_dialog_collects_recurrence(qapp):
    from todo_snake.ui.todo_dialog import TodoDialog

    dialog = TodoDialog(None)
    dialog._recurrence_combo.setCurrentIndex(dialog._recurrence_combo.findData("WEEKLY"))
    dialog._recurrence_interval.setValue(2)
    assert dialog.form_data().recurrence == "FREQ=WEEKLY;INTERVAL=2"

    dialog._recurrence_combo.setCurrentIndex(dialog._recurrence_combo.findData(""))
    assert dialog.form_data().recurrence is None
    dialog.close()


def test_choosing_a_recurrence_enables_the_due_date(qapp):
    from todo_snake.ui.todo_dialog import TodoDialog

    dialog = TodoDialog(None)
    assert not dialog._due_switch.isChecked()
    dialog._recurrence_combo.setCurrentIndex(dialog._recurrence_combo.findData("WEEKLY"))
    # A repeat needs an anchor, so the due date is switched on automatically.
    assert dialog._due_switch.isChecked()
    assert dialog.form_data().due_at is not None
    dialog.close()


def test_toolbar_sync_failure_is_reported(qapp, tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QMessageBox

    from todo_snake.persistence import create_repository
    from todo_snake.service import TodoService
    from todo_snake.sync.accounts import AccountStore, SyncAccount, SyncProvider
    from todo_snake.sync.journal import SyncJournal
    from todo_snake.sync.manager import SyncManager
    from todo_snake.ui.main_window import MainWindow

    path = tmp_path / "todo.db"
    service = TodoService(create_repository("sqlite", path))
    manager = SyncManager(service, SyncJournal(path))
    store = AccountStore(QSettings(str(tmp_path / "accounts.ini"), QSettings.Format.IniFormat))
    store.save(SyncAccount(provider=SyncProvider.NEXTCLOUD, label="broken", enabled=True))
    window = MainWindow(service, sync_manager=manager, account_store=store)
    window._reload()

    warned: list = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: warned.append(args))

    window._on_sync()
    qapp.processEvents()

    assert warned  # the user is told, not left guessing
    assert "Sync failed" in window._status_label.text()
    assert "broken" in window._status_label.text()  # the failing account is named
    window.close()


def test_note_field_visible_in_both_modes(qapp):
    from PySide6.QtWidgets import QPlainTextEdit

    new_dialog = TodoDialog(None)
    assert isinstance(new_dialog._note_edit, QPlainTextEdit)  # shown when creating too
    assert new_dialog._note_edit.toPlainText() == ""

    todo = Todo(title="edit me", note="some details\nsecond line")
    edit_dialog = TodoDialog(None, todo)
    assert isinstance(edit_dialog._note_edit, QPlainTextEdit)
    assert edit_dialog._note_edit.toPlainText() == "some details\nsecond line"
    edit_dialog.close()
    new_dialog.close()


def test_new_task_saves_note(qapp, monkeypatch, tmp_path):
    from todo_snake.ui.todo_dialog import TodoFormData

    service = TodoService(SqliteTodoRepository(tmp_path / "ui-note.db"))
    window = MainWindow(service)
    window.show()

    captured: list[str] = []
    real_add_todo = service.add_todo

    def fake_service_add(*args, **kwargs):
        captured.append(kwargs.get("note", ""))
        return real_add_todo(*args, **kwargs)

    monkeypatch.setattr(window._service, "add_todo", fake_service_add)
    monkeypatch.setattr(
        "todo_snake.ui.todo_dialog.TodoDialog.create",
        lambda parent: TodoFormData(
            title="noted",
            priority=TodoPriority.MEDIUM,
            due_at=None,
            note="a fresh note",
            status=TodoStatus.OPEN,
            start_at=None,
            due_all_day=False,
            remind_before=0,
            recurrence=None,
        ),
    )

    window._on_new()
    QApplication.instance().processEvents()
    assert captured == ["a fresh note"]
    assert service.list_todos()[0].note == "a fresh note"
    window.close()


def test_done_column_renders_switch_pills(wired):
    """The checkable (DONE) column must draw the switch pills: green for an
    open (running) task, gray for a done one. A native checkbox would
    contribute none of these track-colored pixels."""
    from PySide6.QtGui import QColor

    service, window, _ = wired
    service.add_todo("open task")
    done = service.add_todo("done task")
    service.toggle_done(done.id)
    window._reload()
    QApplication.instance().processEvents()

    img = window._table.viewport().grab().toImage()

    def count(rgb: tuple[int, int, int], tol: int) -> int:
        n = 0
        for y in range(img.height()):
            for x in range(img.width()):
                c = QColor(img.pixel(x, y))
                if sum(abs(a - b) for a, b in zip((c.red(), c.green(), c.blue()), rgb)) < tol:
                    n += 1
        return n

    green = count((0x81, 0xC7, 0x84), 40)
    gray = count((0x9A, 0xA0, 0xA6), 40)
    assert green > 100, f"open-state (green) pill not drawn in table: {green} px"
    assert gray > 100, f"done-state (gray) pill not drawn in table: {gray} px"


def test_header_stays_theme_native(wired):
    """Do not touch the header: it must keep the platform theme's default
    look (no stylesheet forced by the app)."""
    _, window, _ = wired
    assert window._table.horizontalHeader().styleSheet() == ""


def test_sort_done_column_floats_done_down(wired):
    from PySide6.QtCore import Qt

    service, window, _ = wired
    service.add_todo("open me")
    done = service.add_todo("done me")
    service.toggle_done(done.id)
    window._reload()

    window._proxy.sort(0, Qt.SortOrder.AscendingOrder)
    assert window._proxy.index(0, 1).data() == "open me"
    assert window._proxy.index(1, 1).data() == "done me"

    window._proxy.sort(0, Qt.SortOrder.DescendingOrder)
    assert window._proxy.index(0, 1).data() == "done me"
    assert window._proxy.index(1, 1).data() == "open me"


def test_switch_click_toggles_done(wired):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtGui import QMouseEvent

    service, window, _ = wired
    todo = service.add_todo("toggle me")
    window._reload()
    QApplication.instance().processEvents()

    assert not todo.is_done
    index = window._proxy.index(0, 0)
    rect = window._table.visualRect(index)
    viewport = window._table.viewport()

    def click(pos: QPoint) -> None:
        press = QMouseEvent(
            QMouseEvent.Type.MouseButtonPress,
            pos,
            viewport.mapToGlobal(pos),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        release = QMouseEvent(
            QMouseEvent.Type.MouseButtonRelease,
            pos,
            viewport.mapToGlobal(pos),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        QApplication.instance().sendEvent(viewport, press)
        QApplication.instance().sendEvent(viewport, release)
        QApplication.instance().processEvents()

    click(rect.center())
    assert service.list_todos()[0].is_done
    click(rect.center())
    assert not service.list_todos()[0].is_done


def test_tray_toggle_label_sync(wired):
    _, window, tray = wired
    window.show()
    QApplication.instance().processEvents()
    assert tray._action_toggle.text() == "Hide"
    window.hide()
    QApplication.instance().processEvents()
    assert tray._action_toggle.text() == "Show"


def test_import_reloads_table(wired, tmp_path):
    _, window, _ = wired
    data_file = tmp_path / "in.json"
    data_file.write_text('[{"title": "imported", "priority": "high"}]', encoding="utf-8")

    window._service.import_json(data_file.read_text(encoding="utf-8"))
    window._reload()
    assert window._table_model.rowCount() == 1
    assert window._table_model.todo_at(0).title == "imported"


def test_export_produces_service_payload(wired):
    service, window, _ = wired
    service.add_todo("export me")
    window._reload()
    payload = window._service.export_json()
    assert '"title": "export me"' in payload


def test_multi_select_delete(wired, monkeypatch):
    service, window, _ = wired
    for title in ("eins", "zwei", "drei"):
        service.add_todo(title)
    window._reload()

    model = window._table.model()  # the proxy
    selection = window._table.selectionModel()
    selection.select(model.index(0, 0), selection.SelectionFlag.ClearAndSelect)
    selection.select(model.index(2, 0), selection.SelectionFlag.Select)

    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        "todo_snake.ui.main_window.QMessageBox.question",
        lambda *a, **k: QMessageBox.StandardButton.Yes,
    )
    window._on_delete()
    assert [t.title for t in service.list_todos()] == ["zwei"]


def test_file_menu_has_settings_action(wired):
    _, window, _ = wired
    top = window.menuBar().actions()
    assert top and top[0].menu() is not None
    labels = [action.text() for action in top[0].menu().actions()]
    assert any(label == "Settings…" for label in labels)


def test_delete_records_tombstone_when_syncing(qapp, monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QMessageBox

    from todo_snake.sync.accounts import AccountStore
    from todo_snake.sync.journal import SyncJournal
    from todo_snake.sync.manager import SyncManager

    path = tmp_path / "sync.db"
    service = TodoService(SqliteTodoRepository(path))
    journal = SyncJournal(path)
    manager = SyncManager(service, journal)
    store = AccountStore(QSettings(str(tmp_path / "accounts.ini"), QSettings.Format.IniFormat))
    window = MainWindow(service, sync_manager=manager, account_store=store)
    window.show()
    todo = service.add_todo("delete me")
    window._reload()

    selection = window._table.selectionModel()
    proxy = window._table.model()
    selection.select(proxy.index(0, 0), selection.SelectionFlag.ClearAndSelect)

    monkeypatch.setattr(
        "todo_snake.ui.main_window.QMessageBox.question",
        lambda *a, **k: QMessageBox.StandardButton.Yes,
    )
    window._on_delete()
    assert service.list_todos() == []
    assert todo.uid in journal.tombstones()
    window.close()


def test_settings_dialog_smoke(qapp):
    from todo_snake.ui.settings_dialog import SettingsDialog

    dialog = SettingsDialog(None)
    assert dialog.windowTitle() == "Settings"
    dialog.close()


def test_account_dialog_only_offers_nextcloud_fields_for_nextcloud(qapp):
    from todo_snake.sync.accounts import SyncProvider
    from todo_snake.ui.settings_dialog import AccountDialog

    dialog = AccountDialog(None)
    find = dialog._provider_combo.findData
    # Nextcloud: a calendar URL + the connect button, no separate server/credentials.
    assert dialog._connect_button.isVisibleTo(dialog)
    assert dialog._form.isRowVisible(dialog._calendar_edit)
    assert not dialog._form.isRowVisible(dialog._server_edit)
    assert not dialog._form.isRowVisible(dialog._password_edit)
    # WebDAV: server + manual credentials, no connect button.
    dialog._provider_combo.setCurrentIndex(find(SyncProvider.WEBDAV))
    assert not dialog._connect_button.isVisibleTo(dialog)
    assert dialog._form.isRowVisible(dialog._server_edit)
    assert dialog._form.isRowVisible(dialog._password_edit)
    assert not dialog._form.isRowVisible(dialog._calendar_edit)
    dialog.close()


def test_account_dialog_applies_login_flow_credentials(qapp):
    from todo_snake.ui.settings_dialog import AccountDialog

    dialog = AccountDialog(None)
    dialog._on_credentials("https://cloud.example.com", "alice", "s3cret")
    assert dialog._server_edit.text() == "https://cloud.example.com"
    assert dialog._username_edit.text() == "alice"
    assert dialog._password_edit.text() == "s3cret"
    assert dialog._label_edit.text() == "https://cloud.example.com"
    dialog.close()


def test_toolbar_sync_action_tracks_enabled_accounts(qapp, tmp_path):
    from PySide6.QtCore import QSettings

    from todo_snake.persistence import create_repository
    from todo_snake.service import TodoService
    from todo_snake.sync.accounts import AccountStore, SyncAccount
    from todo_snake.sync.journal import SyncJournal
    from todo_snake.sync.manager import SyncManager
    from todo_snake.ui.main_window import MainWindow

    path = tmp_path / "todo.db"
    service = TodoService(create_repository("sqlite", path))
    manager = SyncManager(service, SyncJournal(path))
    store = AccountStore(QSettings(str(tmp_path / "accounts.ini"), QSettings.Format.IniFormat))
    window = MainWindow(service, sync_manager=manager, account_store=store)

    window._reload()
    assert not window._action_sync.isEnabled()

    store.save(SyncAccount(label="a", enabled=True))
    window._reload()
    assert window._action_sync.isEnabled()

    account = store.list_accounts()[0]
    account.enabled = False
    store.save(account)
    window._reload()
    assert not window._action_sync.isEnabled()

    window.close()


def test_sync_button_shows_activity_and_resets(qapp, tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QMessageBox

    from todo_snake.persistence import create_repository
    from todo_snake.service import TodoService
    from todo_snake.sync.accounts import AccountStore, SyncAccount
    from todo_snake.sync.journal import SyncJournal
    from todo_snake.sync.manager import SyncManager
    from todo_snake.ui.main_window import MainWindow

    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: None)
    path = tmp_path / "todo.db"
    service = TodoService(create_repository("sqlite", path))
    manager = SyncManager(service, SyncJournal(path))
    store = AccountStore(QSettings(str(tmp_path / "accounts.ini"), QSettings.Format.IniFormat))
    store.save(SyncAccount(label="a", enabled=True))
    window = MainWindow(service, sync_manager=manager, account_store=store)
    window._reload()

    window._on_sync()
    assert window._sync_anim_timer.isActive()
    qapp.processEvents()
    assert not window._sync_anim_timer.isActive()

    window.close()


def test_account_dialog_reconnect_uses_the_stored_server(qapp, monkeypatch):
    """Editing an account shows only the calendar *name*; "Connect" must still
    work, using the stored server URL (reconnect without deleting)."""
    from PySide6.QtCore import QObject, Signal

    from todo_snake.sync.accounts import SyncAccount, SyncProvider
    from todo_snake.ui import account_dialog as ad

    started: dict = {}

    class _DummyFlow(QObject):
        login_url_ready = Signal(str)
        credentials_ready = Signal(str, str, str)
        failed = Signal(str)

        def __init__(self, server, parent=None):
            super().__init__(parent)
            started["server"] = server

        def start(self):
            started["started"] = True

        def cancel(self):
            pass

    warnings: list = []
    monkeypatch.setattr(ad, "NextcloudLoginFlow", _DummyFlow)
    monkeypatch.setattr(ad.QMessageBox, "warning", lambda *a, **k: warnings.append(a))

    account = SyncAccount(
        provider=SyncProvider.NEXTCLOUD,
        label="dino",
        server_url="https://cloud.example.com",
        remote_path="tasks",
        username="alice",
        app_password="x",
    )
    dialog = ad.AccountDialog(None, account)
    dialog._on_connect()

    assert started.get("server") == "https://cloud.example.com"
    assert started.get("started") is True
    assert not warnings
    dialog.close()


def test_editing_with_a_blank_password_keeps_the_stored_one(qapp, monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings

    from todo_snake.sync.accounts import AccountStore, SyncAccount, SyncProvider
    from todo_snake.ui import settings_dialog as sd
    from todo_snake.ui.settings_dialog import AccountFormData

    store = AccountStore(QSettings(str(tmp_path / "accounts.ini"), QSettings.Format.IniFormat))
    account = SyncAccount(
        provider=SyncProvider.NEXTCLOUD,
        label="dino",
        server_url="https://cloud.example.com",
        remote_path="tasks",
        username="alice",
        app_password="secret",
    )
    store.save(account)

    monkeypatch.setattr(
        sd.AccountDialog,
        "create",
        staticmethod(
            lambda parent, acc=None: AccountFormData(
                label="dino",
                provider=SyncProvider.NEXTCLOUD,
                server_url="https://cloud.example.com",
                remote_path="tasks",
                username="alice",
                app_password="",
            )
        ),
    )
    dialog = sd.SettingsDialog(None, store, None)
    dialog._account_list.setCurrentRow(0)
    dialog._on_edit()

    assert store.get(account.uid).app_password == "secret"
    dialog.close()


def test_account_dialog_form_data_uses_the_calendar_field(qapp):
    from todo_snake.sync.accounts import SyncProvider
    from todo_snake.ui.settings_dialog import AccountDialog

    dialog = AccountDialog(None)
    dialog._label_edit.setText("dino")
    dialog._server_edit.setText("https://dino")
    dialog._calendar_edit.setText("https://dino/apps/tasks/calendars/tasks")

    data = dialog.form_data()

    assert data.provider == SyncProvider.NEXTCLOUD
    assert data.server_url == "https://dino"
    assert data.remote_path == "https://dino/apps/tasks/calendars/tasks"
    dialog.close()


def test_account_dialog_test_connection_reports_success(qapp, monkeypatch):
    from todo_snake.sync.webdav import FetchResult
    from todo_snake.ui import account_dialog as ad

    class _FakeTransport:
        def fetch(self):
            return FetchResult(True, b'{"format":"todo-snake","schema_version":1,"items":[]}')

    monkeypatch.setattr(ad, "create_transport", lambda *a, **k: _FakeTransport())
    dialog = ad.AccountDialog(None)
    dialog._on_test_connection()
    assert "Connection OK" in dialog._connect_status.text()
    dialog.close()


def test_account_dialog_test_connection_reports_failure(qapp, monkeypatch):
    from todo_snake.sync.webdav import SyncTransportError
    from todo_snake.ui import account_dialog as ad

    class _FakeTransport:
        def fetch(self):
            raise SyncTransportError("HTTP 401 Unauthorized")

    monkeypatch.setattr(ad, "create_transport", lambda *a, **k: _FakeTransport())
    dialog = ad.AccountDialog(None)
    dialog._on_test_connection()
    assert "Connection failed" in dialog._connect_status.text()
    assert "401" in dialog._connect_status.text()
    dialog.close()


def test_attachments_dialog_lists_and_removes(qapp, tmp_path):
    from todo_snake.persistence.attachments import SqliteAttachmentRepository
    from todo_snake.service.attachment_service import AttachmentService
    from todo_snake.ui.attachments_dialog import AttachmentsDialog

    attachments = AttachmentService(SqliteAttachmentRepository(tmp_path / "test.db"))
    todo = Todo(uid="u-1", title="With files")
    attachments.add("u-1", "one.txt", b"1")
    attachments.add("u-1", "two.txt", b"22")
    attachments.sync_remote_urls("u-1", "acc", ("https://cloud/remote/three.txt",))

    dialog = AttachmentsDialog(None, todo, attachments)
    assert dialog._list.count() == 3
    # A file without local bytes is marked as remote.
    assert " (remote)" in dialog._list.item(2).text()
    assert " (remote)" not in dialog._list.item(0).text()
    # Nothing selected yet: the item actions are disabled.
    assert not dialog._open_button.isEnabled()
    assert not dialog._remove_button.isEnabled()

    dialog._list.setCurrentRow(0)
    assert dialog._open_button.isEnabled()
    dialog._on_remove()
    assert dialog._list.count() == 2
    assert [a.filename for a in attachments.list_for("u-1")] == ["two.txt", "three.txt"]
    dialog.close()


def test_attachments_action_requires_a_selected_task(qapp, tmp_path):
    from todo_snake.persistence.attachments import SqliteAttachmentRepository
    from todo_snake.service.attachment_service import AttachmentService

    attachments = AttachmentService(SqliteAttachmentRepository(tmp_path / "test.db"))
    service = TodoService(SqliteTodoRepository(tmp_path / "test.db"))
    window = MainWindow(service, attachment_service=attachments)
    window.show()
    try:
        # No selection: disabled even though the service is present.
        assert not window._action_attachments.isEnabled()
        service.add_todo("pick me")
        window._reload()
        window._table.selectRow(0)
        assert window._action_attachments.isEnabled()
    finally:
        window.close()


def test_table_shows_attachment_count_and_tooltip(qapp, tmp_path):
    from todo_snake.persistence.attachments import SqliteAttachmentRepository
    from todo_snake.service.attachment_service import AttachmentService
    from todo_snake.ui.model import TodoColumn

    attachments = AttachmentService(SqliteAttachmentRepository(tmp_path / "test.db"))
    service = TodoService(SqliteTodoRepository(tmp_path / "test.db"))
    window = MainWindow(service, attachment_service=attachments)
    window.show()
    try:
        todo = service.add_todo("has files")
        service.add_todo("plain")
        attachments.add(todo.uid, "report.pdf", b"%PDF")
        attachments.add(todo.uid, "photo.png", b"png")
        window._reload()

        model = window._table_model
        role = Qt.ItemDataRole
        with_files = model.index(model.row_of_todo(todo.id), int(TodoColumn.FILES))
        assert model.data(with_files, role.DisplayRole) == "2"
        assert model.data(with_files, role.DecorationRole) is not None
        tooltip = model.data(with_files, role.ToolTipRole)
        assert "report.pdf" in tooltip and "photo.png" in tooltip

        plain_id = next(t.id for t in service.list_todos() if t.title == "plain")
        plain = model.index(model.row_of_todo(plain_id), int(TodoColumn.FILES))
        assert model.data(plain, role.DisplayRole) == ""
        assert model.data(plain, role.DecorationRole) is None
        assert (
            model.headerData(int(TodoColumn.FILES), Qt.Orientation.Horizontal, role.DisplayRole)
            == "Files"
        )
    finally:
        window.close()


def test_todo_dialog_shows_attachments_button_only_when_editing(qapp, tmp_path):
    from todo_snake.persistence.attachments import SqliteAttachmentRepository
    from todo_snake.service.attachment_service import AttachmentService
    from todo_snake.ui.todo_dialog import TodoDialog

    attachments = AttachmentService(SqliteAttachmentRepository(tmp_path / "test.db"))
    todo = Todo(uid="u-1", title="existing")

    editing = TodoDialog(None, todo, attachments)
    assert editing._attachments_button.isVisibleTo(editing)
    assert editing._attachments_button.text() == "Attachments…"
    attachments.add("u-1", "a.pdf", b"%PDF")
    editing._update_attachments_button()
    assert editing._attachments_button.text() == "Attachments (1)…"
    editing.close()

    creating = TodoDialog(None, None, attachments)
    assert not creating._attachments_button.isVisibleTo(creating)
    creating.close()


def test_attachments_dialog_uses_48px_icons(qapp, tmp_path):
    from PySide6.QtCore import QBuffer, QIODevice, QSize
    from PySide6.QtGui import QImage

    from todo_snake.persistence.attachments import SqliteAttachmentRepository
    from todo_snake.service.attachment_service import AttachmentService
    from todo_snake.ui import file_icons
    from todo_snake.ui.attachments_dialog import AttachmentsDialog

    image = QImage(120, 60, QImage.Format.Format_RGB32)
    image.fill(0x22AA55)
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")

    attachments = AttachmentService(SqliteAttachmentRepository(tmp_path / "test.db"))
    attachments.add("u-1", "report.pdf", b"%PDF")
    attachments.add("u-1", "photo.png", bytes(buffer.data()))
    dialog = AttachmentsDialog(None, Todo(uid="u-1", title="x"), attachments)
    assert dialog._list.iconSize() == QSize(48, 48)
    assert not dialog._list.item(0).icon().isNull()
    # The image renders a real preview, not the generic image-type icon.
    assert (
        dialog._list.item(1).icon().cacheKey() != file_icons.type_icon("photo.png", "").cacheKey()
    )
    dialog.close()


def test_settings_dialog_can_disable_and_enable_an_account(qapp, tmp_path):
    from PySide6.QtCore import QSettings

    from todo_snake.sync.accounts import AccountStore, SyncAccount, SyncProvider
    from todo_snake.sync.journal import SyncJournal
    from todo_snake.sync.manager import SyncManager
    from todo_snake.ui.settings_dialog import SettingsDialog

    store = AccountStore(QSettings(str(tmp_path / "accounts.ini"), QSettings.Format.IniFormat))
    account = SyncAccount(
        provider=SyncProvider.NEXTCLOUD,
        label="dino",
        server_url="https://cloud.example.com",
        remote_path="tasks",
        username="alice",
        app_password="secret",
    )
    store.save(account)

    service = TodoService(SqliteTodoRepository(tmp_path / "todos.db"))
    manager = SyncManager(service, SyncJournal(tmp_path / "todos.db"))
    dialog = SettingsDialog(None, store, manager)

    item = dialog._account_list.item(0)
    assert item.checkState() == Qt.CheckState.Checked
    assert dialog._sync_button.isEnabled()

    # Unchecking the row disables the account without deleting it.
    item.setCheckState(Qt.CheckState.Unchecked)
    assert store.get(account.uid) is not None
    assert store.get(account.uid).enabled is False
    refreshed = dialog._account_list.item(0)
    assert refreshed.checkState() == Qt.CheckState.Unchecked
    assert refreshed.foreground().color().name() == "#8a8a8a"
    assert refreshed.toolTip() == "Sync disabled"
    assert "sync disabled" in dialog._last_sync_label.text()
    # A disabled account is not synced, not even manually.
    assert not dialog._sync_button.isEnabled()

    # Checking it again re-enables it.
    refreshed.setCheckState(Qt.CheckState.Checked)
    assert store.get(account.uid).enabled is True
    assert dialog._sync_button.isEnabled()
    dialog.close()


def test_settings_offers_cleanup_only_for_nextcloud(qapp, tmp_path):
    from PySide6.QtCore import QSettings

    from todo_snake.persistence.attachments import SqliteAttachmentRepository
    from todo_snake.service.attachment_service import AttachmentService
    from todo_snake.sync.accounts import AccountStore, SyncAccount, SyncProvider
    from todo_snake.ui.settings_dialog import SettingsDialog

    store = AccountStore(QSettings(str(tmp_path / "accounts.ini"), QSettings.Format.IniFormat))
    store.save(
        SyncAccount(
            provider=SyncProvider.NEXTCLOUD,
            label="dino",
            server_url="https://dino",
            remote_path="tasks",
            username="alice",
            app_password="pw",
        )
    )
    attachments = AttachmentService(SqliteAttachmentRepository(tmp_path / "todos.db"))

    dialog = SettingsDialog(None, store, None, attachments)
    assert dialog._cleanup_button.isEnabled()
    dialog.close()

    # Without an attachment service the action is unavailable.
    plain = SettingsDialog(None, store, None, None)
    assert not plain._cleanup_button.isEnabled()
    plain.close()


def test_settings_cleanup_deletes_orphaned_files(qapp, monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QMessageBox

    from todo_snake.persistence.attachments import SqliteAttachmentRepository
    from todo_snake.service.attachment_service import AttachmentService
    from todo_snake.sync.accounts import AccountStore, SyncAccount, SyncProvider
    from todo_snake.ui import settings_dialog as sd
    from todo_snake.ui.settings_dialog import SettingsDialog

    store = AccountStore(QSettings(str(tmp_path / "accounts.ini"), QSettings.Format.IniFormat))
    store.save(
        SyncAccount(
            uid="acc-a",
            provider=SyncProvider.NEXTCLOUD,
            label="dino",
            server_url="https://dino",
            remote_path="tasks",
            username="alice",
            app_password="pw",
        )
    )
    attachments = AttachmentService(SqliteAttachmentRepository(tmp_path / "todos.db"))

    orphan = "https://dino/remote.php/dav/files/alice/Todo%20Snake/Attachments/u-1/orphan.txt"

    class _FakeStore:
        def __init__(self):
            self.deleted: list[str] = []

        def list_attachment_files(self):
            return [orphan]

        def delete(self, url):
            self.deleted.append(url)
            return True

        def close(self):
            pass

    fake = _FakeStore()
    monkeypatch.setattr(sd, "make_file_store", lambda account, parent=None: fake)
    monkeypatch.setattr(
        QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)

    dialog = SettingsDialog(None, store, None, attachments)
    dialog._account_list.setCurrentRow(0)
    dialog._on_cleanup()

    assert fake.deleted == [orphan]
    dialog.close()
