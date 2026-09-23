# Todo Snake

![Todo snake](docs/todo-snake.jpeg)

A clean PySide6 TODO app with system tray integration. Tasks are stored in a
local SQLite database, and the app hides to the system tray instead of exiting
when the window is closed.

## Features

- Add, edit, delete and mark tasks done (double-click to edit)
- Filter by status, full-text search, priorities and due dates
- Import / export as JSON
- Optional cloud sync via WebDAV or CalDAV (see [Sync](#sync))
- System tray with notifications ("All done!")
- Single-instance enforcement
- Translatable UI (German included; follows the system locale, override with `TODO_SNAKE_LANG`)
- XDG-compliant data directory

![App screenshot](docs/screen.png)

## Sync

Tasks can sync to your own cloud — no account with a third party is required.
Two providers are supported:

- **WebDAV** — store the sync document on any WebDAV server: Nextcloud,
  ownCloud, rclone (`rclone serve webdav`), Apache `mod_dav`, …
- **CalDAV** — sync each task as a `VTODO` resource against a CalDAV server:
  Baïkal (sabre/dav), Radicale, Nextcloud Tasks, fruux or Vikunja.

Configure accounts under *Settings → Sync accounts*. Credentials are sent as
HTTP Basic over TLS (plain `http://` is only allowed for localhost). Conflicts
are resolved per task with last-write-wins; deletions propagate as tombstones.
For CalDAV, paste the full calendar collection URL, e.g.
`https://cloud.example.com/remote.php/dav/calendars/alice/tasks/`.

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

Python 3.10+ on Linux with a Qt platform (X11 or Wayland).

## Development

Setup, running the tests and project structure:
[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md). To run from source:

```sh
python main.py
```

## License

[LICENSE](LICENSE)