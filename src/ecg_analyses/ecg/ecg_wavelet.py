"""ECG-named wavelet compatibility module.

Transitional shim that re-exports wavelet helpers from inherited module.
"""
from src.ecg_analyses.ver.ver_wavelet import compute_wavelet_scalogram

__all__ = ["compute_wavelet_scalogram"]
