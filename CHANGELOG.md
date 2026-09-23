# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Due date and time**: tasks now carry a full due timestamp (stored as UTC)
  instead of a date only. The dialog shows a date field with a calendar popup
  plus a separate time field, a "Now" shortcut, and turning the due switch on
  defaults to the current time.
- **Due reminders**: when a task's due time passes the app opens a persistent
  window (stays until dismissed) offering to snooze for 2, 5 or 10 minutes, and
  the tray icon blinks until it is handled. Reminders fire on time and catch up
  once on startup for tasks that came due while the app was closed.
- Cloud sync with two providers, configurable under *Settings → Sync accounts*:
  - **WebDAV (generic)** — store the sync document on any plain WebDAV server
    (rclone, Apache `mod_dav`, ownCloud, …) via a configurable base path,
    alongside the existing Nextcloud support.
  - **CalDAV** — sync each task as a `VTODO` resource against any CalDAV
    server: Baïkal (sabre/dav), Radicale, Nextcloud Tasks, fruux or Vikunja.
- Dependency-free iCalendar (`VTODO`) reader/writer.
- Full-precision sync timestamps carried in `X-TODO-SNAKE-*` extension
  properties, so last-write-wins also works for changes made within the same
  second (iCalendar `LAST-MODIFIED` is only second-resolution).

### Changed

- Sync documents and iCalendar now carry the due timestamp as a date-time
  (`due_at` / `DUE:<UTC DATE-TIME>`) instead of a date. Legacy date-only values
  are still read as UTC midnight.

### Fixed

- Task-completed and "All done!" tray notifications are now actually shown; the
  signal was emitted but never connected to the tray.
- Local edits now advance `updated_at`, so edits propagate between devices.
  Previously only creations and deletions synced, because an updated task kept
  its old timestamp and lost last-write-wins on every other device.
