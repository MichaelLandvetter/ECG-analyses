"""ECG-oriented configuration for the ECG Analysis application.

This module exposes the ECG-relevant configuration subset from the inherited
``ver_config`` module, adds an ECG-specific file format definition, and
defines defaults for the ECG processing pipeline introduced in the first
ECG-processing PR.

Usage::

    from ecg_config import (
        ECG_CONFIG, ECG_FILTER_CONFIG, ECG_DISPLAY_CONFIG,
        ECG_FILE_CONFIG, ECG_PROCESSING_CONFIG,
    )

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
    # Lines starting with these prefixes are treated as single-line comments and skipped.
    # Multi-line comment blocks (e.g. /* ... */) are not supported — only line-based comments.
    "comment_chars": ("#", "//", "%"),
    # Column index for the ECG signal (0-based; only column present).
    "ecg_column": 0,
    # Number of header rows to skip before numeric data begins.
    "skip_header": 0,
}

# ---------------------------------------------------------------------------
# ECG processing pipeline configuration
# ---------------------------------------------------------------------------
# These defaults populate the ECG Processing Settings tab and are persisted
# to user_settings.json under the key "ECG_PROCESSING_CONFIG".
#
# String constants are defined here directly (not imported from ecg_pipeline)
# to avoid a circular-import dependency:  ecg_config → ecg_pipeline → ecg_config.
# The canonical constant names live in ecg_pipeline; these are the matching values.

ECG_PROCESSING_CONFIG: dict = {
    # --- Filter ---
    "filter_mode": "Butterworth bandpass",   # ECG_FILTER_DEFAULT from ecg_pipeline
    "lowcut_hz": 0.5,                        # bandpass lower corner (Hz)
    "highcut_hz": 40.0,                      # bandpass upper corner (Hz)
    "filter_order": 4,                       # IIR filter order
    "notch_hz": 50.0,                        # power-line notch frequency (50 or 60 Hz)

    # --- R-peak detection ---
    "detector_method": "neurokit",           # ECG_DETECTOR_DEFAULT from ecg_pipeline

    # --- Rolling-window parameters (streaming / real-time) ---
    "rolling_window_s": 5.0,                 # rolling buffer length (seconds)
    "detection_interval_s": 0.2,             # how often to run detection (seconds)
    "boundary_guard_s": 0.5,                 # right-edge hold-back guard (seconds)
}

# Apply any saved user overrides from user_settings.json
import logging as _logging
_log = _logging.getLogger(__name__)
try:
    from ver_settings import SettingsManager as _SM
    _saved = _SM().load_settings()
    if "ECG_PROCESSING_CONFIG" in _saved:
        ECG_PROCESSING_CONFIG.update(_saved["ECG_PROCESSING_CONFIG"])
except Exception as _exc:
    _log.debug("Could not apply ECG_PROCESSING_CONFIG overrides from JSON: %s", _exc)
