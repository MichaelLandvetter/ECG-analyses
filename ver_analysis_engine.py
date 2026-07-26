"""Inherited VER analysis engine — thin adapter layer.

This module is the single import boundary between the main application
orchestration (``ver_main.py``) and the inherited VER-specific analysis
components.  All VER-specific analysis functions exported here are
**inherited placeholders** scheduled for ECG replacement.

**What makes up the inherited VER analysis engine:**

+----------------------------+--------------------------------------------+------------------------------+
| Component                  | Source module (current)                    | ECG replacement target       |
+============================+============================================+==============================+
| ``detect_ver_peaks``       | ``ver_peaks.py`` — P1/P2/P3 detection      | ``ecg_peaks.py`` (P/Q/R/S/T) |
| ``classify_ecg_signal``    | ``ecg_classifier.py`` — ECG boundary       | real ECG classifier logic    |
| ``evaluate_ver_peak``      | alias → ``classify_ecg_signal`` (compat)   | remove after all callers ↑   |
| ``save_ecg_report``        | ``ecg_report.py`` — ECG boundary           | real ECG report logic        |
| ``save_ver_report``        | alias → ``save_ecg_report`` (compat)       | remove after all callers ↑   |
| ``refresh_classifier_cfg`` | propagates settings across modules         | update in place              |
+----------------------------+--------------------------------------------+------------------------------+

**NOT managed here (handled separately):**

- ``ECGScopeProcessor`` (``ecg_scope.py``) — ECG-oriented placeholder
  boundary for trigger/epoch/averaging.  It is currently backed by inherited
  ``VERScopeProcessor`` logic from ``ver_scope.py`` and is the first module
  transition boundary (REPLACEMENT TARGET 1).  See
  ``docs/ecg-transition-priorities.md`` for sequencing/risk notes.

**How to apply ECG modules via this boundary:**

1. Implement ``ecg_peaks.py`` with ECG morphology detection.
2. Update ``ecg_classifier.py`` and ``ecg_report.py`` with real ECG logic.
3. Update the imports *inside this file* to pull from the ECG modules.
4. No other changes to ``ver_main.py`` are needed for those three modules.
5. Remove backward-compat aliases (``evaluate_ver_peak``, ``save_ver_report``)
   once all callers have been switched to the ECG-named functions.
6. Remove or rename this file once all VER analysis modules are replaced.

See ``docs/ecg-transition-priorities.md`` for the full ranked replacement
sequence and safe ordering rationale.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Public API of this adapter module — defines the analysis engine surface
# ---------------------------------------------------------------------------
__all__ = [
    # ECG-named boundary functions (preferred — use these in new/updated code)
    "classify_ecg_signal",
    "save_ecg_report",
    # Backward-compat aliases (deprecated — to be removed after all callers updated)
    "evaluate_ver_peak",
    "save_ver_report",
    # Peak detection (still inherited VER — REPLACEMENT TARGET 2)
    "detect_ver_peaks",
    # Settings propagation
    "refresh_classifier_cfg",
]

# ---------------------------------------------------------------------------
# INHERITED VER ANALYSIS ENGINE — all re-exported through this adapter layer
# ---------------------------------------------------------------------------

# REPLACEMENT TARGET 2 — ver_peaks.py → ecg_peaks.py
# ECG equivalent: R-peak / P / Q / R / S / T morphology detection
from ver_peaks import detect_ver_peaks
from ver_peaks import refresh_classifier_cfg as _refresh_peaks_cfg

# REPLACEMENT TARGET 3 (boundary established) — ecg_classifier.py wraps ver_classifier.py
# ECG equivalent: QRS duration, PR/QT interval, rhythm classification
# The VER-specific logic still runs underneath; replace delegation inside ecg_classifier.py.
from ecg_classifier import classify_ecg_signal
from ecg_classifier import refresh_classifier_cfg as _refresh_classifier_cfg

# Backward-compat alias — callers that still reference evaluate_ver_peak will
# continue to work.  Switch callers to classify_ecg_signal and remove this alias.
evaluate_ver_peak = classify_ecg_signal

# REPLACEMENT TARGET 4 (boundary established) — ecg_report.py wraps ver_report.py
# ECG equivalent: PDF/CSV with ECG-standard metrics and interval tables
# The VER-specific layout still runs underneath; replace delegation inside ecg_report.py.
from ecg_report import save_ecg_report

# Backward-compat alias — callers that still reference save_ver_report will
# continue to work.  Switch callers to save_ecg_report and remove this alias.
save_ver_report = save_ecg_report


def refresh_classifier_cfg(cfg: dict) -> None:
    """Propagate updated classifier/peak settings to all analysis modules.

    Call this after the user saves settings in the GUI so that the next
    analysis run picks up the new configuration without a restart.

    Delegates to ``ecg_classifier.refresh_classifier_cfg`` (which in turn
    delegates to the inherited VER classifier cache).  Update when the ECG
    classifier implements its own settings management.
    """
    _refresh_peaks_cfg(cfg)
    _refresh_classifier_cfg(cfg)
