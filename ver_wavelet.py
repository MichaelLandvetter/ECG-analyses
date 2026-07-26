"""Wavelet analysis utilities for VER averaged epochs aligned with wavelib."""

from __future__ import annotations

from typing import Optional, Tuple

import numpy as np
import pywt

from ver_config import ACQ_CONFIG, WAVELET_CONFIG

def compute_wavelet_scalogram(epoch: np.ndarray, sample_rate: Optional[float] = None, config: Optional[dict] = None) -> Tuple[np.ndarray, np.ndarray]:
    """Computes a wavelet scalogram using dyadic scales matching wavelib."""
    cfg = dict(WAVELET_CONFIG)
    if config:
        cfg.update(config)

    fs = float(sample_rate if sample_rate is not None else ACQ_CONFIG["sample_rate"])
    data = np.asarray(epoch, dtype=float)
    
    # 1. Standard Morlet wavelet definition
    bandwidth = cfg.get("bandwidth", 1.5)
    center_freq = cfg.get("center_freq", 2.0)
    wavelet_shape = f'cmor{bandwidth}-{center_freq}'

    # 2. Generate dyadic logarithmic scales (0.5 to 512) matching wavelib's Y-axis
    # Using 16 fractional sub-octaves per power of 2 for fine resolution
    sub_octaves = 16 
    powers = np.arange(np.log2(0.5), np.log2(512) + 1/sub_octaves, 1/sub_octaves)
    scales = 2 ** powers

    # 3. Compute the Transform using the raw scale matrix
    coeffs, _ = pywt.cwt(data, scales, wavelet_shape, sampling_period=1.0 / fs)
    
    # 4. Calculate Absolute Power (Remove individual block variance normalization)
    # This allows fading signals to naturally look darker/faded in the plot
    power = np.abs(coeffs) ** 2

    return power, scales

    # NOTE: Contrast compression (np.sqrt) is removed to match wavelib's true power scale.
    # The variable is named 'scales' internally but returned where 'freqs' is expected 
    # to maintain compatibility with the report script signature.
    return normalized_power, scales

if __name__ == "__main__":
    t = np.arange(0, 0.5, 1.0 / ACQ_CONFIG["sample_rate"])
    synthetic = np.sin(2 * np.pi * 10 * t) + 0.3 * np.sin(2 * np.pi * 20 * t)
    pwr, s = compute_wavelet_scalogram(synthetic)
    print("Scalogram shape:", pwr.shape, "Scale vector limits:", (s.min(), s.max()))
