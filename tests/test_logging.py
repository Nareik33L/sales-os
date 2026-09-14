"""Rotating file log under data/logs; secrets must never appear in the file."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytest

from core.logging_setup import LOGGER_NAME, setup_logging


def test_setup_logging_writes_rotating_file(tmp_path: Path):
    log_dir = tmp_path / "logs"
    log_path = setup_logging(log_dir=log_dir, console=False, force=True)
    assert log_path == log_dir / "salesos.log"
    logger = logging.getLogger(LOGGER_NAME)
    logger.info("demo-log-line")
    for handler in logger.handlers:
        handler.flush()
    text = log_path.read_text(encoding="utf-8")
    assert "demo-log-line" in text
    assert any(isinstance(h, RotatingFileHandler) for h in logger.handlers)


def test_secrets_are_redacted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    secret = "sk-demo-secret-value-not-real"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    log_path = setup_logging(log_dir=tmp_path / "logs", console=False, force=True)
    logging.getLogger(LOGGER_NAME).warning("provider key=%s", secret)
    for handler in logging.getLogger(LOGGER_NAME).handlers:
        handler.flush()
    text = log_path.read_text(encoding="utf-8")
    assert secret not in text
    assert "***" in text
