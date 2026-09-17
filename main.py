#!/usr/bin/env python3
"""Convenience launcher — run without installing: ``python main.py``.
When installed via pip, use the ``todo-snake`` console script instead.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from todo_snake.app import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())