"""Module for evaluating and classifying Visually Evoked Responses (VERs)."""

import logging
from typing import Tuple, Dict, Optional

log = logging.getLogger(__name__)

# Module-level settings cache.  Populated on the first call and refreshed
# whenever the caller passes an explicit ``classifier_cfg`` dict (e.g. after
# the user clicks "Save Settings" in the GUI).
_cached_classifier_cfg: dict | None = None


def _get_classifier_cfg(override: dict | None) -> dict:
    """Return classifier config, using the module cache unless an override is supplied."""
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
    ``evaluate_ver_peak`` calls use the new values without restarting.
    """
    _get_classifier_cfg(cfg)


def evaluate_ver_peak(
    peak_scale: float,
    peak_power: float,
    p1_latency,
    p2_latency,
    p3_latency,
    p2_snr_val: float,
    classifier_cfg: dict | None = None,
):
    cfg = _get_classifier_cfg(classifier_cfg)

    # Extract values with defaults
    min_scale = cfg.get("min_scale", 8.0)
    max_scale = cfg.get("max_scale", 32.0)
    min_power = cfg.get("min_power", 1.0e-7)
    p2_min = cfg.get("p2_min_latency", 40.0)
    p2_max = cfg.get("p2_max_latency", 120.0)
    ipi_min = cfg.get("ipi_min", 20.0)
    ipi_max = cfg.get("ipi_max", 85.0)
    p3_p2_max = cfg.get("p3_p2_max", 120.0)
    snr_threshold = cfg.get("snr_threshold", 2.0)

    # 1. Scale/Frequency Verification
    scale_is_valid = (min_scale <= peak_scale <= max_scale)

    # 2. Time-Frequency Synchronization
    sync_is_valid = (peak_power > min_power)

    # 3. P2 Window Verification
    p2_window_valid = False
    if p2_latency is not None:
        p2_window_valid = (p2_min <= p2_latency <= p2_max)

    # 4. Structural Verification
    structure_is_valid = False
    if p2_latency is not None and p1_latency is not None:
        inter_peak_interval = p2_latency - p1_latency
        structure_is_valid = (ipi_min <= inter_peak_interval <= ipi_max)
        if p3_latency is not None:
            structure_is_valid = structure_is_valid and ((p3_latency - p2_latency) <= p3_p2_max)

    # 5. NEW: SNR Verification
    snr_is_valid = (p2_snr_val >= snr_threshold)

    # --- COMBINE CRITERIA ---
    is_ver = bool(scale_is_valid and sync_is_valid and p2_window_valid and structure_is_valid and snr_is_valid)

    failure_details = {
        "Scale Range": scale_is_valid,
        "Minimum Power": sync_is_valid,
        "P2 Latency": p2_window_valid,
        "Peak Structure": structure_is_valid,
        "SNR": snr_is_valid  # <-- Added to the failure reasons!
    }

    return is_ver, failure_details