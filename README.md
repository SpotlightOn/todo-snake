# Todo Snake

![Todo snake](docs/todo-snake.jpeg)

[![CI][ci-badge]][ci-url] [![Socket][socket-badge]][socket-url] [![Release][release-badge]][release-url] [![License][license-badge]][license-url]
[![Python][python-badge]][python-url] [![Qt][qt-badge]][qt-url] [![Linux][linux-badge]](#requirements) [![macOS][macos-badge]](#requirements) [![Windows][windows-badge]](#requirements) 

**Eat your todos.** 🐍 Todo Snake is a fast, simple task manager that just
works: a clean UI living in the system tray — add a task, attach a file, set a
reminder or a repeat rule, tick it off, done. No account and no cloud required
— tasks stay in a local SQLite database. Want them everywhere? Sync to your
own Nextcloud or any CalDAV server.

## Features

- Add, edit, delete and mark tasks done (double-click to edit)
- Status (**open / in progress / done**), an optional **start date**, **all-day**
  due dates and a per-task **reminder lead time**
- Recurring tasks (daily / weekly / monthly / yearly), shown with an ∞ in the
  list; completing one advances it to the next occurrence
- Due date **and time** per task, with a persistent reminder window (snooze 2/5/10 min) and a blinking tray icon
- Filter by status, full-text search, priorities and due dates
- **Attachments**: files per task, stored locally and opened with one click
  (uploaded to Nextcloud Files when a Nextcloud account is set up). A **Files**
  column marks tasks with attachments; the list shows image previews and
  type icons.
- Import / export as JSON
- Optional cloud sync via WebDAV or CalDAV (see [Sync](#sync))
- System tray with notifications ("All done!")
- Single-instance enforcement
- Translatable UI (German included; follows the system locale, override with `TODO_SNAKE_LANG`)
- XDG-compliant data directory

![App screenshot](docs/screen.png)

## Sync

Tasks can sync to your own cloud — no account with a third party is required.

- **Nextcloud (Tasks)** — syncs with the **Nextcloud Tasks app**: every task is
  a `VTODO` in the task calendar you choose. Use *Connect to Nextcloud…* in the
  account dialog: paste the **full calendar URL** (e.g.
  `https://cloud.example.com/apps/tasks/calendars/tasks`) and sign in via Login
  Flow v2 (SSO and 2FA included) — one field is enough; a calendar that does not
  exist yet is created on the first sync. No shell access needed.
- **CalDAV** — sync against any other CalDAV server: Baïkal (sabre/dav),
  Radicale, fruux or Vikunja. Paste the full calendar collection URL, e.g.
  `https://cloud.example.com/remote.php/dav/calendars/alice/tasks/`.
- **WebDAV (generic)** — keep the sync state as a JSON document on any plain
  WebDAV server: rclone (`rclone serve webdav`), Apache `mod_dav`, ownCloud, …

Configure accounts under *Settings → Sync accounts*. Credentials are sent as
HTTP Basic over TLS (plain `http://` is only allowed for localhost). Conflicts
are resolved per task with last-write-wins; deletions propagate as tombstones.
Each account has a checkbox in the list: uncheck it to **disable** the account
without deleting it (a disabled account is skipped by every sync, manual
included).

Attachment files live in Nextcloud under *Files → Todo Snake/Attachments/*.
Removing an attachment deletes its file on the next sync, and every sync also
**sweeps the task folders** for files nothing references any more (so leftovers
from earlier versions disappear on their own). *Clean up orphaned files…* does
the same for the whole folder on demand, after a confirmation.

Trigger a sync anytime with the **Sync now** button in the toolbar (disabled
while no account is enabled), or turn on periodic sync under
*Settings → Sync behavior*.

## Install

User-level XDG install (recommended, no root):

```sh
./install.sh
```

Launch from the application menu, or run:

```sh
~/.local/share/todo-snake/venv/bin/todo-snake
```

Other options (system-wide, repo-local venv, manual pip) and uninstall
instructions: [docs/INSTALL.md](docs/INSTALL.md).

## Requirements

Python 3.10+ on Linux with a Qt platform (X11 or Wayland), and
[PySide6](https://pypi.org/project/PySide6/) 6.11.2 (Qt 6.11) or newer within
6.11. Everything else is the standard library — the sync does not pull in any
HTTP or iCalendar dependency.

## Development

Setup, running the tests and project structure:
[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md). To run from source:

```sh
python main.py
```

## License

[LICENSE](LICENSE)

<!-- Badges -->
[ci-url]: https://github.com/SpotlightOn/todo-snake/actions/workflows/ci.yml
[ci-badge]: https://github.com/SpotlightOn/todo-snake/actions/workflows/ci.yml/badge.svg?branch=main

[socket-url]: https://socket.dev/pypi/package/todo-snake
[socket-badge]: https://badge.socket.dev/pypi/package/todo-snake

[release-url]: https://github.com/SpotlightOn/todo-snake/releases
[release-badge]: https://img.shields.io/github/v/release/SpotlightOn/todo-snake?label=release&sort=semver&color=2f6f4f

[license-url]: LICENSE
[license-badge]: https://img.shields.io/github/license/SpotlightOn/todo-snake?color=2f6f4f

[python-url]: https://www.python.org/
[python-badge]: https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white

[qt-url]: https://www.qt.io/
[qt-badge]: https://img.shields.io/badge/Qt-6.11-41CD52?logo=qt&logoColor=white

[linux-badge]: https://img.shields.io/badge/Linux-FCC624?logo=linux&logoColor=black
[macos-badge]: https://img.shields.io/badge/macOS-000000?logo=apple&logoColor=white
[windows-badge]: https://img.shields.io/badge/Windows-0078D6

[ruff-url]: https://docs.astral.sh/ruff/
[ruff-badge]: https://img.shields.io/badge/code%20style-ruff-000000?logo=ruff&logoColor=white