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

## Translations (i18n)

The UI is translatable via Qt's linguist toolchain:

- Every user-visible string in a widget/model lives behind `self.tr(...)` or
  `QCoreApplication.translate(...)` (priority labels consistently use the
  `TodoTableModel` context, see `ui/model.py::priority_label`). Plain string
  literals are **not** translated.
- Compiled catalogs ship as `src/todo_snake/resources/i18n/todo_snake_<lang>.qm`
  (see `package-data` in `pyproject.toml`; commit both `.ts` and `.qm`).
  English (`todo_snake_en`) ships as an explicit identity catalog: it is the
  fallback language, so `TODO_SNAKE_LANG=en` or an English system locale
  always selects English.
- At startup `todo_snake.i18n.load_translator` installs the catalog matching
  the system locale. Override per process:

  ```sh
  TODO_SNAKE_LANG=de todo-snake
  ```

To add a language or refresh the catalog after editing strings:

```sh
./scripts/update_translations.sh           # refresh all languages
./scripts/update_translations.sh de        # refresh just German
```

This runs `pyside6-lupdate` (extracts `tr()`/`translate()` texts) and
`pyside6-lrelease` (compiles `.qm`). Edit `.ts` by hand or with Qt Linguist
(`pyside6-linguist`). A new language starts as

```sh
cp src/todo_snake/resources/i18n/todo_snake_de.ts \
   src/todo_snake/resources/i18n/todo_snake_fr.ts
# edit the <translation> texts, then:
./scripts/update_translations.sh fr
```

The test suite checks that every `.ts` is fully translated and compiled and
that the German catalog actually applies (`tests/test_i18n.py`).

## Run from source

```sh
python main.py
# or: python -m todo_snake
```

## Project structure

```
├── main.py                  # Convenience launcher (python main.py)
├── install.sh / uninstall.sh
├── todo-snake.desktop       # Desktop entry template (Exec= is substituted; Icon= is the theme icon name)
├── scripts/
│   └── update_translations.sh  # Regenerate .ts + .qm catalogs
├── docs/                    # Screenshots and this documentation
├── src/todo_snake/
│   ├── app.py               # Composition root + single-instance guard
│   ├── config.py            # Metadata + XDG data paths
│   ├── i18n.py              # Locale detection + QTranslator loading
│   ├── single_instance.py   # QLockFile ownership + QLocalServer "show" channel
│   ├── domain/              # Todo model, enums, validation
│   ├── persistence/         # Repository interface + SQLite backend
│   ├── service/             # Business logic (add/update/toggle/import/export)
│   ├── ui/                  # MainWindow, dialog, tray, table model, icons
│   └── resources/
│       ├── icons/           # SVG icons (app icon: todo.svg)
│       └── i18n/            # Translation files (todo_snake_de.ts/.qm)
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