"""Time-domain peak detection for VER waveforms (Peak-1, Peak-2, Peak-3)."""

from __future__ import annotations
import logging
from typing import TypedDict

import numpy as np
from scipy.signal import find_peaks

import ver_config

log = logging.getLogger(__name__)

MIN_NOISE_RMS = 1e-10
DEFAULT_PEAK_DETECTION_MODE = "legacy_top3"
DOMINANT_OPPOSITE_NEIGHBORS_MODE = "dominant_opposite_neighbors"

# Module-level settings cache — loaded once on first use and replaced when
# an explicit ``classifier_cfg`` dict is passed in (e.g. after user saves
# settings in the GUI).
_cached_classifier_cfg: dict | None = None


def _get_classifier_cfg(override: dict | None) -> dict:
    """Return the classifier config dict, using the module cache unless an override is given."""
    global _cached_classifier_cfg
    if override is not None:
        _cached_classifier_cfg = override
        return override
    if _cached_classifier_cfg is not None:
        return _cached_classifier_cfg
    # First-time load only.
    try:
        from ver_settings import SettingsManager
        _cached_classifier_cfg = SettingsManager().load_settings().get("CLASSIFIER_CONFIG", {})
    except Exception as exc:
        log.warning("Could not load CLASSIFIER_CONFIG from settings: %s", exc)
        _cached_classifier_cfg = {}
    return _cached_classifier_cfg


def refresh_classifier_cfg(cfg: dict) -> None:
    """Push an updated classifier config dict into the module cache.

    Call this after the user saves settings in the GUI so that subsequent
    ``detect_ver_peaks`` calls use the new values without restarting.
    """
    _get_classifier_cfg(cfg)


class VERPeak(TypedDict):
    latency_ms: float   # time in ms where peak occurs
    amplitude: float    # amplitude value at the peak
    found: bool         # False if no clear peak found in window
    snr: float
    above_threshold: bool


VERPeaksResult = TypedDict(
    "VERPeaksResult",
    {
        "Peak-1": VERPeak,
        "Peak-2": VERPeak,
        "Peak-3": VERPeak,
        "VER_detected": bool,
        "noise_rms": float,
    },
)


def _find_extrema_indices(segment: np.ndarray) -> np.ndarray:
    """Return robust positive and negative extrema indices for a waveform segment."""

    signal_range = float(np.max(segment) - np.min(segment))
    # Require peaks to stand out by at least 10% of segment range.
    # 1e-10 prevents zero-prominence calls for near-flat numeric input; it has no physiological meaning.
    min_prominence = max(0.1 * signal_range, 1e-10)
    # Keep detected peaks at least ~20ms apart at 250Hz (5 samples).
    min_distance = 5

    pos_peaks, _ = find_peaks(segment, prominence=min_prominence, distance=min_distance)
    neg_peaks, _ = find_peaks(-segment, prominence=min_prominence, distance=min_distance)
    return np.concatenate([pos_peaks, neg_peaks])


def _resolve_peak_detection_mode(mode: str | None) -> str:
    """Return a supported peak-detection mode, falling back to the legacy mode."""

    if mode == DOMINANT_OPPOSITE_NEIGHBORS_MODE:
        return DOMINANT_OPPOSITE_NEIGHBORS_MODE
    if mode is not None and mode not in (
        DEFAULT_PEAK_DETECTION_MODE,
        DOMINANT_OPPOSITE_NEIGHBORS_MODE,
    ):
        log.warning(
            "Unknown peak_detection_mode %r; falling back to %s",
            mode,
            DEFAULT_PEAK_DETECTION_MODE,
        )
    return DEFAULT_PEAK_DETECTION_MODE


def _legacy_peak_assignments(segment: np.ndarray, seg_times: np.ndarray) -> dict[str, int | None]:
    """Return the historical Peak-1/2/3 assignments."""

    all_peak_indices = _find_extrema_indices(segment)
    if len(all_peak_indices) == 0:
        # No local extrema found (e.g. flat signal) — fall back to the samples with the
        # largest absolute values. These may not be strict local maxima, but they represent
        # the most prominent features in a signal with no clear peaks.
        all_peak_indices = np.argsort(np.abs(segment))[-3:]

    # Rank by absolute amplitude, take top 3, then report them in time order.
    ranked = sorted(all_peak_indices, key=lambda i: abs(segment[i]), reverse=True)
    top3_sorted = sorted(ranked[:3], key=lambda i: seg_times[i])
    peak_names = ["Peak-1", "Peak-2", "Peak-3"]
    return {
        name: top3_sorted[i] if i < len(top3_sorted) else None
        for i, name in enumerate(peak_names)
    }


def _dominant_opposite_neighbor_assignments(segment: np.ndarray) -> dict[str, int | None]:
    """Return Peak-1/2/3 as opposite-polarity neighbors around the dominant peak."""

    candidate_indices = sorted(set(_find_extrema_indices(segment)))
    # The new mode is defined around the dominant absolute-amplitude sample, not just the
    # strongest previously detected extremum, so inspect the full post-stimulus segment here.
    dominant_idx = int(np.argmax(np.abs(segment)))
    dominant_amp = float(segment[dominant_idx])
    dominant_sign = np.sign(dominant_amp)
    if dominant_sign == 0:
        return {
            "Peak-1": None,
            "Peak-2": dominant_idx,
            "Peak-3": None,
        }

    def is_opposite(value: float) -> bool:
        return bool(value * dominant_sign < 0)

    before = None
    after = None
    for idx in candidate_indices:
        if not is_opposite(segment[idx]):
            continue
        if idx < dominant_idx:
            before = idx
        elif idx > dominant_idx:
            after = idx
            break

    return {
        "Peak-1": before,
        "Peak-2": dominant_idx,
        "Peak-3": after,
    }


def detect_ver_peaks(
    epoch_avg: np.ndarray,
    epoch_time_ms: np.ndarray,
    classifier_cfg: dict | None = None,
) -> VERPeaksResult:
    """
    Detect VER peaks between 0 and 200ms post-stimulus.

    Default mode preserves the historical behavior: find robust local maxima/minima,
    rank them by absolute amplitude, take the top three, then return them in latency order.
    Optional mode returns the dominant absolute-amplitude peak as Peak-2 plus the nearest
    opposite-polarity extrema before/after it as Peak-1/Peak-3.

    Works for any species regardless of polarity convention.

    Parameters
    ----------
    epoch_avg : np.ndarray
        Averaged epoch waveform (same length as epoch_time_ms)
    epoch_time_ms : np.ndarray
        Time axis in milliseconds (negative values = pre-stimulus)
    classifier_cfg : dict, optional
        Pre-loaded classifier settings dict.  When provided the module-level
        cache is updated so that subsequent calls reuse the same values without
        re-reading the JSON file.  Pass ``None`` (default) to use the cached
        config or load it from disk on the first call.

    Returns
    -------
    dict with Peak-1/2/3 plus SNR flags, VER_detected and noise_rms
    """
    cfg = _get_classifier_cfg(classifier_cfg)
    snr_threshold = cfg.get("snr_threshold", 2.0)
    peak_detection_mode = _resolve_peak_detection_mode(cfg.get("peak_detection_mode"))
    def _empty_peak() -> VERPeak:
        return {
            "latency_ms": float("nan"),
            "amplitude": float("nan"),
            "found": False,
            "snr": float("nan"),
            "above_threshold": False,
        }

    # Use the configured baseline window for both baseline correction and noise estimation.
    baseline_mask = (
        (epoch_time_ms >= ver_config.BASELINE_START_MS)
        & (epoch_time_ms < ver_config.BASELINE_END_MS)
    )
    baseline = float(np.mean(epoch_avg[baseline_mask])) if np.any(baseline_mask) else 0.0

    noise_mask = (
        (epoch_time_ms >= ver_config.BASELINE_START_MS)
        & (epoch_time_ms < ver_config.BASELINE_END_MS)
    )
    baseline_segment = epoch_avg[noise_mask]
    noise_rms = float(np.sqrt(np.mean(baseline_segment ** 2))) if np.any(noise_mask) else MIN_NOISE_RMS
    noise_rms = max(noise_rms, MIN_NOISE_RMS)

    mask = (epoch_time_ms >= 0) & (epoch_time_ms <= 200)
    if not np.any(mask):
        return {
            'Peak-1': _empty_peak(),
            'Peak-2': _empty_peak(),
            'Peak-3': _empty_peak(),
            'VER_detected': False,
            'noise_rms': noise_rms,
        }

    segment = epoch_avg[mask] - baseline
    seg_times = epoch_time_ms[mask]
    if peak_detection_mode == DOMINANT_OPPOSITE_NEIGHBORS_MODE:
        peak_assignments = _dominant_opposite_neighbor_assignments(segment)
    else:
        peak_assignments = _legacy_peak_assignments(segment, seg_times)

    result: VERPeaksResult = {
        "Peak-1": _empty_peak(),
        "Peak-2": _empty_peak(),
        "Peak-3": _empty_peak(),
        "VER_detected": False,
        "noise_rms": noise_rms,
    }
    peak_names = ['Peak-1', 'Peak-2', 'Peak-3']
    for name in peak_names:
        idx = peak_assignments.get(name)
        if idx is not None:
            result[name] = {
                "latency_ms": float(seg_times[idx]),
                "amplitude": float(segment[idx]),
                "found": True,
                "snr": float("nan"),
                "above_threshold": False,
            }
        else:
            result[name] = _empty_peak()

    for name in peak_names:
        if result[name]["found"]:
            snr = abs(result[name]["amplitude"]) / noise_rms
            result[name]["snr"] = snr
            result[name]["above_threshold"] = snr >= snr_threshold

    result["VER_detected"] = any(result[name]["above_threshold"] for name in peak_names)
    result["noise_rms"] = noise_rms

    return result
