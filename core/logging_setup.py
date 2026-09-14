"""Rotating application log under data/logs/. Never writes secrets."""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOGGER_NAME = "salesos"
DEFAULT_LOG_FILE = "salesos.log"
DEFAULT_LEVEL = "INFO"
MAX_BYTES = 1_048_576  # 1 MiB
BACKUP_COUNT = 5

_SECRET_NAME_MARKERS = ("TOKEN", "SECRET", "PASSWORD", "API_KEY", "ACCESS_KEY")
_HANDLER_MARK = "_salesos_handler"


def default_data_dir() -> Path:
    return Path(os.environ.get("SALESOS_DATA_DIR", "data"))


def default_log_dir() -> Path:
    return default_data_dir() / "logs"


def _secret_values() -> list[str]:
    values: list[str] = []
    for key, value in os.environ.items():
        if not value or len(value) < 8:
            continue
        name = key.upper()
        if any(marker in name for marker in _SECRET_NAME_MARKERS):
            values.append(value)
    values.sort(key=len, reverse=True)
    return values


class RedactSecretsFilter(logging.Filter):
    """Replace secret env values in log records with ***."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except (TypeError, ValueError):
            return True
        redacted = message
        for secret in _secret_values():
            if secret in redacted:
                redacted = redacted.replace(secret, "***")
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


_LEVELS = {
    "CRITICAL": logging.CRITICAL,
    "ERROR": logging.ERROR,
    "WARNING": logging.WARNING,
    "INFO": logging.INFO,
    "DEBUG": logging.DEBUG,
}


def _level_from_env(level: str | None) -> int:
    name = (level or os.environ.get("SALESOS_LOG_LEVEL") or DEFAULT_LEVEL).upper()
    if name not in _LEVELS:
        raise ValueError(f"Unknown log level {name!r} (set SALESOS_LOG_LEVEL)")
    return _LEVELS[name]


def _marked_handlers(logger: logging.Logger) -> list[logging.Handler]:
    return [h for h in logger.handlers if getattr(h, _HANDLER_MARK, False)]


def setup_logging(
    *,
    level: str | None = None,
    log_dir: Path | str | None = None,
    console: bool = True,
    force: bool = False,
) -> Path:
    """Configure the salesos logger with a rotating file handler.

    Returns the log file path. Idempotent unless force=True.
    """
    directory = Path(log_dir) if log_dir is not None else default_log_dir()
    directory.mkdir(parents=True, exist_ok=True)
    log_path = directory / DEFAULT_LOG_FILE

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(_level_from_env(level))
    logger.propagate = False

    existing = _marked_handlers(logger)
    if existing and not force:
        same_file = any(
            isinstance(handler, RotatingFileHandler)
            and Path(handler.baseFilename).resolve() == log_path.resolve()
            for handler in existing
        )
        if same_file:
            return log_path
        force = True
    if force or existing:
        for handler in list(existing):
            logger.removeHandler(handler)
            handler.close()

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s"
    )
    redact = RedactSecretsFilter()

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.addFilter(redact)
    setattr(file_handler, _HANDLER_MARK, True)
    logger.addHandler(file_handler)

    if console:
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        stream_handler.addFilter(redact)
        setattr(stream_handler, _HANDLER_MARK, True)
        logger.addHandler(stream_handler)

    return log_path
