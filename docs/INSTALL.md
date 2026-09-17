# Installation

`install.sh` and `uninstall.sh` install/remove snake-todo and register it with
the desktop environment, following the
[XDG Base Directory specification](https://specifications.freedesktop.org/basedir-spec/):

| Artifact       | Location                                    |
| -------------- | ------------------------------------------- |
| desktop entry  | `$XDG_DATA_HOME/applications/` (e.g. `~/.local/share/applications`) |
| icon           | `$XDG_DATA_HOME/icons/hicolor/scalable/apps/` |
| Python package | `$XDG_DATA_HOME/snake-todo/venv/`           |

The installed `.desktop` entry points directly at the executable and icon, so
no icon-theme cache refresh is needed.

## Options

### Recommended: user-level XDG install (no root)

```sh
./install.sh
```

Works on systems with PEP 668 "externally managed" Python (Debian, Ubuntu,
Fedora 41+, ...) because it installs into a dedicated virtualenv rather than
system site-packages.

### Virtualenv inside the repository

```sh
./install.sh --src-venv
# launch: .venv/bin/snake-todo
```

### System-wide

```sh
sudo ./install.sh --system
```

### Manual pip install

```sh
pip install .   # installs the `snake-todo` console script
```

## Uninstall

```sh
./uninstall.sh
```

Removes the XDG desktop entry, icon and venv. Data files (`todos.db`) are kept.

## Data directory

Task data lives at `~/.local/share/SnakeTodo/snake-todo/todos.db` (follows
XDG, overridable via the `SNAKE_TODO_DB` environment variable).