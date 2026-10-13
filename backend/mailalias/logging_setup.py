"""JSON-lines logging to stdout and a daily-rotated file per service.

Never log message bodies, subjects or plaintext addresses: log ids and hashes instead.
"""

# 1st party imports
import json
import logging
import sys
from datetime import UTC, datetime
from logging.handlers import TimedRotatingFileHandler
from typing import Any

# local imports
from mailalias.config import get_settings

# Attributes every LogRecord has; anything else was passed via `extra=` and is emitted as a field.
_STANDARD_ATTRS = frozenset(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    """Render each record as one JSON object, including `extra=` fields."""

    def format(self, record: logging.LogRecord) -> str:
        """Serialise a log record to a JSON line.

        Args:
            record: The record to format.
        Returns:
            A single-line JSON string.
        """
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(service: str, level: int = logging.INFO) -> None:
    """Send root logging to stdout and `{LOG_DIR}/{service}/{service}.log` as JSON lines.

    Args:
        service: Service name (api, processor, worker...), used for the log path.
        level: Minimum level to emit.
    Returns:
        None.
    """
    log_dir = get_settings().log_dir / service
    log_dir.mkdir(parents=True, exist_ok=True)
    formatter = JsonFormatter()

    file_handler = TimedRotatingFileHandler(
        log_dir / f"{service}.log", when="midnight", backupCount=14, utc=True, encoding="utf-8"
    )
    stream_handler = logging.StreamHandler(sys.stdout)
    for handler in (file_handler, stream_handler):
        handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(file_handler)
    root.addHandler(stream_handler)
    root.setLevel(level)
    # httpx logs full request URLs at INFO; keep it quiet so tokens in paths never leak.
    logging.getLogger("httpx").setLevel(logging.WARNING)
