"""Whole-file pre-analysis helpers for artifact exclusion threshold suggestion."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ver_acquisition import FileAcquisitionSimulator
from ver_config import FILE_CONFIG, FILTER_CONFIG
from ver_filter import BandpassFilter
from ver_scope import VERScopeProcessor

MAD_TO_SIGMA = 1.4826  # Converts MAD to std-dev equivalent assuming normal distribution.
ROBUST_SIGMA_MULTIPLIER = 3.0
MIN_THRESHOLD_UV = 1e-6
MIN_SELECTABLE_THRESHOLD_UV = 1e-4
# Keep 1 in every N samples for the display trace (~62.5 Hz at 250 Hz input).
_SIGNAL_DOWNSAMPLE_FACTOR = 4


def _build_threshold_stats(peak_values: np.ndarray, threshold_uv: float) -> ExclusionThresholdStats:
    threshold = max(float(threshold_uv), MIN_SELECTABLE_THRESHOLD_UV)
    rejected = int(np.count_nonzero(peak_values > threshold))
    total = int(peak_values.size)
    accepted = total - rejected
    rejected_percent = (rejected / total * 100.0) if total else 0.0
    return ExclusionThresholdStats(
        threshold_uv=threshold,
        total_epochs=total,
        accepted_epochs=accepted,
        rejected_epochs=rejected,
        rejected_percent=rejected_percent,
    )


@dataclass(frozen=True)
class ExclusionThresholdStats:
    """Accepted/rejected whole-file counts for a candidate symmetric threshold."""

    threshold_uv: float
    total_epochs: int
    accepted_epochs: int
    rejected_epochs: int
    rejected_percent: float


@dataclass(frozen=True)
class ExclusionSuggestion:
    """Whole-file exclusion tuning data.

    `peak_values_uv` stores one max-absolute filtered amplitude value per detected
    epoch, as a 1-D NumPy array, so the UI can recompute accepted/rejected estimates
    live without re-parsing the file.

    `filtered_signal_uv` holds a downsampled copy of the causal-filtered continuous
    signal (1 in every `_SIGNAL_DOWNSAMPLE_FACTOR` samples) so the UI can render a
    time-series plot for visual threshold selection.  `signal_sample_rate` gives the
    effective sample rate of that downsampled trace.

    Large arrays are hidden from `repr` to avoid dumping them in logs or test output.
    """

    suggested_threshold_uv: float
    total_epochs: int
    accepted_epochs: int
    rejected_epochs: int
    peak_values_uv: np.ndarray = field(repr=False)
    filtered_signal_uv: np.ndarray = field(
        default_factory=lambda: np.array([], dtype=float), repr=False
    )
    signal_sample_rate: float = 0.0  # effective Hz of filtered_signal_uv after downsampling

    def stats_for_threshold(self, threshold_uv: float) -> ExclusionThresholdStats:
        return _build_threshold_stats(self.peak_values_uv, threshold_uv)


def _suggest_threshold_from_peaks(peak_values: np.ndarray) -> float:
    if peak_values.size == 0:
        raise ValueError("No complete epochs were detected. Verify trigger settings and file format.")

    median_peak = float(np.median(peak_values))
    mad = float(np.median(np.abs(peak_values - median_peak)))
    robust_sigma = MAD_TO_SIGMA * mad

    if robust_sigma <= 0:
        robust_sigma = float(np.std(peak_values))

    # Suggest threshold at median peak plus 3 robust standard deviations.
    suggested = median_peak + (ROBUST_SIGMA_MULTIPLIER * robust_sigma)
    if suggested < MIN_THRESHOLD_UV:
        suggested = max(median_peak, MIN_THRESHOLD_UV)
    return float(suggested)


def suggest_exclusion_from_file(
    file_path: str,
    *,
    epoch_config: dict,
    file_config: dict | None = None,
    bandpass_filter=None,
) -> ExclusionSuggestion:
    active_file_config = dict(FILE_CONFIG)
    if file_config:
        active_file_config.update(file_config)

    scope_filter = bandpass_filter or BandpassFilter(
        {
            "lowcut_hz": float(FILTER_CONFIG["lowcut_hz"]),
            "highcut_hz": float(FILTER_CONFIG["highcut_hz"]),
            "sample_rate": float(FILTER_CONFIG["sample_rate"]),
            "order": int(FILTER_CONFIG["order"]),
        }
    )

    # Separate causal filter for the continuous streaming signal display trace.
    # Using the same settings as scope_filter but independent state so the epoch
    # zero-phase path is not affected.
    stream_filter = BandpassFilter(
        {
            "lowcut_hz": float(FILTER_CONFIG["lowcut_hz"]),
            "highcut_hz": float(FILTER_CONFIG["highcut_hz"]),
            "sample_rate": float(FILTER_CONFIG["sample_rate"]),
            "order": int(FILTER_CONFIG["order"]),
        }
    )

    scope = VERScopeProcessor(scope_filter, epoch_config=epoch_config)
    simulator = FileAcquisitionSimulator(file_path, speed_factor=None, file_config=active_file_config)
    epoch_peak_abs: list[float] = []
    display_signal: list[float] = []
    sample_index = 0

    for sample in simulator.stream_samples():
        result = scope.process_sample(bool(sample[0]), float(sample[1]))
        if result["epoch_complete"] and result["completed_epoch"] is not None:
            epoch_peak_abs.append(float(np.max(np.abs(result["completed_epoch"]))))

        # Collect downsampled streaming-filtered signal for the signal plot.
        filt_val = stream_filter.process_sample(float(sample[1]))
        if sample_index % _SIGNAL_DOWNSAMPLE_FACTOR == 0:
            display_signal.append(filt_val)
        sample_index += 1

    peak_values = np.asarray(epoch_peak_abs, dtype=float)
    suggested_threshold = _suggest_threshold_from_peaks(peak_values)
    suggested_stats = _build_threshold_stats(peak_values, suggested_threshold)

    input_sample_rate = float(FILTER_CONFIG["sample_rate"])
    display_sample_rate = input_sample_rate / _SIGNAL_DOWNSAMPLE_FACTOR

    return ExclusionSuggestion(
        suggested_threshold_uv=suggested_threshold,
        total_epochs=suggested_stats.total_epochs,
        accepted_epochs=suggested_stats.accepted_epochs,
        rejected_epochs=suggested_stats.rejected_epochs,
        peak_values_uv=peak_values,
        filtered_signal_uv=np.asarray(display_signal, dtype=float),
        signal_sample_rate=display_sample_rate,
    )
