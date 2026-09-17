"""Bundled SVG icons, loaded as Qt resources."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QIcon

_ICON_DIR = Path(__file__).resolve().parent.parent / "resources" / "icons"


def _icon(name: str) -> QIcon:
    return QIcon(str(_ICON_DIR / f"{name}.svg"))


def create_todo_icon() -> QIcon:
    return _icon("todo")


def create_plus_icon() -> QIcon:
    return _icon("add")


def create_pencil_icon() -> QIcon:
    return _icon("edit")


def create_trash_icon() -> QIcon:
    return _icon("delete")