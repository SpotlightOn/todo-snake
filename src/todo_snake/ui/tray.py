"""System tray integration with SNI-aware activation.

Qt on Linux/Wayland registers the tray through the StatusNotifierItem (SNI)
protocol. If the app starts before the system tray host
(``org.kde.StatusNotifierWatcher`` / the Plasma "StatusNotifierHost") is
running, Qt silently fails to register and the icon never appears
(see lxqt-qtplugin#107, kde bug 425315). ``isSystemTrayAvailable()`` is often
``True`` here even though no tray is usable, so it must **not** be the gate.

We therefore *postpone* ``setVisible(True)`` until the tray host is actually
reachable and retry on a timer, instead of trusting desktop state at startup.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from todo_snake.config import APP_DISPLAY_NAME

if TYPE_CHECKING:
    from todo_snake.ui.main_window import MainWindow


class TrayIcon(QSystemTrayIcon):
    """Owns the tray menu and forwards user intent to the main window.

    Activation is SNI-aware: the icon is only made visible once the tray host
    is confirmed available, retried on a timer. This avoids the Wayland
    startup race where the icon (and implicitly the window) never appears.
    """

    def __init__(
        self,
        window: MainWindow,
        *,
        retry_interval_ms: int = 1000,
        max_retries: int = 30,
        parent=None,
    ):
        super().__init__(window.windowIcon(), parent)
        self._window = window
        self._retries_left = max(1, int(max_retries))
        self.setToolTip(APP_DISPLAY_NAME)

        self._action_toggle = QAction(self.tr("Hide"), self)
        menu = QMenu()
        menu.addAction(self.tr("New task…"), window.new_task_from_tray)
        self._action_sync = QAction(self.tr("Sync now"), self)
        self._action_sync.triggered.connect(window.sync_all)
        menu.addAction(self._action_sync)
        menu.addAction(self._action_toggle)
        menu.addSeparator()
        menu.addAction(self.tr("Quit"), window.quit_app)
        self.setContextMenu(menu)

        self._action_toggle.triggered.connect(self.toggle_window)
        self.activated.connect(self._on_activated)
        window.visibility_changed.connect(self._on_window_visibility_changed)

        self._retry_timer = QTimer(self)
        self._retry_timer.setInterval(retry_interval_ms)
        self._retry_timer.timeout.connect(self._maybe_activate)
        self._retry_timer.start()
        self._maybe_activate()

    # -- activation -----------------------------------------------------------

    def _maybe_activate(self) -> None:
        """Become visible once the tray host is usable; give up gracefully."""
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.setVisible(True)
            self._retry_timer.stop()
            return
        self._retries_left -= 1
        if self._retries_left <= 0:
            self._retry_timer.stop()

    def toggle_window(self) -> None:
        if self._window.isVisible() and not self._window.isMinimized():
            self._window.hide()
        else:
            self._window.show_window()

    def show_notification(self, title: str, body: str) -> None:
        if self.isVisible() and self.supportsMessages():
            self.showMessage(
                title,
                body,
                QSystemTrayIcon.MessageIcon.Information,
                6000,
            )

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.toggle_window()

    def _on_window_visibility_changed(self, visible: bool) -> None:
        self._action_toggle.setText(self.tr("Hide") if visible else self.tr("Show"))
