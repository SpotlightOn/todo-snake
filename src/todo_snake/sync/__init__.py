"""Sync layer — cloud providers, documents and the sync cycle.

Layout, from pure to Qt-bound:

* ``accounts``    — the account model (provider, server, credentials).
* ``document``    — the device-agnostic sync document + last-write-wins merge.
* ``icalendar``   — a minimal RFC 5545 (VTODO) reader/writer.
* ``journal``/``state`` — persisted tombstones and the known server resources.
* ``attachments`` — attachment <-> server glue (upload, mirror, orphan scan).
* ``engine``      — the cycle itself: fetch, merge, apply, upload. No Qt.
* ``transports``  — provider -> concrete transport.
* ``webdav``/``caldav``/``nextcloud``/``file_store`` — the I/O (QtNetwork).
* ``login_flow``/``credentials``/``behavior``/``account_store`` — settings.
* ``manager``     — Qt adapter that turns engine results into signals.

Providers: ``Nextcloud`` syncs with the Tasks app (CalDAV/VTODO), ``CalDAV``
with any other CalDAV server, ``WebDAV`` stores a JSON document on a plain
WebDAV server, ``Google`` is scaffolded but not implemented.
"""
