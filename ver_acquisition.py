"""Data acquisition module for file replay and USB serial microcontrollers."""

from __future__ import annotations

import time
import struct
import logging
from pathlib import Path
from typing import Generator, Optional

import numpy as np

from ver_config import ACQ_CONFIG, FILE_CONFIG, SERIAL_CONFIG

log = logging.getLogger(__name__)


class FileAcquisitionSimulator:
    """Replay a raw text file sample-by-sample."""

    def __init__(
        self,
        file_path: str,
        sample_rate: Optional[float] = None,
        speed_factor: Optional[float] = 1.0,
        file_config: Optional[dict] = None,
    ):
        self.file_path = Path(file_path)
        self.sample_rate = sample_rate if sample_rate is not None else ACQ_CONFIG["sample_rate"]
        # speed_factor=1.0 → real-time, 10.0 → 10× faster, None → maximum speed (no sleep)
        self.speed_factor = speed_factor
        self.file_config = dict(FILE_CONFIG)
        if file_config:
            self.file_config.update(file_config)

    def _open(self) -> None:
        """Dummy open method so the background worker doesn't crash."""
        pass

    def close(self) -> None:
        """Dummy close method so the background worker doesn't crash."""
        pass

    def stream_samples(self) -> Generator[np.ndarray, None, None]:
        if not self.file_path.exists():
            raise FileNotFoundError(f"Data file not found: {self.file_path}")

        data = np.loadtxt(
            str(self.file_path),
            delimiter=self.file_config["delimiter"],
            skiprows=self.file_config["skip_header"],
            dtype=float,
        )

        if data.ndim == 1:
            data = data.reshape(1, -1)

        base_sleep = 1.0 / float(self.sample_rate)
        trigger_column = int(self.file_config["trigger_column"])
        eeg_column = int(self.file_config["eeg_column"])
        trigger_mode = self.file_config.get("trigger_mode", "level")
        trigger_threshold = float(self.file_config.get("trigger_threshold", 0.5))

        next_yield_time = time.perf_counter()

        for row in data:
            trigger_value = float(row[trigger_column])
            if trigger_mode == "level" or trigger_mode == "threshold":
                trigger = trigger_value > trigger_threshold
            elif trigger_mode == "interval":
                trigger = trigger_value > trigger_threshold
            else:
                raise ValueError(f"Unsupported trigger mode: {trigger_mode}")

            eeg = float(row[eeg_column])
            yield np.asarray([1.0 if trigger else 0.0, eeg], dtype=float)
            
            # --- DYNAMIC SPEED TRACKING LOGIC ---
            # 1. Read speed INSIDE the loop so live UI changes work instantly!
            current_speed = self.speed_factor
            
            if current_speed is not None and current_speed > 0:
                sleep_interval = base_sleep / current_speed
                next_yield_time += sleep_interval
                
                now = time.perf_counter()
                time_to_wait = next_yield_time - now
                
                if time_to_wait > 0.002:
                    time.sleep(time_to_wait)
                    
                # 2. Only reset the clock if we fall massively behind (2 full seconds).
                # This stops the "1x is too fast" bug where it was skipping micro-stutters.
                elif time_to_wait < -2.0:
                    next_yield_time = now
            else:
                # 3. Maximum speed: don't sleep, but keep the clock synced to 'now'
                # so it smoothly transitions if you change the dropdown back to 1x or 10x.
                next_yield_time = time.perf_counter()
                
class SerialAcquisitionSource:
    """Read live ECG data from a microcontroller over USB serial and log it.

    ECG serial path notes (transition)
    ------------------------------------
    - Only the raw ECG channel is extracted from each binary packet.
    - The flash/stimulus trigger field present in the hardware packet is
      intentionally discarded; flash-trigger decoding is legacy VER behaviour
      and is NOT part of the active ECG workflow.
    - The saved log file contains one column: raw ECG samples only.
    - The yielded sample format is ``np.array([0.0, ecg_value])`` — the leading
      0.0 keeps the format compatible with ``ECGFileLoader.stream_samples()``
      and the ``_handle_single_sample`` pipeline in ``ver_main.py``.
    - Future work: a transitional analysis hook in ``_handle_single_sample``
      (currently driven by the inherited VER trigger/scope processor) will be
      wired to online R-peak detection once the ECG processing module is ready.
    """

    def __init__(
        self,
        port: Optional[str] = None,
        baud_rate: Optional[int] = None,
        sample_rate: Optional[float] = None,
        timeout: Optional[float] = None,
    ):
        self.port = str(port if port is not None else SERIAL_CONFIG["port"])
        self.baud_rate = int(baud_rate if baud_rate is not None else SERIAL_CONFIG["baud_rate"])
        self.sample_rate = float(sample_rate if sample_rate is not None else ACQ_CONFIG["sample_rate"])
        self.timeout = float(timeout if timeout is not None else SERIAL_CONFIG.get("timeout", 2.0))
        self._serial = None
        self._buffer = bytearray()
        self._binary_header = b"\xA5\x5A"
        self._binary_footer = 0x01
        self._binary_packet_size = 9
        self._stream_format: str = "unknown"  # unknown | csv | binary
        self._line_buffer_limit = 1024
        self._dropped_malformed_lines = 0
        self._last_malformed_log_ts = 0.0
        self._malformed_log_interval_s = 5.0
        self._last_timestamp_ms: Optional[int] = None
        self._timing_delta_ms_ema: Optional[float] = None
        self._timing_alpha = 0.1
        self._last_timing_warning_ts = 0.0
        self._timing_warning_interval_s = 5.0
        self._observed_sample_rate_hz: Optional[float] = None
        self._timestamp_wrap_modulus = 2**32
        # Rollover detection window around millis() uint32 wrap boundary.
        self._rollover_guard_ms = 60000

        # NOTE: Flash-trigger state fields (_serial_trigger_high, _serial_trigger_floor,
        # etc.) have been removed from the ECG serial path.  The trigger_state bytes
        # in each hardware packet are parsed but discarded; only the raw ECG channel
        # is used.  See _try_parse_binary_sample() below.

        # Raw ECG capture bookkeeping.
        self._raw_log_file = None
        self._raw_log_path = None

    def _open(self) -> None:
        if self._serial is not None:
            return
        try:
            import serial  # pyserial
        except ImportError as exc:
            raise RuntimeError("pyserial is not installed.") from exc
        self._serial = serial.Serial(self.port, baudrate=self.baud_rate, timeout=self.timeout)

        # Keep a session stamp for serial naming, but defer raw export until
        # the user saves reports (so serial raw data lands in the chosen folder).
        try:
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self._raw_log_path = Path(f"ECG_Serial_{timestamp}.txt")
        except Exception as e:
            print(f"Warning: Could not initialize serial raw capture label: {e}")
            self._raw_log_path = None

    def close(self) -> None:
        if self._serial is not None:
            try:
                self._serial.close()
            except Exception:
                pass
            self._serial = None
            
        if getattr(self, '_raw_log_file', None) is not None:
            try:
                self._raw_log_file.close()
            except Exception:
                pass
            self._raw_log_file = None

    def _log_malformed_line(self, reason: str, line: str = "") -> None:
        self._dropped_malformed_lines += 1
        now = time.monotonic()
        if (now - self._last_malformed_log_ts) < self._malformed_log_interval_s:
            return
        self._last_malformed_log_ts = now
        line_preview = line if len(line) <= 120 else f"{line[:117]}..."
        log.warning(
            "Dropped malformed serial line (%s). dropped_total=%d line=%r",
            reason,
            self._dropped_malformed_lines,
            line_preview,
        )

    def _update_timing_from_timestamp(self, timestamp_ms: int) -> None:
        if self._last_timestamp_ms is None:
            self._last_timestamp_ms = timestamp_ms
            return

        delta = int(timestamp_ms) - int(self._last_timestamp_ms)
        if delta == 0:
            # Duplicate timestamp sample: keep streaming without warning.
            self._last_timestamp_ms = timestamp_ms
            return

        if delta < 0:
            # Handle microcontroller millis() rollover (uint32 wrap).
            if int(self._last_timestamp_ms) >= (self._timestamp_wrap_modulus - self._rollover_guard_ms) and int(timestamp_ms) < self._rollover_guard_ms:
                delta = (int(timestamp_ms) + self._timestamp_wrap_modulus) - int(self._last_timestamp_ms)
            else:
                self._last_timestamp_ms = timestamp_ms
                now = time.monotonic()
                if (now - self._last_timing_warning_ts) >= self._timing_warning_interval_s:
                    self._last_timing_warning_ts = now
                    log.warning("Non-monotonic serial timestamp delta detected: %d ms", delta)
                return

        self._last_timestamp_ms = timestamp_ms

        if self._timing_delta_ms_ema is None:
            self._timing_delta_ms_ema = float(delta)
        else:
            alpha = self._timing_alpha
            self._timing_delta_ms_ema = (1.0 - alpha) * self._timing_delta_ms_ema + alpha * float(delta)

        if self._timing_delta_ms_ema > 0:
            self._observed_sample_rate_hz = 1000.0 / self._timing_delta_ms_ema

        nominal_delta_ms = 1000.0 / float(self.sample_rate) if self.sample_rate > 0 else 0.0
        if nominal_delta_ms > 0 and abs(delta - nominal_delta_ms) > max(2.0, nominal_delta_ms * 0.5):
            now = time.monotonic()
            if (now - self._last_timing_warning_ts) >= self._timing_warning_interval_s:
                self._last_timing_warning_ts = now
                log.warning(
                    "Serial timing irregularity: delta=%d ms nominal=%.2f ms observed_rate=%.2f Hz",
                    delta,
                    nominal_delta_ms,
                    self._observed_sample_rate_hz if self._observed_sample_rate_hz is not None else -1.0,
                )

    def _try_parse_csv_line(self, raw_line: bytes) -> Optional[np.ndarray]:
        try:
            line = raw_line.decode("utf-8")
        except UnicodeDecodeError:
            return None

        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            if self._stream_format == "unknown":
                self._stream_format = "csv"
            return np.asarray([], dtype=float)

        parts = [p.strip() for p in stripped.split(",")]
        lower_parts = [p.lower() for p in parts]
        if len(parts) == 2 and lower_parts[0] == "timestamp_ms" and lower_parts[1] == "ecg_raw":
            self._stream_format = "csv"
            return np.asarray([], dtype=float)

        if len(parts) == 2:
            try:
                timestamp_ms = int(parts[0], 10)
                ecg_raw = int(parts[1], 10)
            except ValueError:
                self._log_malformed_line("invalid integer fields", stripped)
                return np.asarray([], dtype=float)

            if timestamp_ms < 0:
                self._log_malformed_line("negative timestamp", stripped)
                return np.asarray([], dtype=float)
            if timestamp_ms >= self._timestamp_wrap_modulus:
                self._log_malformed_line("timestamp outside uint32 ms range", stripped)
                return np.asarray([], dtype=float)

            self._stream_format = "csv"
            self._update_timing_from_timestamp(timestamp_ms)
            # Keep ecg_raw integer unbounded here for broad compatibility with
            # signed/unsigned ADC formats used across different firmware stacks.
            return np.asarray([0.0, float(ecg_raw)], dtype=float)

        # Keep compatibility with old one-column serial payloads.
        if len(parts) == 1:
            try:
                ecg_raw = int(parts[0], 10)
            except ValueError:
                self._log_malformed_line("unknown line format", stripped)
                return np.asarray([], dtype=float)
            self._stream_format = "csv"
            return np.asarray([0.0, float(ecg_raw)], dtype=float)

        self._log_malformed_line("unexpected field count", stripped)
        return np.asarray([], dtype=float)

    def _try_parse_binary_sample(self, resync: bool = False) -> Optional[np.ndarray]:
        header_index = self._buffer.find(self._binary_header)
        if header_index < 0:
            if resync and len(self._buffer) > 1:
                del self._buffer[:-1]
            return None
        if header_index > 0:
            del self._buffer[:header_index]
        if len(self._buffer) < self._binary_packet_size:
            return None

        packet = bytes(self._buffer[: self._binary_packet_size])
        if packet[-1] != self._binary_footer:
            del self._buffer[0]
            return None

        try:
            # Parse the full hardware packet to consume all bytes correctly.
            # trigger_state is read from the packet but intentionally discarded:
            # flash-trigger decoding is legacy VER behaviour; the ECG serial path
            # uses only the raw ECG channel.  A future R-peak detector will
            # provide beat-locked triggering instead.
            _, _trigger_state_unused, eeg, _ = struct.unpack("<2sHf1s", packet)
        except struct.error:
            del self._buffer[0]
            return None

        del self._buffer[: self._binary_packet_size]
        # Return format matches ECGFileLoader: [0.0, ecg_value].
        # The leading 0.0 is a placeholder trigger (no hardware trigger in ECG path).
        return np.asarray([0.0, float(eeg)], dtype=float)

    def _try_parse_next_sample(self) -> Optional[np.ndarray]:
        if self._stream_format == "binary":
            return self._try_parse_binary_sample(resync=True)

        newline_index = self._buffer.find(b"\n")
        header_index = self._buffer.find(self._binary_header)

        if self._stream_format == "unknown":
            if header_index == 0:
                self._stream_format = "binary"
                return self._try_parse_binary_sample(resync=True)
            if header_index > 0 and (newline_index < 0 or header_index < newline_index):
                del self._buffer[:header_index]
                self._stream_format = "binary"
                return self._try_parse_binary_sample(resync=True)

        if newline_index >= 0:
            raw_line = bytes(self._buffer[:newline_index])
            del self._buffer[: newline_index + 1]
            parsed = self._try_parse_csv_line(raw_line)
            if parsed is None:
                self._log_malformed_line("non-utf8 line")
                return np.asarray([], dtype=float)
            return parsed

        if len(self._buffer) > self._line_buffer_limit:
            drop_n = len(self._buffer) - self._line_buffer_limit
            del self._buffer[:drop_n]
            self._log_malformed_line("serial buffer overflow/glitch")
            newline_index = self._buffer.find(b"\n")
            if newline_index >= 0:
                raw_line = bytes(self._buffer[:newline_index])
                del self._buffer[: newline_index + 1]
                parsed = self._try_parse_csv_line(raw_line)
                if parsed is None:
                    self._log_malformed_line("non-utf8 line")
                    return np.asarray([], dtype=float)
                return parsed
        return None

    def stream_samples(self) -> Generator[np.ndarray, None, None]:
        self._open()
        try:
            while True:
                if self._serial.in_waiting > 0:
                    raw_bytes = self._serial.read(self._serial.in_waiting)
                    self._buffer.extend(raw_bytes)

                while True:
                    sample = self._try_parse_next_sample()
                    if sample is None:
                        break
                    if sample.size == 0:
                        continue
                    yield sample

                time.sleep(0.001)
        finally:
            self.close()
