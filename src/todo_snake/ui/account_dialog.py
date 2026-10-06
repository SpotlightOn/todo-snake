"""Form for adding or editing a sync account."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from todo_snake.sync.accounts import SyncAccount, SyncProvider
from todo_snake.sync.document import SyncDocument
from todo_snake.sync.login_flow import NextcloudLoginFlow
from todo_snake.sync.nextcloud import split_calendar_url
from todo_snake.sync.transports import create_transport
from todo_snake.sync.webdav import SyncTransportError, validate_server_url


@dataclass(frozen=True)
class AccountFormData:
    label: str
    provider: str
    server_url: str
    remote_path: str
    username: str
    app_password: str


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
