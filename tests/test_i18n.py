"""Tests for the translation setup: shipped catalogs, completeness, wiring."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from PySide6.QtCore import QLocale, Qt, QTranslator

from todo_snake.domain import TodoPriority
from todo_snake.i18n import available_language_codes, resolve_language, translations_dir
from todo_snake.ui.model import TodoColumn, TodoTableModel, priority_label
from todo_snake.ui.todo_dialog import TodoDialog


def test_ts_files_are_translated_and_compiled(qapp):
    """Every .ts ships a .qm, and no source string stays untranslated."""
    dir_path = translations_dir()
    ts_files = sorted(dir_path.glob("todo_snake_*.ts"))
    assert ts_files, "no translation source files shipped"

    for ts in ts_files:
        assert (dir_path / (ts.stem + ".qm")).is_file(), f"{ts.name} not compiled"
        root = ET.parse(ts).getroot()
        unfinished = root.findall(".//translation[@type='unfinished']")
        assert not unfinished, f"{ts.name}: {len(unfinished)} unfinished translation(s)"


def test_available_language_codes(qapp):
    codes = available_language_codes()
    assert "de" in codes
    assert "en" in codes


def test_resolve_language_override(monkeypatch):
    monkeypatch.setenv("TODO_SNAKE_LANG", "de")
    assert resolve_language() == "de"


def test_resolve_language_english_override(monkeypatch):
    monkeypatch.setenv("TODO_SNAKE_LANG", "en")
    assert resolve_language() == "en"


def test_resolve_language_preferred_beats_override(monkeypatch):
    monkeypatch.setenv("TODO_SNAKE_LANG", "fr")
    assert resolve_language("de") == "de"


def test_resolve_language_unknown_returns_none(monkeypatch):
    monkeypatch.setenv("TODO_SNAKE_LANG", "fr")
    assert resolve_language() is None


def test_resolve_language_region_shortened(monkeypatch):
    monkeypatch.setenv("TODO_SNAKE_LANG", "de_AT")
    assert resolve_language() == "de"


def test_german_translations_apply(qapp):
    """With the German catalog installed, dialogs and table headers are German."""
    translator = QTranslator(qapp)
    assert translator.load(QLocale("de"), "todo_snake", "_", str(translations_dir()), ".qm")
    qapp.installTranslator(translator)
    try:
        dialog = TodoDialog()
        assert dialog.windowTitle() == "Neue Aufgabe"
        assert dialog._ok_button.text() == "Speichern"
        assert dialog._priority_combo.itemText(0) == "Niedrig"
        dialog.close()

        model = TodoTableModel()
        role = Qt.ItemDataRole.DisplayRole
        assert model.headerData(TodoColumn.TITLE, Qt.Orientation.Horizontal, role) == "Aufgabe"
        assert model.headerData(TodoColumn.PRIORITY, Qt.Orientation.Horizontal, role) == "Priorität"
        assert priority_label(TodoPriority.MEDIUM) == "Mittel"
    finally:
        qapp.removeTranslator(translator)


def test_english_source_when_no_translator(qapp):
    """Without any translator installed the app shows the English source text."""
    dialog = TodoDialog()
    assert dialog.windowTitle() == "New task"
    assert dialog._ok_button.text() == "Save"
    dialog.close()
    assert priority_label(TodoPriority.HIGH) == "High"


def test_english_catalog_keeps_english(qapp):
    """The ``en`` catalog is the explicit English fallback: installing it must
    keep English texts even on a non-English machine."""
    translator = QTranslator(qapp)
    assert translator.load(QLocale("en"), "todo_snake", "_", str(translations_dir()), ".qm")
    qapp.installTranslator(translator)
    try:
        dialog = TodoDialog()
        assert dialog.windowTitle() == "New task"
        assert dialog._ok_button.text() == "Save"
        assert dialog._priority_combo.itemText(0) == "Low"
        dialog.close()
    finally:
        qapp.removeTranslator(translator)
