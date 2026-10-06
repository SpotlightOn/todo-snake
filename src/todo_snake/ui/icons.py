"""Bundled SVG icons, loaded as Qt resources."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

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


def create_sync_icon() -> QIcon:
    return _icon("sync")


def create_sync_active_icon() -> QIcon:
    return _icon("sync-active")


def create_sync_error_icon() -> QIcon:
    return _icon("sync-error")


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


_recurrence_icon: QIcon | None = None


def recurrence_icon() -> QIcon | None:
    """A small ∞ used as a list decoration for recurring tasks (built once)."""
    global _recurrence_icon
    if _recurrence_icon is None:
        _recurrence_icon = _build_recurrence_icon()
    return _recurrence_icon


def _build_recurrence_icon(size: int = 16) -> QIcon | None:
    if QApplication.instance() is None:  # a QPixmap needs a running app
        return None
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    font = painter.font()
    font.setPixelSize(int(size * 0.85))
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(QColor("#6b6b6b"))
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "\u221e")
    painter.end()
    return QIcon(pixmap)
