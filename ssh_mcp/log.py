"""Custom logging configuration for SSH operations.

Two rules matter here:

* Logs go to **stderr**. Under the MCP stdio transport stdout *is* the
  JSON-RPC channel, so a single stray byte there breaks the protocol.
* Command output is **truncated** before logging. Remote commands regularly
  return megabytes of text; echoing all of it to stderr buries real errors.
"""

import os
from sys import stderr

from loguru import logger as custom_logger

MAX_LOGGED_OUTPUT = 2000
TRUNCATION_MARKER = "... [truncated]"


def log_formatter(record: dict) -> str:
    """Format log records for consistent console output."""
    if record["level"].name == "TRACE":
        return "<fg #70acde>{time:MM-DD-YYYY HH:mm:ss}</fg #70acde> | <fg #cfe2f3>{level}</fg #cfe2f3>: <light-white>{message}</light-white>\n"
    if record["level"].name == "INFO":
        return "<fg #70acde>{time:MM-DD-YYYY HH:mm:ss}</fg #70acde> | <fg #9cbfdd>{level}</fg #9cbfdd>: <light-white>{message}</light-white>\n"
    if record["level"].name == "DEBUG":
        return "<fg #70acde>{time:MM-DD-YYYY HH:mm:ss}</fg #70acde> | <fg #8598ea>{level}</fg #8598ea>: <light-white>{message}</light-white>\n"
    if record["level"].name == "WARNING":
        return "<fg #70acde>{time:MM-DD-YYYY HH:mm:ss}</fg #70acde> |  <fg #dcad5a>{level}</fg #dcad5a>: <light-white>{message}</light-white>\n"
    if record["level"].name == "SUCCESS":
        return "<fg #70acde>{time:MM-DD-YYYY HH:mm:ss}</fg #70acde> | <fg #3dd08d>{level}</fg #3dd08d>: <light-white>{message}</light-white>\n"
    if record["level"].name == "ERROR":
        return "<fg #70acde>{time:MM-DD-YYYY HH:mm:ss}</fg #70acde> | <fg #ae2c2c>{level}</fg #ae2c2c>: <light-white>{message}</light-white>\n"
    return "<fg #70acde>{time:MM-DD-YYYY HH:mm:ss}</fg #70acde> | <fg #b3cfe7>{level}</fg #b3cfe7>: <light-white>{message}</light-white>\n"


def shorten(text: str, limit: int = MAX_LOGGED_OUTPUT) -> str:
    """Trim long command output so one noisy command cannot flood the log."""
    if not text:
        return "<empty>"
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n{TRUNCATION_MARKER} ({len(text)} chars total)"


def create_logger() -> custom_logger:
    """Return a logger writing to stderr, level tunable via SSH_LOG_LEVEL."""
    level = (os.environ.get("SSH_LOG_LEVEL") or "INFO").strip().upper() or "INFO"
    custom_logger.remove()
    custom_logger.add(stderr, colorize=True, level=level, format=log_formatter)
    return custom_logger


LOGGER = create_logger()
