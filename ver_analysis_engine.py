"""Inherited VER analysis engine — thin adapter layer.

This module is the single import boundary between the main application
orchestration (``ver_main.py``) and the inherited VER-specific analysis
components.  All VER-specific analysis functions exported here are
**inherited placeholders** scheduled for ECG replacement.

**What makes up the inherited VER analysis engine:**

+----------------------------+-------------------------------------------+------------------------------+
| Component                  | Source module                             | ECG replacement target       |
+============================+===========================================+==============================+
| ``detect_ver_peaks``       | ``ver_peaks.py`` — P1/P2/P3 detection     | ``ecg_peaks.py`` (P/Q/R/S/T) |
| ``evaluate_ver_peak``      | ``ver_classifier.py`` — SNR/latency gates | ``ecg_classifier.py``        |
| ``save_ver_report``        | ``ver_report.py`` — PDF/CSV generation    | ``ecg_report.py``            |
| ``refresh_classifier_cfg`` | propagates settings across modules        | update in place              |
+----------------------------+-------------------------------------------+------------------------------+

**NOT managed here (handled separately):**

- ``ECGScopeProcessor`` (``ecg_scope.py``) — ECG-oriented placeholder
  boundary for trigger/epoch/averaging.  It is currently backed by inherited
  ``VERScopeProcessor`` logic from ``ver_scope.py`` and is the first module
  transition boundary (REPLACEMENT TARGET 1).  See
  ``docs/ecg-transition-priorities.md`` for sequencing/risk notes.

**How to apply ECG modules via this boundary:**

1. Implement ``ecg_peaks.py``, ``ecg_classifier.py``, and ``ecg_report.py``.
2. Update the imports *inside this file* to pull from the new ECG modules
   instead of the ``ver_*`` modules.
3. No other changes to ``ver_main.py`` are needed for those three modules.
4. Remove or rename this file once all VER analysis modules are replaced.

See ``docs/ecg-transition-priorities.md`` for the full ranked replacement
sequence and safe ordering rationale.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Public API of this adapter module — defines the VER analysis engine surface
# ---------------------------------------------------------------------------
__all__ = [
    "detect_ver_peaks",
    "evaluate_ver_peak",
    "save_ver_report",
    "refresh_classifier_cfg",
]

# ---------------------------------------------------------------------------
# INHERITED VER ANALYSIS ENGINE — all re-exported through this adapter layer
# ---------------------------------------------------------------------------

# REPLACEMENT TARGET 2 — ver_peaks.py → ecg_peaks.py
# ECG equivalent: R-peak / P / Q / R / S / T morphology detection
from ver_peaks import detect_ver_peaks
from ver_peaks import refresh_classifier_cfg as _refresh_peaks_cfg

# REPLACEMENT TARGET 3 — ver_classifier.py → ecg_classifier.py
# ECG equivalent: QRS duration, PR/QT interval, rhythm classification
from ver_classifier import evaluate_ver_peak
from ver_classifier import refresh_classifier_cfg as _refresh_classifier_cfg

# REPLACEMENT TARGET 4 — ver_report.py → ecg_report.py
# ECG equivalent: PDF/CSV with ECG-standard metrics and interval tables
from ver_report import save_ver_report


def refresh_classifier_cfg(cfg: dict) -> None:
    """Propagate updated classifier/peak settings to all VER analysis modules.

    Call this after the user saves settings in the GUI so that the next
    analysis run picks up the new configuration without a restart.

    ECG equivalent: call the analogous refresh functions in the ECG peaks
    and classifier modules when they replace ``ver_peaks`` and
    ``ver_classifier``.
    """
    _refresh_peaks_cfg(cfg)
    _refresh_classifier_cfg(cfg)
