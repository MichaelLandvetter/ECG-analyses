"""ECG-oriented report placeholder interface.

TRANSITIONAL MODULE — REPLACEMENT TARGET 4 (report/classifier boundary)
========================================================================
This module defines the ECG-facing boundary for replacing the inherited
VER-specific report generator.  It intentionally does **not** implement ECG
report logic yet.  Instead it keeps the application runnable by delegating to
the inherited ``save_ver_report`` function from ``ver_report.py``.

Responsibilities of this placeholder boundary:
- expose a neutrally-named ``save_ecg_report`` function to callers
- accept the same parameters as the underlying VER report function
- return the same result dict (``png``, ``pdf``, ``report_dir``,
  ``summary_csv``, ``waveforms_csv``) so callers require no structural changes
- isolate direct caller dependency on ``ver_report.py`` so future ECG report
  logic can be swapped in here with minimal caller changes

Inherited behavior still used underneath:
- PDF figure layout (``_build_figures_page``, ``_build_stats_table_page``)
- CSV column headers still use VER labels (``VER_label``, ``N_flashes_total``,
  ``N_flashes_accepted``) — these will be replaced when the ECG scope/peak
  schema is finalised
- Report wording, statistics page title, and axis labels from ``ver_report.py``

Future replacement path:
- Replace the delegation inside ``save_ecg_report`` with real ECG report
  generation logic (ECG-standard metrics: RR interval, QRS width, PR/QT
  interval tables; ECG-labelled CSV columns; ECG-oriented PDF layout).
- Update parameter names to reflect ECG session structure (``session_beats``
  instead of ``session_ver_peaks``, ``beats_per_block`` instead of flash counts,
  etc.) once the scope/peak modules are replaced.
- Adjacent next replacement targets after this boundary is established:
  ``ver_peaks.py`` (Rank 2) and coordinated classifier/report schema update.

See ``docs/ecg-transition-priorities.md § Rank 5`` and ``TRANSITION.md``.
"""

from __future__ import annotations

from typing import List, Optional

import numpy as np

# INHERITED VER ANALYSIS ENGINE — delegated through this placeholder boundary.
# Replace this import with ECG-specific report logic when implementing ecg_report.
from src.ecg_analyses.ver.ver_report import save_ver_report as _save_ver_report

def save_ecg_report(
    data_file_path: str,
    session_averages: List[np.ndarray],
    epoch_time_ms: np.ndarray,
    session_wavelets: Optional[List[np.ndarray]] = None,
    session_wavelet_freqs: Optional[np.ndarray] = None,
    session_labels: Optional[List[str]] = None,
    session_ver_peaks: Optional[List[dict]] = None,
    session_flash_counts: Optional[List[Optional[int]]] = None,
    session_flash_counts_accepted: Optional[List[Optional[int]]] = None,
    session_artifact_rejection_enabled: Optional[List[Optional[bool]]] = None,
    session_artifact_exclusion_thresholds: Optional[List[Optional[float]]] = None,
    human_overrides: Optional[List[bool]] = None,
    force_stem: Optional[str] = None,
) -> Optional[dict]:
    """Generate and save the transitional ECG analysis report.

    This is an ECG-named placeholder that currently delegates entirely to the
    inherited VER report generator.  The PDF and CSV output produced here is
    therefore VER-domain output with VER-specific labels — it is **not** a
    true ECG report.

    Parameters match ``ver_report.save_ver_report`` exactly.  They will be
    updated when the scope, peaks, and classifier modules are replaced:
    - ``session_ver_peaks`` will become ``session_signal_features`` or similar
    - ``session_flash_counts`` will become ``session_beat_counts``
    - Inherited VER CSV columns (``VER_label``, ``N_flashes_total``) will be
      replaced with ECG-standard metrics

    Returns
    -------
    dict or None
        ``{"png": ..., "pdf": ..., "report_dir": ..., "summary_csv": ...,
        "waveforms_csv": ...}`` on success, ``None`` if no session data.
    """
    # Delegate to inherited VER report — to be replaced with ECG report logic.
    return _save_ver_report(
        data_file_path,
        session_averages,
        epoch_time_ms,
        session_wavelets=session_wavelets,
        session_wavelet_freqs=session_wavelet_freqs,
        session_labels=session_labels,
        session_ver_peaks=session_ver_peaks,
        session_flash_counts=session_flash_counts,
        session_flash_counts_accepted=session_flash_counts_accepted,
        session_artifact_rejection_enabled=session_artifact_rejection_enabled,
        session_artifact_exclusion_thresholds=session_artifact_exclusion_thresholds,
        human_overrides=human_overrides,
        force_stem=force_stem,
    )
