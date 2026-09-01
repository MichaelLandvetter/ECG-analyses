"""Bandpass filter utilities for real-time and offline VER processing."""

from __future__ import annotations

import logging
from typing import Optional
import numpy as np
from scipy.signal import butter, sosfilt, sosfilt_zi, sosfiltfilt, savgol_filter, firwin, filtfilt

from ver_config import FILTER_CONFIG
from ver_constants import DEFAULT_SCOPE_FILTER_MODE, SCOPE_FILTER_FIR, SCOPE_FILTER_SAVGOL

log = logging.getLogger(__name__)


class BandpassFilter:
    """Butterworth bandpass filter with selectable zero-phase paths for the scope."""

    def __init__(self, config: Optional[dict] = None):
        self.config = dict(FILTER_CONFIG)
        if config:
            self.config.update(config)
        self._dc_mean = 0.0
        self._dc_count = 0

        self.scope_mode = DEFAULT_SCOPE_FILTER_MODE

        self.redesign(self.config["lowcut_hz"], self.config["highcut_hz"])

    def set_scope_mode(self, mode: str):
        """Allows the UI to change the filter used for Scope averaging."""
        self.scope_mode = mode

    def redesign(self, lowcut_hz: float, highcut_hz: float, order: Optional[int] = None) -> None:
        self.config["lowcut_hz"] = float(lowcut_hz)
        self.config["highcut_hz"] = float(highcut_hz)
        if order is not None:
            self.config["order"] = int(order)

        self.sample_rate = float(self.config["sample_rate"])
        self.nyquist = self.sample_rate / 2.0
        low = self.config["lowcut_hz"] / self.nyquist
        high = self.config["highcut_hz"] / self.nyquist
        if not (0.0 < low < high < 1.0):
            raise ValueError("Invalid bandpass bounds. Require 0 < lowcut < highcut < Nyquist")

        self.sos = butter(self.config["order"], [low, high], btype="band", output="sos")
        self._zi = sosfilt_zi(self.sos)
        self._dc_mean = 0.0
        self._dc_count = 0

    def process_sample(self, sample: float) -> float:
        """Causal real-time filter path preserving state between samples."""
        self._dc_count += 1
        self._dc_mean += (float(sample) - self._dc_mean) / self._dc_count
        centered = float(sample) - self._dc_mean
        y, self._zi = sosfilt(self.sos, np.array([centered], dtype=float), zi=self._zi)
        return float(y[0])

    def process_block(self, samples: np.ndarray) -> np.ndarray:
        samples = np.asarray(samples, dtype=float)
        if samples.size == 0:
            return samples
        centered = samples - np.mean(samples)
        y, self._zi = sosfilt(self.sos, centered, zi=self._zi)
        return y

    def apply_zero_phase(self, samples: np.ndarray, baseline_mean: Optional[float] = None) -> np.ndarray:
        """Zero-phase offline filtering path for extracted epochs."""
        samples = np.asarray(samples, dtype=float)
        if samples.size == 0:
            return samples
            
        dc = np.mean(samples) if baseline_mean is None else float(baseline_mean)
        centered = samples - dc

        # Calculate a safe padding length for short epoch arrays
        safe_padlen = min(len(centered) - 1, 21)
        if safe_padlen < 0: safe_padlen = 0

        # --- APPLY THE SELECTED SCOPE FILTER ---
        try:
            if self.scope_mode == SCOPE_FILTER_FIR:
                numtaps = int(self.sample_rate * 0.1)
                if numtaps % 2 == 0: numtaps += 1
                if numtaps > len(centered) // 3:
                    numtaps = (len(centered) // 3) | 1
                if numtaps < 5: numtaps = 5

                low = self.config["lowcut_hz"] / self.nyquist
                high = self.config["highcut_hz"] / self.nyquist
                taps = firwin(numtaps, [low, high], pass_zero=False)
                y = filtfilt(taps, 1.0, centered, padlen=safe_padlen)

            elif self.scope_mode == SCOPE_FILTER_SAVGOL:
                window = int(self.sample_rate * 0.05)
                if window % 2 == 0: window += 1
                if window > len(centered): window = len(centered) | 1
                if window < 5: window = 5

                savgol_y = savgol_filter(centered, window_length=window, polyorder=3)
                y = sosfiltfilt(self.sos, savgol_y, padlen=safe_padlen)

            else:
                # Butterworth (default)
                y = sosfiltfilt(self.sos, centered, padlen=safe_padlen)

            return y

        except Exception as e:
            log.warning("Filter fallback triggered in mode '%s': %s", self.scope_mode, e)
            return sosfilt(self.sos, centered)