"""UI smoke tests — run fully offscreen."""

import pytest
from PySide6.QtWidgets import QApplication

from snake_todo.domain import TodoStatus
from snake_todo.persistence.sqlite import SqliteTodoRepository
from snake_todo.service import TodoService
from snake_todo.ui.main_window import MainWindow
from snake_todo.ui.todo_dialog import TodoDialog
from snake_todo.ui.tray import TrayIcon


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


def test_tray_toggle_label_sync(wired):
    _, window, tray = wired
    window.show()
    QApplication.instance().processEvents()
    assert tray._action_toggle.text() == "Hide"
    window.hide()
    QApplication.instance().processEvents()
    assert tray._action_toggle.text() == "Show"


def test_import_reloads_table(wired, tmp_path):
    service, window, _ = wired
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
        "snake_todo.ui.main_window.QMessageBox.question",
        lambda *a, **k: QMessageBox.StandardButton.Yes,
    )
    window._on_delete()
    assert [t.title for t in service.list_todos()] == ["zwei"]