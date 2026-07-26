"""Module for downsampling LabChart data files."""

from collections import Counter
from pathlib import Path

import numpy as np
from scipy.signal import decimate


def downsample_labchart_file(input_filepath: str) -> tuple[str, str]:
    """
    Downsample a LabChart .txt file from 1000 Hz to 250 Hz using anti-alias decimation.
    Saves the result as <original_name>_250_Hz.txt in the same directory.

    Returns:
        (output_file_path, warning_note)
    """
    input_path = Path(input_filepath)
    output_path = input_path.parent / f"{input_path.stem}_250_Hz{input_path.suffix}"

    source_rate_hz = 1000
    target_rate_hz = 250
    decimation_factor = source_rate_hz // target_rate_hz

    with open(input_path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    data_rows = []
    header_lines = []
    parsing_started = False

    for line in lines:
        parts = line.strip().split("\t")
        try:
            numeric_parts = [float(p) for p in parts if p.strip()]
            if numeric_parts:
                data_rows.append(numeric_parts)
                parsing_started = True
        except ValueError:
            if not parsing_started:
                header_lines.append(line)

    if not data_rows:
        raise ValueError("No numeric data rows found in file.")

    # Enforce consistent row width before creating ndarray
    widths = [len(r) for r in data_rows]
    target_width, _ = Counter(widths).most_common(1)[0]

    cleaned_rows = [r for r in data_rows if len(r) == target_width]
    dropped = len(data_rows) - len(cleaned_rows)

    if not cleaned_rows:
        raise ValueError("No valid numeric rows with consistent column count were found.")

    dropped_note = ""
    if dropped:
        dropped_note = (
            f"Warning: dropped {dropped} malformed row(s) with inconsistent column counts."
        )

    array = np.asarray(cleaned_rows, dtype=float)

    decimated_cols = []
    for col_idx in range(array.shape[1]):
        col = array[:, col_idx]
        try:
            # Primary attempt: FIR filter (highest quality, linear phase)
            dec = decimate(col, q=decimation_factor, ftype="fir", zero_phase=True)
        except Exception:
            try:
                # Secondary attempt: IIR filter (handles shorter/awkward arrays better)
                dec = decimate(col, q=decimation_factor, ftype="iir", zero_phase=True)
            except Exception as e:
                raise RuntimeError(
                    f"Anti-alias decimation completely failed on column {col_idx + 1}. "
                    f"Data might be too short or corrupted. Error: {e}"
                )
        decimated_cols.append(dec)

    decimated = np.column_stack(decimated_cols)

    with open(output_path, "w", encoding="utf-8") as f:
        for line in header_lines:
            f.write(line)
        for row in decimated:
            f.write("\t".join(f"{v:.6g}" for v in row) + "\n")

    return str(output_path), dropped_note