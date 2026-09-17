"""Locale detection and Qt translation loading.

Translations live as ``resources/i18n/todo_snake_<lang>.qm`` next to the
package data. The UI strings are wrapped in ``tr()`` /
``QCoreApplication.translate`` so they get picked up by ``pyside6-lupdate``;
see ``docs/DEVELOPMENT.md`` for the workflow. At startup the app loads the
translation matching the system locale, overridable per process with the
``TODO_SNAKE_LANG`` environment variable (e.g. ``TODO_SNAKE_LANG=de``).

English ships as its own catalog too (``todo_snake_en.qm``): it is the
explicit fallback language, so ``TODO_SNAKE_LANG=en`` (or any English system
locale) always selects English rather than leaving the UI untranslated.
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QLocale, QTranslator
from PySide6.QtWidgets import QApplication

_I18N_DIR = Path(__file__).resolve().parent / "resources" / "i18n"


def translations_dir() -> Path:
    """Directory that contains the compiled ``.qm`` translation files."""
    return _I18N_DIR


def available_language_codes() -> list[str]:
    """Language codes for which a compiled ``.qm`` exists (e.g. ``["de", "en"]``)."""
    prefix = "todo_snake_"
    return sorted(
        p.stem.removeprefix(prefix)
        for p in _I18N_DIR.glob("todo_snake_*.qm")
        if p.stem.startswith(prefix)
    )


def resolve_language(preferred: str | None = None) -> str | None:
    """Pick the closest available language for ``preferred``.

    ``preferred`` wins over the ``TODO_SNAKE_LANG`` override, which wins over
    the system locale. Only the language part (``de`` from ``de_DE``) is
    matched; ``None`` means no catalog is available for the language (the
    built-in English source strings then stay active).
    """
    wanted = preferred or os.environ.get("TODO_SNAKE_LANG")
    if wanted:
        tag = wanted.replace("_", "-").split("-", 1)[0].lower()
    else:
        tag = QLocale.system().name().split("_", 1)[0].lower()
    return tag if tag in available_language_codes() else None


def load_translator(app: QApplication, language: str | None = None) -> QTranslator | None:
    """Install a translator for the resolved language, if available.

    Returns the installed translator (the app owns it) or ``None`` when the
    requested locale has no compiled translation — the English source strings
    then remain active.
    """
    tag = resolve_language(language)
    if tag is None or not translations_dir().is_dir():
        return None
    translator = QTranslator(app)
    if translator.load(QLocale(tag), "todo_snake", "_", str(translations_dir()), ".qm"):
        app.installTranslator(translator)
        QLocale.setDefault(QLocale(tag))
        return translator
    return None
