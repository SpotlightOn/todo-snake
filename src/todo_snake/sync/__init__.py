"""Sync layer — cloud providers, documents and the sync manager.

Scope for this iteration:
* ``Nextcloud`` syncs with the Nextcloud **Tasks app** (CalDAV/VTODO): the app
  signs in via browser *Login Flow v2* and discovers the task calendar itself.
* ``WebDAV`` is a generic provider for any plain WebDAV server (rclone,
  Apache ``mod_dav``, ownCloud, …) using a configurable base path; it stores the
  sync state as a JSON document.
* ``CalDAV`` syncs todos as VTODO resources against any CalDAV server
  (Baïkal/sabre/dav, Radicale, fruux, Vikunja).
* ``Google`` is scaffolded in the account model but intentionally not
  functional yet: it requires an OAuth 2.0 desktop flow and a Google Cloud
  project, which we add as a follow-up.
"""

from .accounts import AccountStore, SyncAccount, SyncProvider
from .caldav import CalDAVTransport
from .document import MergePlan, SyncDocument, SyncItem, merge_documents
from .manager import SyncManager
from .webdav import WebDAVTransport

__all__ = [
    "AccountStore",
    "CalDAVTransport",
    "MergePlan",
    "SyncAccount",
    "SyncDocument",
    "SyncItem",
    "SyncManager",
    "SyncProvider",
    "WebDAVTransport",
    "merge_documents",
]
