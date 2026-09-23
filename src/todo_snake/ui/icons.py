"""Bundled SVG icons, loaded as Qt resources."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter

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


def create_alert_icon(size: int = 64) -> QIcon:
    """The todo icon with a red badge, used to make the tray icon blink."""
    base = create_todo_icon().pixmap(size, size)
    if base.isNull():
        return create_todo_icon()
    painter = QPainter(base)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#d32f2f"))
    radius = size * 0.32
    painter.drawEllipse(
        QRectF(size - 2 * radius - 1, size - 2 * radius - 1, 2 * radius, 2 * radius)
    )
    painter.end()
    return QIcon(base)
