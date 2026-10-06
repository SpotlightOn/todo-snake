"""Settings dialog: manage sync accounts and sync behavior."""

from __future__ import annotations

from datetime import datetime, timezone

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from todo_snake.domain.attachment import filename_from_url
from todo_snake.sync.accounts import AccountStore, SyncAccount, SyncProvider
from todo_snake.sync.attachments import find_orphans
from todo_snake.sync.behavior import SyncBehavior
from todo_snake.sync.file_store import make_file_store
from todo_snake.sync.webdav import SyncTransportError

# Re-exported so existing imports keep working (and tests can patch them here).
from todo_snake.ui.account_dialog import AccountDialog, AccountFormData

__all__ = ["AccountDialog", "AccountFormData", "SettingsDialog"]


_DISABLED_COLOR = QColor("#8a8a8a")

_DISABLED_COLOR = QColor("#8a8a8a")


class SettingsDialog(QDialog):
    """Two tabs: manage sync accounts, and configure sync behavior."""

    reload_requested = Signal()

    def __init__(
        self,
        parent=None,
        account_store: AccountStore | None = None,
        sync_manager=None,
        attachments=None,
    ):
        super().__init__(parent)
        self._store = account_store if account_store is not None else AccountStore()
        self._manager = sync_manager
        # Optional AttachmentService: enables the orphan cleanup action.
        self._attachments = attachments

        self.setWindowTitle(self.tr("Settings"))
        self.setMinimumWidth(480)

        tabs = QTabWidget(self)
        tabs.addTab(self._build_accounts_tab(), self.tr("Sync accounts"))
        tabs.addTab(self._build_behavior_tab(), self.tr("Sync behavior"))

        close_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        close_box.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(close_box)

        if self._manager is not None:
            self._manager.sync_finished.connect(self._on_sync_finished)
            self._manager.sync_failed.connect(self._on_sync_failed)

        self._refresh()

    # -- construction --------------------------------------------------------

    def _build_accounts_tab(self) -> QWidget:
        page = QWidget(self)
        self._account_list = QListWidget(page)
        self._account_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self._account_list.itemSelectionChanged.connect(self._update_controls)
        # Checking/unchecking an item toggles that account's sync.
        self._account_list.itemChanged.connect(self._on_account_item_changed)

        self._add_button = QPushButton(self.tr("Add…"), page)
        self._edit_button = QPushButton(self.tr("Edit…"), page)
        self._remove_button = QPushButton(self.tr("Remove"), page)
        self._sync_button = QPushButton(self.tr("Sync now"), page)
        self._cleanup_button = QPushButton(self.tr("Clean up orphaned files…"), page)
        self._add_button.clicked.connect(self._on_add)
        self._edit_button.clicked.connect(self._on_edit)
        self._remove_button.clicked.connect(self._on_remove)
        self._sync_button.clicked.connect(self._on_sync)
        self._cleanup_button.clicked.connect(self._on_cleanup)

        button_column = QVBoxLayout()
        for button in (
            self._add_button,
            self._edit_button,
            self._remove_button,
            self._sync_button,
        ):
            button_column.addWidget(button)
        button_column.addSpacing(12)
        button_column.addWidget(self._cleanup_button)
        button_column.addStretch(1)

        top_row = QHBoxLayout()
        top_row.addWidget(self._account_list, 1)
        top_row.addLayout(button_column)

        self._last_sync_label = QLabel("", page)

        bottom = QVBoxLayout()
        bottom.addWidget(self._last_sync_label)

        layout = QVBoxLayout(page)
        layout.addLayout(top_row, 1)
        layout.addLayout(bottom)
        return page

    def _build_behavior_tab(self) -> QWidget:
        page = QWidget(self)
        behavior = SyncBehavior.load()

        self._startup_check = QCheckBox(self.tr("Synchronize on startup"), page)
        self._periodic_check = QCheckBox(self.tr("Synchronize periodically"), page)
        self._interval_spin = QSpinBox(page)
        self._interval_spin.setRange(1, 1440)
        self._interval_spin.setSuffix(self.tr(" min"))
        self._interval_spin.setValue(behavior.periodic_minutes)

        self._startup_check.setChecked(behavior.sync_on_startup)
        self._periodic_check.setChecked(behavior.periodic_enabled)
        self._interval_spin.setEnabled(behavior.periodic_enabled)

        info = QLabel(
            self.tr(
                "Periodic sync runs while the app is open. Manual sync is always "
                "available via the “Sync now” toolbar button."
            ),
            page,
        )
        info.setWordWrap(True)

        self._periodic_check.toggled.connect(self._interval_spin.setEnabled)

        form = QFormLayout()
        form.addRow(self._startup_check)
        form.addRow(self._periodic_check)
        form.addRow(self.tr("Interval:"), self._interval_spin)

        layout = QVBoxLayout(page)
        layout.addLayout(form)
        layout.addWidget(info)
        layout.addStretch(1)

        for widget in (
            self._startup_check,
            self._periodic_check,
            self._interval_spin,
        ):
            if isinstance(widget, QSpinBox):
                widget.valueChanged.connect(self._save_behavior)
            else:
                widget.toggled.connect(self._save_behavior)
        return page

    # -- account list --------------------------------------------------------

    def _accounts(self) -> list[SyncAccount]:
        return self._store.list_accounts()

    def _selected_account(self) -> SyncAccount | None:
        item = self._account_list.currentItem()
        if item is None:
            return None
        return self._store.get(item.data(Qt.ItemDataRole.UserRole))

    def _refresh(self, select_uid: str | None = None) -> None:
        """Rebuild the list, keeping the selection (or forcing ``select_uid``)."""
        if select_uid is None:
            current = self._selected_account()
            select_uid = current.uid if current is not None else None
        # Rebuilding the items must not be mistaken for user toggles.
        self._account_list.blockSignals(True)
        self._account_list.clear()
        for account in self._accounts():
            provider = {
                SyncProvider.NEXTCLOUD: self.tr("Nextcloud"),
                SyncProvider.WEBDAV: self.tr("WebDAV"),
                SyncProvider.CALDAV: self.tr("CalDAV"),
                SyncProvider.GOOGLE: self.tr("Google"),
            }.get(account.provider, account.provider)
            item = QListWidgetItem(f"{account.display_name} — {provider}")
            item.setData(Qt.ItemDataRole.UserRole, account.uid)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if account.enabled else Qt.CheckState.Unchecked
            )
            if not account.enabled:
                item.setForeground(QBrush(_DISABLED_COLOR))
                item.setToolTip(self.tr("Sync disabled"))
            self._account_list.addItem(item)
        self._account_list.blockSignals(False)
        self._select_account(select_uid)

    def _select_account(self, uid: str | None) -> None:
        if self._account_list.count() == 0:
            self._update_controls()
            return
        row = 0
        if uid is not None:
            for index in range(self._account_list.count()):
                if self._account_list.item(index).data(Qt.ItemDataRole.UserRole) == uid:
                    row = index
                    break
        self._account_list.setCurrentRow(row)
        # ``setCurrentRow`` may not emit when the row is unchanged; be explicit.
        self._update_controls()

    def _update_controls(self) -> None:
        account = self._selected_account()
        has_account = account is not None
        self._edit_button.setEnabled(has_account)
        self._remove_button.setEnabled(has_account)
        # A disabled account is not synced, not even manually.
        self._sync_button.setEnabled(has_account and self._manager is not None and account.enabled)
        self._cleanup_button.setEnabled(
            has_account
            and account.provider == SyncProvider.NEXTCLOUD
            and self._attachments is not None
        )
        if account is not None:
            last = account.last_sync_at
            if last is None:
                text = self.tr("Never synchronized")
            else:
                text = self.tr("Last sync: {time}").format(
                    time=last.astimezone().strftime("%Y-%m-%d %H:%M")
                )
            if not account.enabled:
                text = self.tr("{text} · sync disabled").format(text=text)
            self._last_sync_label.setText(text)
        else:
            self._last_sync_label.setText("")

    # -- account handlers ----------------------------------------------------

    def _on_add(self) -> None:
        values = AccountDialog.create(self)
        if values is None:
            return
        account = SyncAccount(
            label=values.label,
            provider=values.provider,
            server_url=values.server_url,
            remote_path=values.remote_path or None,
            username=values.username,
            app_password=values.app_password,
        )
        self._store.save(account)
        self._refresh(select_uid=account.uid)

    def _on_edit(self) -> None:
        account = self._selected_account()
        if account is None:
            return
        values = AccountDialog.create(self, account)
        if values is None:
            return
        replaced = SyncAccount(
            uid=account.uid,
            provider=values.provider,
            label=values.label,
            server_url=values.server_url,
            remote_path=values.remote_path or None,
            username=values.username,
            # Never wipe a stored credential just because the field is blank
            # (e.g. when the keyring could not be read).
            app_password=values.app_password or account.app_password,
            enabled=account.enabled,
            last_sync_at=account.last_sync_at,
        )
        self._store.save(replaced)
        self._refresh()

    def _on_remove(self) -> None:
        account = self._selected_account()
        if account is None:
            return
        answer = QMessageBox.question(
            self,
            self.tr("Remove account"),
            self.tr("Really remove the account „{name}“?").format(name=account.display_name),
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._store.delete(account.uid)
            self._refresh()

    def _on_account_item_changed(self, item: QListWidgetItem) -> None:
        """User toggled an account's checkbox: enable/disable and persist it."""
        account = self._store.get(item.data(Qt.ItemDataRole.UserRole))
        if account is None:
            return
        enabled = item.checkState() == Qt.CheckState.Checked
        if enabled == account.enabled:
            return
        account.enabled = enabled
        self._store.save(account)
        self._refresh()
        # The toolbar's "Sync now" state depends on the enabled accounts.
        self.reload_requested.emit()

    def _on_sync(self) -> None:
        account = self._selected_account()
        if account is None or self._manager is None or not account.enabled:
            return
        if account.provider == SyncProvider.GOOGLE:
            QMessageBox.information(
                self,
                self.tr("Not available"),
                self.tr("Google sync is not implemented yet. Please use a Nextcloud account."),
            )
            return
        self._sync_button.setEnabled(False)
        self.sync_account(account)

    def sync_account(self, account: SyncAccount) -> None:
        """Run a sync and refresh the list once it finished."""
        self._manager.trigger_sync(account)
        self._refresh()
        self.reload_requested.emit()

    # -- orphaned attachment files -------------------------------------------

    def _on_cleanup(self) -> None:
        """Delete attachment files on the server that no task references."""
        account = self._selected_account()
        if account is None or self._attachments is None:
            return
        if account.provider != SyncProvider.NEXTCLOUD:
            QMessageBox.information(
                self,
                self.tr("Not available"),
                self.tr("Cleaning up orphaned files is only available for Nextcloud accounts."),
            )
            return

        orphans = self._scan_orphans(account)
        if orphans is None:  # transport error, already reported
            return
        if not orphans:
            QMessageBox.information(
                self,
                self.tr("Nothing to clean up"),
                self.tr("No orphaned files were found on „{name}“.").format(
                    name=account.display_name
                ),
            )
            return

        names = "\n".join(f"• {filename_from_url(url)}" for url in orphans[:15])
        if len(orphans) > 15:
            names += "\n…"
        answer = QMessageBox.question(
            self,
            self.tr("Delete orphaned files"),
            self.tr(
                "{count} file(s) on „{name}“ are not attached to any task any more. "
                "Delete them?\n\n{names}"
            ).format(count=len(orphans), name=account.display_name, names=names),
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        deleted, failed = self._delete_orphans(account, orphans)
        message = self.tr("Deleted {count} file(s) from „{name}“.").format(
            count=deleted, name=account.display_name
        )
        if failed:
            message += "\n\n" + self.tr("{count} file(s) could not be deleted.").format(
                count=len(failed)
            )
        QMessageBox.information(self, self.tr("Cleanup finished"), message)

    def _scan_orphans(self, account: SyncAccount) -> list[str] | None:
        """List the server's unreferenced attachment files (``None`` on error)."""
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        file_store = None
        try:
            file_store = make_file_store(account, self)
            return find_orphans(account, self._attachments, file_store)
        except SyncTransportError as exc:
            QMessageBox.warning(self, self.tr("Cleanup failed"), str(exc))
            return None
        finally:
            QApplication.restoreOverrideCursor()
            if file_store is not None:
                file_store.close()

    def _delete_orphans(self, account: SyncAccount, urls: list[str]) -> tuple[int, list[str]]:
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        file_store = None
        deleted: int = 0
        failed: list[str] = []
        try:
            file_store = make_file_store(account, self)
            for url in urls:
                try:
                    if file_store.delete(url):
                        deleted += 1
                except SyncTransportError as exc:
                    failed.append(f"{url}: {exc}")
        except SyncTransportError as exc:
            failed.append(str(exc))
        finally:
            QApplication.restoreOverrideCursor()
            if file_store is not None:
                file_store.close()
        return deleted, failed

    def _on_sync_finished(self, uid: str, stats: dict) -> None:
        account = self._store.get(uid)
        if account is not None:
            account.last_sync_at = datetime.now(timezone.utc)
            self._store.save(account)
        self._refresh()

    def _on_sync_failed(self, uid: str, message: str) -> None:
        account = self._store.get(uid)
        name = account.display_name if account is not None else uid
        QMessageBox.warning(
            self,
            self.tr("Sync failed"),
            self.tr("Synchronization with „{name}“ failed:\n{message}").format(
                name=name, message=message
            ),
        )

    # -- behavior ------------------------------------------------------------

    def _save_behavior(self) -> None:
        SyncBehavior(
            sync_on_startup=self._startup_check.isChecked(),
            periodic_enabled=self._periodic_check.isChecked(),
            periodic_minutes=int(self._interval_spin.value()),
        ).save()
