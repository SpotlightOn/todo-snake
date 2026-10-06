"""Credential storage for sync accounts.

Prefers the OS keyring (freedesktop Secret Service via ``secret-tool``) so app
passwords are not kept in a plain settings file. Falls back to ``QSettings`` when
no keyring is reachable, so the app still works on headless/minimal systems.

Set ``TODO_SNAKE_NO_KEYRING=1`` to force the fallback (used by the tests).
"""

from __future__ import annotations

import os
import shutil
import subprocess

from PySide6.QtCore import QSettings

_SERVICE = "todo-snake"
_ENV_DISABLE = "TODO_SNAKE_NO_KEYRING"
_TIMEOUT_S = 5


class QSettingsBackend:
    """Plain ``QSettings`` fallback (same key the store used before)."""

    def __init__(self, settings: QSettings):
        self._settings = settings

    @staticmethod
    def _key(uid: str) -> str:
        return f"sync/accounts/{uid}/app_password"

    def get(self, uid: str) -> str | None:
        return self._settings.value(self._key(uid)) or None

    def set(self, uid: str, password: str) -> bool:
        self._settings.setValue(self._key(uid), password)
        self._settings.sync()
        return True

    def delete(self, uid: str) -> None:
        self._settings.remove(self._key(uid))
        self._settings.sync()


class SecretToolBackend:
    """Secret Service backend using ``secret-tool`` (libsecret)."""

    def get(self, uid: str) -> str | None:
        try:
            result = subprocess.run(
                ["secret-tool", "lookup", "service", _SERVICE, "account", uid],
                capture_output=True,
                text=True,
                timeout=_TIMEOUT_S,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return result.stdout.strip() or None

    def set(self, uid: str, password: str) -> bool:
        try:
            result = subprocess.run(
                [
                    "secret-tool",
                    "store",
                    "--label",
                    f"Todo Snake: {uid}",
                    "service",
                    _SERVICE,
                    "account",
                    uid,
                ],
                input=password,
                text=True,
                timeout=_TIMEOUT_S,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        # Verify it is actually retrievable — a present-but-locked keyring would
        # otherwise silently swallow the secret.
        return result.returncode == 0 and self.get(uid) == password

    def delete(self, uid: str) -> None:
        try:
            subprocess.run(
                ["secret-tool", "clear", "service", _SERVICE, "account", uid],
                timeout=_TIMEOUT_S,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            pass


class Credentials:
    """Reads/writes the app password for a sync account.

    Uses the OS keyring when it works, but **always falls back to
    ``QSettings``** on read and when a keyring write does not verify, so a
    missing/locked keyring can never lock a user out of their sync.
    """

    def __init__(self, settings: QSettings, backend=None):
        self._settings_backend = QSettingsBackend(settings)
        self._backend = backend if backend is not None else _default_backend(settings)
        # A distinct keyring backend (not the plain QSettings fallback).
        self._use_keyring = not isinstance(self._backend, QSettingsBackend)

    def get(self, uid: str) -> str | None:
        value = self._backend.get(uid)
        if value is None and self._use_keyring:
            value = self._settings_backend.get(uid)
        return value

    def set(self, uid: str, password: str | None) -> None:
        if not password:
            self.delete(uid)
            return
        if bool(self._backend.set(uid, password)):
            if self._use_keyring:
                # Stored securely; drop the plaintext copy.
                self._settings_backend.delete(uid)
        else:
            self._settings_backend.set(uid, password)

    def delete(self, uid: str) -> None:
        self._backend.delete(uid)
        if self._use_keyring:
            self._settings_backend.delete(uid)


def _default_backend(settings: QSettings):
    if (
        not os.environ.get(_ENV_DISABLE)
        and shutil.which("secret-tool")
        and os.environ.get("DBUS_SESSION_BUS_ADDRESS")
    ):
        return SecretToolBackend()
    return QSettingsBackend(settings)
