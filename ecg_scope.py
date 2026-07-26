"""ECG-oriented scope processor placeholder interface.

This module defines the first ECG-facing boundary for replacing inherited
VER scope processing.  It intentionally does **not** implement ECG analysis
yet.  Instead, it keeps the app runnable by delegating to the inherited
``VERScopeProcessor`` from ``ver_scope.py``.

Responsibilities of this placeholder boundary:
- provide an ECG-named processor class for callers (`ECGScopeProcessor`)
- preserve the current result-dict contract consumed by `ver_main.py`
  and `ver_preflight.py`
- isolate direct caller dependency on `ver_scope.py` so a future ECG
  implementation can be swapped in this module with minimal caller changes

Inherited behavior still used underneath:
- rising-edge trigger detection
- flash-count session completion
- pre/post-stimulus epoch extraction

Future replacement path:
- replace this delegation with real ECG beat-locked logic (R-peak trigger
  and ECG windowing) while preserving or explicitly migrating the result-dict
  contract used by callers.
- likely adjacent next replacement target: `ver_peaks.py` via
  `ver_analysis_engine.py`.
"""

from __future__ import annotations

from ver_scope import VERScopeProcessor


class ECGScopeProcessor(VERScopeProcessor):
    """Transitional ECG-named boundary that delegates to inherited VER logic."""

    pass
