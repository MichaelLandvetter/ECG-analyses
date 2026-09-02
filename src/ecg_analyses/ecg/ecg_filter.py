"""ECG-named filter compatibility module.

Transitional shim that re-exports BandpassFilter from the inherited module.
"""
from src.ecg_analyses.ver.ver_filter import BandpassFilter

__all__ = ["BandpassFilter"]
