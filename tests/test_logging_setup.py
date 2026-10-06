"""Tests for the rotating sync log setup."""

from __future__ import annotations

import logging

from todo_snake import logging_setup


def _reset(monkeypatch, tmp_path):
    monkeypatch.setattr(logging_setup, "default_log_path", lambda: tmp_path / "sync.log")
    monkeypatch.setattr(logging_setup, "_configured", False)
    logger = logging.getLogger(logging_setup.LOGGER_NAME)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
    return logger


def test_configure_logging_writes_records(tmp_path, monkeypatch):
    logger = _reset(monkeypatch, tmp_path)
    try:
        logging_setup.configure_logging()
        logging_setup.get_sync_logger().info("hello sync")
        for handler in logger.handlers:
            handler.flush()
        assert "hello sync" in (tmp_path / "sync.log").read_text(encoding="utf-8")
    finally:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)


def test_configure_logging_is_idempotent(tmp_path, monkeypatch):
    logger = _reset(monkeypatch, tmp_path)
    try:
        logging_setup.configure_logging()
        logging_setup.configure_logging()
        assert len(logger.handlers) == 1
    finally:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
