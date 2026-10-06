"""Tests for the Nextcloud Tasks integration (URL parsing + auto-create)."""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import ClassVar

import pytest

from todo_snake.sync.accounts import SyncAccount, SyncProvider
from todo_snake.sync.document import SyncDocument
from todo_snake.sync.nextcloud import (
    NextcloudTasksTransport,
    normalize_calendar_name,
    split_calendar_url,
)
from todo_snake.sync.webdav import SyncTransportError


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("tasks", "tasks"),
        ("/remote.php/dav/calendars/alice/tasks/", "tasks"),
        ("https://cloud.example.com/remote.php/dav/calendars/alice/tasks/", "tasks"),
        ("https://dino/apps/tasks/calendars/tasks", "tasks"),
        ("", ""),
        ("https://dino/", ""),
    ],
)
def test_normalize_calendar_name_accepts_any_input(value, expected):
    assert normalize_calendar_name(value) == expected


def test_split_calendar_url_accepts_the_tasks_web_url():
    assert split_calendar_url("https://dino/apps/tasks/calendars/tasks") == (
        "https://dino",
        "tasks",
    )


def test_split_calendar_url_accepts_a_caldav_url():
    assert split_calendar_url(
        "https://cloud.example.com/remote.php/dav/calendars/alice/tasks/"
    ) == ("https://cloud.example.com", "tasks")


def test_split_calendar_url_keeps_a_subpath_server():
    assert split_calendar_url("https://host.example.com/nextcloud/apps/tasks/calendars/tasks") == (
        "https://host.example.com/nextcloud",
        "tasks",
    )


def test_split_calendar_url_bare_name_has_no_base():
    assert split_calendar_url("tasks") == ("", "tasks")


def test_split_calendar_url_strips_index_php():
    assert split_calendar_url("https://host.example.com/index.php/apps/tasks/calendars/tasks") == (
        "https://host.example.com",
        "tasks",
    )


def test_collection_base_strips_index_php_from_the_stored_server(qapp):
    account = SyncAccount(
        provider=SyncProvider.NEXTCLOUD,
        server_url="https://host.example.com/index.php",
        remote_path="tasks",
        username="alice",
    )
    transport = NextcloudTasksTransport(account)
    try:
        assert (
            transport._collection_base()
            == "https://host.example.com/remote.php/dav/calendars/alice/tasks/"
        )
    finally:
        transport._nam.deleteLater()


def test_collection_base_is_built_from_the_name(qapp):
    account = SyncAccount(
        provider=SyncProvider.NEXTCLOUD,
        server_url="https://cloud.example.com",
        remote_path="tasks",
        username="alice",
    )
    transport = NextcloudTasksTransport(account)
    try:
        assert (
            transport._collection_base()
            == "https://cloud.example.com/remote.php/dav/calendars/alice/tasks/"
        )
    finally:
        transport._nam.deleteLater()


def test_collection_base_accepts_a_pasted_web_url(qapp):
    account = SyncAccount(
        provider=SyncProvider.NEXTCLOUD,
        server_url="https://cloud.example.com",
        remote_path="https://dino/apps/tasks/calendars/tasks",
        username="alice",
    )
    transport = NextcloudTasksTransport(account)
    try:
        assert (
            transport._collection_base()
            == "https://cloud.example.com/remote.php/dav/calendars/alice/tasks/"
        )
    finally:
        transport._nam.deleteLater()


def test_collection_base_requires_a_calendar(qapp):
    account = SyncAccount(
        provider=SyncProvider.NEXTCLOUD,
        server_url="https://cloud.example.com",
        username="alice",
    )
    transport = NextcloudTasksTransport(account)
    try:
        with pytest.raises(SyncTransportError):
            transport._collection_base()
    finally:
        transport._nam.deleteLater()


# -- live fake server: a missing calendar must be created --------------------


class _TasksHandler(BaseHTTPRequestHandler):
    calls: ClassVar[list[tuple[str, str]]] = []

    def _send(self, code: int, body: bytes = b"") -> None:
        self.send_response(code)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_REPORT(self):
        type(self).calls.append(("REPORT", self.path))
        self._send(404)

    def do_MKCALENDAR(self):
        type(self).calls.append(("MKCALENDAR", self.path))
        self._send(201)

    def log_message(self, *args):  # keep test output clean
        pass


@pytest.fixture()
def tasks_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _TasksHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    _TasksHandler.calls = []
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_fetch_creates_a_missing_calendar(qapp, tasks_server):
    account = SyncAccount(
        provider=SyncProvider.NEXTCLOUD,
        server_url=tasks_server,
        remote_path="tasks",
        username="alice",
        app_password="t0ps3cret",
    )
    transport = NextcloudTasksTransport(account)
    try:
        result = transport.fetch()
        assert result.found is True
        assert SyncDocument.from_json(result.body.decode()).items == {}
        assert ("MKCALENDAR", "/remote.php/dav/calendars/alice/tasks/") in _TasksHandler.calls
    finally:
        transport._nam.deleteLater()


def test_create_transport_routes_nextcloud_to_tasks(qapp):
    from todo_snake.sync.manager import create_transport

    transport = create_transport(
        SyncAccount(
            provider=SyncProvider.NEXTCLOUD,
            server_url="https://cloud.example.com",
            remote_path="tasks",
            username="alice",
        )
    )
    try:
        assert isinstance(transport, NextcloudTasksTransport)
    finally:
        transport._nam.deleteLater()
