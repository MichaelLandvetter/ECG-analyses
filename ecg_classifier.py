"""ECG-oriented classifier placeholder interface.

TRANSITIONAL MODULE — REPLACEMENT TARGET 3 (report/classifier boundary)
========================================================================
This module defines the ECG-facing boundary for replacing the inherited
VER-specific classifier.  It intentionally does **not** implement ECG
classification logic yet.  Instead it keeps the application runnable by
delegating to the inherited ``evaluate_ver_peak`` function from
``ver_classifier.py``.

Responsibilities of this placeholder boundary:
- expose a neutrally-named ``classify_ecg_signal`` function to callers
- accept the same numeric inputs as the underlying VER classifier
- return a neutral ``(is_detected, check_details)`` tuple rather than
  ``(is_ver, failure_details)`` so callers are one step less VER-specific
- isolate direct caller dependency on ``ver_classifier.py`` so future ECG
  classification logic can be swapped in here with minimal caller changes

Inherited behavior still used underneath:
- VER-tuned SNR / latency / scale / power gate thresholds from
  ``ver_classifier.py`` (P2 latency window 40–120 ms, inter-peak interval
  20–85 ms, etc.)
- The ``check_details`` keys (``"Scale Range"``, ``"Minimum Power"``,
  ``"P2 Latency"``, ``"Peak Structure"``, ``"SNR"``) are still VER labels
  produced by the inherited logic and will remain until ``ver_classifier.py``
  is replaced with real ECG decision logic.

Future replacement path:
- Replace the delegation inside ``classify_ecg_signal`` with real ECG
  classification logic (rhythm classification, QRS duration gate, PR/QT
  interval checks, arrhythmia detection).
- Update the ``check_details`` key names to ECG-standard labels.
- Update the ``refresh_classifier_cfg`` parameters to ECG-relevant thresholds
  (RR interval, QRS width, etc.).
- Adjacent next replacement targets: ``ver_peaks.py`` (Rank 2) and then
  coordinated ``ver_report.py`` / ``ver_ml_logger.py`` schema update.

See ``docs/ecg-transition-priorities.md § Rank 3`` and ``TRANSITION.md``.
"""

from __future__ import annotations

import logging
from typing import Optional, Tuple, Dict

# INHERITED VER ANALYSIS ENGINE — delegated through this placeholder boundary.
# Replace this import with ECG-specific logic when implementing ecg_classifier.
from ver_classifier import evaluate_ver_peak as _evaluate_ver_peak
from ver_classifier import refresh_classifier_cfg as _ver_refresh_cfg

log = logging.getLogger(__name__)


def classify_ecg_signal(
    peak_scale: float,
    peak_power: float,
    feature1_latency: Optional[float],
    feature2_latency: Optional[float],
    feature3_latency: Optional[float],
    feature2_snr: float,
    classifier_cfg: Optional[dict] = None,
) -> Tuple[bool, Dict[str, bool]]:
    """Classify a signal epoch using the transitional ECG boundary.

    Parameters
    ----------
    peak_scale:
        Dominant scale (Hz) from the wavelet scalogram.
    peak_power:
        Peak power from the wavelet scalogram.
    feature1_latency:
        Latency (ms) of the first detected waveform feature, or ``None``.
    feature2_latency:
        Latency (ms) of the second detected waveform feature, or ``None``.
    feature3_latency:
        Latency (ms) of the third detected waveform feature, or ``None``.
    feature2_snr:
        Signal-to-noise ratio at the second feature.
    classifier_cfg:
        Optional classifier configuration dict; if ``None``, the module-level
        cache is used (populated from ``SettingsManager`` on first call).

    Returns
    -------
    is_detected : bool
        ``True`` if the signal epoch passes all classifier gates.
    check_details : dict[str, bool]
        Per-check pass/fail flags.  Key names are still inherited from the
        underlying VER classifier (``"Scale Range"``, ``"Minimum Power"``,
        ``"P2 Latency"``, ``"Peak Structure"``, ``"SNR"``) and will be
        updated when the ECG classifier is implemented.

    Notes
    -----
    The classification logic is still entirely inherited from
    ``ver_classifier.evaluate_ver_peak``.  These results are **not** ECG
    classifications; they are VER-domain pass/fail decisions used as temporary
    placeholders until real ECG classification is implemented.
    """
    # Delegate to inherited VER classifier — to be replaced with ECG logic.
    is_detected, check_details = _evaluate_ver_peak(
        peak_scale,
        peak_power,
        feature1_latency,
        feature2_latency,
        feature3_latency,
        feature2_snr,
        classifier_cfg,
    )
    return is_detected, check_details


def refresh_classifier_cfg(cfg: dict) -> None:
    """Push an updated classifier config dict into the module cache.

    Call this after the user saves settings in the GUI so that subsequent
    ``classify_ecg_signal`` calls use the new values without restarting.

    Delegates to the inherited VER classifier settings cache.  Replace with
    ECG-specific threshold management when implementing the ECG classifier.
    """
    _ver_refresh_cfg(cfg)
