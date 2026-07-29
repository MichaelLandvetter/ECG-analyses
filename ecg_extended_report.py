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
import re
from pathlib import Path
from typing import Any

import numpy as np

# ---------------------------------------------------------------------------
# Physiological search-window constants for beat-by-beat wave matching
# (all values are in seconds, measured from each R-peak)
# ---------------------------------------------------------------------------
# P wave: expected 300 ms to 50 ms BEFORE the R-peak
_P_SEARCH_FAR_S: float = 0.30   # far (earliest) edge of search window
_P_SEARCH_NEAR_S: float = 0.05  # near (latest) edge of search window
# Q wave: expected 100 ms to 5 ms BEFORE the R-peak
_Q_SEARCH_FAR_S: float = 0.10
_Q_SEARCH_NEAR_S: float = 0.005
# S wave: expected 5 ms to 120 ms AFTER the R-peak
_S_SEARCH_NEAR_S: float = 0.005
_S_SEARCH_FAR_S: float = 0.12
# T wave: expected 50 ms to 500 ms AFTER the R-peak
_T_SEARCH_NEAR_S: float = 0.05
_T_SEARCH_FAR_S: float = 0.50

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

def _find_nearest_wave(
    wave_idx: np.ndarray,
    r: int,
    window_start: int,
    window_end: int,
) -> int | None:
    """Return the sample index of the nearest wave peak to *r* within a window.

    Parameters
    ----------
    wave_idx:
        Array of sample indices for a wave type (P / Q / S / T).
    r:
        R-peak sample index (the reference point).
    window_start, window_end:
        Inclusive sample-index bounds of the search window (absolute indices,
        already offset from *r*).  ``window_start`` must be ≤ ``window_end``.

    Returns
    -------
    int or None
        Sample index of the nearest matching peak, or ``None`` if no peak
        falls within the window.
    """
    if wave_idx.size == 0:
        return None
    in_win = wave_idx[(wave_idx >= window_start) & (wave_idx <= window_end)]
    if in_win.size == 0:
        return None
    return int(in_win[np.argmin(np.abs(in_win - r))])


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
        Bazett-corrected mean QT (QT_ms / sqrt(RR_s)) in ms, using the
        following RR interval (i.e. the interval from the current R-peak
        to the next R-peak), which is the beat containing the QT measurement.
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
    _p_far  = int(round(_P_SEARCH_FAR_S  * fs))  # P far edge: 300 ms before R
    _p_near = int(round(_P_SEARCH_NEAR_S * fs))  # P near edge: 50 ms before R
    _q_far  = int(round(_Q_SEARCH_FAR_S  * fs))  # Q far edge: 100 ms before R
    _q_near = int(round(_Q_SEARCH_NEAR_S * fs))  # Q near edge: 5 ms before R
    _s_near = int(round(_S_SEARCH_NEAR_S * fs))  # S near edge: 5 ms after R
    _s_far  = int(round(_S_SEARCH_FAR_S  * fs))  # S far edge: 120 ms after R
    _t_near = int(round(_T_SEARCH_NEAR_S * fs))  # T near edge: 50 ms after R
    _t_far  = int(round(_T_SEARCH_FAR_S  * fs))  # T far edge: 500 ms after R

    try:
        pr_ms: list[float] = []
        qrs_ms: list[float] = []
        qt_ms: list[float] = []
        qtc_ms: list[float] = []

        for i, r in enumerate(r_peaks):
            r = int(r)
            # RR interval for Bazett QTc: use the following RR interval
            # (current R-peak to next R-peak), which is the beat that
            # contains the QT measurement being corrected.
            rr_s: float | None = (
                (r_peaks[i + 1] - r) / fs if i < r_peaks.size - 1 else None
            )

            # --- PR interval: nearest P peak in window [r-300ms, r-50ms] ---
            nearest_p = _find_nearest_wave(p_idx, r, r - _p_far, r - _p_near)
            if nearest_p is not None:
                pr_ms.append((r - nearest_p) * 1000.0 / fs)

            # --- QRS: Q in [r-100ms, r-5ms] matched to S in [r+5ms, r+120ms] ---
            nearest_q = _find_nearest_wave(q_idx, r, r - _q_far, r - _q_near)
            if nearest_q is not None:
                nearest_s = _find_nearest_wave(s_idx, r, r + _s_near, r + _s_far)
                if nearest_s is not None:
                    dur = (nearest_s - nearest_q) * 1000.0 / fs
                    if dur > 0:
                        qrs_ms.append(dur)

                # --- QT interval: Q → T where T is in [r+50ms, r+500ms] ---
                nearest_t = _find_nearest_wave(t_idx, r, r + _t_near, r + _t_far)
                if nearest_t is not None:
                    dur = (nearest_t - nearest_q) * 1000.0 / fs
                    if dur > 0:
                        qt_ms.append(dur)
                        if rr_s and rr_s > 0:
                            # Bazett's formula: QTc_ms = QT_ms / sqrt(RR_s)
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


def sanitize_output_stem(stem: str | None, fallback: str = "ecg_analysis") -> str:
    """Return a filesystem-safe output stem with a stable fallback."""
    base = (stem or "").strip()
    if not base:
        return fallback
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._-")
    return safe or fallback


def _nearest_waves_for_r(r: int, fs: float, p_idx: np.ndarray, q_idx: np.ndarray, s_idx: np.ndarray, t_idx: np.ndarray) -> tuple[int | None, int | None, int | None, int | None]:
    _p_far = int(round(_P_SEARCH_FAR_S * fs))
    _p_near = int(round(_P_SEARCH_NEAR_S * fs))
    _q_far = int(round(_Q_SEARCH_FAR_S * fs))
    _q_near = int(round(_Q_SEARCH_NEAR_S * fs))
    _s_near = int(round(_S_SEARCH_NEAR_S * fs))
    _s_far = int(round(_S_SEARCH_FAR_S * fs))
    _t_near = int(round(_T_SEARCH_NEAR_S * fs))
    _t_far = int(round(_T_SEARCH_FAR_S * fs))
    p = _find_nearest_wave(p_idx, r, r - _p_far, r - _p_near)
    q = _find_nearest_wave(q_idx, r, r - _q_far, r - _q_near)
    s = _find_nearest_wave(s_idx, r, r + _s_near, r + _s_far)
    t = _find_nearest_wave(t_idx, r, r + _t_near, r + _t_far)
    return p, q, s, t


def _write_continuous_time_series_csv(report_data: dict, out_path: Path) -> None:
    fs = float(report_data["sample_rate"])
    raw = np.asarray(report_data["raw_signal"], dtype=float)
    filt = np.asarray(report_data["filtered_signal"], dtype=float)
    hr_times = np.asarray(report_data.get("hr_times_s", []), dtype=float)
    hr_bpm = np.asarray(report_data.get("hr_bpm", []), dtype=float)
    peak_idx = np.asarray(report_data.get("r_peak_indices", []), dtype=int)
    quality = np.asarray(report_data.get("signal_quality", []), dtype=float)
    if quality.size != raw.size:
        quality = np.full(raw.size, np.nan, dtype=float)

    time_s = np.arange(raw.size, dtype=float) / fs
    hr_per_sample = np.full(raw.size, np.nan, dtype=float)
    if hr_times.size and hr_bpm.size:
        indices = np.round(hr_times * fs).astype(int)
        valid_mask = (indices >= 0) & (indices < raw.size)
        hr_per_sample[indices[valid_mask]] = hr_bpm[valid_mask]

    r_indicator = np.zeros(raw.size, dtype=int)
    valid_peaks = peak_idx[(peak_idx >= 0) & (peak_idx < raw.size)]
    r_indicator[valid_peaks] = 1

    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "Time_Seconds",
                "ECG_Raw",
                "ECG_Clean",
                "Heart_Rate_BPM",
                "Signal_Quality",
                "R_Peak_Indicator",
            ]
        )
        for i in range(raw.size):
            writer.writerow(
                [
                    f"{time_s[i]:.6f}",
                    f"{raw[i]:.9f}",
                    f"{filt[i]:.9f}",
                    "" if np.isnan(hr_per_sample[i]) else f"{hr_per_sample[i]:.6f}",
                    "" if np.isnan(quality[i]) else f"{quality[i]:.6f}",
                    int(r_indicator[i]),
                ]
            )


def _write_beat_morphology_csv(report_data: dict, out_path: Path) -> None:
    fs = float(report_data["sample_rate"])
    r_peaks = np.asarray(report_data.get("r_peak_indices", []), dtype=int)
    p_idx = np.asarray(report_data.get("p_peak_indices", []), dtype=int)
    q_idx = np.asarray(report_data.get("q_peak_indices", []), dtype=int)
    s_idx = np.asarray(report_data.get("s_peak_indices", []), dtype=int)
    t_idx = np.asarray(report_data.get("t_peak_indices", []), dtype=int)

    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "Beat_Number",
                "R_Peak_Sample",
                "R_Peak_Time_Sec",
                "P_Peak_Sample",
                "Q_Peak_Sample",
                "S_Peak_Sample",
                "T_Peak_Sample",
                "RR_Interval_ms",
                "PR_Interval_ms",
                "QRS_Duration_ms",
                "QT_Interval_ms",
            ]
        )
        prev_r: int | None = None
        for beat_no, r in enumerate(r_peaks.tolist(), start=1):
            p, q, s, t = _nearest_waves_for_r(int(r), fs, p_idx, q_idx, s_idx, t_idx)

            rr_ms = np.nan if prev_r is None else ((r - prev_r) * 1000.0 / fs)
            pr_ms = np.nan if p is None else ((r - p) * 1000.0 / fs)
            qrs_ms = np.nan
            if q is not None and s is not None and s > q:
                qrs_ms = (s - q) * 1000.0 / fs
            qt_ms = np.nan
            if q is not None and t is not None and t > q:
                qt_ms = (t - q) * 1000.0 / fs

            writer.writerow(
                [
                    beat_no,
                    int(r),
                    f"{(r / fs):.6f}",
                    p if p is not None else np.nan,
                    q if q is not None else np.nan,
                    s if s is not None else np.nan,
                    t if t is not None else np.nan,
                    rr_ms,
                    pr_ms,
                    qrs_ms,
                    qt_ms,
                ]
            )
            prev_r = int(r)


def _write_hrv_summary_csv(report_data: dict, out_path: Path) -> None:
    fs = float(report_data["sample_rate"])
    r_peaks = np.asarray(report_data.get("r_peak_indices", []), dtype=int)
    row: dict[str, Any] = {
        "Source_Label": str(report_data.get("source_label", "")),
        "Sample_Rate_Hz": fs,
        "Beat_Count": int(r_peaks.size),
    }

    if _NK_AVAILABLE and r_peaks.size >= 4:
        try:
            fs_int = int(round(fs))
            hrv_df = nk.hrv(r_peaks, sampling_rate=fs_int, show=False)
            for col in hrv_df.columns:
                val = hrv_df[col].iloc[0]
                if val is None or (isinstance(val, float) and np.isnan(val)):
                    row[col] = np.nan
                else:
                    row[col] = val
        except Exception as exc:
            log.warning("HRV summary export failed to compute nk.hrv metrics: %s", exc)
    elif not _NK_AVAILABLE:
        log.debug("HRV summary export: NeuroKit2 unavailable.")
    else:
        log.debug("HRV summary export: too few beats (%d).", int(r_peaks.size))

    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(row.keys()))
        writer.writeheader()
        writer.writerow(row)


def _write_average_template_csv(report_data: dict, out_path: Path) -> None:
    fs = float(report_data["sample_rate"])
    filt = np.asarray(report_data.get("filtered_signal", []), dtype=float)
    r_peaks = np.asarray(report_data.get("r_peak_indices", []), dtype=int)

    before_s = 0.25
    after_s = 0.45
    before_n = int(round(before_s * fs))
    after_n = int(round(after_s * fs))
    win_len = before_n + after_n + 1

    beats: list[np.ndarray] = []
    for r in r_peaks.tolist():
        start = int(r) - before_n
        end = int(r) + after_n + 1
        if start < 0 or end > filt.size:
            continue
        beat = filt[start:end]
        if beat.size == win_len:
            beats.append(beat)

    rel_time_s = (np.arange(win_len, dtype=float) - before_n) / fs
    if beats:
        stacked = np.vstack(beats)
        mean_amp = np.mean(stacked, axis=0)
        std_amp = np.std(stacked, axis=0, ddof=0)
    else:
        mean_amp = np.full(win_len, np.nan, dtype=float)
        std_amp = np.full(win_len, np.nan, dtype=float)

    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["Relative_Time_Sec", "Mean_Amplitude_mV", "Std_Dev_mV"])
        for i in range(win_len):
            writer.writerow([f"{rel_time_s[i]:.6f}", mean_amp[i], std_amp[i]])


def save_neurokit2_report_set(report_data: dict, out_dir: Path, output_stem: str | None = None) -> dict[str, Path | None]:
    """Write the 4-file NeuroKit2 ECG report set using source-stem naming.

    The stem is derived from the analyzed source file label/prefix (sanitized),
    with ``ecg_analysis`` fallback when unavailable.

    Files:
    - ``*_ecg_continuous_time_series.csv``: continuous raw/clean/rate/quality/R-markers
    - ``*_ecg_beat_morphology_landmarks.csv``: beat-wise morphology landmarks + intervals
    - ``*_ecg_hrv_summary_metrics.csv``: NeuroKit2 HRV summary from this run context
    - ``*_ecg_average_template_wave.csv``: average beat template (mean/std wave)
    """
    stem = sanitize_output_stem(output_stem or str(report_data.get("output_prefix", "")))
    paths = {
        "continuous": out_dir / f"{stem}_ecg_continuous_time_series.csv",
        "morphology": out_dir / f"{stem}_ecg_beat_morphology_landmarks.csv",
        "hrv_summary": out_dir / f"{stem}_ecg_hrv_summary_metrics.csv",
        "average_template": out_dir / f"{stem}_ecg_average_template_wave.csv",
    }
    writers = {
        "continuous": _write_continuous_time_series_csv,
        "morphology": _write_beat_morphology_csv,
        "hrv_summary": _write_hrv_summary_csv,
        "average_template": _write_average_template_csv,
    }
    written: dict[str, Path | None] = {}
    for key, writer in writers.items():
        path = paths[key]
        try:
            writer(report_data, path)
            log.info("ECG report CSV written: %s", path)
            written[key] = path
        except Exception as exc:
            log.warning("ECG report CSV (%s) could not be written: %s", key, exc)
            written[key] = None
    return written
