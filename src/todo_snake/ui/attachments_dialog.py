"""Dialog: manage the attachments of one task (local-first)."""

from __future__ import annotations

import mimetypes
import shutil
import tempfile
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from todo_snake.domain.attachment import Attachment
from todo_snake.domain.todo import Todo
from todo_snake.service.attachment_service import AttachmentService, AttachmentTooLargeError
from todo_snake.ui import file_icons

#: Preview/type icon size in the list.
_ICON_SIZE = 48


def _human_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.0f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


class AttachmentsDialog(QDialog):
    """List, add, open and remove the attachments of a single task."""

    def __init__(self, parent: QWidget | None, todo: Todo, service: AttachmentService):
        super().__init__(parent)
        self._todo = todo
        self._service = service
        self._tempdir: str | None = None
        #: Rendered icons, keyed by attachment id (thumbnails are not re-decoded).
        self._icons: dict[int, QIcon] = {}
        self.setWindowTitle(self.tr("Attachments — {title}").format(title=todo.title))
        self.setMinimumWidth(440)

        self._list = QListWidget(self)
        self._list.setIconSize(QSize(_ICON_SIZE, _ICON_SIZE))
        self._list.setSpacing(2)
        self._add_button = QPushButton(self.tr("Add file…"), self)
        self._open_button = QPushButton(self.tr("Open file"), self)
        self._remove_button = QPushButton(self.tr("Remove"), self)
        self._add_button.clicked.connect(self._on_add)
        self._open_button.clicked.connect(self._on_open)
        self._remove_button.clicked.connect(self._on_remove)
        self._list.itemSelectionChanged.connect(self._update_buttons)
        self._list.itemDoubleClicked.connect(lambda _item: self._on_open())

        button_column = QVBoxLayout()
        button_column.addWidget(self._add_button)
        button_column.addWidget(self._open_button)
        button_column.addWidget(self._remove_button)
        button_column.addStretch(1)

        row = QHBoxLayout()
        row.addWidget(self._list, 1)
        row.addLayout(button_column)

        close_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        close_box.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(row)
        layout.addWidget(close_box)

        self._refresh()

    # -- helpers -------------------------------------------------------------

    def _refresh(self) -> None:
        self._list.clear()
        for attachment in self._service.list_for(self._todo.uid):
            suffix = "" if attachment.has_data else self.tr(" (remote)")
            item = QListWidgetItem(
                f"{attachment.filename}  ·  {_human_size(attachment.size)}{suffix}"
            )
            item.setData(Qt.ItemDataRole.UserRole, attachment.id)
            if attachment.id is not None:
                item.setIcon(self._icon_for(attachment))
            self._list.addItem(item)
        self._update_buttons()

    def _icon_for(self, attachment: Attachment) -> QIcon:
        """A cached preview (images) or type icon for one attachment."""
        if attachment.id is not None:
            cached = self._icons.get(attachment.id)
            if cached is not None:
                return cached
        payload = None
        if attachment.has_data and attachment.id is not None:
            stored = self._service.read(attachment.id)
            payload = stored.data if stored is not None else None
        icon = file_icons.attachment_icon(attachment.filename, attachment.mime, payload, _ICON_SIZE)
        if attachment.id is not None:
            self._icons[attachment.id] = icon
        return icon

    def _selected_id(self) -> int | None:
        item = self._list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    def _update_buttons(self) -> None:
        has_selection = self._selected_id() is not None
        self._open_button.setEnabled(has_selection)
        self._remove_button.setEnabled(has_selection)

    # -- actions -------------------------------------------------------------

    def _on_add(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, self.tr("Add file"))
        if not path:
            return
        source = Path(path)
        try:
            data = source.read_bytes()
        except OSError as exc:
            QMessageBox.critical(self, self.tr("Could not read the file"), str(exc))
            return
        mime, _ = mimetypes.guess_type(str(source))
        try:
            self._service.add(self._todo.uid, source.name, data, mime or "")
        except AttachmentTooLargeError as exc:
            QMessageBox.warning(self, self.tr("File too large"), str(exc))
            return
        self._refresh()

    def _on_open(self) -> None:
        attachment_id = self._selected_id()
        if attachment_id is None:
            return
        attachment = self._service.read(attachment_id)
        if attachment is None:
            return
        if attachment.data is not None:
            if self._tempdir is None:
                self._tempdir = tempfile.mkdtemp(prefix="todo-snake-")
            target = Path(self._tempdir) / attachment.filename
            try:
                target.write_bytes(attachment.data)
            except OSError as exc:
                QMessageBox.critical(self, self.tr("Could not open the file"), str(exc))
                return
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))
        elif attachment.any_remote_url:
            QDesktopServices.openUrl(QUrl(attachment.any_remote_url))

    def _on_remove(self) -> None:
        attachment_id = self._selected_id()
        if attachment_id is None:
            return
        self._service.remove(attachment_id)
        self._refresh()

    def done(self, result: int) -> None:
        if self._tempdir is not None:
            shutil.rmtree(self._tempdir, ignore_errors=True)
            self._tempdir = None
        super().done(result)
