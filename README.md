# Todo Snake

![Todo snake](docs/todo-snake.jpeg)

A clean PySide6 TODO app with system tray integration. Tasks are stored in a
local SQLite database, and the app hides to the system tray instead of exiting
when the window is closed.

## Features

- Add, edit, delete and mark tasks as done (double-click to edit)
- Filter by status (all / open / done) and full-text search
- Priorities (low / medium / high) and due dates, overdue highlighting
- Import / export as JSON
- System tray icon with hide/show toggle and notifications ("All done!")
- XDG-compliant data directory (`~/.local/share/SnakeTodo/snake-todo/todos.db`)

## Requirements

- Python 3.10+ on Linux with a Qt platform (X11 or Wayland)

## Installation

`install.sh` installs the Python package and registers the app with the
desktop environment, following the
[XDG Base Directory specification](https://specifications.freedesktop.org/basedir-spec/):

| Artifact          | Location                                        |
| ----------------- | ----------------------------------------------- |
| desktop entry     | `$XDG_DATA_HOME/applications/` (e.g. `~/.local/share/applications`) |
| icon              | `$XDG_DATA_HOME/icons/hicolor/scalable/apps/`   |
| Python package    | `$XDG_DATA_HOME/snake-todo/venv/`               |

After installation, launch the app from the application menu or run:

```
~/.local/share/snake-todo/venv/bin/snake-todo
```

### Recommended: user-level XDG install (no root)

```
./install.sh
```

This works on systems with PEP 668 "externally managed" Python (Debian,
Ubuntu, Fedora 41+, ...) because it installs into a dedicated virtualenv, not
into system site-packages.

### Alternative: virtualenv inside the repository

```
./install.sh --src-venv
# launch: .venv/bin/snake-todo
```

### Alternative: system-wide

```
sudo ./install.sh --system
```

### Manual pip install

```
pip install .            # installs the `snake-todo` console script
```

## Uninstall

```
./uninstall.sh
```

This removes the XDG desktop entry, icon and venv. Files created in the data
directory (`todos.db`) are kept.

## Development

### Development install

Requirements-style (installs runtime deps, the editable package and pytest):

```
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
```

Or canonical `pyproject.toml` style (equivalent):

```
.venv/bin/pip install -e '.[dev]'
```

`requirements.txt` alone installs only the runtime dependencies (PySide6).

### Running the tests

UI tests run fully offscreen, so no display is needed. Run from the repo root:

```
.venv/bin/pytest
```

For verbose output: `pytest -v`. Tests live in `tests/` (domain, service,
repository, UI smoke tests). Linting is configured via Ruff (`line-length = 100`).

Run the app from source without installing:

```
python main.py
```

Linting is configured via Ruff (`line-length = 100`).

## Project structure

```
├── main.py                  # Convenience launcher (python main.py)
├── install.sh / uninstall.sh
├── todo-snake.desktop       # Desktop entry template (Exec= is substituted)
├── docs/
├── src/snake_todo/
│   ├── app.py               # Composition root
│   ├── config.py            # Metadata + XDG data paths
│   ├── domain/              # Todo model, enums, validation
│   ├── persistence/         # Repository interface + SQLite backend
│   ├── service/             # Business logic (add/update/toggle/import/export)
│   ├── ui/                  # MainWindow, dialog, tray, table model, icons
│   └── resources/icons/     # SVG icons (app icon: todo.svg)
└── tests/                   # pytest suite (domain, service, repository, UI)
```

## License

See [LICENSE](LICENSE).