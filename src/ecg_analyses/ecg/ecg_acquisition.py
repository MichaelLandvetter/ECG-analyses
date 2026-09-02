"""ECG-named acquisition compatibility module.

Transitional shim that re-exports acquisition sources from inherited module.
"""
from src.ecg_analyses.ver.ver_acquisition import (
    FileAcquisitionSimulator,
    SerialAcquisitionSource,
)

__all__ = ["FileAcquisitionSimulator", "SerialAcquisitionSource"]
