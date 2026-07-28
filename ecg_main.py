"""ECG Analysis — canonical application entrypoint.

Run this file to start the ECG Analysis application::

    python ecg_main.py

This module owns application startup orchestration.  ``ver_main.py``
contains the main window class (``VERMainWindow``) during the current
naming-transition phase; its ``main()`` function is a backward-compatibility
shim that delegates here.

See ``docs/module_migration_status.md`` for the full module lifecycle plan
and ``docs/ver_cleanup_audit.md`` for the ``ver_*.py`` keep/remove audit.
"""

from __future__ import annotations

import logging
import sys

from PyQt6.QtWidgets import QApplication

if getattr(sys, 'frozen', False):
    import pyi_splash  # type: ignore[import]  # only present in packaged build

from ver_logging import setup_frozen_debug_logging, setup_logging
from ver_main import VERMainWindow

log = logging.getLogger(__name__)


def main() -> None:
    """Start the ECG Analysis application.

    This is the canonical ECG application entry point.  It owns the
    startup sequence: logging, Qt application object, main window,
    splash-screen teardown, and event-loop execution.
    """
    log_path = setup_logging()
    debug_log_path = setup_frozen_debug_logging()
    log.info("ECG Analysis application starting (log: %s)", log_path)
    frozen_debug_log = logging.getLogger("ver.frozen_debug")
    frozen_debug_log.info(
        "startup: sys.frozen=%s executable=%s script=%s diagnostics_log=%s",
        getattr(sys, "frozen", False),
        sys.executable,
        __file__,
        debug_log_path,
    )
    app = QApplication(sys.argv)
    win = VERMainWindow()
    win.show()

    if getattr(sys, 'frozen', False):
        pyi_splash.close()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
