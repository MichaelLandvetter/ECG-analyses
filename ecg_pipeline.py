"""ECG processing pipeline: cleaning, R-peak detection, and heart-rate computation.

This module introduces the first real ECG-specific analysis layer.

Architecture
------------
Three levels are provided, each with a clear interface:

1. **ECGCleaningFilter** — batch signal cleaning / filtering.
   Supports four selectable strategies (see ``ECG_FILTER_*`` constants):

   * ``Butterworth bandpass``     — zero-phase IIR Butterworth (default 0.5–40 Hz)
   * ``Zero-phase IIR bandpass``  — identical path, explicit zero-phase name
   * ``Zero-phase IIR + Notch``   — Butterworth + IIR notch (50 or 60 Hz)
   * ``NeuroKit2 ecg_clean``      — ``nk.ecg_clean`` (requires NeuroKit2; falls
                                     back to Butterworth if library is absent)

2. **ECGRPeakDetector** — batch R-peak detection on a cleaned signal array.
   Wraps NeuroKit2 ``nk.ecg_peaks`` (when available) with a SciPy-based
   fallback.  Selectable method strings are defined as ``ECG_DETECTOR_*``.

3. **ECGRollingProcessor** — streaming / rolling-window coordinator.
   Maintains an internal circular buffer and runs detection every
   ``detection_interval_s`` seconds.  Only peaks confirmed outside the
   configurable boundary-guard zone are reported, preventing spurious
   edge detections from leaking across chunk boundaries.

4. **ECGOfflineProcessor** — whole-file batch coordinator.
   Accepts the full signal array and processes it in one pass (optionally
   using ``nk.ecg_process`` for best-accuracy results).  Designed for use
   when ``speed_factor=None`` (maximum speed) so that all computation
   completes before the display is updated.

Extension points (deferred to future PRs)
------------------------------------------
- ``nk.ecg_delineate``  (P/Q/S/T wave boundaries)
- ``nk.ecg_quality``    (signal quality index)
- HRV metrics (RMSSD, SDNN)
- Arrhythmia classification
"""

from __future__ import annotations

import logging
import sys
from collections import deque
from dataclasses import dataclass, field
from typing import NamedTuple

import numpy as np
from scipy.signal import butter, sosfiltfilt, sosfilt, sosfilt_zi, iirnotch, filtfilt

log = logging.getLogger(__name__)
frozen_debug_log = logging.getLogger("ver.frozen_debug")

# ---------------------------------------------------------------------------
# Optional NeuroKit2 import
# ---------------------------------------------------------------------------
try:
    import neurokit2 as nk  # type: ignore
    _NK_AVAILABLE = True
except ImportError:
    nk = None
    _NK_AVAILABLE = False
    log.debug("NeuroKit2 not installed — ECG_FILTER_NEUROKIT2 and NK2 detectors will "
              "fall back to Butterworth / SciPy-based detection.")

# ---------------------------------------------------------------------------
# Filter mode string constants (canonical keys — use these, not raw strings)
# ---------------------------------------------------------------------------
ECG_FILTER_BUTTERWORTH    = "Butterworth bandpass"
ECG_FILTER_ZEROPHASE_IIR  = "Zero-phase IIR bandpass"
ECG_FILTER_IIR_NOTCH      = "Zero-phase IIR + Notch"
ECG_FILTER_NEUROKIT2      = "NeuroKit2 ecg_clean"

ECG_FILTER_MODES: list[str] = [
    ECG_FILTER_BUTTERWORTH,
    ECG_FILTER_ZEROPHASE_IIR,
    ECG_FILTER_IIR_NOTCH,
    ECG_FILTER_NEUROKIT2,
]
ECG_FILTER_DEFAULT: str = ECG_FILTER_BUTTERWORTH

# ---------------------------------------------------------------------------
# R-peak detector method constants
# ---------------------------------------------------------------------------
ECG_DETECTOR_NEUROKIT    = "neurokit"
ECG_DETECTOR_HAMILTON    = "hamilton2002"
ECG_DETECTOR_PANTOMPKINS = "pantompkins1985"
ECG_DETECTOR_ENGZEE      = "engzeemod2012"

ECG_DETECTOR_METHODS: list[str] = [
    ECG_DETECTOR_NEUROKIT,
    ECG_DETECTOR_HAMILTON,
    ECG_DETECTOR_PANTOMPKINS,
    ECG_DETECTOR_ENGZEE,
]
ECG_DETECTOR_DEFAULT: str = ECG_DETECTOR_NEUROKIT

# ---------------------------------------------------------------------------
# Physiological sanity bounds for RR-interval → BPM
# ---------------------------------------------------------------------------
_MIN_RR_S: float = 0.2   # RR < 0.2 s → HR > 300 BPM (artefact / double detection)
_MAX_RR_S: float = 3.0   # RR > 3.0 s → HR < 20 BPM (missed beat / asystole)

# Minimum number of samples before peak detection is attempted.
_MIN_SAMPLES_FOR_DETECTION: int = 50


# ---------------------------------------------------------------------------
# Result containers
# ---------------------------------------------------------------------------

class ECGRollingResult(NamedTuple):
    """Results returned by :class:`ECGRollingProcessor` after each detection pass."""

    new_peak_indices: list[int]
    """Global sample indices of newly confirmed R-peaks."""

    new_peak_times_s: list[float]
    """Timestamps in seconds (``idx / sample_rate``) for each new R-peak."""

    new_hr_times_s: list[float]
    """Timestamps at which each new HR estimate was computed (second peak in pair)."""

    new_hr_bpm: list[float]
    """Instantaneous heart-rate values in BPM for each RR pair."""


@dataclass
class ECGOfflineResult:
    """Results from a full-file offline analysis pass."""

    filtered_signal: np.ndarray = field(default_factory=lambda: np.array([]))
    """Zero-phase filtered ECG trace."""

    r_peak_indices: list[int] = field(default_factory=list)
    """Sample indices of all detected R-peaks."""

    r_peak_times_s: list[float] = field(default_factory=list)
    """R-peak timestamps in seconds."""

    hr_times_s: list[float] = field(default_factory=list)
    """Timestamps for each instantaneous HR estimate."""

    hr_bpm: list[float] = field(default_factory=list)
    """Instantaneous HR values (BPM)."""

    mean_hr_bpm: float | None = None
    """Mean HR over the whole recording (None if fewer than 2 beats detected)."""

    beat_count: int = 0
    """Total number of confirmed R-peaks detected."""

    duration_s: float = 0.0
    """Duration of the recording in seconds."""

    p_peak_indices: list[int] = field(default_factory=list)
    """Sample indices of P-wave peaks (empty if delineation was not performed)."""

    q_peak_indices: list[int] = field(default_factory=list)
    """Sample indices of Q-wave peaks (empty if delineation was not performed)."""

    s_peak_indices: list[int] = field(default_factory=list)
    """Sample indices of S-wave peaks (empty if delineation was not performed)."""

    t_peak_indices: list[int] = field(default_factory=list)
    """Sample indices of T-wave peaks (empty if delineation was not performed)."""


# ---------------------------------------------------------------------------
# 1. ECGCleaningFilter — static batch filtering utilities
# ---------------------------------------------------------------------------

class ECGCleaningFilter:
    """Batch signal-cleaning utilities for ECG data.

    All methods operate on 1-D ``float64`` NumPy arrays and return a filtered
    array of the same length.  All paths are **zero-phase** (offline-safe).
    For causal real-time filtering, use :class:`ver_filter.BandpassFilter`
    directly.

    Notes
    -----
    * The NeuroKit2 method requires ``neurokit2`` to be installed.  If the
      library is absent, a warning is logged and Butterworth fallback is used.
    * All paths handle very short signals gracefully by adjusting padding.
    """

    @staticmethod
    def clean(
        signal: np.ndarray,
        sample_rate: float = 250.0,
        mode: str = ECG_FILTER_BUTTERWORTH,
        lowcut_hz: float = 0.5,
        highcut_hz: float = 40.0,
        filter_order: int = 4,
        notch_hz: float = 50.0,
        notch_q: float = 30.0,
    ) -> np.ndarray:
        """Apply the selected cleaning strategy to *signal*.

        Parameters
        ----------
        signal:
            Raw 1-D ECG samples.
        sample_rate:
            Sampling frequency in Hz.
        mode:
            One of the ``ECG_FILTER_*`` constants.  Falls back to Butterworth
            on unknown values.
        lowcut_hz, highcut_hz:
            Bandpass corner frequencies (Hz).  Must satisfy
            ``0 < lowcut < highcut < sample_rate / 2``.
        filter_order:
            IIR filter order (Butterworth / zero-phase IIR paths only).
        notch_hz:
            Notch filter frequency in Hz (``ECG_FILTER_IIR_NOTCH`` path only).
        notch_q:
            Notch quality factor (sharpness).

        Returns
        -------
        np.ndarray
            Filtered 1-D float64 array, same length as *signal*.
        """
        signal = np.asarray(signal, dtype=float)
        if signal.size < 2:
            return signal.copy()

        if mode == ECG_FILTER_NEUROKIT2:
            if _NK_AVAILABLE:
                return ECGCleaningFilter._clean_neurokit2(signal, sample_rate)
            log.warning("NeuroKit2 not installed; falling back to Butterworth for ECG cleaning.")
            mode = ECG_FILTER_BUTTERWORTH

        if mode == ECG_FILTER_IIR_NOTCH:
            bp = ECGCleaningFilter._butterworth_zerophase(
                signal, sample_rate, lowcut_hz, highcut_hz, filter_order
            )
            return ECGCleaningFilter._apply_notch(bp, sample_rate, notch_hz, notch_q)

        # Butterworth zero-phase and Zero-phase IIR use the same path
        return ECGCleaningFilter._butterworth_zerophase(
            signal, sample_rate, lowcut_hz, highcut_hz, filter_order
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _butterworth_zerophase(
        signal: np.ndarray,
        sample_rate: float,
        lowcut_hz: float,
        highcut_hz: float,
        order: int,
    ) -> np.ndarray:
        nyquist = sample_rate / 2.0
        low = lowcut_hz / nyquist
        high = highcut_hz / nyquist
        low = max(1e-4, min(low, 0.999))
        high = max(low + 1e-4, min(high, 0.9999))
        try:
            sos = butter(order, [low, high], btype="band", output="sos")
            # sosfiltfilt requires padlen < signal length.  The minimum safe padlen
            # is 3 × (2 * order + 1), which is the SOS filter-state length (two
            # states per section × order sections) multiplied by 3 for edge stability.
            # If the signal is shorter than that, fall back to causal sosfilt to avoid
            # edge artefacts from zero-padding.
            min_padlen = 3 * (2 * order + 1)
            centered = signal - np.mean(signal)
            if signal.size <= min_padlen:
                log.debug(
                    "Butterworth zero-phase: signal too short (%d ≤ %d); using causal sosfilt.",
                    signal.size, min_padlen,
                )
                return sosfilt(sos, centered)
            return sosfiltfilt(sos, centered, padlen=min_padlen)
        except Exception as exc:
            log.warning("Butterworth zero-phase filter failed (%s); returning input.", exc)
            return signal.copy()

    @staticmethod
    def _apply_notch(
        signal: np.ndarray,
        sample_rate: float,
        notch_hz: float,
        q: float,
    ) -> np.ndarray:
        try:
            b, a = iirnotch(notch_hz / (sample_rate / 2.0), q)
            min_padlen = 3 * max(len(b), len(a))
            if signal.size <= min_padlen:
                log.debug(
                    "Notch filter: signal too short (%d ≤ %d); skipping notch.",
                    signal.size, min_padlen,
                )
                return signal.copy()
            return filtfilt(b, a, signal, padlen=min_padlen)
        except Exception as exc:
            log.warning("Notch filter failed (%s); skipping notch step.", exc)
            return signal.copy()

    @staticmethod
    def _clean_neurokit2(signal: np.ndarray, sample_rate: float) -> np.ndarray:
        try:
            cleaned = nk.ecg_clean(signal, sampling_rate=int(round(sample_rate)), method="neurokit")
            return np.asarray(cleaned, dtype=float)
        except Exception as exc:
            log.warning("nk.ecg_clean failed (%s); falling back to Butterworth.", exc)
            return ECGCleaningFilter._butterworth_zerophase(signal, sample_rate, 0.5, 40.0, 4)


# ---------------------------------------------------------------------------
# 2. ECGRPeakDetector — batch R-peak detection
# ---------------------------------------------------------------------------

class ECGRPeakDetector:
    """Detect R-peaks in a pre-cleaned ECG segment.

    Wraps NeuroKit2 ``nk.ecg_peaks`` with a robust SciPy-based fallback so the
    app functions even when NeuroKit2 is not installed.

    Usage::

        detector = ECGRPeakDetector(sample_rate=250)
        indices = detector.detect(cleaned_signal, method=ECG_DETECTOR_NEUROKIT)
    """

    def __init__(self, sample_rate: float = 250.0):
        self.sample_rate = float(sample_rate)

    def detect(
        self,
        cleaned_signal: np.ndarray,
        method: str = ECG_DETECTOR_NEUROKIT,
    ) -> np.ndarray:
        """Return R-peak sample indices for *cleaned_signal*.

        Falls back to the SciPy-based threshold detector if NeuroKit2 is
        unavailable or the requested method raises an exception.

        Parameters
        ----------
        cleaned_signal:
            Pre-filtered 1-D ECG array.  Should already be baseline-corrected
            (mean-centered); the detector does not apply any filtering.
        method:
            One of the ``ECG_DETECTOR_*`` constants.

        Returns
        -------
        np.ndarray
            1-D integer array of sample indices, sorted ascending.
        """
        cleaned_signal = np.asarray(cleaned_signal, dtype=float)
        if cleaned_signal.size < _MIN_SAMPLES_FOR_DETECTION:
            return np.array([], dtype=int)

        if _NK_AVAILABLE:
            try:
                _, info = nk.ecg_peaks(cleaned_signal, sampling_rate=int(round(self.sample_rate)), method=method)
                peaks = np.asarray(info.get("ECG_R_Peaks", []), dtype=int)
                peaks = peaks[(peaks >= 0) & (peaks < cleaned_signal.size)]
                return np.sort(peaks)
            except Exception as exc:
                # Log at DEBUG for short signals (expected NK2 limitation);
                # at WARNING only for full-length signals where NK2 should succeed.
                _log_fn = log.debug if cleaned_signal.size < int(self.sample_rate) * 2 else log.warning
                _log_fn("nk.ecg_peaks failed (method=%r, %s); using SciPy fallback.", method, exc)

        return self._scipy_fallback(cleaned_signal)

    def _scipy_fallback(self, cleaned_signal: np.ndarray) -> np.ndarray:
        """Simple threshold-based QRS detector using SciPy (no NeuroKit2)."""
        try:
            from scipy.signal import find_peaks
            # Estimate dynamic threshold: 0.6 × 98th-percentile amplitude
            threshold = 0.6 * float(np.percentile(cleaned_signal, 98))
            min_distance = int(round(self.sample_rate * _MIN_RR_S))
            peaks, _ = find_peaks(cleaned_signal, height=threshold, distance=max(1, min_distance))
            return peaks.astype(int)
        except Exception as exc:
            log.warning("SciPy fallback peak detector failed (%s); returning empty.", exc)
            return np.array([], dtype=int)


# ---------------------------------------------------------------------------
# 3. ECGRollingProcessor — streaming / rolling-window coordinator
# ---------------------------------------------------------------------------

class ECGRollingProcessor:
    """Rolling-buffer ECG coordinator for streaming / real-time use.

    Accumulates incoming samples in a fixed-size circular buffer and runs
    peak detection every ``detection_interval_s`` seconds.  Only peaks outside
    the configurable **boundary guard zone** (the right-edge of the window) are
    reported, ensuring that partially-visible QRS complexes are not reported
    prematurely.

    Parameters
    ----------
    sample_rate:
        ECG sampling rate in Hz (default 250 Hz for USB serial).
    window_s:
        Rolling buffer length in seconds.  Detection runs on this window.
    detection_interval_s:
        How often (in seconds) to run peak detection.  Smaller values give
        lower latency at the cost of more computation.
    boundary_guard_s:
        Peaks within this many seconds of the window right-edge are held back
        until they move further from the boundary.
    filter_mode:
        One of the ``ECG_FILTER_*`` constants.  Applied to the buffer before
        detection.
    lowcut_hz, highcut_hz:
        Bandpass corner frequencies.
    notch_hz:
        Power-line notch frequency (used only with ``ECG_FILTER_IIR_NOTCH``).
    detector_method:
        One of the ``ECG_DETECTOR_*`` constants.
    """

    def __init__(
        self,
        sample_rate: float = 250.0,
        window_s: float = 5.0,
        detection_interval_s: float = 0.2,
        boundary_guard_s: float = 0.5,
        filter_mode: str = ECG_FILTER_BUTTERWORTH,
        lowcut_hz: float = 0.5,
        highcut_hz: float = 40.0,
        filter_order: int = 4,
        notch_hz: float = 50.0,
        detector_method: str = ECG_DETECTOR_NEUROKIT,
    ):
        self.sample_rate = float(sample_rate)
        self._window_samples = int(round(window_s * sample_rate))
        self._detection_interval = max(1, int(round(detection_interval_s * sample_rate)))
        self._boundary_guard = int(round(boundary_guard_s * sample_rate))
        self.filter_mode = filter_mode
        self.lowcut_hz = lowcut_hz
        self.highcut_hz = highcut_hz
        self.filter_order = filter_order
        self.notch_hz = notch_hz
        self.detector_method = detector_method

        self._buffer: deque[float] = deque(maxlen=self._window_samples)
        self._global_idx: int = 0            # total samples received
        self._samples_since_det: int = 0     # samples since last detection pass
        self._last_reported_idx: int = -1    # last global index already reported

        self._detector = ECGRPeakDetector(sample_rate=self.sample_rate)

        # Accumulate ALL confirmed peaks (global indices) for HR computation
        self._all_peak_global: list[int] = []

    def add_sample(self, ecg_raw: float) -> ECGRollingResult | None:
        """Add one raw ECG sample and run detection if due.

        Parameters
        ----------
        ecg_raw:
            Single raw ECG sample value.

        Returns
        -------
        ECGRollingResult or None
            A result with newly confirmed peaks if a detection pass was run
            and found new peaks.  ``None`` if no detection was run or no new
            peaks were found.
        """
        self._buffer.append(float(ecg_raw))
        self._global_idx += 1
        self._samples_since_det += 1

        if self._samples_since_det < self._detection_interval:
            return None
        if len(self._buffer) < _MIN_SAMPLES_FOR_DETECTION:
            return None

        return self._run_detection()

    def _run_detection(self) -> ECGRollingResult | None:
        self._samples_since_det = 0

        window = np.asarray(self._buffer, dtype=float)
        buf_len = len(window)

        # First sample in the window has this global index
        window_start_global = self._global_idx - buf_len

        # Apply selected filter to the window
        cleaned = ECGCleaningFilter.clean(
            window,
            sample_rate=self.sample_rate,
            mode=self.filter_mode,
            lowcut_hz=self.lowcut_hz,
            highcut_hz=self.highcut_hz,
            filter_order=self.filter_order,
            notch_hz=self.notch_hz,
        )

        # Detect peaks in the cleaned window
        local_peaks = self._detector.detect(cleaned, method=self.detector_method)

        if local_peaks.size == 0:
            return None

        # Convert local window indices → global sample indices
        global_peaks = (local_peaks + window_start_global).tolist()

        # Apply boundary guard: only report peaks not too close to right edge
        right_edge = self._global_idx
        guard_start = right_edge - self._boundary_guard
        confirmed = [g for g in global_peaks if g < guard_start and g > self._last_reported_idx]

        if not confirmed:
            return None

        self._last_reported_idx = confirmed[-1]
        self._all_peak_global.extend(confirmed)

        # Compute HR for the new peaks, including one predecessor peak when
        # available so the first RR interval can be computed.
        # `len(_all_peak_global) - len(confirmed) - 1` is the index of the
        # predecessor peak.  When _all_peak_global has no predecessor (e.g. on
        # the very first detection pass, or when confirmed covers all stored
        # peaks), this expression is negative; max(0, ...) clamps to 0 so the
        # slice falls back to the beginning of the list.
        start_idx = max(0, len(self._all_peak_global) - len(confirmed) - 1)
        hr_times, hr_bpm = _peaks_to_hr(
            self._all_peak_global[start_idx:],
            self.sample_rate,
        )

        # Build result
        peak_times_s = [g / self.sample_rate for g in confirmed]
        return ECGRollingResult(
            new_peak_indices=confirmed,
            new_peak_times_s=peak_times_s,
            new_hr_times_s=hr_times,
            new_hr_bpm=hr_bpm,
        )

    def reset(self) -> None:
        """Reset all buffers and internal state."""
        self._buffer.clear()
        self._global_idx = 0
        self._samples_since_det = 0
        self._last_reported_idx = -1
        self._all_peak_global.clear()

    def reconfigure(
        self,
        filter_mode: str | None = None,
        lowcut_hz: float | None = None,
        highcut_hz: float | None = None,
        notch_hz: float | None = None,
        detector_method: str | None = None,
    ) -> None:
        """Update configuration parameters without losing buffered data."""
        if filter_mode is not None:
            self.filter_mode = filter_mode
        if lowcut_hz is not None:
            self.lowcut_hz = lowcut_hz
        if highcut_hz is not None:
            self.highcut_hz = highcut_hz
        if notch_hz is not None:
            self.notch_hz = notch_hz
        if detector_method is not None:
            self.detector_method = detector_method


# ---------------------------------------------------------------------------
# 4. ECGOfflineProcessor — whole-file batch coordinator
# ---------------------------------------------------------------------------

class ECGOfflineProcessor:
    """Process an entire ECG file in a single batch pass.

    Intended for use when ``speed_factor=None`` (maximum-speed file replay):
    all computation completes before the display is updated, ensuring no
    intermediate renders during analysis.

    When NeuroKit2 is available, ``nk.ecg_process`` is used for best-accuracy
    peak detection and HR estimation.  A manual clean→detect pipeline is used
    as fallback.

    Parameters
    ----------
    sample_rate:
        ECG sampling rate in Hz.
    filter_mode:
        Cleaning strategy (one of ``ECG_FILTER_*``).
    lowcut_hz, highcut_hz:
        Bandpass corners.
    notch_hz:
        Notch frequency for the ``ECG_FILTER_IIR_NOTCH`` path.
    detector_method:
        R-peak detector (one of ``ECG_DETECTOR_*``).
    """

    def __init__(
        self,
        sample_rate: float = 250.0,
        filter_mode: str = ECG_FILTER_BUTTERWORTH,
        lowcut_hz: float = 0.5,
        highcut_hz: float = 40.0,
        filter_order: int = 4,
        notch_hz: float = 50.0,
        detector_method: str = ECG_DETECTOR_NEUROKIT,
    ):
        self.sample_rate = float(sample_rate)
        self.filter_mode = filter_mode
        self.lowcut_hz = lowcut_hz
        self.highcut_hz = highcut_hz
        self.filter_order = filter_order
        self.notch_hz = notch_hz
        self.detector_method = detector_method

    def process(self, raw_signal: np.ndarray) -> ECGOfflineResult:
        """Process the full *raw_signal* array and return an :class:`ECGOfflineResult`.

        Parameters
        ----------
        raw_signal:
            1-D float64 array of raw ECG samples.

        Returns
        -------
        ECGOfflineResult
            Filtered signal, R-peak positions, and HR estimates.
        """
        raw_signal = np.asarray(raw_signal, dtype=float)
        result = ECGOfflineResult(duration_s=raw_signal.size / self.sample_rate)

        if raw_signal.size < _MIN_SAMPLES_FOR_DETECTION:
            log.warning("ECGOfflineProcessor: signal too short (%d samples)", raw_signal.size)
            result.filtered_signal = raw_signal.copy()
            return result

        # Attempt NeuroKit2 full pipeline first (best accuracy)
        if _NK_AVAILABLE:
            frozen_debug_log.debug(
                "delineation start: raw_samples=%d sample_rate=%.3f",
                raw_signal.size,
                self.sample_rate,
            )
            try:
                signals_df, info = nk.ecg_process(
                    raw_signal,
                    sampling_rate=int(round(self.sample_rate)),
                )
                result.filtered_signal = np.asarray(signals_df["ECG_Clean"], dtype=float)
                peaks = np.asarray(info.get("ECG_R_Peaks", []), dtype=int)
                peaks = peaks[(peaks >= 0) & (peaks < raw_signal.size)]
                result.r_peak_indices = sorted(peaks.tolist())
                result.r_peak_times_s = [i / self.sample_rate for i in result.r_peak_indices]
                hr_times, hr_bpm = _peaks_to_hr(result.r_peak_indices, self.sample_rate)
                result.hr_times_s = hr_times
                result.hr_bpm = hr_bpm
                result.beat_count = len(result.r_peak_indices)
                result.mean_hr_bpm = float(np.mean(hr_bpm)) if hr_bpm else None
                # Extract P/Q/S/T delineation indices from the signals DataFrame.
                # NeuroKit2 delineation columns are binary (1 = peak, 0 or NaN = no peak);
                # fillna(0) correctly treats NaN (undetected) as 0 before the == 1 test.
                extracted_counts: dict[str, int] = {}
                for col, attr in [
                    ("ECG_P_Peaks", "p_peak_indices"),
                    ("ECG_Q_Peaks", "q_peak_indices"),
                    ("ECG_S_Peaks", "s_peak_indices"),
                    ("ECG_T_Peaks", "t_peak_indices"),
                ]:
                    if col in signals_df.columns:
                        vals = np.asarray(signals_df[col].fillna(0), dtype=float)
                        idx = np.where(vals == 1)[0].tolist()
                        setattr(result, attr, idx)
                        extracted_counts[attr] = len(idx)
                    else:
                        extracted_counts[attr] = 0
                        frozen_debug_log.warning(
                            "delineation column missing from nk.ecg_process output: %s",
                            col,
                        )
                if extracted_counts and not any(extracted_counts.values()) and result.r_peak_indices:
                    frozen_debug_log.warning(
                        "delineation fallback: ecg_process yielded zero P/Q/S/T markers; running nk.ecg_delineate"
                    )
                    try:
                        _, waves = nk.ecg_delineate(
                            result.filtered_signal,
                            rpeaks=np.asarray(result.r_peak_indices, dtype=int),
                            sampling_rate=int(round(self.sample_rate)),
                            method="dwt",
                            show=False,
                        )
                        for waves_key, attr in [
                            ("ECG_P_Peaks", "p_peak_indices"),
                            ("ECG_Q_Peaks", "q_peak_indices"),
                            ("ECG_S_Peaks", "s_peak_indices"),
                            ("ECG_T_Peaks", "t_peak_indices"),
                        ]:
                            idx = _finite_int_indices(np.asarray(waves.get(waves_key, []), dtype=float))
                            setattr(result, attr, idx)
                            extracted_counts[attr] = len(idx)
                    except (ValueError, RuntimeError, TypeError) as exc:
                        frozen_debug_log.exception("nk.ecg_delineate fallback failed: %s", exc)
                frozen_debug_log.debug(
                    "delineation end: r_peaks=%d p=%d q=%d s=%d t=%d",
                    len(result.r_peak_indices),
                    extracted_counts.get("p_peak_indices", 0),
                    extracted_counts.get("q_peak_indices", 0),
                    extracted_counts.get("s_peak_indices", 0),
                    extracted_counts.get("t_peak_indices", 0),
                )
                return result
            except Exception as exc:
                frozen_debug_log.exception("nk.ecg_process pipeline failed; using manual fallback: %s", exc)
                log.warning("nk.ecg_process failed (%s); using manual pipeline.", exc)
        else:
            frozen_debug_log.warning(
                "delineation skipped: neurokit2 unavailable (frozen=%s)",
                bool(getattr(sys, "frozen", False)),
            )

        # Manual pipeline (NeuroKit2 absent or raised an exception)
        filtered = ECGCleaningFilter.clean(
            raw_signal,
            sample_rate=self.sample_rate,
            mode=self.filter_mode,
            lowcut_hz=self.lowcut_hz,
            highcut_hz=self.highcut_hz,
            filter_order=self.filter_order,
            notch_hz=self.notch_hz,
        )
        result.filtered_signal = filtered

        detector = ECGRPeakDetector(sample_rate=self.sample_rate)
        peaks = detector.detect(filtered, method=self.detector_method)
        result.r_peak_indices = sorted(peaks.tolist())
        result.r_peak_times_s = [i / self.sample_rate for i in result.r_peak_indices]
        hr_times, hr_bpm = _peaks_to_hr(result.r_peak_indices, self.sample_rate)
        result.hr_times_s = hr_times
        result.hr_bpm = hr_bpm
        result.beat_count = len(result.r_peak_indices)
        result.mean_hr_bpm = float(np.mean(hr_bpm)) if hr_bpm else None
        return result


# ---------------------------------------------------------------------------
# Utility: convert peak indices → instantaneous HR
# ---------------------------------------------------------------------------

def _finite_int_indices(values: np.ndarray) -> list[int]:
    """Return finite integer sample indices from a NeuroKit2 wave output array."""
    vals = np.asarray(values, dtype=float)
    if vals.size == 0:
        return []
    vals = vals[np.isfinite(vals)]
    return vals.astype(int).tolist()


def _peaks_to_hr(
    peak_indices: list[int],
    sample_rate: float,
) -> tuple[list[float], list[float]]:
    """Convert a list of peak sample indices to instantaneous HR times and BPM.

    Only RR intervals within the physiological range
    ``(_MIN_RR_S, _MAX_RR_S)`` are included.  Outliers (missed beat / double
    detection) are silently dropped.

    Parameters
    ----------
    peak_indices:
        Sorted list of R-peak sample indices (global or window-local).
    sample_rate:
        Sampling frequency in Hz.

    Returns
    -------
    hr_times_s:
        Timestamp (in seconds, at the second/later peak of each pair).
    hr_bpm:
        Instantaneous HR in BPM for each accepted RR interval.
    """
    hr_times: list[float] = []
    hr_bpm_vals: list[float] = []

    if len(peak_indices) < 2:
        return hr_times, hr_bpm_vals

    for i in range(1, len(peak_indices)):
        rr_s = (peak_indices[i] - peak_indices[i - 1]) / sample_rate
        if _MIN_RR_S < rr_s < _MAX_RR_S:
            bpm = 60.0 / rr_s
            t_s = peak_indices[i] / sample_rate
            hr_times.append(t_s)
            hr_bpm_vals.append(bpm)

    return hr_times, hr_bpm_vals
