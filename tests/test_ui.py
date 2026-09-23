"""UI smoke tests — run fully offscreen."""

import pytest
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
