"""ECG-named main-window boundary module.

Transitional boundary: re-export the inherited VERMainWindow under an ECG name
so callers can migrate away from ver_main imports without changing behavior.
"""
from src.ecg_analyses.ver.ver_main import VERMainWindow as ECGMainWindow

__all__ = ["ECGMainWindow"]
