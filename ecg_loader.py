"""ECG file loader for plain one-column text files.

This module provides the active ECG file input path.  It replaces the
inherited ``FileAcquisitionSimulator`` multi-column SD-card / LabChart
assumptions for the ECG workflow.

Expected file format
--------------------
A plain ``.txt`` file with **one numeric value per line** (raw ADC counts or
millivolts).  Empty lines and lines starting with ``#``, ``//``, or ``%``
are silently skipped.  Non-numeric data lines that do not match any comment
prefix produce a logged warning and are also skipped.

Example::

    # ECG recording — 250 Hz
    0.0012
    0.0015
    -0.0008
    ...

Usage::

    loader = ECGFileLoader("recording.txt", sample_rate=250)

    # Load the full signal as a NumPy array (with validation feedback)
    signal, errors = loader.load()
    if errors:
        print("Validation issues:", errors)

    # Stream samples sample-by-sample (compatible with the acquisition pipeline)
    for sample in loader.stream_samples():
        # sample is np.array([0.0, ecg_value])
        ...

Transition note
---------------
This loader is the active ECG input path (see ``docs/module_migration_status.md``).
The inherited ``FileAcquisitionSimulator`` in ``ver_acquisition.py`` is kept as a
legacy shim for multi-column / trigger-based file formats and USB serial replay.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Generator

import numpy as np

log = logging.getLogger(__name__)

_COMMENT_PREFIXES = ("#", "//", "%")


class ECGFileLoader:
    """Load a plain one-column ECG text file and stream samples.

    The yielded sample format ``np.array([trigger, ecg_value])`` is
    intentionally compatible with the existing ``_handle_single_sample``
    pipeline in ``ver_main.py``.  The trigger channel is always ``0.0``
    (no hardware trigger in plain ECG text files).

    Parameters
    ----------
    file_path:
        Path to the ``.txt`` ECG data file.
    sample_rate:
        Sample rate in Hz used for replay timing.  Defaults to 250 Hz.
    speed_factor:
        Replay speed multiplier.  ``1.0`` → real-time, ``10.0`` → 10×,
        ``None`` → maximum speed (no sleep).
    """

    def __init__(
        self,
        file_path: str,
        sample_rate: float = 250.0,
        speed_factor: float | None = 1.0,
    ):
        self.file_path = Path(file_path)
        self.sample_rate = float(sample_rate)
        self.speed_factor = speed_factor

    # ------------------------------------------------------------------
    # Compatibility shims — required by the AcquisitionWorker contract
    # ------------------------------------------------------------------

    def _open(self) -> None:
        pass

    def close(self) -> None:
        pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self) -> tuple[np.ndarray, list[str]]:
        """Read the entire file and return ``(signal_array, validation_errors)``.

        Non-numeric lines are skipped with a warning message appended to the
        returned error list; they do not raise an exception.

        Returns
        -------
        signal_array :
            1-D float64 array of ECG sample values.  Empty array if the file
            contains no valid numeric data.
        validation_errors :
            List of human-readable validation messages (non-fatal).  An empty
            list means the file loaded cleanly.
        """
        samples: list[float] = []
        errors: list[str] = []

        if not self.file_path.exists():
            errors.append(f"File not found: {self.file_path}")
            return np.array([], dtype=float), errors

        with self.file_path.open(encoding="utf-8", errors="replace") as fh:
            for lineno, raw_line in enumerate(fh, start=1):
                line = raw_line.strip()
                if not line:
                    continue
                if any(line.startswith(pfx) for pfx in _COMMENT_PREFIXES):
                    continue
                try:
                    samples.append(float(line))
                except ValueError:
                    msg = f"Line {lineno}: skipped non-numeric value {line!r}"
                    errors.append(msg)
                    log.warning("ECGFileLoader: %s", msg)

        if not samples:
            errors.append(
                f"No valid ECG data found in '{self.file_path.name}'. "
                "Ensure the file contains one numeric value per line."
            )

        return np.array(samples, dtype=float), errors

    def stream_samples(self) -> Generator[np.ndarray, None, None]:
        """Stream the file sample-by-sample at the configured replay speed.

        Each yielded item is ``np.array([trigger, ecg_value])`` where
        ``trigger`` is always ``0.0`` (no hardware trigger in plain ECG
        files).  This format is compatible with the existing
        ``_handle_single_sample`` pipeline in ``ver_main.py``.

        Raises
        ------
        FileNotFoundError
            If the file does not exist when streaming begins.
        ValueError
            If the file contains no valid ECG samples after skipping comments
            and non-numeric lines.
        """
        if not self.file_path.exists():
            raise FileNotFoundError(f"ECG data file not found: {self.file_path}")

        signal, errors = self.load()

        if signal.size == 0:
            raise ValueError(
                f"No valid ECG data found in '{self.file_path.name}'. "
                "Ensure the file contains one numeric value per line."
            )

        if errors:
            log.warning(
                "ECGFileLoader: %d validation issue(s) while reading '%s'",
                len(errors),
                self.file_path.name,
            )

        # Minimum sleep: waits under 2 ms are shorter than typical OS sleep
        # resolution, so skip the syscall to avoid waking up later than expected.
        _MIN_SLEEP_S = 0.002
        # Clock reset: if we fall more than 2 s behind schedule (e.g. after a UI
        # pause or heavy processing burst) reset the reference time instead of
        # trying to catch up by skipping sleeps for seconds.
        _CLOCK_RESET_S = 2.0

        base_sleep = 1.0 / self.sample_rate
        next_yield_time = time.perf_counter()

        for value in signal:
            yield np.array([0.0, float(value)], dtype=float)

            current_speed = self.speed_factor
            if current_speed is not None and current_speed > 0:
                sleep_interval = base_sleep / current_speed
                next_yield_time += sleep_interval
                now = time.perf_counter()
                wait = next_yield_time - now
                if wait > _MIN_SLEEP_S:
                    time.sleep(wait)
                elif wait < -_CLOCK_RESET_S:
                    # Fell far behind (e.g. after a pause); reset the clock.
                    next_yield_time = now
            else:
                # Maximum speed — no sleep; keep clock in sync for smooth
                # transitions when the speed combo is changed back to 1× or 10×.
                next_yield_time = time.perf_counter()
