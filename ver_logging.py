"""Centralised logging configuration for the ECG analysis application.

Writes structured log entries to a rotating file in a user-writable location
so that EXE users have a usable audit trail without cluttering the console.

Usage
-----
Import and call ``setup_logging()`` once at startup (in ``main()``), then use
the standard ``logging`` module anywhere in the application::

    import logging
    log = logging.getLogger(__name__)
    log.info("Worker started")
    log.exception("Unexpected error during report generation")

The log file location is resolved in this priority order:
1. ``logs/`` subdirectory next to the running EXE / script  (writable check).
2. ``~/.ecg_analyses/logs/``  (user home folder fallback).
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from pathlib import Path

# Public name exposed for callers that want a module-level logger.
logger = logging.getLogger("ver")

_LOG_FILENAME = "ver_app.log"
_FROZEN_DEBUG_LOG_FILENAME = "ecg_frozen_debug.log"
_MAX_BYTES = 2 * 1024 * 1024   # 2 MB per file
_BACKUP_COUNT = 3               # keep up to 3 rotated files


def _resolve_log_dir() -> Path:
    """Return a writable directory for log files."""
    # Next to the EXE / script is the preferred location.
    if getattr(sys, "frozen", False):
        candidate = Path(sys.executable).parent / "logs"
    else:
        candidate = Path(__file__).parent / "logs"

    try:
        candidate.mkdir(parents=True, exist_ok=True)
        # Quick write-permission probe.
        probe = candidate / ".write_probe"
        probe.touch()
        probe.unlink()
        return candidate
    except OSError:
        pass

    # Fallback: user home directory.
    fallback = Path.home() / ".ecg_analyses" / "logs"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def setup_logging(level: int = logging.DEBUG) -> Path:
    """Configure the root ``ver`` logger with a rotating file handler.

    Should be called exactly once, from ``main()`` before any other module
    emits log records.

    Parameters
    ----------
    level:
        Minimum severity captured to file (default: ``DEBUG``).

    Returns
    -------
    Path
        Absolute path of the log file that was opened.
    """
    log_dir = _resolve_log_dir()
    log_path = log_dir / _LOG_FILENAME

    root_ver = logging.getLogger("ver")
    if root_ver.handlers:
        # Already configured — skip re-initialisation.
        return log_path

    root_ver.setLevel(level)

    # --- Rotating file handler ---
    file_handler = logging.handlers.RotatingFileHandler(
        log_path,
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_fmt = logging.Formatter(
        fmt="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(file_fmt)
    root_ver.addHandler(file_handler)

    # --- Console handler (WARNING and above only, to keep stdout clean) ---
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.WARNING)
    console_fmt = logging.Formatter("%(levelname)s: %(message)s")
    console_handler.setFormatter(console_fmt)
    root_ver.addHandler(console_handler)

    # Prevent propagation to the root Python logger to avoid duplicate output.
    root_ver.propagate = False

    root_ver.info("Logging initialised — log file: %s", log_path)
    return log_path


def _find_writable_frozen_debug_log_path() -> tuple[Path, list[str]]:
    """Find a writable diagnostics log path for frozen-mode debugging."""
    base_dir = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
    attempts: list[Path] = [
        base_dir / _FROZEN_DEBUG_LOG_FILENAME,
        Path.home() / ".ecg_analyses" / _FROZEN_DEBUG_LOG_FILENAME,
    ]
    reasons: list[str] = []
    for candidate in attempts:
        try:
            candidate.parent.mkdir(parents=True, exist_ok=True)
            with candidate.open("a", encoding="utf-8"):
                pass
            return candidate, reasons
        except OSError as exc:
            reasons.append(f"{candidate}: {exc}")
    return attempts[-1], reasons


def setup_frozen_debug_logging(enabled: bool | None = None) -> Path:
    """Configure a dedicated diagnostics logger for EXE plotting investigations."""
    if enabled is None:
        enabled = bool(getattr(sys, "frozen", False) or os.environ.get("ECG_FROZEN_DEBUG"))
    log_path, fallback_reasons = _find_writable_frozen_debug_log_path()
    dbg_logger = logging.getLogger("ver.frozen_debug")
    if dbg_logger.handlers:
        return log_path
    if not enabled:
        dbg_logger.addHandler(logging.NullHandler())
        dbg_logger.propagate = False
        return log_path

    dbg_logger.setLevel(logging.DEBUG)
    file_handler = logging.FileHandler(log_path, mode="w", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    dbg_logger.addHandler(file_handler)
    dbg_logger.propagate = False
    dbg_logger.debug("Frozen diagnostics logging initialised at: %s", log_path)
    if fallback_reasons:
        dbg_logger.warning("Primary diagnostics path unavailable; fallback used.")
        for reason in fallback_reasons:
            dbg_logger.warning("Path check failure: %s", reason)
    return log_path
