"""Trigger detection, epoch extraction, and running/session averaging.

INHERITED VER ANALYSIS ENGINE — REPLACEMENT TARGET 1
=====================================================
This module is the first component to replace when implementing ECG analysis.
The flash-locked epoch model here is fundamentally incompatible with ECG data.

**VER-specific logic in this module:**
- Rising-edge trigger detection (``process_sample``) — assumes an external
  flash/stimulus trigger channel; ECG needs R-peak detection (e.g. Pan-Tompkins).
- Flash-count-based session completion (``flashes_per_session``) — should be
  replaced with beat-count or time-window-based block structure for ECG.
- Pre/post-stimulus epoch window (``pre_stim_ms``, ``post_stim_ms``) — flash-
  locked windows; ECG uses R-peak-locked PQRST windows instead.

**Callers (must be updated together when this module is replaced):**
- ``ver_main.py`` — instantiates ``VERScopeProcessor``, calls ``process_sample``
  sample by sample, reads all keys from the result dict.
- ``ver_preflight.py`` — whole-file pre-scan using ``VERScopeProcessor``.

**Result-dict interface** (``process_sample`` return keys):
  ``trigger_detected``, ``epoch_complete``, ``epoch_rejected``,
  ``session_complete``, ``completed_epoch``, ``running_average``,
  ``completed_session_average``, ``flash_count``, ``flash_count_accepted``,
  ``session_index``, ``session_number``, ``completed_session_number``,
  ``completed_session_flash_count``, ``completed_session_flash_count_accepted``,
  ``artifact_rejection_enabled``, ``artifact_exclusion_threshold``

Any ECG replacement (``ecg_scope.py``) must return the same keys — or update
all read sites in ``ver_main.py`` in the same PR.  See the risk note in
``docs/ecg-transition-priorities.md § Biggest architectural risk``.

**Generic pieces worth keeping:**
- Ring buffer (``pre_buffer``) — paradigm-agnostic; reuse for ECG.
- Artifact rejection by amplitude threshold — reuse for ECG.
- Bandpass-filtered epoch storage and running average — reuse for ECG.

See ``docs/ecg-transition-priorities.md`` and ``TRANSITION.md`` for context.
"""

from __future__ import annotations

from collections import deque
from typing import Dict, List, Optional

import numpy as np

from ver_config import ACQ_CONFIG, EPOCH_CONFIG


class VERScopeProcessor:
    """Ring-buffer trigger detection, epoch extraction, and session averaging.

    Inherited VER analysis component — REPLACEMENT TARGET 1.
    Replace with ``ECGScopeProcessor`` in ``ecg_scope.py`` implementing
    R-peak detection (e.g. Pan-Tompkins) and beat-locked epoch windows.
    Preserve the ``process_sample`` result-dict key names during replacement
    to minimise changes to call sites in ``ver_main.py``.
    """

    def __init__(self, bandpass_filter, epoch_config: Optional[dict] = None):
        self.bandpass_filter = bandpass_filter
        self.config = dict(EPOCH_CONFIG)
        if epoch_config:
            self.config.update(epoch_config)

        self.sample_rate = ACQ_CONFIG["sample_rate"]
        self.pre_samples = int(self.config["pre_stim_ms"] * self.sample_rate / 1000)
        self.post_samples = int(self.config["post_stim_ms"] * self.sample_rate / 1000)
        self.epoch_samples = self.pre_samples + self.post_samples

        self.epoch_time_ms = (np.arange(self.epoch_samples) / self.sample_rate * 1000.0) - self.config["pre_stim_ms"]
        self.reset()

    def reset(self) -> None:
        self.pre_buffer = deque(maxlen=self.pre_samples)
        self.prev_trigger = 0.0
        self.pending_epochs: List[Dict[str, object]] = []
        self.session_epochs: List[np.ndarray] = []
        self.session_averages: List[np.ndarray] = []
        self.flash_count = 0          # total trigger events (governs session completion)
        self.flash_count_accepted = 0  # epochs that passed artifact rejection
        self.session_index = 0
        self.running_average = None

    def _active_session_number(self) -> int:
        return min(self.config["num_sessions"], self.session_index + 1)

    def _artifact_settings(self) -> tuple[bool, float]:
        artifact_enabled = bool(self.config.get("artifact_rejection_enabled", True))
        threshold = float(self.config.get("artifact_exclusion_uv", 0.01))
        return artifact_enabled, threshold

    def _finalize_current_session(self) -> dict:
        artifact_enabled, threshold = self._artifact_settings()
        # Edge case: all epochs were rejected — produce a zero waveform.
        if self.running_average is not None:
            session_average = self.running_average.copy()
        else:
            session_average = np.zeros(self.epoch_samples)
        completed_session_number = self.session_index + 1
        completed_flash_count_accepted = self.flash_count_accepted
        self.session_averages.append(session_average)
        self.session_index += 1
        self.session_epochs = []
        self.running_average = None
        self.flash_count = 0
        self.flash_count_accepted = 0
        return {
            "session_average": session_average,
            "session_number": completed_session_number,
            "flash_count_accepted": completed_flash_count_accepted,
            "artifact_rejection_enabled": artifact_enabled,
            "artifact_exclusion_threshold": threshold,
        }

    def save_partial_session(self, min_flashes: Optional[int] = None) -> Optional[dict]:
        required_flashes = self.config["flashes_per_session"]
        threshold = required_flashes // 2 if min_flashes is None else int(min_flashes)
        if self.running_average is None or self.flash_count < threshold:
            return None

        partial_flash_count = self.flash_count
        partial_session = self._finalize_current_session()
        partial_session["flash_count"] = partial_flash_count
        # flash_count_accepted is already included from _finalize_current_session
        return partial_session

    def process_sample(self, trigger_value: float, eeg_sample: float) -> dict:
        artifact_enabled, threshold = self._artifact_settings()
        result = {
            "trigger_detected": False,
            "epoch_complete": False,
            "epoch_rejected": False,
            "session_complete": False,
            "completed_epoch": None,
            "running_average": self.running_average,
            "completed_session_average": None,
            "flash_count": self.flash_count,
            "flash_count_accepted": self.flash_count_accepted,
            "session_index": self.session_index,
            "session_number": self._active_session_number(),
            "completed_session_number": None,
            "completed_session_flash_count": None,
            "completed_session_flash_count_accepted": None,
            "artifact_rejection_enabled": artifact_enabled,
            "artifact_exclusion_threshold": threshold,
        }

        for pending in list(self.pending_epochs):
            pending["samples"].append(float(eeg_sample))
            pending["remaining"] -= 1
            if pending["remaining"] <= 0:
                epoch = np.asarray(pending["samples"][: self.epoch_samples], dtype=float)
                baseline = float(np.mean(epoch[: self.pre_samples])) if self.pre_samples > 0 else float(np.mean(epoch))
                filtered_epoch = self.bandpass_filter.apply_zero_phase(epoch, baseline_mean=baseline)

                # --- Artifact rejection ---
                epoch_rejected = artifact_enabled and np.any(np.abs(filtered_epoch) > threshold)
                self.flash_count += 1  # always count total triggers

                if not epoch_rejected:
                    self.session_epochs.append(filtered_epoch)
                    self.running_average = np.mean(np.vstack(self.session_epochs), axis=0)
                    self.flash_count_accepted += 1

                result.update(
                    {
                        "epoch_complete": True,
                        "epoch_rejected": epoch_rejected,
                        "completed_epoch": filtered_epoch,
                        "running_average": self.running_average,
                        "flash_count": self.flash_count,
                        "flash_count_accepted": self.flash_count_accepted,
                    }
                )

                self.pending_epochs.remove(pending)

                if self.flash_count >= self.config["flashes_per_session"]:
                    session_total = self.flash_count
                    session_accepted = self.flash_count_accepted
                    completed_session = self._finalize_current_session()
                    result.update(
                        {
                            "session_complete": True,
                            "completed_session_average": completed_session["session_average"],
                            "session_index": self.session_index,
                            "completed_session_number": completed_session["session_number"],
                            "completed_session_flash_count": session_total,
                            "completed_session_flash_count_accepted": session_accepted,
                            "artifact_rejection_enabled": completed_session["artifact_rejection_enabled"],
                            "artifact_exclusion_threshold": completed_session["artifact_exclusion_threshold"],
                        }
                    )

        rising_edge = float(trigger_value) > 0 and self.prev_trigger <= 0
        if rising_edge:
            pre = list(self.pre_buffer)
            if len(pre) == self.pre_samples:
                self.pending_epochs.append(
                    {
                        "samples": pre + [float(eeg_sample)],
                        "remaining": max(0, self.post_samples - 1),
                    }
                )
                result["trigger_detected"] = True

        self.pre_buffer.append(float(eeg_sample))
        self.prev_trigger = float(trigger_value)
        return result

    def has_completed_all_sessions(self) -> bool:
        return self.session_index >= self.config["num_sessions"]
