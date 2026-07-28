"""Extended NeuroKit2-derived ECG summary report generator.

Produces a single-row CSV with rich HRV, rate, and morphology metrics
derived from a completed ECG offline analysis run.  This is the **third**
CSV output alongside the two existing reports:

  1. ``{prefix}_beat_summary.csv``      — per-beat R-peak / RR / HR table
  2. ``{prefix}_continuous_signals.csv`` — time-series raw / filtered / HR
  3. ``{prefix}_extended_nk_summary.csv`` — single-row NeuroKit2 summary (THIS FILE)

All expensive or error-prone metric categories are individually guarded
so a failure in one category never prevents the others from being written.
If NeuroKit2 is unavailable, rate statistics and morphology estimates are
still written; HRV columns are simply left empty.

Public API
----------
compute_extended_nk_metrics(report_data) -> dict
    Returns a flat dict of all available metrics.

save_extended_nk_summary_csv(report_data, out_path)
    Writes the single-row CSV to *out_path*.
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Any

import numpy as np

# ---------------------------------------------------------------------------
# Physiological search-window constants for beat-by-beat wave matching
# (all values are in seconds relative to each R-peak)
# ---------------------------------------------------------------------------
# P wave: expected 300 ms to 50 ms BEFORE the R-peak
_P_SEARCH_LO_S: float = 0.30
_P_SEARCH_HI_S: float = 0.05
# Q wave: expected 100 ms to 5 ms BEFORE the R-peak
_Q_SEARCH_LO_S: float = 0.10
_Q_SEARCH_HI_S: float = 0.005
# S wave: expected 5 ms to 120 ms AFTER the R-peak
_S_SEARCH_LO_S: float = 0.005
_S_SEARCH_HI_S: float = 0.12
# T wave: expected 50 ms to 500 ms AFTER the R-peak
_T_SEARCH_LO_S: float = 0.05
_T_SEARCH_HI_S: float = 0.50

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional NeuroKit2 import — same guard pattern as ecg_pipeline.py
# ---------------------------------------------------------------------------
try:
    import neurokit2 as nk  # type: ignore
    _NK_AVAILABLE = True
except ImportError:
    nk = None
    _NK_AVAILABLE = False
    log.debug(
        "NeuroKit2 not available — HRV metrics will be skipped in the extended summary CSV."
    )


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def compute_extended_nk_metrics(report_data: dict) -> dict[str, Any]:
    """Compute extended ECG metrics from a completed offline analysis.

    Builds a flat ``{column: value}`` dict suitable for a single-row CSV.
    Each metric category is wrapped in its own exception handler so partial
    failures leave that category empty without aborting the whole export.

    Parameters
    ----------
    report_data:
        Pre-report data dict produced by
        ``VERMainWindow._build_pre_report_data``.  Expected keys:
        ``sample_rate``, ``raw_signal``, ``filtered_signal``,
        ``r_peak_indices``, ``r_peak_times_s``, ``hr_times_s``, ``hr_bpm``,
        ``beat_count``, ``mean_hr_bpm``, ``duration_s``, ``source_label``,
        ``output_prefix``, ``p_peak_indices``, ``q_peak_indices``,
        ``s_peak_indices``, ``t_peak_indices``.

    Returns
    -------
    dict
        Flat mapping of metric name → value (float, int, str, or ``""``).
        Empty string signals a missing or unavailable value.
    """
    row: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------
    row["source_label"] = str(report_data.get("source_label", ""))
    row["sample_rate"] = float(report_data.get("sample_rate", 0.0))
    row["duration_s"] = float(report_data.get("duration_s", 0.0))
    row["beat_count"] = int(report_data.get("beat_count", 0))

    fs = float(report_data.get("sample_rate", 250.0))
    hr_bpm = np.asarray(report_data.get("hr_bpm", []), dtype=float)
    r_peaks = np.asarray(report_data.get("r_peak_indices", []), dtype=int)

    # ------------------------------------------------------------------
    # Core rate statistics
    # ------------------------------------------------------------------
    try:
        if hr_bpm.size >= 2:
            row["ECG_Rate_Mean"] = float(np.mean(hr_bpm))
            row["ECG_Rate_SD"] = float(np.std(hr_bpm, ddof=1))
            row["ECG_Rate_Max"] = float(np.max(hr_bpm))
            row["ECG_Rate_Min"] = float(np.min(hr_bpm))
        else:
            row["ECG_Rate_Mean"] = ""
            row["ECG_Rate_SD"] = ""
            row["ECG_Rate_Max"] = ""
            row["ECG_Rate_Min"] = ""
    except Exception as exc:
        log.warning("Rate statistics failed: %s", exc)
        row.setdefault("ECG_Rate_Mean", "")
        row.setdefault("ECG_Rate_SD", "")
        row.setdefault("ECG_Rate_Max", "")
        row.setdefault("ECG_Rate_Min", "")

    # ------------------------------------------------------------------
    # NeuroKit2 HRV metrics (time-domain, frequency-domain, nonlinear)
    # ------------------------------------------------------------------
    if _NK_AVAILABLE and r_peaks.size >= 4:
        try:
            fs_int = int(round(fs))
            if abs(fs - fs_int) > 0.1:
                log.warning(
                    "Sample rate %.4f Hz rounds to %d Hz; large rounding may affect HRV accuracy.",
                    fs,
                    fs_int,
                )
            hrv_df = nk.hrv(r_peaks, sampling_rate=fs_int, show=False)
            for col in hrv_df.columns:
                val = hrv_df[col].iloc[0]
                if val is None or (isinstance(val, float) and np.isnan(val)):
                    row[col] = ""
                else:
                    try:
                        row[col] = float(val)
                    except (TypeError, ValueError):
                        row[col] = str(val)
        except Exception as exc:
            log.warning(
                "nk.hrv failed; HRV columns omitted from extended summary: %s", exc
            )
    elif not _NK_AVAILABLE:
        log.debug("NeuroKit2 not available; HRV columns skipped in extended summary.")
    else:
        log.debug(
            "Too few beats (%d) for reliable HRV metrics; skipped.", int(r_peaks.size)
        )

    # ------------------------------------------------------------------
    # Morphology metrics from delineated P/Q/S/T wave peak indices
    # ------------------------------------------------------------------
    _add_morphology_metrics(row, report_data, fs, r_peaks)

    return row


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _add_morphology_metrics(
    row: dict[str, Any],
    report_data: dict,
    fs: float,
    r_peaks: np.ndarray,
) -> None:
    """Compute per-beat morphology metrics and add means to *row* in-place.

    Uses delineated P/Q/S/T peak indices stored in *report_data*.  For each
    R-peak the nearest wave peak within a physiological search window is
    matched; the metric is the mean across all successfully matched beats.

    Durations are reported in **milliseconds**.  Columns are pre-filled with
    ``""`` so that even a complete failure leaves all keys present in *row*.

    Metrics computed
    ----------------
    ECG_PR_Interval_Mean
        Mean P-peak → R-peak interval (ms).  P-duration (onset→offset) is
        not computed because only peak positions are stored.
    ECG_QRS_Duration_Mean
        Mean Q-peak → S-peak duration (ms).
    ECG_QT_Interval_Mean
        Mean Q-peak → T-peak duration (ms).
    ECG_QTc_Mean
        Bazett-corrected mean QT (QT_ms / sqrt(RR_s)) in ms.
    ECG_P_Duration_Mean, ECG_T_Duration_Mean
        Set to ``""``; onset/offset positions are not stored by the current
        pipeline and cannot be computed from peaks alone.
    """
    morphology_keys = [
        "ECG_P_Duration_Mean",
        "ECG_PR_Interval_Mean",
        "ECG_QRS_Duration_Mean",
        "ECG_QT_Interval_Mean",
        "ECG_QTc_Mean",
        "ECG_T_Duration_Mean",
    ]
    # Pre-fill all fields so the columns are always present in the CSV
    for k in morphology_keys:
        row[k] = ""

    if r_peaks.size < 2:
        return

    p_idx = np.asarray(report_data.get("p_peak_indices", []), dtype=int)
    q_idx = np.asarray(report_data.get("q_peak_indices", []), dtype=int)
    s_idx = np.asarray(report_data.get("s_peak_indices", []), dtype=int)
    t_idx = np.asarray(report_data.get("t_peak_indices", []), dtype=int)

    # All four wave arrays are empty → nothing to compute
    if not any(arr.size for arr in (p_idx, q_idx, s_idx, t_idx)):
        return

    # Physiological search windows relative to each R-peak (in samples).
    _p_lo = -int(round(_P_SEARCH_LO_S * fs))  # P: 300 ms before R
    _p_hi = -int(round(_P_SEARCH_HI_S * fs))  # P: 50 ms before R
    _q_lo = -int(round(_Q_SEARCH_LO_S * fs))  # Q: 100 ms before R
    _q_hi = -int(round(_Q_SEARCH_HI_S * fs))  # Q: 5 ms before R
    _s_lo =  int(round(_S_SEARCH_LO_S * fs))  # S: 5 ms after R
    _s_hi =  int(round(_S_SEARCH_HI_S * fs))  # S: 120 ms after R
    _t_lo =  int(round(_T_SEARCH_LO_S * fs))  # T: 50 ms after R
    _t_hi =  int(round(_T_SEARCH_HI_S * fs))  # T: 500 ms after R

    try:
        pr_ms: list[float] = []
        qrs_ms: list[float] = []
        qt_ms: list[float] = []
        qtc_ms: list[float] = []

        for i, r in enumerate(r_peaks.tolist()):
            # RR interval needed for Bazett QTc (use preceding beat's RR)
            rr_s: float | None = (r - r_peaks[i - 1]) / fs if i > 0 else None

            # --- PR interval: distance from nearest preceding P peak to R ---
            if p_idx.size:
                in_win = p_idx[(p_idx >= r + _p_lo) & (p_idx <= r + _p_hi)]
                if in_win.size:
                    nearest_p = int(in_win[np.argmin(np.abs(in_win - r))])
                    pr_ms.append((r - nearest_p) * 1000.0 / fs)

            # --- QRS and QT: need matched Q in each beat ---
            nearest_q: int | None = None
            if q_idx.size:
                in_win_q = q_idx[(q_idx >= r + _q_lo) & (q_idx <= r + _q_hi)]
                if in_win_q.size:
                    nearest_q = int(in_win_q[np.argmin(np.abs(in_win_q - r))])

            # QRS duration: Q → S
            if nearest_q is not None and s_idx.size:
                in_win_s = s_idx[(s_idx >= r + _s_lo) & (s_idx <= r + _s_hi)]
                if in_win_s.size:
                    nearest_s = int(in_win_s[np.argmin(np.abs(in_win_s - r))])
                    dur = (nearest_s - nearest_q) * 1000.0 / fs
                    if dur > 0:
                        qrs_ms.append(dur)

            # QT interval: Q → T; also compute Bazett QTc if RR available
            if nearest_q is not None and t_idx.size:
                in_win_t = t_idx[(t_idx >= r + _t_lo) & (t_idx <= r + _t_hi)]
                if in_win_t.size:
                    nearest_t = int(in_win_t[np.argmin(np.abs(in_win_t - r))])
                    dur = (nearest_t - nearest_q) * 1000.0 / fs
                    if dur > 0:
                        qt_ms.append(dur)
                        if rr_s and rr_s > 0:
                            # Bazett's formula: QTc = QT_ms / sqrt(RR_s)
                            qtc_ms.append(dur / np.sqrt(rr_s))

        if pr_ms:
            row["ECG_PR_Interval_Mean"] = float(np.mean(pr_ms))
        if qrs_ms:
            row["ECG_QRS_Duration_Mean"] = float(np.mean(qrs_ms))
        if qt_ms:
            row["ECG_QT_Interval_Mean"] = float(np.mean(qt_ms))
        if qtc_ms:
            row["ECG_QTc_Mean"] = float(np.mean(qtc_ms))

    except Exception as exc:
        log.warning("Morphology metric computation failed: %s", exc)


def save_extended_nk_summary_csv(report_data: dict, out_path: Path) -> None:
    """Write a single-row extended NeuroKit2 summary CSV to *out_path*.

    Always writes a file: unavailable metrics are left as empty cells
    rather than aborting.  The parent directory of *out_path* must exist.

    Parameters
    ----------
    report_data:
        Pre-report data dict (see :func:`compute_extended_nk_metrics`).
    out_path:
        Destination ``Path`` for the CSV file.

    Raises
    ------
    OSError
        If the file cannot be created (e.g. permission denied).
    """
    metrics = compute_extended_nk_metrics(report_data)
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(metrics.keys()))
        writer.writeheader()
        writer.writerow(metrics)
    log.info("Extended NeuroKit2 summary CSV written: %s", out_path)
