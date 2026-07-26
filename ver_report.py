"""Generate final summary VER report figures."""

from __future__ import annotations

import csv
import math
import datetime
from pathlib import Path
from typing import List, Optional
from ver_config import EPOCH_CONFIG

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.lines import Line2D
from ver_wavelet import compute_wavelet_scalogram
from matplotlib import colors
from ver_classifier import evaluate_ver_peak

# Keeping the variable name the same so it doesn't break references
MINUTE_COLORS = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
    "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",]


def _get_report_dir(data_file_path: str) -> Path:
    """Create and return the report output directory. Handles live streams automatically."""
    data_path = Path(data_file_path)

    # 1. Explicitly intercept the dummy name used for live streams
    if "serial_live_report" in data_path.stem:
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        # We put the live sessions in the 'Reports' folder next to the program
        report_dir = Path.cwd() / "Reports" / f"Live_Session_{timestamp}"
        
    # 2. Check if it's a real data file analysis
    elif data_path.exists() or data_path.suffix.lower() in ['.txt', '.csv']:
        report_dir = data_path.parent / "Reports" / data_path.stem
        
    # 3. Fallback for any other unrecognized live stream strings
    else:
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        report_dir = Path.cwd() / "Reports" / f"Live_Session_{timestamp}"

    report_dir.mkdir(parents=True, exist_ok=True)
    return report_dir

def save_ver_report(
    data_file_path: str,
    session_averages: List[np.ndarray],
    epoch_time_ms: np.ndarray,
    session_wavelets: Optional[List[np.ndarray]] = None,
    session_wavelet_freqs: Optional[np.ndarray] = None,
    session_labels: Optional[List[str]] = None,
    session_ver_peaks: Optional[List[dict]] = None,
    session_flash_counts: Optional[List[Optional[int]]] = None,
    session_flash_counts_accepted: Optional[List[Optional[int]]] = None,
    session_artifact_rejection_enabled: Optional[List[Optional[bool]]] = None,
    session_artifact_exclusion_thresholds: Optional[List[Optional[float]]] = None,
    human_overrides: Optional[List[bool]] = None,
    force_stem: Optional[str] = None
) -> Optional[dict]:
    
    if not session_averages:
        return None

    # 1. Establish the unified prefix (stem) for folders and files
    data_path = Path(data_file_path)
    if force_stem:
        stem = force_stem
    else:
        stem = data_path.stem
        # Only generate a timestamp on the VERY FIRST pass for live data
        if "serial_live_report" in stem:
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            stem = f"Live_Session_{timestamp}"

    # 2. Establish the directory using the locked stem
    if "serial_live_report" in data_path.stem or "Live_Session" in stem:
        report_dir = Path.cwd() / "Reports" / stem
    else:
        report_dir = data_path.parent / "Reports" / stem
        
    report_dir.mkdir(parents=True, exist_ok=True)
    
    # 3. Establish all file paths using the locked stem!
    png_path = report_dir / f"{stem}.png"
    pdf_path = report_dir / f"{stem}.pdf"
    summary_path = report_dir / f"{stem}_summary.csv"
    waveforms_path = report_dir / f"{stem}_waveforms.csv"

    # 4. Compute Wavelets if missing
    averages = np.asarray(session_averages, dtype=float)
    if session_wavelets is None or session_wavelet_freqs is None:
        computed_wavelets = []
        freqs = None
        for avg in averages:
            power, freqs = compute_wavelet_scalogram(avg)
            computed_wavelets.append(power)
        session_wavelets = computed_wavelets
        session_wavelet_freqs = freqs

    freq_min = float(session_wavelet_freqs[0])
    freq_max = float(session_wavelet_freqs[-1])
    
    # Calculate seconds dynamically for fallback labels
    seconds_per_block = int(EPOCH_CONFIG["flashes_per_session"] / 2.0)
    labels = session_labels or [f"{int(idx * seconds_per_block)} s" for idx in range(1, len(averages) + 1)]

    # 5. Build Figures
    fig1 = _build_figures_page(
        averages,
        epoch_time_ms,
        session_wavelets,
        session_wavelet_freqs,
        freq_min,
        freq_max,
        labels,
        session_ver_peaks=session_ver_peaks,
    )

    fig2 = _build_stats_table_page(
        session_wavelets, 
        session_wavelet_freqs, 
        epoch_time_ms, 
        labels, 
        session_ver_peaks, 
        human_overrides
    )

    # 6. Save Figures to Disk
    fig1.savefig(png_path, dpi=150)
    with PdfPages(pdf_path) as pdf:
        pdf.savefig(fig1, bbox_inches="tight")
        pdf.savefig(fig2, bbox_inches="tight")

    plt.close(fig1)
    plt.close(fig2)

    # 7. Save CSVs
    _write_summary_csv(
        summary_path,
        session_wavelets,
        session_wavelet_freqs,
        epoch_time_ms,
        session_ver_peaks,
        session_flash_counts,
        human_overrides,
        session_flash_counts_accepted,
        session_artifact_rejection_enabled=session_artifact_rejection_enabled,
        session_artifact_exclusion_thresholds=session_artifact_exclusion_thresholds,
    )
    print(f"Saved summary CSV: {summary_path}")

    _write_waveforms_csv(waveforms_path, averages, epoch_time_ms)
    print(f"Saved waveforms CSV: {waveforms_path}")

    return {
        "png": str(png_path), 
        "pdf": str(pdf_path), 
        "report_dir": str(report_dir), 
        "summary_csv": str(summary_path), 
        "waveforms_csv": str(waveforms_path)
    }

def _write_summary_csv(
    path: Path,
    session_wavelets: List[np.ndarray],
    session_wavelet_freqs: np.ndarray, # Carrying your Scales array
    epoch_time_ms: np.ndarray,
    session_ver_peaks: Optional[List[dict]],
    session_flash_counts: Optional[List[Optional[int]]],
    human_overrides: Optional[List[bool]] = None,
    session_flash_counts_accepted: Optional[List[Optional[int]]] = None,
    session_artifact_rejection_enabled: Optional[List[Optional[bool]]] = None,
    session_artifact_exclusion_thresholds: Optional[List[Optional[float]]] = None,
) -> None:
    """Write per-block summary statistics to a CSV file with perfectly aligned columns."""

    def _peak_vals(ver_peaks, key):
        if ver_peaks is None:
            return "", "", ""
        p = ver_peaks.get(key, {})
        if p.get("found"):
            lat = p["latency_ms"]
            amp = p["amplitude"]
            snr = p.get("snr", float("nan"))
            lat_val = "" if math.isnan(lat) else lat
            amp_val = "" if math.isnan(amp) else amp
            snr_val = "" if math.isnan(snr) else snr
            return lat_val, amp_val, snr_val
        return "", "", ""

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        
        # FIXED HEADERS: Explicitly ordered columns to prevent cell skipping or shifting
        writer.writerow([
            "Time_Block", "N_flashes_total", "N_flashes_accepted", "N_flashes_rejected",
            "Peak_power", "Peak_scale", "Wavelet_peak_latency_ms", 
            "VER_label", "Reason", "Noise_RMS",
            "Peak1_latency_ms", "Peak1_amplitude", "Peak1_SNR",
            "Peak2_latency_ms", "Peak2_amplitude", "Peak2_SNR",
            "Peak3_latency_ms", "Peak3_amplitude", "Peak3_SNR",
            "Exclusion_Enabled", "Exclusion_Threshold",
        ])
        
        for idx, wavelet in enumerate(session_wavelets):
            # Locate raw wavelet landmarks
            peak_idx = np.unravel_index(np.argmax(wavelet), wavelet.shape)
            peak_power = float(wavelet[peak_idx])
            peak_scale = float(session_wavelet_freqs[peak_idx[0]])
            wavelet_peak_latency_ms = float(epoch_time_ms[peak_idx[1]])

            n_flashes_total = ""
            n_flashes_accepted = ""
            n_flashes_rejected = ""
            if session_flash_counts and idx < len(session_flash_counts):
                fc = session_flash_counts[idx]
                if fc is not None:
                    n_flashes_total = fc
                    if session_flash_counts_accepted and idx < len(session_flash_counts_accepted):
                        fa = session_flash_counts_accepted[idx]
                        if fa is not None:
                            n_flashes_accepted = fa
                            n_flashes_rejected = fc - fa

            exclusion_enabled = EPOCH_CONFIG.get("artifact_rejection_enabled", True)
            if session_artifact_rejection_enabled and idx < len(session_artifact_rejection_enabled):
                artifact_enabled = session_artifact_rejection_enabled[idx]
                if artifact_enabled is not None:
                    exclusion_enabled = artifact_enabled

            exclusion_threshold = EPOCH_CONFIG.get("artifact_exclusion_uv", 0.01)
            if session_artifact_exclusion_thresholds and idx < len(session_artifact_exclusion_thresholds):
                artifact_threshold = session_artifact_exclusion_thresholds[idx]
                if artifact_threshold is not None:
                    exclusion_threshold = artifact_threshold

            # Extract structural data from time-domain peaks dictionary
            ver_peaks = session_ver_peaks[idx] if session_ver_peaks and idx < len(session_ver_peaks) else None
            p1_lat, p1_amp, p1_snr = _peak_vals(ver_peaks, "Peak-1")
            p2_lat, p2_amp, p2_snr = _peak_vals(ver_peaks, "Peak-2")
            p3_lat, p3_amp, p3_snr = _peak_vals(ver_peaks, "Peak-3")
            
            # --- EXTRACT VARIABLES FOR CSV EVALUATION ---
            p1_latency_val = None
            p2_latency_val = None
            p3_latency_val = None
            p2_snr_val = 0.0
            
            if ver_peaks is not None:
                p1_dict = ver_peaks.get('Peak-1', {})
                p2_dict = ver_peaks.get('Peak-2', {})
                p3_dict = ver_peaks.get('Peak-3', {})
                
                p1_latency_val = float(p1_dict['latency_ms']) if p1_dict.get('found') and p1_dict.get('latency_ms') is not None else None
                p2_latency_val = float(p2_dict['latency_ms']) if p2_dict.get('found') and p2_dict.get('latency_ms') is not None else None
                p3_latency_val = float(p3_dict['latency_ms']) if p3_dict.get('found') and p3_dict.get('latency_ms') is not None else None
                
                p2_snr_val = float(p2_dict['snr']) if p2_dict.get('found') and p2_dict.get('snr') is not None else 0.0

            # EXTERNAL MULTI-PARAMETRIC EVALUATION ---
            is_ver, failure_details = evaluate_ver_peak(peak_scale, peak_power, p1_latency_val, p2_latency_val, p3_latency_val, p2_snr_val)
            
        
            # --- NEW OVERRIDE LOGIC FOR CSV ---
            if human_overrides is not None and idx < len(human_overrides):
                is_ver = human_overrides[idx]
                reason = "Human Validated" if is_ver else "Human Rejected"
            else:
                if is_ver:
                    reason = "Passed"
                else:
                    failed_tests = [test_name for test_name, passed in failure_details.items() if not passed]
                    reason = "Failed: " + ", ".join(failed_tests)    
            
            # Finalize the label based on whoever made the final decision
            ver_label = "Yes" if is_ver else "No"
            
            # ----------------------------------
            
            noise_rms = ""
            
            if ver_peaks is not None:
                noise = ver_peaks.get("noise_rms", float("nan"))
                if isinstance(noise, (int, float)):
                    noise_rms = "" if math.isnan(noise) else noise
            
            # Dynamic time tracking logic
            seconds = int((idx + 1) * (EPOCH_CONFIG["flashes_per_session"] / 2.0))

            # WRITER MAPPING: Every variable is written exactly to match its corresponding header index
            writer.writerow([
                f"{seconds} s", 
                n_flashes_total,
                n_flashes_accepted,
                n_flashes_rejected,
                f"{peak_power:.3e}", 
                f"{peak_scale:.1f}", 
                f"{wavelet_peak_latency_ms:.1f}", 
                ver_label,
                reason,
                noise_rms,
                p1_lat, p1_amp, p1_snr,
                p2_lat, p2_amp, p2_snr,
                p3_lat, p3_amp, p3_snr,
                exclusion_enabled, exclusion_threshold,
            ])

def _write_waveforms_csv(
    path: Path,
    averages: np.ndarray,
    epoch_time_ms: np.ndarray,
) -> None:
    """Write per-block VER waveforms to a CSV file (one column per block)."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        seconds_per_block = int(EPOCH_CONFIG["flashes_per_session"] / 2.0)
        header = ["Time_ms"] + [f"{int((idx + 1) * seconds_per_block)}s" for idx in range(len(averages))]
        writer.writerow(header)
        for t_idx, t in enumerate(epoch_time_ms):
            row = [t] + [float(avg[t_idx]) for avg in averages]
            writer.writerow(row)


def _build_figures_page(
    averages: np.ndarray,
    epoch_time_ms: np.ndarray,
    session_wavelets: List[np.ndarray],
    session_wavelet_freqs: np.ndarray,
    freq_min: float,
    freq_max: float,
    labels: List[str],
    session_ver_peaks: Optional[List[dict]] = None,
) -> plt.Figure:
    fig = plt.figure(figsize=(18, 10), facecolor="white", constrained_layout=True)
    gs = fig.add_gridspec(2, 1)

    # Row 1: Sequential VER averages on a block axis
    ax1 = fig.add_subplot(gs[0, 0])
    ax1.set_facecolor("white")
    epoch_width = float(epoch_time_ms[-1] - epoch_time_ms[0])
    epoch_start = float(epoch_time_ms[0])
    for idx, avg in enumerate(averages):
        x_offset = idx * epoch_width
        x_plot = epoch_time_ms - epoch_start + x_offset
        ax1.plot(
            x_plot,
            avg,
            linewidth=1.2,
            alpha=0.9,
            color=MINUTE_COLORS[idx % len(MINUTE_COLORS)],
        )
        if idx > 0:
            ax1.axvline(x=x_offset, color="gray", linestyle="--", linewidth=0.8, alpha=0.5)
        ver_peaks = session_ver_peaks[idx] if session_ver_peaks and idx < len(session_ver_peaks) else None
        if ver_peaks:
            for peak_name, color in [("Peak-1", "blue"), ("Peak-2", "red"), ("Peak-3", "green")]:
                peak = ver_peaks.get(peak_name)
                if peak and peak.get("found"):
                    marker_x = float(peak["latency_ms"]) - epoch_start + x_offset
                    marker_y = float(peak["amplitude"])
                    if math.isnan(marker_x) or math.isnan(marker_y):
                        continue
                    marker = '^' if peak["amplitude"] >= 0 else 'v'
                    if peak.get("above_threshold", True):
                        marker_face_color = color
                        marker_edge_color = color
                    else:
                        marker_face_color = "none"
                        marker_edge_color = "#888888"
                    ax1.plot(
                        marker_x,
                        marker_y,
                        marker=marker,
                        markerfacecolor=marker_face_color,
                        markeredgecolor=marker_edge_color,
                        markersize=6,
                        linestyle="None",
                    )
    total_width = epoch_width * len(averages)
    tick_positions = [(idx + 0.5) * epoch_width for idx in range(len(averages))]
    
    # Dynamic labels for X-axis
    seconds_per_block = int(EPOCH_CONFIG["flashes_per_session"] / 2.0)
    tick_labels = [f"{int((idx + 1) * seconds_per_block)}s" for idx in range(len(averages))]
    
    ax1.axhline(y=0, color="gray", linestyle="--", linewidth=0.8, alpha=0.5)
    ax1.set_xlim(0.0, total_width)
    ax1.set_xticks(tick_positions)
    ax1.set_xticklabels(tick_labels)
    ax1.set_title("VER Evolution")
    ax1.set_xlabel("Time Block")
    ax1.set_ylabel("Amplitude (µV)")
    ax1.legend(
        handles=[
            Line2D([0], [0], marker='D', color="blue", linestyle="None", markersize=6, label="Peak-1"),
            Line2D([0], [0], marker='D', color="red", linestyle="None", markersize=6, label="Peak-2"),
            Line2D([0], [0], marker='D', color="green", linestyle="None", markersize=6, label="Peak-3"),
        ],
        loc="upper right",
        fontsize=8,
        framealpha=0.8,
    )

        # Row 2: Wavelet scalograms sequentially in one wide panel
    ax2 = fig.add_subplot(gs[1, 0])
    ax2.set_facecolor("white")
    
    # Combine the wavelets first
    combined_wavelets = np.hstack(session_wavelets)
    
    # scale to the 98.5th percentile to bring out the faint structures
    global_vmax = float(np.percentile(combined_wavelets, 98.5))
    
            
    # Create matching time bins for the x-axis grid
    time_points = np.linspace(0.0, total_width, combined_wavelets.shape[1])
    
    # 3. Paint the combined matrix using pcolormesh to handle log scale grids
        # 1. Combine the raw wavelets
    combined_wavelets = np.hstack(session_wavelets)

    # 2. Establish a floor for zero/negative values to avoid math errors in log space
    # We'll set the floor to 1/1000th of the absolute maximum power value
    max_val = np.max(combined_wavelets)
    min_val = max_val / 1000.0

    # 3. Paint the canvas using a true Logarithmic Normalization scale
    """
    cmap="viridis" (Matplotlib Default): A perceptually uniform map that goes from deep purple (low energy) through teal and green to bright yellow (high energy). It is highly optimized for human eyes to spot gradual transitions and is completely colorblind-friendly.
    cmap="magma" or cmap="inferno": These move from pitch black through dark purple and fiery orange to vibrant white. They make low-amplitude features (like your 4th and 5th blocks) stand out sharply against a pure black background.
    cmap="cubehelix": This creates a smooth, twisting loop through the color spectrum that increases monotonically in brightness. It ensures that if your report is ever printed or copied in black-and-white, the information and shading transitions remain perfectly readable.
    cmap="gist_earth": This closely mimics traditional physical laboratory scales, using earthy greens, oceanic blues, and bright landmass whites.
    
    """
    
    im = ax2.pcolormesh(
        time_points,
        session_wavelet_freqs,
        combined_wavelets,
        shading="nearest",
        cmap="gist_earth",
        #cmap="magma",
        #cmap="cubehelix",
        #cmap="inferno",        
        #cmap="viridis",
        norm=colors.LogNorm(vmin=min_val, vmax=max_val)  # Replaces vmin/vmax with log norm
    )
    
    # 4. Enforce the exact logarithmic scale profile and matching limits
    ax2.set_yscale('log', base=2)
    ax2.set_ylim(session_wavelet_freqs.min(), session_wavelet_freqs.max())
    
    ax2.set_xticks(tick_positions)
    ax2.set_xticklabels(tick_labels)
    for idx in range(1, len(labels)):
        ax2.axvline(idx * epoch_width, color="gray", linestyle="--", linewidth=0.8, alpha=0.5)
        
    ax2.set_title("Wavelet Scalograms by Time Block")
    ax2.set_xlabel("Time Block")
    
    # Update label text to match what you are passing ('Scale' vs 'Frequency')
    ax2.set_ylabel("Scale")
    # Adds subtle dashed horizontal gridlines aligned with the log2 scale ticks
    ax2.grid(True, axis='y', which='both', color='white', linestyle=':', linewidth=0.5, alpha=0.3)

    fig.colorbar(im, ax=ax2, label="Power", shrink=0.9)
    
    return fig

def _build_stats_table_page(
    session_wavelets: List[np.ndarray],
    session_wavelet_freqs: np.ndarray,
    epoch_time_ms: np.ndarray,
    labels: List[str],
    session_ver_peaks: Optional[List[dict]] = None,
    human_overrides: Optional[List[bool]] = None,
) -> plt.Figure:
    
    # 1. PRE-POPULATE ROWS FIRST (So we can calculate height correctly)
    col_labels = [
        "Block", "Label", "VER?", "Reason",
        "Peak-1 Latency (ms)", "Peak-1 Amp",
        "Peak-2 Latency (ms)", "Peak-2 Amp",
        "Peak-3 Latency (ms)", "Peak-3 Amp",
        "Peak Scale", "Peak Latency (ms)", "Peak Power",
    ]
    rows = []
    for idx, wavelet in enumerate(session_wavelets):
        peak_idx = np.unravel_index(np.argmax(wavelet), wavelet.shape)
        peak_scale = float(session_wavelet_freqs[peak_idx[0]])
        peak_latency_ms = float(epoch_time_ms[peak_idx[1]])
        peak_power = float(wavelet[peak_idx])

        ver_peaks = session_ver_peaks[idx] if session_ver_peaks and idx < len(session_ver_peaks) else None
        
        # Helper to format peak data
        def _fmt_peak(peaks, key):
            if peaks is None: return "—", "—", 0.0
            p = peaks.get(key, {})
            if p.get('found'):
                snr = p.get("snr", float("nan"))
                amp = f"{p['amplitude']:.4f}"
                return f"{p['latency_ms']:.0f}", amp, (0.0 if math.isnan(snr) else float(snr))
            return "—", "—", 0.0

        p1_lat, p1_amp, _ = _fmt_peak(ver_peaks, 'Peak-1')
        p2_lat, p2_amp, _ = _fmt_peak(ver_peaks, 'Peak-2')
        p3_lat, p3_amp, _ = _fmt_peak(ver_peaks, 'Peak-3')
        
        ver_label, reason = "—", "No Peaks Found"
        if ver_peaks is not None:
            p1_d, p2_d, p3_d = ver_peaks.get('Peak-1',{}), ver_peaks.get('Peak-2',{}), ver_peaks.get('Peak-3',{})
            p1_l = float(p1_d['latency_ms']) if p1_d.get('found') else None
            p2_l = float(p2_d['latency_ms']) if p2_d.get('found') else None
            p3_l = float(p3_d['latency_ms']) if p3_d.get('found') else None
            p2_snr_val = float(p2_d['snr']) if p2_d.get('found') and p2_d.get('snr') is not None else 0.0
            
            
            # 1. Computer makes its initial guess
            #is_ver, failure_details = evaluate_ver_peak(peak_scale, peak_power, p1_l, p2_l, p3_l)
            is_ver, failure_details = evaluate_ver_peak(peak_scale, peak_power, p1_l, p2_l, p3_l, p2_snr_val)
            
            
            # --- 2. NEW OVERRIDE LOGIC ---
            if human_overrides is not None and idx < len(human_overrides):
                # Replace the computer's guess with the human's truth
                is_ver = human_overrides[idx]
                reason = "Human Validated" if is_ver else "Human Rejected"
            else:
                # If no overrides (first pass), use the computer's logic
                reason = "Passed" if is_ver else "Failed:\n" + "\n".join([n for n, p in failure_details.items() if not p])
            # -----------------------------
            
            # 3. Finalize the label based on whoever made the final decision
            ver_label = "Yes" if is_ver else "No"

        seconds = int((idx + 1) * (EPOCH_CONFIG["flashes_per_session"] / 2.0))
        rows.append([str(idx + 1), labels[idx] if idx < len(labels) else f"{seconds} s", ver_label, reason,
                     p1_lat, p1_amp, p2_lat, p2_amp, p3_lat, p3_amp, f"{peak_scale:.1f}", f"{peak_latency_ms:.0f}", f"{peak_power:.3e}"])
    # 2. DYNAMIC FIGURE SETUP
    fig_height = max(5, 1.5 + (0.5 * len(rows)))
    fig, ax = plt.subplots(figsize=(16, fig_height), facecolor="white")
    ax.axis("off")
    ax.set_title("VER Analysis — Peak Statistics", fontsize=14, fontweight="bold", y=1.0)
    
    # 3. TABLE SETUP
    custom_widths = [0.04, 0.07, 0.04, 0.10, 0.09, 0.07, 0.09, 0.07, 0.09, 0.07, 0.06, 0.09, 0.07]
    table = ax.table(cellText=rows, colLabels=col_labels, loc="center", cellLoc="center", colWidths=custom_widths)
    
    table.auto_set_font_size(False)
    table.set_fontsize(8) # Size 8 ensures 13 columns fit across an 18-inch page
    table.scale(1, 3.5)   # Height scaling only

    # 4. COLORING
    for (row_idx, col_idx), cell in table.get_celld().items():
        cell.set_edgecolor("lightgray")
        if row_idx == 0:
            cell.set_facecolor("#4472C4")
            cell.set_text_props(color="white", fontweight="bold")
        elif row_idx % 2 == 0:
            cell.set_facecolor("#E9EFF7")
    
    plt.tight_layout()
    return fig
