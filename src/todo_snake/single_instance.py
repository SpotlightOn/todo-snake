"""Single-instance enforcement.

Ownership is decided by a ``QLockFile`` — robust against stale locks left by
crashed processes and immune to ``QLocalServer``'s "auto-remove the existing
socket file and rebind" behaviour, which otherwise lets two processes both
believe they are the sole listener. The owner additionally binds a
``QLocalServer`` so a second launch can ask the running instance to raise its
window (and exit) instead of silently starting a duplicate.
"""

from __future__ import annotations

from PySide6.QtCore import QLockFile, QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


class SingleInstanceGuard(QObject):
    """Exactly one process per ``lock_path`` may own the app.

    Emits ``show_requested`` when another process asks the running instance to
    appear. ``lock_path`` and ``socket_name`` must match across processes that
    should share the instance (derived from the same data/application key).
    """

    show_requested = Signal()

    def __init__(self, lock_path, socket_name, parent=None):
        super().__init__(parent)
        self._lock = QLockFile(str(lock_path))
        # Staleness is decided by the holder's PID, not by age.
        self._lock.setStaleLockTime(0)
        self._socket_name = socket_name
        self._server = QLocalServer(self)
        self._server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)

    def start(self) -> bool:
        """Claim the instance. ``True`` if this process is the primary."""
        if self._lock.tryLock(100):
            self._server.removeServer(self._socket_name)
            if self._server.listen(self._socket_name):
                self._server.newConnection.connect(self._on_new_connection)
                return True
            self._lock.unlock()
        self._request_show()
        return False

    def _on_new_connection(self) -> None:
        connection = self._server.nextPendingConnection()
        connection.readyRead.connect(connection.disconnectFromServer)
        self.show_requested.emit()

    def _request_show(self) -> None:
        # The primary may still be binding its socket: retry briefly.
        for _ in range(10):
            socket = QLocalSocket(self)
            socket.connectToServer(self._socket_name)
            if socket.waitForConnected(200):
                socket.write(b"show")
                socket.flush()
                socket.waitForBytesWritten(200)
                socket.disconnectFromServer()
                return
            socket.disconnectFromServer()
            del socket