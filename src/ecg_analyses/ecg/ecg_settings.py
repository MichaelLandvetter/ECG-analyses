"""ECG-named settings compatibility module.

Transitional shim that re-exports SettingsManager from the inherited module.
"""
from src.ecg_analyses.ver.ver_settings import SettingsManager

__all__ = ["SettingsManager"]
