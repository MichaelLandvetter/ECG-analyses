"""ECG Analysis — canonical application entrypoint.

Run this file to start the ECG Analysis application::

    python ecg_main.py

Backward compatibility: ``ver_main.py`` is kept as a thin delegating shim
that calls this module's ``main`` function.  New development and documentation
should reference ``ecg_main.py`` as the canonical launcher.

Transition note: The main window class (``VERMainWindow``) is still defined
in ``ver_main.py`` during the current naming-transition phase.  See
``docs/module_migration_status.md`` for the full module lifecycle plan and
the sequence of future renames.
"""

from ver_main import main

if __name__ == "__main__":
    main()
