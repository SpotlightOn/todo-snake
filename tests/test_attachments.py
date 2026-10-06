"""Tests for task attachments: storage, service and sync helpers."""

from __future__ import annotations

import pytest

from todo_snake.domain.attachment import MAX_ATTACHMENT_BYTES
from todo_snake.domain.todo import Todo
from todo_snake.persistence.attachments import SqliteAttachmentRepository
from todo_snake.service.attachment_service import AttachmentService, AttachmentTooLargeError
from todo_snake.service.todo_service import TodoService
from todo_snake.sync.accounts import SyncAccount, SyncProvider
from todo_snake.sync.attachments import upload_local_attachments
from todo_snake.sync.document import SyncItem
from todo_snake.sync.file_store import NextcloudFileStore, make_file_store


@pytest.fixture()
def service(tmp_path):
    return AttachmentService(SqliteAttachmentRepository(tmp_path / "todos.db"))


def test_add_list_and_read_bytes(service):
    added = service.add("u-1", "note.txt", b"hello", "text/plain")
    assert added.id is not None
    listed = service.list_for("u-1")
    assert [a.filename for a in listed] == ["note.txt"]
    assert listed[0].size == 5
    assert listed[0].data is None  # listing does not load the bytes
    assert listed[0].has_data is True
    full = service.read(added.id)
    assert full.data == b"hello"
    assert full.has_data is True


def test_attachments_are_scoped_to_their_task(service):
    service.add("u-1", "a.txt", b"a")
    service.add("u-2", "b.txt", b"b")
    assert [a.filename for a in service.list_for("u-1")] == ["a.txt"]


def test_size_cap_is_enforced(service):
    with pytest.raises(AttachmentTooLargeError):
        service.add("u-1", "big.bin", b"x" * (MAX_ATTACHMENT_BYTES + 1))


def test_remove(service):
    added = service.add("u-1", "a.txt", b"a")
    service.remove(added.id)
    assert service.list_for("u-1") == []


def test_deleting_a_todo_purges_its_attachments(tmp_path):
    from todo_snake.persistence.sqlite import SqliteTodoRepository

    repository = SqliteTodoRepository(tmp_path / "todos.db")
    attachments = AttachmentService(SqliteAttachmentRepository(tmp_path / "todos.db"))
    service = TodoService(repository, attachments)

    todo = service.add_todo("Task")
    attachments.add(todo.uid, "a.txt", b"a")
    service.delete_todo(todo.id)
    assert attachments.list_for(todo.uid) == []


def test_sync_remote_urls_adds_and_prunes_link_only_rows(service):
    local = service.add("u-1", "local.txt", b"x")
    service.set_remote_url(local.id, "acc-1", "https://cloud/a/local.txt")
    service.sync_remote_urls(
        "u-1", "acc-1", ("https://cloud/a/local.txt", "https://cloud/b/other.txt")
    )

    rows = {a.any_remote_url: a for a in service.list_for("u-1")}
    assert set(rows) == {"https://cloud/a/local.txt", "https://cloud/b/other.txt"}
    assert rows["https://cloud/b/other.txt"].filename == "other.txt"
    assert rows["https://cloud/b/other.txt"].has_data is False
    assert rows["https://cloud/b/other.txt"].url_for("acc-1") == "https://cloud/b/other.txt"
    # The locally stored file is never dropped.
    assert rows["https://cloud/a/local.txt"].has_data is True
    assert service.read(local.id).data == b"x"

    # A URL the task no longer references drops the link-only row.
    service.sync_remote_urls("u-1", "acc-1", ("https://cloud/a/local.txt",))
    assert [a.any_remote_url for a in service.list_for("u-1")] == ["https://cloud/a/local.txt"]


def test_remote_urls_are_tracked_per_account(service):
    local = service.add("u-1", "shared.txt", b"x")
    service.set_remote_url(local.id, "acc-1", "https://one/files/shared.txt")
    service.set_remote_url(local.id, "acc-2", "https://two/files/shared.txt")

    stored = service.read(local.id)
    assert stored.url_for("acc-1") == "https://one/files/shared.txt"
    assert stored.url_for("acc-2") == "https://two/files/shared.txt"

    # Dropping one account's copy keeps the other one and the local file.
    service.sync_remote_urls("u-1", "acc-1", ())
    remaining = service.list_for("u-1")
    assert len(remaining) == 1
    assert remaining[0].url_for("acc-1") is None
    assert remaining[0].url_for("acc-2") == "https://two/files/shared.txt"
    assert remaining[0].has_data is True


def test_upload_local_attachments_uploads_per_account(service):
    file_store = _RecordingFileStore()
    service.add("u-1", "note.txt", b"hello")

    urls = upload_local_attachments([_todo("u-1")], service, file_store, "acc-1")
    assert urls == {"u-1": ("https://files/u-1/note.txt",)}
    assert file_store.uploads == [("u-1", "note.txt", b"hello")]

    # A second run for the same account reuses the remembered URL.
    urls = upload_local_attachments([_todo("u-1")], service, file_store, "acc-1")
    assert urls == {"u-1": ("https://files/u-1/note.txt",)}
    assert len(file_store.uploads) == 1

    # A different account gets its own upload (the same local file).
    urls = upload_local_attachments([_todo("u-1")], service, file_store, "acc-2")
    assert urls == {"u-1": ("https://files/u-1/note.txt",)}
    assert len(file_store.uploads) == 2


def test_sync_item_roundtrips_attachments_through_json():
    item = SyncItem.from_todo(_todo("u-1"), ("https://x/a", "https://x/b"))
    restored = SyncItem.from_dict(item.to_dict())
    assert restored.attachments == ("https://x/a", "https://x/b")
    minimal = SyncItem.from_dict(
        {
            "uid": "u",
            "title": "t",
            "created_at": item.created_at.isoformat(),
            "updated_at": item.updated_at.isoformat(),
        }
    )
    assert minimal.attachments == ()


def test_make_file_store_only_for_nextcloud():
    assert make_file_store(_account(SyncProvider.WEBDAV)) is None
    assert make_file_store(_account(SyncProvider.CALDAV)) is None
    store = make_file_store(_account(SyncProvider.NEXTCLOUD))
    assert isinstance(store, NextcloudFileStore)


def test_nextcloud_file_store_creates_folders_and_returns_url(monkeypatch):
    store = NextcloudFileStore(_account(SyncProvider.NEXTCLOUD))
    monkeypatch.setattr(store, "_files_root", lambda: "https://cloud/remote.php/dav/files/alice")
    calls: list[tuple[bytes, str]] = []

    def fake_exchange(method, url, body=None):
        calls.append((method, url.toString()))
        return (201, b"")

    monkeypatch.setattr(store._dav, "exchange", fake_exchange)
    url = store.upload("u-1", "a b.txt", b"data")

    assert url == (
        "https://cloud/remote.php/dav/files/alice/Todo%20Snake/Attachments/u-1/a%20b.txt"
    )
    assert [c[0] for c in calls] == [b"MKCOL", b"MKCOL", b"MKCOL", b"PUT"]
    # ``QUrl`` renders the decoded path; the folder chain and file name match.
    assert calls[-1][1] == (
        "https://cloud/remote.php/dav/files/alice/Todo Snake/Attachments/u-1/a b.txt"
    )


# -- helpers -----------------------------------------------------------------


def _todo(uid: str, **overrides):
    values = {"uid": uid, "title": "Task"}
    values.update(overrides)
    return Todo(**values)


def _account(provider: SyncProvider) -> SyncAccount:
    return SyncAccount(
        uid="acc",
        label="Test",
        provider=provider,
        server_url="https://cloud",
        remote_path="",
        username="alice",
        app_password="secret",
    )


class _RecordingFileStore:
    def __init__(self):
        self.uploads: list[tuple[str, str, bytes]] = []

    def upload(self, todo_uid: str, filename: str, data: bytes) -> str:
        self.uploads.append((todo_uid, filename, data))
        return f"https://files/{todo_uid}/{filename}"


def test_migration_from_the_single_remote_url_schema(tmp_path):
    """An existing database (one `remote_url` per file) is upgraded in place."""
    import sqlite3

    db_path = tmp_path / "todos.db"
    connection = sqlite3.connect(db_path)
    connection.executescript(
        """
        CREATE TABLE attachments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            todo_uid TEXT NOT NULL,
            filename TEXT NOT NULL,
            mime TEXT NOT NULL DEFAULT '',
            size INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            data BLOB,
            remote_url TEXT
        );
        """
    )
    connection.execute(
        "INSERT INTO attachments (todo_uid, filename, mime, size, created_at, data, remote_url)"
        " VALUES ('u-1', 'a.txt', 'text/plain', 5, '2026-01-01T00:00:00+00:00', ?, ?)",
        (b"hello", "https://old/files/a.txt"),
    )
    connection.commit()
    connection.close()

    service = AttachmentService(SqliteAttachmentRepository(db_path))
    rows = service.list_for("u-1")
    assert len(rows) == 1
    assert rows[0].remote_urls == {}  # the old URL was not attributable to an account
    assert rows[0].has_data is True
    assert service.read(rows[0].id).data == b"hello"

    connection = sqlite3.connect(db_path)
    columns = {row[1] for row in connection.execute("PRAGMA table_info(attachments)")}
    connection.close()
    assert "remote_url" not in columns
    assert "remote_urls" in columns


def test_removing_a_local_attachment_queues_its_uploaded_copies(service):
    attachment = service.add("u-1", "a.txt", b"x")
    service.set_remote_url(attachment.id, "acc-1", "https://one/files/a.txt")
    service.set_remote_url(attachment.id, "acc-2", "https://two/files/a.txt")

    service.remove(attachment.id)

    assert service.list_for("u-1") == []
    assert [url for _id, url in service.pending_deletions("acc-1")] == ["https://one/files/a.txt"]
    assert [url for _id, url in service.pending_deletions("acc-2")] == ["https://two/files/a.txt"]

    service.drop_deletion(service.pending_deletions("acc-1")[0][0])
    assert service.pending_deletions("acc-1") == []


def test_removing_a_link_only_attachment_is_not_queued(service):
    """A file owned by another client must never be deleted from the server."""
    service.sync_remote_urls("u-1", "acc-1", ("https://other/files/x.txt",))
    link_only = service.list_for("u-1")[0]
    assert link_only.has_data is False

    service.remove(link_only.id)

    assert service.pending_deletions("acc-1") == []


def test_deleting_a_todo_queues_its_uploaded_files(service):
    attachment = service.add("u-1", "a.txt", b"a")
    service.set_remote_url(attachment.id, "acc-1", "https://one/files/a.txt")

    service.delete_for_todo("u-1")

    assert service.list_for("u-1") == []
    assert [url for _id, url in service.pending_deletions("acc-1")] == ["https://one/files/a.txt"]


def test_file_store_deletes_only_its_own_folder(monkeypatch):
    store = NextcloudFileStore(_account(SyncProvider.NEXTCLOUD))
    monkeypatch.setattr(store, "_files_root", lambda: "https://cloud/remote.php/dav/files/alice")
    calls: list[tuple[bytes, str]] = []

    def fake_exchange(method, url, body=None):
        calls.append((method, url.toString()))
        return (204, b"")

    monkeypatch.setattr(store._dav, "exchange", fake_exchange)

    own = "https://cloud/remote.php/dav/files/alice/Todo%20Snake/Attachments/u-1/a.txt"
    assert store.delete(own) is True
    assert calls[0][0] == b"DELETE"
    assert calls[0][1].endswith("Attachments/u-1/a.txt")

    # A file outside the attachment folder is left alone (not ours).
    calls.clear()
    foreign = "https://cloud/remote.php/dav/files/alice/Documents/report.pdf"
    assert store.delete(foreign) is False
    assert calls == []


_PROPFIND_BODY = b"""<?xml version="1.0"?>
<d:multistatus xmlns:d="DAV:">
  <d:response><d:href>/remote.php/dav/files/alice/Todo%20Snake/Attachments/</d:href>
    <d:propstat><d:prop><d:resourcetype><d:collection/></d:resourcetype></d:prop></d:propstat>
  </d:response>
  <d:response><d:href>/remote.php/dav/files/alice/Todo%20Snake/Attachments/u-1/</d:href>
    <d:propstat><d:prop><d:resourcetype><d:collection/></d:resourcetype></d:prop></d:propstat>
  </d:response>
  <d:response><d:href>/remote.php/dav/files/alice/Todo%20Snake/Attachments/u-1/a.txt</d:href>
    <d:propstat><d:prop><d:resourcetype/></d:prop></d:propstat>
  </d:response>
</d:multistatus>
"""


def test_file_store_lists_attachment_files(monkeypatch):
    store = NextcloudFileStore(_account(SyncProvider.NEXTCLOUD))
    monkeypatch.setattr(store, "_files_root", lambda: "https://cloud/remote.php/dav/files/alice")
    monkeypatch.setattr(
        store._dav, "exchange", lambda method, url, body=None, depth=None: (207, _PROPFIND_BODY)
    )

    assert store.list_attachment_files() == [
        "https://cloud/remote.php/dav/files/alice/Todo%20Snake/Attachments/u-1/a.txt"
    ]


def test_file_store_handles_a_missing_attachments_folder(monkeypatch):
    store = NextcloudFileStore(_account(SyncProvider.NEXTCLOUD))
    monkeypatch.setattr(store, "_files_root", lambda: "https://cloud/remote.php/dav/files/alice")
    monkeypatch.setattr(
        store._dav, "exchange", lambda method, url, body=None, depth=None: (404, b"")
    )
    assert store.list_attachment_files() == []


def test_remote_urls_for_account(service):
    one = service.add("u-1", "a.txt", b"a")
    two = service.add("u-2", "b.txt", b"b")
    service.set_remote_url(one.id, "acc-1", "https://one/files/a.txt")
    service.set_remote_url(two.id, "acc-2", "https://two/files/b.txt")

    assert service.remote_urls_for_account("acc-1") == {"https://one/files/a.txt"}
    assert service.remote_urls_for_account("acc-2") == {"https://two/files/b.txt"}
    assert service.remote_urls_for_account("acc-3") == set()


def test_find_orphans_matches_by_decoded_url(service):
    import types

    from todo_snake.sync.attachments import find_orphans

    account = types.SimpleNamespace(uid="acc-1")
    attachment = service.add("u-1", "kept.txt", b"x")
    service.set_remote_url(
        attachment.id, "acc-1", "https://cloud/Todo%20Snake/Attachments/u-1/kept.txt"
    )

    class _Store:
        def list_attachment_files(self):
            return [
                # The server reports the href decoded — it must still match.
                "https://cloud/Todo Snake/Attachments/u-1/kept.txt",
                "https://cloud/Todo%20Snake/Attachments/u-1/orphan.txt",
            ]

    assert find_orphans(account, service, _Store()) == [
        "https://cloud/Todo%20Snake/Attachments/u-1/orphan.txt"
    ]
