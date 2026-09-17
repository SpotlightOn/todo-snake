"""Turn a ``QCheckBox`` into a toggle switch via a stylesheet.

Follows the Qt Style Sheets approach (``QCheckBox::indicator`` + ``image:``
per state), see
https://doc.qt.io/qt-6/stylesheet-examples.html#customizing-qcheckbox
This keeps the regular ``QCheckBox`` semantics (``setChecked``/``toggled``)
while rendering as a pill switch with a sliding knob.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import (
    QByteArray,
    QEvent,
    QPointF,
    QRect,
    QRectF,
    QSize,
    QSizeF,
    Qt,
)
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
)

_ICON_DIR = Path(__file__).resolve().parent.parent / "resources" / "icons"
_SWITCH_OFF = (_ICON_DIR / "switch-off.svg").as_posix()
_SWITCH_ON = (_ICON_DIR / "switch-on.svg").as_posix()

# The delegate renders the switch SVGs again at runtime — scaled to the target
# size and with the track recolored — so the SVG files stay the single source
# of truth and no raster assets are needed.
_PILL_SIZE = QSize(40, 20)
_TRACK_SOURCE_OFF = "#9aa0a6"  # track color inside switch-off.svg (knob left)
_TRACK_SOURCE_ON = "#4c9fff"  # track color inside switch-on.svg (knob right)
_COLOR_RUNNING = "#81c784"  # open/running task -> lighter green
_COLOR_DONE = "#9aa0a6"  # done task -> dezent grau


def _render_switch_pill(
    svg_path: str, source_track_hex: str, target_track_hex: str, dpr: float
) -> QPixmap:
    """Render a switch SVG at ``_PILL_SIZE`` with a recolored track."""
    svg_text = Path(svg_path).read_text(encoding="utf-8")
    if source_track_hex not in svg_text:
        raise RuntimeError(f"{svg_path}: track color {source_track_hex} not found in SVG")
    svg_text = svg_text.replace(source_track_hex, target_track_hex)
    renderer = QSvgRenderer()
    if not renderer.load(QByteArray(svg_text.encode("utf-8"))):
        raise RuntimeError(f"cannot load SVG: {svg_path}")

    pixmap = QPixmap(round(_PILL_SIZE.width() * dpr), round(_PILL_SIZE.height() * dpr))
    pixmap.fill(Qt.GlobalColor.transparent)
    pixmap.setDevicePixelRatio(dpr)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(QPointF(0, 0), QSizeF(_PILL_SIZE)))
    painter.end()
    return pixmap


def switch_stylesheet(selector: str = "QCheckBox::indicator") -> str:
    """Stylesheet that renders check indicators as a pill switch.

    ``selector`` targets the indicator sub-control of the widget that draws the
    checkbox, e.g. ``"QCheckBox::indicator"`` (dialog) or
    ``"QTableView::indicator"`` (checkable table column).
    """
    return f"""
{selector} {{ width: 46px; height: 26px; }}
{selector}:unchecked {{ image: url("{_SWITCH_OFF}"); }}
{selector}:checked {{ image: url("{_SWITCH_ON}"); }}
"""


def apply_switch_style(checkbox: QCheckBox) -> None:
    """Apply the switch look to ``checkbox``."""
    checkbox.setStyleSheet(switch_stylesheet())


class SwitchDelegate(QStyledItemDelegate):
    """Paint the switch pills directly into a checkable item-view column.

    Used for e.g. the ``DONE`` column of the todo table: each row gets a
    pill switch (green = open, gray = done). Painter-based so it does not
    depend on the platform style or on image-format plugins; the pills are
    rendered from the switch SVGs at ``__init__`` time (scaled to target
    size and recolored). Everything else (selection, alternating rows,
    header) stays native.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        dpr = float(parent.devicePixelRatioF()) if parent is not None else 1.0
        self._pix_not_done = _render_switch_pill(
            _SWITCH_OFF, _TRACK_SOURCE_OFF, _COLOR_RUNNING, dpr
        )
        self._pix_done = _render_switch_pill(_SWITCH_ON, _TRACK_SOURCE_ON, _COLOR_DONE, dpr)

    def paint(self, painter: QPainter, option, index) -> None:
        check_state = index.data(Qt.ItemDataRole.CheckStateRole)
        opts = QStyleOptionViewItem(option)
        self.initStyleOption(opts, index)
        if check_state is None:
            super().paint(painter, option, index)
            return
        opts.features &= ~QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator
        style = opts.widget.style() if opts.widget is not None else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opts, painter, opts.widget)
        pix = self._pix_done if check_state == Qt.CheckState.Checked else self._pix_not_done
        target = _centered(option.rect, _PILL_SIZE.width(), _PILL_SIZE.height())
        painter.drawPixmap(target, pix)

    def editorEvent(self, event, model, option, index) -> bool:
        if (
            option.rect.contains(event.position().toPoint())
            and event.type() == QEvent.Type.MouseButtonRelease
            and index.data(Qt.ItemDataRole.CheckStateRole) is not None
        ):
            current = model.data(index, Qt.ItemDataRole.CheckStateRole)
            new_state = (
                Qt.CheckState.Unchecked
                if current == Qt.CheckState.Checked
                else Qt.CheckState.Checked
            )
            if model.setData(index, new_state, Qt.ItemDataRole.CheckStateRole):
                return True
        return super().editorEvent(event, model, option, index)


def _centered(rect, width: int, height: int) -> QRect:
    """Return ``rect`` reduced to ``size`` and centered inside it."""
    return QRect(
        rect.center().x() - width // 2,
        rect.center().y() - height // 2,
        width,
        height,
    )
