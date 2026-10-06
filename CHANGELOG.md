# Changelog

Notable changes only. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) / [SemVer](https://semver.org/).

## [Unreleased]

### Added
- **Nextcloud Tasks sync** (`VTODO`): one calendar-URL field, browser login (Login Flow v2, SSO/2FA included), calendar created on demand, both directions.
- Task fields: **status** (open / in progress / done), **start date**, **all-day** due dates, per-task **reminder lead**.
- **Recurring tasks** (daily / weekly / monthly / yearly, `∞` in the list); completing one advances to the next occurrence.
- Toolbar **Sync now** (greyed out without an enabled account); periodic sync optional.
- Sync diagnostics: rotating `sync.log` and a **Test connection** button in the account dialog.
- Lossless VTODO edits: only owned fields are rewritten, foreign properties are kept.
- Conditional writes (`If-Match`) and per-account deletion tracking (UIDs + ETags).
- App passwords in the OS keyring, with a `QSettings` fallback.

### Changed
- *Nextcloud* now syncs the Tasks calendar; JSON-file sync moved to the generic **WebDAV** provider (CalDAV unchanged).

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
