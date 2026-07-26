"""Data acquisition module for file replay and USB serial microcontrollers."""

from __future__ import annotations

import time
import struct
from pathlib import Path
from typing import Generator, Optional

import numpy as np

from ver_config import ACQ_CONFIG, FILE_CONFIG, SERIAL_CONFIG


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
    """Read live EEG/trigger data from a microcontroller over USB serial and log it."""

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
        self._serial_trigger_high = False
        self._serial_trigger_floor = 0.0
        self._serial_trigger_ceil = 1.0
        self._serial_trigger_high_threshold = float(SERIAL_CONFIG.get("trigger_high_threshold", 0.7))
        self._serial_trigger_low_threshold = float(SERIAL_CONFIG.get("trigger_low_threshold", 0.3))
        
        # Clean logging variables
        self._raw_log_file = None
        self._raw_log_path = None

    def _decode_serial_trigger(self, trigger_state: int) -> float:
        raw_level = max(0.0, float(trigger_state))
        self._serial_trigger_floor = min(self._serial_trigger_floor, raw_level)
        self._serial_trigger_ceil = max(self._serial_trigger_ceil, raw_level)
        span = self._serial_trigger_ceil - self._serial_trigger_floor
        if span > 0:
            normalized_level = (raw_level - self._serial_trigger_floor) / span
        else:
            normalized_level = 0.0

        if self._serial_trigger_high:
            if normalized_level <= self._serial_trigger_low_threshold:
                self._serial_trigger_high = False
        elif normalized_level >= self._serial_trigger_high_threshold:
            self._serial_trigger_high = True

        return 1.0 if self._serial_trigger_high else 0.0

    def _open(self) -> None:
        if self._serial is not None:
            return
        try:
            import serial  # pyserial
        except ImportError as exc:
            raise RuntimeError("pyserial is not installed.") from exc
        self._serial = serial.Serial(self.port, baudrate=self.baud_rate, timeout=self.timeout)

        # Start the background data logger
        try:
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self._raw_log_path = Path(f"RAW_USB_Data_{timestamp}.txt")
            self._raw_log_file = open(self._raw_log_path, "w")
            
            # Write exactly 2 columns of dummy headers if your LabChart config expects skipped lines
            skip_lines = int(FILE_CONFIG.get("skip_header", 0))
            for i in range(skip_lines):
                self._raw_log_file.write(f"Header_{i}\tHeader_{i}\n")
        except Exception as e:
            print(f"Warning: Could not start raw data logger: {e}")
            self._raw_log_file = None

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

    def _try_parse_binary_sample(self) -> Optional[np.ndarray]:
        header_index = self._buffer.find(self._binary_header)
        if header_index < 0:
            if len(self._buffer) > 1:
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
            _, trigger_state, eeg, _ = struct.unpack("<2sHf1s", packet)
        except struct.error:
            del self._buffer[0]
            return None

        del self._buffer[: self._binary_packet_size]
        trigger_level = self._decode_serial_trigger(trigger_state)
        return np.asarray([trigger_level, float(eeg)], dtype=float)

    def stream_samples(self) -> Generator[np.ndarray, None, None]:
        self._open()
        try:
            while True:
                if self._serial.in_waiting > 0:
                    raw_bytes = self._serial.read(self._serial.in_waiting)
                    self._buffer.extend(raw_bytes)

                while True:
                    sample = self._try_parse_binary_sample()
                    if sample is not None:
                        # --- STRICTLY 2 COLUMNS (Trigger, EEG) ---
                        if self._raw_log_file is not None:
                            row = [str(sample[0]), str(sample[1])]
                            self._raw_log_file.write("\t".join(row) + "\n")
                            
                        yield sample
                    else:
                        break

                time.sleep(0.001)
        finally:
            self.close()