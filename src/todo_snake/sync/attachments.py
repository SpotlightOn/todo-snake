"""Attachment <-> sync glue.

Everything that connects the local attachment store with a server lives here:

* **Upload** (before a sync): local files that have no copy on *this* account
  yet are pushed to the account's file store; the resulting URLs go into the
  ``ATTACH`` property of the task.
* **Mirror** (after a sync): the ``ATTACH`` URLs the server reports for *this*
  account become link-only rows, so the UI shows files attached elsewhere.
* **Clean up**: list what actually lives in the attachments folder and report
  the files no task references any more (leftovers from deleted attachments or
  from before deletions were tracked).

Every operation is per account: one file can live on several servers, each task
carrying its own server's URL.
"""

from __future__ import annotations

from urllib.parse import unquote


def upload_local_attachments(
    todos, attachments, file_store, account_uid: str
) -> dict[str, tuple[str, ...]]:
    """Upload every file missing on ``account_uid`` and return this account's URLs.

    Returns ``{todo_uid: (remote_url, ...)}`` for every task that has at least
    one attachment with a URL on this account.
    """
    urls: dict[str, tuple[str, ...]] = {}
    for todo in todos:
        if todo.uid is None:
            continue
        collected: list[str] = []
        for attachment in attachments.list_for(todo.uid, with_data=True):
            known = attachment.url_for(account_uid)
            if known:
                collected.append(known)
                continue
            if attachment.data is None:
                continue
            remote_url = file_store.upload(todo.uid, attachment.filename, attachment.data)
            attachments.set_remote_url(attachment.id, account_uid, remote_url)
            collected.append(remote_url)
        if collected:
            urls[todo.uid] = tuple(collected)
    return urls


def normalize_url(url: str) -> str:
    """Percent-decoded URL, so server hrefs match our stored URLs."""
    return unquote(url.strip()).rstrip("/")


def find_orphans(account, attachments, file_store) -> list[str]:
    """URLs of files below the attachment folder that no attachment references."""
    known = {normalize_url(url) for url in attachments.remote_urls_for_account(account.uid)}
    return [url for url in file_store.list_attachment_files() if normalize_url(url) not in known]


def remove_unreferenced_files(file_store, todo_uids, protected_urls) -> list[str]:
    """Delete the files of given tasks that nothing references any more.

    Runs during every sync as a self-healing step: a file whose local record was
    lost (e.g. deleted before deletions were tracked) would otherwise stay on the
    server forever. Only the tasks' own folders are touched, and ``protected_urls``
    must list every URL we know the account is using — locally recorded uploads
    plus everything the server reported as an ``ATTACH``.
    """
    protected = {normalize_url(url) for url in protected_urls}
    removed: list[str] = []
    for todo_uid in todo_uids:
        for url in file_store.files_of_task(todo_uid):
            if normalize_url(url) in protected:
                continue
            if file_store.delete(url):
                removed.append(url)
    return removed
