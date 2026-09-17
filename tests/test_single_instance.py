"""Tests for the single-instance guard (offscreen, no display needed)."""

from __future__ import annotations

import gc
import uuid

from PySide6.QtCore import QLockFile, QObject
from PySide6.QtWidgets import QApplication

from snake_todo.single_instance import SingleInstanceGuard


def _socket_name() -> str:
    return f"snake-todo-test-{uuid.uuid4().hex}"


def test_second_instance_is_rejected(qapp, tmp_path):
    lock = tmp_path / "app.lock"
    name = _socket_name()

    primary = SingleInstanceGuard(lock, name)
    assert primary.start() is True

    secondary = SingleInstanceGuard(lock, name)
    assert secondary.start() is False
    QApplication.instance().processEvents()


def test_lock_survives_when_reference_is_dropped(qapp, tmp_path):
    """The lock must stay held while the guard is owned by the app (parent +
    attribute), even if the caller drops its local reference — guards against
    duplicate launches after ``build_application`` returns."""
    lock = tmp_path / "app.lock"
    name = _socket_name()

    primary = SingleInstanceGuard(lock, name, parent=QApplication.instance())
    QApplication.instance()._snake_todo_guard = primary
    assert primary.start() is True
    del primary
    gc.collect()
    QApplication.instance().processEvents()

    rival = SingleInstanceGuard(lock, name)
    assert rival.start() is False
    QApplication.instance().processEvents()


def test_qlockfile_is_released_on_full_destruction(qapp, tmp_path):
    """Sanity check: once every reference and the app parent are gone, the
    lock file really is free again (otherwise the guard would be useless)."""
    lock = tmp_path / "app.lock"
    name = _socket_name()

    primary = SingleInstanceGuard(lock, name)
    assert primary.start() is True
    del primary
    gc.collect()
    QApplication.instance().processEvents()

    raw = QLockFile(str(lock))
    assert raw.tryLock(100) is True


def test_secondary_triggers_show_requested(qapp, tmp_path):
    lock = tmp_path / "app.lock"
    name = _socket_name()
    fired: list[bool] = []

    primary = SingleInstanceGuard(lock, name)
    primary.show_requested.connect(lambda: fired.append(True))
    assert primary.start() is True

    secondary = SingleInstanceGuard(lock, name)
    assert secondary.start() is False
    QApplication.instance().processEvents()
    assert fired
    QApplication.instance().processEvents()


def test_stale_lock_is_reclaimed(qapp, tmp_path):
    lock = tmp_path / "app.lock"
    name = _socket_name()

    primary = SingleInstanceGuard(lock, name)
    assert primary.start() is True

    # Simulate a crash: lock and socket file gone, nobody is running.
    lock.unlink(missing_ok=True)

    next_user = SingleInstanceGuard(lock, name)
    assert next_user.start() is True
    QApplication.instance().processEvents()