"""ECG-named logging compatibility module.

Transitional shim that re-exports logging setup helpers from the inherited module.
"""
from src.ecg_analyses.ver.ver_logging import setup_logging, setup_frozen_debug_logging

__all__ = ["setup_logging", "setup_frozen_debug_logging"]
