"""Settings dialog: manage sync accounts and sync behavior."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
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
from todo_snake.sync.document import SyncDocument
from todo_snake.sync.login_flow import NextcloudLoginFlow
from todo_snake.sync.manager import create_transport
from todo_snake.sync.nextcloud import split_calendar_url
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
        self._provider_combo.addItem(self.tr("CalDAV (Baïkal, Radicale, …)"), SyncProvider.CALDAV)
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

        self._calendar_edit = QLineEdit(self)
        self._calendar_edit.setPlaceholderText(
            "https://cloud.example.com/apps/tasks/calendars/tasks"
        )

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
            self._calendar_edit.setText(account.remote_path or "")
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
        self._form.addRow(self.tr("Calendar:"), self._calendar_edit)
        self._form.addRow(self.tr("Path:"), self._path_edit)
        self._form.addRow(self.tr("Username:"), self._username_edit)
        self._form.addRow(self.tr("Password:"), self._password_edit)

        self._hint = QLabel("")
        self._hint.setWordWrap(True)

        self._connect_button = QPushButton(self.tr("Connect to Nextcloud…"), self)
        self._connect_button.clicked.connect(self._on_connect)
        self._connect_status = QLabel("")
        self._connect_status.setWordWrap(True)
        self._connect_status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._test_button = QPushButton(self.tr("Test connection"), self)
        self._test_button.clicked.connect(self._on_test_connection)
        self._flow: NextcloudLoginFlow | None = None

        layout = QVBoxLayout(self)
        layout.addLayout(self._form)
        layout.addWidget(self._connect_button)
        layout.addWidget(self._connect_status)
        layout.addWidget(self._test_button)
        layout.addWidget(self._hint)
        layout.addWidget(self._buttons)

        for edit in (
            self._label_edit,
            self._server_edit,
            self._path_edit,
            self._calendar_edit,
            self._username_edit,
            self._password_edit,
        ):
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
        return dialog.form_data()

    def form_data(self) -> AccountFormData:
        """Turn the form into account data.

        Single source of truth: used by *Save* and by the connection test, so
        both always use exactly the same values.
        """
        provider = self._provider_combo.currentData()
        if provider not in SyncProvider.SUPPORTED:
            provider = SyncProvider.NEXTCLOUD
        remote_path = (
            self._calendar_edit.text().strip()
            if provider == SyncProvider.NEXTCLOUD
            else self._path_edit.text().strip()
        )
        return AccountFormData(
            label=self._label_edit.text().strip(),
            provider=provider,
            server_url=self._server_edit.text().strip(),
            remote_path=remote_path,
            username=self._username_edit.text().strip(),
            app_password=self._password_edit.text().strip(),
        )

    def _update_provider_fields(self) -> None:
        """Show/hide provider-specific fields and adjust labels and hint text."""
        provider = self._provider_combo.currentData()
        is_webdav = provider == SyncProvider.WEBDAV
        is_caldav = provider == SyncProvider.CALDAV
        is_nextcloud = provider == SyncProvider.NEXTCLOUD

        self._form.setRowVisible(self._path_edit, is_webdav)
        self._form.setRowVisible(self._server_edit, not is_nextcloud)
        self._form.setRowVisible(self._calendar_edit, is_nextcloud)
        # Nextcloud credentials are provisioned by the browser login flow, so the
        # manual username/app-password rows are not offered for that provider.
        self._form.setRowVisible(self._username_edit, not is_nextcloud)
        self._form.setRowVisible(self._password_edit, not is_nextcloud)
        self._connect_button.setVisible(is_nextcloud)
        self._connect_status.setVisible(is_nextcloud)
        self._test_button.setVisible(provider != SyncProvider.GOOGLE)
        if not is_nextcloud:
            self._cancel_flow()
            self._connect_status.clear()

        server_label = self._form.labelForField(self._server_edit)
        if server_label is not None:
            server_label.setText(self.tr("Calendar URL:") if is_caldav else self.tr("Server URL:"))

        calendar_label = self._form.labelForField(self._calendar_edit)
        if calendar_label is not None:
            calendar_label.setText(self.tr("Calendar URL:"))

        password_label = self._form.labelForField(self._password_edit)
        if password_label is not None:
            password_label.setText(
                self.tr("App password:") if is_nextcloud else self.tr("Password:")
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
                    "Paste the full calendar URL — the Tasks web URL "
                    "(…/apps/tasks/calendars/tasks) or the CalDAV URL — and sign in "
                    "with your browser. Todo Snake creates a device-specific "
                    "password and creates the calendar if it does not exist yet."
                )
            )

    # -- Nextcloud browser login (Login Flow v2) -----------------------------

    def _on_connect(self) -> None:
        """Start Login Flow v2 for the calendar URL the user entered."""
        base, name = split_calendar_url(self._calendar_edit.text())
        if not base:
            # Editing an existing account: the field holds the calendar *name*
            # only, so take the server from the stored account.
            base = self._server_edit.text().strip().rstrip("/")
        if not base or not name:
            QMessageBox.warning(
                self,
                self.tr("Invalid calendar URL"),
                self.tr(
                    "Enter the full calendar URL, e.g. "
                    "“https://cloud.example.com/apps/tasks/calendars/tasks”."
                ),
            )
            return
        try:
            validate_server_url(base)
        except SyncTransportError as exc:
            QMessageBox.warning(self, self.tr("Invalid server URL"), str(exc))
            return
        self._server_edit.setText(base)
        self._calendar_edit.setText(name)
        self._cancel_flow()
        self._connect_button.setEnabled(False)
        self._connect_status.setText(self.tr("Waiting for the browser…"))
        self._flow = NextcloudLoginFlow(base, self)
        self._flow.login_url_ready.connect(self._open_login_url)
        self._flow.credentials_ready.connect(self._on_credentials)
        self._flow.failed.connect(self._on_login_failed)
        self._flow.start()

    def _open_login_url(self, url: str) -> None:
        if not QDesktopServices.openUrl(QUrl(url)):
            self._connect_status.setText(
                self.tr("Open this URL in your browser:\n{url}").format(url=url)
            )

    def _on_credentials(self, server: str, login_name: str, app_password: str) -> None:
        self._server_edit.setText(server)
        self._username_edit.setText(login_name)
        self._password_edit.setText(app_password)
        if not self._label_edit.text().strip():
            self._label_edit.setText(server)
        self._connect_button.setEnabled(True)
        self._connect_status.setText(self.tr("Connected. Review the account and save."))
        self._update_ok_state()

    def _on_login_failed(self, message: str) -> None:
        self._connect_button.setEnabled(True)
        self._connect_status.clear()
        QMessageBox.warning(self, self.tr("Nextcloud login failed"), message)

    # -- connection test -----------------------------------------------------

    def _on_test_connection(self) -> None:
        """Do a real fetch with the entered values and report the outcome.

        Uses :meth:`form_data`, the same source as *Save*, so the test can never
        succeed on different values than the ones being stored."""
        data = self.form_data()
        account = SyncAccount(
            provider=data.provider,
            label=data.label or "test",
            server_url=data.server_url,
            remote_path=data.remote_path or None,
            username=data.username,
            app_password=data.app_password,
        )
        self._connect_status.setText(self.tr("Testing…"))
        try:
            transport = create_transport(account, self)
            result = transport.fetch()
        except SyncTransportError as exc:
            self._connect_status.setText(self.tr("Connection failed: {error}").format(error=exc))
            return
        except NotImplementedError as exc:
            self._connect_status.setText(str(exc))
            return
        count = 0
        if result.found and result.body:
            try:
                count = len(SyncDocument.from_json(result.body.decode("utf-8")).items)
            except ValueError:
                count = 0
        self._connect_status.setText(
            self.tr("Connection OK — {count} tasks found.").format(count=count)
        )

    def _cancel_flow(self) -> None:
        if self._flow is not None:
            self._flow.cancel()
            self._flow = None
            self._connect_button.setEnabled(True)

    def done(self, result: int) -> None:
        self._cancel_flow()
        super().done(result)

    def _update_ok_state(self) -> None:
        provider = self._provider_combo.currentData()
        if provider == SyncProvider.GOOGLE:
            self._ok_button.setEnabled(False)
            return
        needs_calendar = provider == SyncProvider.NEXTCLOUD
        enabled = all(
            (
                bool(self._label_edit.text().strip()),
                bool(self._server_edit.text().strip()),
                bool(self._username_edit.text().strip()),
                bool(self._password_edit.text()),
                not needs_calendar or bool(self._calendar_edit.text().strip()),
            )
        )
        self._ok_button.setEnabled(enabled)
