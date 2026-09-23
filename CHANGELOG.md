# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

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

### Fixed

- Local edits now advance `updated_at`, so edits propagate between devices.
  Previously only creations and deletions synced, because an updated task kept
  its old timestamp and lost last-write-wins on every other device.
