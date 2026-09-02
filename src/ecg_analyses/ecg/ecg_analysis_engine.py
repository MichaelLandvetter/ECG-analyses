"""ECG-named analysis engine compatibility boundary.

Transitional shim that re-exports analysis functions from inherited
ver_analysis_engine so callers can migrate off direct ver_* imports.
"""
from src.ecg_analyses.ver.ver_analysis_engine import (
    detect_ver_peaks,
    refresh_analysis_config,
    save_ecg_report,
    classify_ecg_signal,
)

__all__ = [
    "detect_ver_peaks",
    "refresh_analysis_config",
    "save_ecg_report",
    "classify_ecg_signal",
]
