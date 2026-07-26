"""ECG-oriented configuration for the ECG Analysis application.

This module exposes the ECG-relevant configuration subset from the inherited
``ver_config`` module and adds an ECG-specific file format definition.  It
serves as the canonical config entry-point for the active ECG path.

Usage::

    from ecg_config import ECG_CONFIG, ECG_FILTER_CONFIG, ECG_DISPLAY_CONFIG, ECG_FILE_CONFIG

Backward compatibility: ``ver_config`` is preserved as a compatibility shim.
Settings are persisted via ``ver_settings.SettingsManager`` and the same JSON
file; this module simply re-exports the ECG-relevant subset under ECG-oriented
names and adds the ECG file format definition.

Legacy keys intentionally omitted from this module
---------------------------------------------------
- ``EPOCH_CONFIG``  — VER flash-epoch concept; not used in the ECG input path.
- ``SPECIES``       — VER fish species list; not relevant for ECG.
- ``WAVELET_CONFIG`` — transitional; keep in ver_config until wavelet panel is
                       confirmed replaced by the HR tachometer view.
- ``FILE_FORMATS``  — SD-card / LabChart distinction; replaced by
                       ``ECG_FILE_CONFIG`` below.
"""

from __future__ import annotations

from ver_config import (
    ACQ_CONFIG as _ACQ_CONFIG,
    FILTER_CONFIG as _FILTER_CONFIG,
    SERIAL_CONFIG as _SERIAL_CONFIG,
    DISPLAY_CONFIG as _DISPLAY_CONFIG,
)

# ---------------------------------------------------------------------------
# ECG-oriented config dictionaries (re-exported under ECG names)
# ---------------------------------------------------------------------------

ECG_CONFIG: dict = {
    "sample_rate": _ACQ_CONFIG.get("sample_rate", 250),
    "simulate_realtime": _ACQ_CONFIG.get("simulate_realtime", True),
    "source_mode": _ACQ_CONFIG.get("source_mode", "File"),
}

ECG_FILTER_CONFIG: dict = {
    "lowcut_hz": _FILTER_CONFIG.get("lowcut_hz", 0.5),
    "highcut_hz": _FILTER_CONFIG.get("highcut_hz", 40.0),
    "order": _FILTER_CONFIG.get("order", 4),
    "sample_rate": _FILTER_CONFIG.get("sample_rate", 250),
}

ECG_SERIAL_CONFIG: dict = dict(_SERIAL_CONFIG)

ECG_DISPLAY_CONFIG: dict = {
    "scroll_seconds": _DISPLAY_CONFIG.get("scroll_seconds", 10),
    "scroll_max_fps": _DISPLAY_CONFIG.get("scroll_max_fps", 30),
}

# ---------------------------------------------------------------------------
# ECG file format — plain text, one numeric column (raw ADC or mV values)
# ---------------------------------------------------------------------------
# This replaces the inherited SD-card / LabChart FILE_FORMATS distinction.
# The active ECG input path always expects a single-column .txt file.

ECG_FILE_CONFIG: dict = {
    # Lines starting with these prefixes are treated as comments and skipped.
    "comment_chars": ("#", "//", "%"),
    # Column index for the ECG signal (0-based; only column present).
    "ecg_column": 0,
    # Number of header rows to skip before numeric data begins.
    "skip_header": 0,
}
