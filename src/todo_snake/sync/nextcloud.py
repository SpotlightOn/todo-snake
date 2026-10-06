"""Nextcloud Tasks support (CalDAV / VTODO).

The Nextcloud provider syncs with the **Nextcloud Tasks app**: tasks are
``VTODO`` resources in one task calendar.

The user only provides the **full calendar URL** — either the Tasks web URL
(``https://cloud.example.com/apps/tasks/calendars/tasks``) or the CalDAV URL
(``https://cloud.example.com/remote.php/dav/calendars/alice/tasks/``). From it
the base server URL (for the browser login, Login Flow v2) and the calendar
name are derived, so a single field is enough. A calendar that does not exist
yet is created on the first sync.
"""

from __future__ import annotations

from urllib.parse import quote, unquote

from PySide6.QtCore import QUrl

from todo_snake.sync.caldav import (
    _CALENDAR_QUERY,
    CalDAVTransport,
    parse_multistatus_resources,
)
from todo_snake.sync.document import SyncDocument
from todo_snake.sync.webdav import (
    FetchResult,
    SyncTransportError,
    clean_server_url,
    validate_server_url,
)

_DAV_NS = "DAV:"
_CALDAV_NS = "urn:ietf:params:xml:ns:caldav"

# URL markers after which the calendar name follows / before which the server
# base ends.
_CALENDAR_MARKERS = ("/remote.php/", "/apps/tasks/calendars/")


_MKCALENDAR_TEMPLATE = (
    '<?xml version="1.0" encoding="utf-8" ?>'
    f'<c:mkcalendar xmlns:d="{_DAV_NS}" xmlns:c="{_CALDAV_NS}">'
    "<d:set><d:prop><d:displayname>{name}</d:displayname>"
    '<c:supported-calendar-component-set><c:comp name="VTODO"/>'
    "</c:supported-calendar-component-set>"
    "</d:prop></d:set></c:mkcalendar>"
)


def normalize_calendar_name(value: str) -> str:
    """Extract the calendar collection name from any accepted input."""
    raw = (value or "").strip().rstrip("/")
    if not raw:
        return ""
    if "://" in raw:
        raw = raw.split("://", 1)[1]
        raw = raw.split("/", 1)[1] if "/" in raw else ""
    return unquote(raw.rsplit("/", 1)[-1]) if raw else ""


def split_calendar_url(value: str) -> tuple[str, str]:
    """Split what the user entered into ``(base_server_url, calendar_name)``.

    Accepts the Tasks web URL (``…/apps/tasks/calendars/<name>``), a CalDAV URL
    (``…/remote.php/dav/calendars/<user>/<name>/``) or a bare name (base is then
    empty and must come from elsewhere).
    """
    raw = (value or "").strip()
    if "://" not in raw:
        return "", normalize_calendar_name(raw)
    for marker in _CALENDAR_MARKERS:
        index = raw.find(marker)
        if index == -1:
            continue
        base = clean_server_url(raw[:index])
        rest = raw[index + len(marker) :].strip("/")
        name = unquote(rest.split("/")[-1]) if rest else ""
        return base, name
    parsed = QUrl(raw)
    base = clean_server_url(f"{parsed.scheme()}://{parsed.authority()}")
    return base, normalize_calendar_name(raw)


class NextcloudTasksTransport(CalDAVTransport):
    """CalDAV/VTODO transport against one Nextcloud task calendar.

    The calendar is given by name in ``remote_path`` and is created on the first
    sync when it does not exist yet.
    """

    def __init__(self, account, parent=None, state=None):
        super().__init__(account, parent, state)

    def _collection_base(self) -> str:
        name = normalize_calendar_name(self._account.remote_path or "")
        if not name:
            raise SyncTransportError("No Nextcloud tasks calendar configured.")
        base = clean_server_url(self._account.server_url or "")
        if not base:
            raise SyncTransportError("No server URL configured.")
        validate_server_url(base)
        user = (self._account.username or "").strip()
        if not user:
            raise SyncTransportError("No username configured.")
        return f"{base}/remote.php/dav/calendars/{quote(user, safe='')}/{quote(name, safe='')}/"

    def fetch(self) -> FetchResult:
        status, body = self._dav.exchange(
            b"REPORT",
            QUrl(self._collection_base()),
            _CALENDAR_QUERY.encode("utf-8"),
            content_type="application/xml; charset=utf-8",
            depth="1",
        )
        if status == 404:
            # The chosen calendar does not exist yet: create it, start empty.
            self._create_calendar()
            self._record_state({})
            self._raw = {}
            document = SyncDocument.empty()
        else:
            self._dav.require_success(status)
            parsed = parse_multistatus_resources(body)
            self._raw = {item.uid: raw for item, _etag, raw in parsed}
            self._etags = {item.uid: etag for item, etag, _raw in parsed}
            self._record_state({item.uid: etag for item, etag, _raw in parsed})
            document = SyncDocument(items={item.uid: item for item, _etag, _raw in parsed})
        self._fetched = dict(document.items)
        return FetchResult(True, document.to_json().encode("utf-8"))

    def _create_calendar(self) -> None:
        body = _MKCALENDAR_TEMPLATE.format(
            name=normalize_calendar_name(self._account.remote_path or "")
        ).encode("utf-8")
        status, _ = self._dav.exchange(
            b"MKCALENDAR",
            QUrl(self._collection_base()),
            body,
            content_type="application/xml; charset=utf-8",
        )
        # 201: created; 405/409: already exists (race).
        if status not in (200, 201, 405, 409):
            self._dav.require_success(status)
