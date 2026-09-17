"""Shared pytest fixtures.

The Qt platform is forced to ``offscreen`` here so widget tests run in any
environment (CI, headless server, ...) without a display server.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app
    app.processEvents()
