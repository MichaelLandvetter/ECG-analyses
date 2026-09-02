"""ECG-named analysis engine compatibility boundary.

Provides ECG-first function names while keeping compatibility aliases for
existing ver_* callers during transition.
"""
from src.ecg_analyses.ver.ver_analysis_engine import (
    detect_ver_peaks as detect_ecg_peaks,
    refresh_analysis_config as refresh_ecg_analysis_config,
    save_ecg_report,
    classify_ecg_signal,
)

# Back-compat aliases (temporary during migration)
detect_ver_peaks = detect_ecg_peaks
refresh_analysis_config = refresh_ecg_analysis_config

__all__ = [
    "detect_ecg_peaks",
    "refresh_ecg_analysis_config",
    "save_ecg_report",
    "classify_ecg_signal",
    # compatibility exports
    "detect_ver_peaks",
    "refresh_analysis_config",
]
