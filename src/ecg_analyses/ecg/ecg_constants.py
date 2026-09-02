"""ECG-named constants compatibility module.

Transitional shim that re-exports scope/filter mode constants from the inherited module.
"""
from src.ecg_analyses.ver.ver_constants import (
    DEFAULT_SCOPE_FILTER_MODE,
    SCOPE_FILTER_FIR,
    SCOPE_FILTER_SAVGOL,
)

__all__ = ["DEFAULT_SCOPE_FILTER_MODE", "SCOPE_FILTER_FIR", "SCOPE_FILTER_SAVGOL"]
