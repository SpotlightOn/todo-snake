# Development

## Setup

Requirements-style (runtime deps + editable package + pytest):

```sh
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
```

Or canonical `pyproject.toml` style (equivalent):

```sh
.venv/bin/pip install -e '.[dev]'
```

`requirements.txt` alone installs only the runtime dependencies (PySide6).

## Running the tests

UI tests run fully offscreen, so no display is needed:

```sh
.venv/bin/pytest
```

For verbose output: `pytest -v`. Tests live in `tests/` (domain, service,
repository, UI smoke tests, single-instance guard).

## Linting

Configured via Ruff (`line-length = 100`):

```sh
.venv/bin/ruff check .
```

## Run from source

```sh
python main.py
# or: python -m todo_snake
```

## Project structure

```
├── main.py                  # Convenience launcher (python main.py)
├── install.sh / uninstall.sh
├── todo-snake.desktop       # Desktop entry template (Exec= and Icon= are substituted)
├── docs/                    # Screenshots and this documentation
├── src/todo_snake/
│   ├── app.py               # Composition root + single-instance guard
│   ├── config.py            # Metadata + XDG data paths
│   ├── single_instance.py   # QLockFile ownership + QLocalServer "show" channel
│   ├── domain/              # Todo model, enums, validation
│   ├── persistence/         # Repository interface + SQLite backend
│   ├── service/             # Business logic (add/update/toggle/import/export)
│   ├── ui/                  # MainWindow, dialog, tray, table model, icons
│   └── resources/icons/     # SVG icons (app icon: todo.svg)
└── tests/                   # pytest suite
```

## Architecture notes

- **Layering:** `ui/` maps user gestures to `service/` calls; `service/`
  owns all business rules and talks only to the `TodoRepository` interface;
  `persistence/` provides the SQLite backend. `app.py` is the single
  composition root.
- **Single instance:** a `QLockFile` decides ownership (robust against stale
  locks). The owner also binds a `QLocalServer`; a second launch notifies the
  running instance to raise its window and exits — no duplicate window, no
  concurrent SQLite writes. The guard is held by `QApplication` for its whole
  lifetime.
- **Storage:** short-lived connections per operation; ISO 8601 text columns
  keep the schema portable for a future PostgreSQL backend.