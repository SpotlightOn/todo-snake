# Changelog

Notable changes only. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) / [SemVer](https://semver.org/).

## [0.3.1] - 2026-10-09

### Changed

- Relicensed the project from GPL-3.0-or-later to **MIT**.

## [0.3.0] - 2026-10-06

### Added
- **Nextcloud Tasks sync** (`VTODO`): one calendar-URL field, browser login (Login Flow v2, SSO/2FA included), calendar created on demand, both directions.
- Task fields: **status** (open / in progress / done), **start date**, **all-day** due dates, per-task **reminder lead**.
- **Recurring tasks** (daily / weekly / monthly / yearly, `∞` in the list); completing one advances to the next occurrence.
- Toolbar **Sync now** (greyed out without an enabled account); periodic sync optional.
- Sync diagnostics: rotating `sync.log` and a **Test connection** button in the account dialog.
- Lossless VTODO edits: only owned fields are rewritten, foreign properties are kept.
- Conditional writes (`If-Match`) and per-account deletion tracking (UIDs + ETags).
- App passwords in the OS keyring, with a `QSettings` fallback.
- **Attachments** (`ATTACH`): files per task, stored locally (10 MB cap); uploaded to **every** enabled Nextcloud account (each server gets its own copy and its own `ATTACH` URL) and shown as links when they come from another client. A **Files** column shows the count and the attachment list renders 48×48 previews/type icons.
- Sync accounts can be **disabled per account** (checkbox in the account list) without deleting them; disabled accounts are greyed out and skipped by every sync, manual included.
- Removing an attachment (or deleting a task) also **deletes the uploaded file** from every Nextcloud account on the next sync. Every sync additionally **sweeps the task folders** for files nothing references any more, so leftovers from earlier versions clean themselves up.
- **Settings → Sync accounts → “Clean up orphaned files…”** sweeps the whole attachments folder on demand (after a confirmation).

### Changed
- *Nextcloud* now syncs the Tasks calendar; JSON-file sync moved to the generic **WebDAV** provider (CalDAV unchanged).
- Dependency: **PySide6 6.11.2** (Qt 6.11) is now the minimum and the tested version; 6.12+ is excluded until verified.
- Internal restructure (no behaviour change): the sync cycle moved into a **Qt-free engine** (`sync/engine.py`), the transports share one `DavClient`, and the settings/attachment modules were split up. See [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md#the-sync-package).

### Fixed
- Sync failures are visible (red icon, status bar, dialog) and **name the account**.
- Rejected writes show the server's reason instead of a bare "HTTP 400".
- First sync no longer fails on a missing document (404 = "not created yet").
- Remote edits (incl. due dates) are no longer discarded (`LAST-MODIFIED` vs. our X- timestamp).
- Recurring tasks always get a `DTSTART` anchor (an unanchored `RRULE` is rejected by the server).
- Keyring regression: passwords fall back to `QSettings`; a blank field no longer wipes stored credentials.
- A trailing `/index.php` in a server URL no longer doubles the path (404).

## [0.2.0] - 2026-09-23
- Due date **and time** per task, with persistent reminders (snooze 2/5/10 min) and a blinking tray icon.
- Cloud sync providers: generic **WebDAV** (JSON document) and **CalDAV** (`VTODO`); dependency-free iCalendar reader/writer; full-precision sync timestamps in `X-TODO-SNAKE-*`.
- Fixes: tray notifications actually shown; edits advance `updated_at` so they propagate.
