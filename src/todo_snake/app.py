"""Composition root: wire storage, service and UI together.

This is the only place that knows about concrete implementations. The
storage backend can be selected per environment, e.g.::

    TODO_SNAKE_BACKEND=postgres python -m todo_snake

Once a PostgreSQL backend exists in ``persistence.factory``.

Exactly one process may own the app: ``build_application`` enforces a
single-instance guard (local unix socket). A second launch does not open
another window or touch the database — it signals the running instance to
raise its window and exits.
"""

from __future__ import annotations

import os
import sys

from PySide6.QtWidgets import QApplication

from todo_snake.config import (
    APP_DISPLAY_NAME,
    APP_NAME,
    APP_VERSION,
    ORG_NAME,
    default_db_path,
)
from todo_snake.i18n import load_translator
from todo_snake.persistence import create_repository
from todo_snake.service import TodoService
from todo_snake.single_instance import SingleInstanceGuard
from todo_snake.sync.accounts import AccountStore
from todo_snake.sync.journal import SyncJournal
from todo_snake.sync.manager import SyncManager
from todo_snake.ui.icons import create_todo_icon
from todo_snake.ui.main_window import MainWindow
from todo_snake.ui.tray import TrayIcon

_DEFAULT_BACKEND = "sqlite"


def build_application(
    argv: list[str] | None = None,
    *,
    single_instance: bool = True,
):
    """Create the fully wired Qt application (for tests and the real entry).

    Returns ``(app, guard, window, tray, primary)``. When ``single_instance``
    is on and another process already owns the app, ``primary`` is ``False``
    and ``window``/``tray`` are ``None``. Callers must keep ``guard`` alive
    for the whole app lifetime — it owns the lock that prevents duplicate
    instances.
    """
    app = QApplication.instance() or QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_DISPLAY_NAME)
    app.setOrganizationName(ORG_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setWindowIcon(create_todo_icon())
    # The window hides to the tray instead of quitting on close.
    app.setQuitOnLastWindowClosed(False)
    load_translator(app)

    guard = None
    backend = os.environ.get("TODO_SNAKE_BACKEND", _DEFAULT_BACKEND)
    db_path = default_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if single_instance:
        lock_path = db_path.parent / f"{APP_NAME}.lock"
        guard = SingleInstanceGuard(lock_path, socket_name=f"{APP_NAME}-{os.getuid()}", parent=app)
        if not guard.start():
            return app, guard, None, None, False
        # Keep the guard (and with it the lock) alive for the app's lifetime,
        # even if a caller drops the returned reference.
        app._todo_snake_guard = guard

    repository = create_repository(backend, db_path)
    service = TodoService(repository)
    sync_manager = SyncManager(service, SyncJournal(db_path), parent=app)
    account_store = AccountStore()

    window = MainWindow(
        service,
        tray_enabled=True,
        sync_manager=sync_manager,
        account_store=account_store,
    )
    tray = TrayIcon(window)
    if guard is not None:
        guard.show_requested.connect(window.show_window)
    window.show()
    return app, guard, window, tray, True


def main(argv: list[str] | None = None) -> int:
    app, _guard, _window, _tray, primary = build_application(argv)
    if not primary:
        return 0
    # ``_guard`` stays referenced here, keeping the instance lock held for the
    # entire event-loop lifetime.
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
