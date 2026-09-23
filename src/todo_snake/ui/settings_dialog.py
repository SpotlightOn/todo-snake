"""Settings dialog: manage sync accounts and sync behavior."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from todo_snake.sync.accounts import AccountStore, SyncAccount, SyncProvider
from todo_snake.sync.behavior import SyncBehavior
from todo_snake.sync.webdav import SyncTransportError, validate_server_url


@dataclass(frozen=True)
class AccountFormData:
    label: str
    provider: str
    server_url: str
    remote_path: str
    username: str
    app_password: str


class SettingsDialog(QDialog):
    """Two tabs: manage sync accounts, and configure sync behavior."""

    reload_requested = Signal()

    def __init__(self, parent=None, account_store: AccountStore | None = None, sync_manager=None):
        super().__init__(parent)
        self._store = account_store if account_store is not None else AccountStore()
        self._manager = sync_manager

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

        self._add_button = QPushButton(self.tr("Add…"), page)
        self._edit_button = QPushButton(self.tr("Edit…"), page)
        self._remove_button = QPushButton(self.tr("Remove"), page)
        self._sync_button = QPushButton(self.tr("Sync now"), page)
        self._add_button.clicked.connect(self._on_add)
        self._edit_button.clicked.connect(self._on_edit)
        self._remove_button.clicked.connect(self._on_remove)
        self._sync_button.clicked.connect(self._on_sync)

        button_column = QVBoxLayout()
        for button in (
            self._add_button,
            self._edit_button,
            self._remove_button,
            self._sync_button,
        ):
            button_column.addWidget(button)
        button_column.addStretch(1)

        top_row = QHBoxLayout()
        top_row.addWidget(self._account_list, 1)
        top_row.addLayout(button_column)

        self._enabled_check = QCheckBox(self.tr("Account enabled"), page)
        self._enabled_check.toggled.connect(self._on_enabled_toggled)
        self._last_sync_label = QLabel("", page)

        bottom = QVBoxLayout()
        bottom.addWidget(self._enabled_check, 0, Qt.AlignmentFlag.AlignLeft)
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
        self._change_check = QCheckBox(self.tr("Synchronize after each change"), page)

        self._startup_check.setChecked(behavior.sync_on_startup)
        self._periodic_check.setChecked(behavior.periodic_enabled)
        self._change_check.setChecked(behavior.sync_on_change)
        self._interval_spin.setEnabled(behavior.periodic_enabled)

        info = QLabel(
            self.tr(
                "Periodic and change-triggered sync will run while the app is open. "
                "Manual sync is always available via “Sync now”."
            ),
            page,
        )
        info.setWordWrap(True)

        self._periodic_check.toggled.connect(self._interval_spin.setEnabled)

        form = QFormLayout()
        form.addRow(self._startup_check)
        form.addRow(self._periodic_check)
        form.addRow(self.tr("Interval:"), self._interval_spin)
        form.addRow(self._change_check)

        layout = QVBoxLayout(page)
        layout.addLayout(form)
        layout.addWidget(info)
        layout.addStretch(1)

        for widget in (
            self._startup_check,
            self._periodic_check,
            self._interval_spin,
            self._change_check,
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

    def _refresh(self) -> None:
        self._account_list.clear()
        for account in self._accounts():
            provider = {
                SyncProvider.NEXTCLOUD: self.tr("Nextcloud"),
                SyncProvider.WEBDAV: self.tr("WebDAV"),
                SyncProvider.CALDAV: self.tr("CalDAV"),
                SyncProvider.GOOGLE: self.tr("Google"),
            }.get(account.provider, account.provider)
            suffix = "" if account.enabled else f" ({self.tr('disabled')})"
            item = QListWidgetItem(f"{account.display_name} — {provider}{suffix}")
            item.setData(Qt.ItemDataRole.UserRole, account.uid)
            self._account_list.addItem(item)
        if self._account_list.count() > 0:
            self._account_list.setCurrentRow(0)
        self._update_controls()

    def _update_controls(self) -> None:
        account = self._selected_account()
        has_account = account is not None
        self._edit_button.setEnabled(has_account)
        self._remove_button.setEnabled(has_account)
        self._sync_button.setEnabled(has_account and self._manager is not None)
        self._enabled_check.setEnabled(has_account)
        if account is not None:
            self._enabled_check.blockSignals(True)
            self._enabled_check.setChecked(account.enabled)
            self._enabled_check.blockSignals(False)
            last = account.last_sync_at
            if last is None:
                text = self.tr("Never synchronized")
            else:
                text = self.tr("Last sync: {time}").format(
                    time=last.astimezone().strftime("%Y-%m-%d %H:%M")
                )
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
        self._refresh()

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
            app_password=values.app_password,
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

    def _on_enabled_toggled(self, enabled: bool) -> None:
        account = self._selected_account()
        if account is None:
            return
        account.enabled = enabled
        self._store.save(account)
        self._refresh()

    def _on_sync(self) -> None:
        account = self._selected_account()
        if account is None or self._manager is None:
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
            sync_on_change=self._change_check.isChecked(),
        ).save()


class AccountDialog(QDialog):
    """Form for adding or editing a sync account."""

    def __init__(self, parent: QWidget | None = None, account: SyncAccount | None = None):
        super().__init__(parent)
        self.setWindowTitle(
            self.tr("Edit account") if account is not None else self.tr("Add account")
        )
        self.setModal(True)
        self.setMinimumWidth(420)

        self._provider_combo = QComboBox(self)
        self._provider_combo.addItem(self.tr("Nextcloud"), SyncProvider.NEXTCLOUD)
        self._provider_combo.addItem(self.tr("WebDAV (generic)"), SyncProvider.WEBDAV)
        self._provider_combo.addItem(
            self.tr("CalDAV (Baïkal, Radicale, …)"), SyncProvider.CALDAV
        )
        google_index = self._provider_combo.count()
        self._provider_combo.addItem(self.tr("Google (not yet)"), SyncProvider.GOOGLE)
        self._provider_combo.model().item(google_index).setEnabled(False)
        self._provider_combo.setCurrentIndex(0)

        self._label_edit = QLineEdit(self)
        self._label_edit.setPlaceholderText(self.tr("e.g. My Nextcloud"))

        self._server_edit = QLineEdit(self)
        self._server_edit.setPlaceholderText("https://cloud.example.com")

        self._path_edit = QLineEdit(self)
        self._path_edit.setPlaceholderText(self.tr("/dav/username"))

        self._username_edit = QLineEdit(self)

        self._password_edit = QLineEdit(self)
        self._password_edit.setEchoMode(QLineEdit.EchoMode.Password)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        self._ok_button: QPushButton = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._ok_button.setText(self.tr("Save"))
        self._ok_button.setEnabled(False)

        if account is not None:
            self._label_edit.setText(account.label)
            self._server_edit.setText(account.server_url or "")
            self._path_edit.setText(account.remote_path or "")
            self._username_edit.setText(account.username or "")
            self._password_edit.setText(account.app_password or "")
            if account.provider in (SyncProvider.WEBDAV, SyncProvider.CALDAV):
                self._provider_combo.setCurrentIndex(
                    self._provider_combo.findData(account.provider)
                )
            elif account.provider == SyncProvider.GOOGLE:
                self._provider_combo.setCurrentIndex(google_index)
                self._provider_combo.model().item(google_index).setEnabled(True)

        self._form = QFormLayout()
        self._form.addRow(self.tr("Type:"), self._provider_combo)
        self._form.addRow(self.tr("Name:"), self._label_edit)
        self._form.addRow(self.tr("Server URL:"), self._server_edit)
        self._form.addRow(self.tr("Path:"), self._path_edit)
        self._form.addRow(self.tr("Username:"), self._username_edit)
        self._form.addRow(self.tr("Password:"), self._password_edit)

        self._hint = QLabel("")
        self._hint.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.addLayout(self._form)
        layout.addWidget(self._hint)
        layout.addWidget(self._buttons)

        for edit in (self._label_edit, self._server_edit, self._username_edit, self._password_edit):
            edit.textChanged.connect(self._update_ok_state)
        self._provider_combo.currentIndexChanged.connect(self._update_ok_state)
        self._provider_combo.currentIndexChanged.connect(self._update_provider_fields)
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)

        self._update_provider_fields()
        self._update_ok_state()

    def accept(self) -> None:
        try:
            validate_server_url(self._server_edit.text().strip())
        except SyncTransportError as exc:
            QMessageBox.warning(self, self.tr("Invalid server URL"), str(exc))
            return
        super().accept()

    @classmethod
    def create(cls, parent: QWidget | None, account: SyncAccount | None = None):
        """Run the dialog; return ``AccountFormData`` or ``None`` when cancelled."""
        dialog = cls(parent, account)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        provider = dialog._provider_combo.currentData()
        if provider not in SyncProvider.SUPPORTED:
            provider = SyncProvider.NEXTCLOUD
        return AccountFormData(
            label=dialog._label_edit.text().strip(),
            provider=provider,
            server_url=dialog._server_edit.text().strip(),
            remote_path=dialog._path_edit.text().strip(),
            username=dialog._username_edit.text().strip(),
            app_password=dialog._password_edit.text().strip(),
        )

    def _update_provider_fields(self) -> None:
        """Show/hide provider-specific fields and adjust labels and hint text."""
        provider = self._provider_combo.currentData()
        is_webdav = provider == SyncProvider.WEBDAV
        is_caldav = provider == SyncProvider.CALDAV

        self._form.setRowVisible(self._path_edit, is_webdav)

        server_label = self._form.labelForField(self._server_edit)
        if server_label is not None:
            server_label.setText(
                self.tr("Calendar URL:") if is_caldav else self.tr("Server URL:")
            )

        password_label = self._form.labelForField(self._password_edit)
        if password_label is not None:
            password_label.setText(
                self.tr("App password:")
                if provider == SyncProvider.NEXTCLOUD
                else self.tr("Password:")
            )

        if is_caldav:
            self._hint.setText(
                self.tr(
                    "CalDAV (Baïkal, Radicale, Nextcloud Tasks, fruux, Vikunja). "
                    "Paste the full calendar collection URL, e.g. "
                    "“https://cloud.example.com/remote.php/dav/calendars/alice/tasks/”. "
                    "Every task is stored there as a VTODO."
                )
            )
        elif is_webdav:
            self._hint.setText(
                self.tr(
                    "Generic WebDAV server (rclone, Apache mod_dav, ownCloud, …). "
                    "“Path” is the base folder on the server where Todo Snake "
                    "creates its “todo-snake” directory, e.g. “/dav/alice”. "
                    "Leave it empty to use the server root."
                )
            )
        else:
            self._hint.setText(
                self.tr(
                    "Nextcloud app passwords are created in the Nextcloud web UI "
                    "under Personal settings → Security."
                )
            )

    def _update_ok_state(self) -> None:
        provider = self._provider_combo.currentData()
        if provider == SyncProvider.GOOGLE:
            self._ok_button.setEnabled(False)
            return
        enabled = all(
            (
                bool(self._label_edit.text().strip()),
                bool(self._server_edit.text().strip()),
                bool(self._username_edit.text().strip()),
                bool(self._password_edit.text()),
            )
        )
        self._ok_button.setEnabled(enabled)
