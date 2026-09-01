"""Main window and workflow orchestration for the ECG Analysis application.

NOTE (transition): This module was copied from the VER-analyses codebase.
Class names, internal variable names, and some UI labels still carry the
``VER`` prefix.  They are intentional placeholders until the corresponding
analysis modules (ver_scope, ver_peaks, ver_classifier) are replaced with
ECG-specific implementations.  See TRANSITION.md for the full roadmap.

Application startup (``main()``) has been moved to ``ecg_main.py``, which
is the canonical ECG launcher.  The ``main()`` function in this module is
a backward-compatibility shim that delegates to ``ecg_main.main()``.
"""

from __future__ import annotations

import logging
import shutil
import sys
import time
import csv
import serial
import serial.tools.list_ports
from pathlib import Path

import numpy as np
import pyqtgraph as pg

from PyQt6.QtCore import QObject, QThread, Qt, pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSlider,
    QTextEdit,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

# --- ECG-path modules ---
from ecg_loader import ECGFileLoader
from ecg_pipeline import (
    ECGRollingProcessor,
    ECGOfflineProcessor,
    ECG_FILTER_MODES,
    ECG_FILTER_DEFAULT,
    ECG_FILTER_BUTTERWORTH,
    ECG_FILTER_ZEROPHASE_IIR,
    ECG_FILTER_IIR_NOTCH,
    ECG_DETECTOR_METHODS,
    ECG_DETECTOR_DEFAULT,
)
from ecg_config import ECG_PROCESSING_CONFIG
from ecg_extended_report import save_neurokit2_report_set, sanitize_output_stem

# --- Generic infrastructure (keep for ECG) ---
from src.ecg_analyses.ver.ver_acquisition import FileAcquisitionSimulator, SerialAcquisitionSource
from src.ecg_analyses.ver.ver_config import ACQ_CONFIG, EPOCH_CONFIG, FILTER_CONFIG, SERIAL_CONFIG
from src.ecg_analyses.ver.ver_display import VERDisplayWidget, _FocusableViewBox
from ver_filter import BandpassFilter
from ver_wavelet import compute_wavelet_scalogram
from ver_ml_logger import launch_ml_logger
from ver_settings import SettingsManager
from ver_analysis_flow import (
    BACK_TO_ANALYSIS,
    CANCEL_ANALYSIS,
    PROCEED_TO_VALIDATION,
    normalize_analysis_complete_action,
    should_proceed_to_human_validation,
    status_message_for_analysis_complete_action,
)

# --- Inherited VER analysis engine (transitional) ---
# These imports represent the inherited VER-specific analysis boundary.
# To replace with ECG modules, update ver_analysis_engine.py and ecg_scope.py;
# no other changes to this file are needed for those replacements.
# See docs/ecg-transition-priorities.md for the full replacement sequence.
from ver_analysis_engine import (       # REPLACEMENT BOUNDARY — see ver_analysis_engine.py
    detect_ver_peaks,
    save_ecg_report,                    # ECG-named boundary (wraps inherited ver_report)
    refresh_classifier_cfg as _refresh_analysis_engine_cfg,
)
from ecg_scope import ECGScopeProcessor  # REPLACEMENT BOUNDARY (transitional placeholder)

log = logging.getLogger(__name__)
frozen_debug_log = logging.getLogger("ver.frozen_debug")
ARTIFACT_THRESHOLD_MIN_UV = 0.0001
_PRE_REPORT_BEAT_BEFORE_S = 0.25
_PRE_REPORT_BEAT_AFTER_S = 0.45
_MIN_SAMPLES_FOR_PRE_REPORT = 50
_FILTER_MODES_WITH_LOW_HIGH = {
    ECG_FILTER_BUTTERWORTH,
    ECG_FILTER_ZEROPHASE_IIR,
    ECG_FILTER_IIR_NOTCH,
}
# NOTE: PEAK_DETECTION_MODE_OPTIONS (VER-specific classifier peak mode labels)
# removed along with ClassifierSettingsTab in the ECG cleanup PR.

# Pre-report dialog panel titles — shown when layout is normal vs. focused.
_PRE_TITLE_ECG_NORMAL = (
    "Full ECG \u2014 raw + filtered + R-peaks \u00b7 double-click to enlarge"
)
_PRE_TITLE_HR_NORMAL = (
    "Heart Rate (full duration) \u00b7 double-click to enlarge"
)
_PRE_TITLE_BEATS_NORMAL = (
    "Individual beats + average beat \u00b7 double-click to enlarge"
)
_PRE_TITLE_ECG_FOCUSED = (
    "Full ECG \u2014 raw + filtered + R-peaks \u00b7 double-click to restore"
)
_PRE_TITLE_HR_FOCUSED = (
    "Heart Rate (full duration) \u00b7 double-click to restore"
)
_PRE_TITLE_BEATS_FOCUSED = (
    "Individual beats + average beat \u00b7 double-click to restore"
)
# Marker styling tuned for dark-theme visibility in the pre-report beats panel.
_BEAT_MARKER_SYMBOL_SIZE = 5
_BEAT_MARKER_ALPHA = 220
_BEAT_MARKER_OUTLINE_RGBA = (20, 20, 20, 220)


def _refresh_runtime_classifier_settings(classifier_cfg: dict | None) -> None:
    """Refresh the live classifier/peak config used by the next analysis run.

    When ``classifier_cfg`` is ``None``, an empty config is applied so downstream
    code falls back to its existing defaults.
    """

    cfg = classifier_cfg or {}
    # Delegate to the VER analysis engine adapter; swap for ECG equivalent when ready.
    _refresh_analysis_engine_cfg(cfg)


def _clamp_artifact_threshold(threshold_uv: float) -> float:
    """Clamp a candidate threshold to the minimum supported positive value."""

    return max(float(threshold_uv), ARTIFACT_THRESHOLD_MIN_UV)


def prompt_analysis_complete_action(parent) -> str:
    """Ask whether to proceed to validation or return to analysis."""

    dialog = QMessageBox(parent)
    dialog.setWindowTitle("Analysis Complete")
    dialog.setText("Reached the end of the analysis. What would you like to do next?")
    dialog.setInformativeText(
        "Back to Analysis keeps the current results so you can adjust filter or classifier "
        "settings and rerun the analysis."
    )
    proceed_button = dialog.addButton("Proceed to Manual Review", QMessageBox.ButtonRole.YesRole)
    back_button = dialog.addButton("Back to Analysis", QMessageBox.ButtonRole.NoRole)
    dialog.setDefaultButton(proceed_button)
    dialog.exec()

    clicked_button = dialog.clickedButton()
    button_actions = (
        (proceed_button, PROCEED_TO_VALIDATION),
        (back_button, BACK_TO_ANALYSIS),
    )
    for button, action in button_actions:
        if clicked_button == button:
            return action

    log.info("Analysis complete dialog closed without a recognized button selection; treating as back to analysis.")
    return BACK_TO_ANALYSIS
def auto_detect_file_format(filepath: str) -> str | None:
    """
    Reads the first data line of the file and determines the format.
    LabChart and USB serial typically has 2 columns, SD-card has 5 columns.
    """
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue  # Skip empty lines
                
                columns = line.split("\t")
                
                # Check if it looks like a data row rather than a text header
                try:
                    [float(col) for col in columns if col.strip()]
                except ValueError:
                    continue # Skip header rows
                
                # Make the decision based on column count
                if len(columns) == 2:
                    return "LabChart"
                elif len(columns) >= 5:
                    return "SD-card"
                
                return None # Unknown format
    except Exception as e:
        log.exception("Error reading file for auto-detection: %s", e)

    return None

# NOTE: DownsampleDialog (VER-specific LabChart downsampling tool) has been
# removed from the active ECG UI path.  The underlying ver_downsample module
# is retained as legacy code but is no longer accessible from the application
# menu.  See Task 4 in the cleanup PR for details.

class ExclusionTuningDialog(QDialog):
    """Pre-analysis dialog for visual artifact-threshold tuning via signal plot.

    Shows the whole-file downsampled filtered signal as the primary selection
    surface.  Two linked draggable horizontal lines (±T) let the user set the
    symmetric threshold directly on the signal trace — mirroring the current
    clinical workflow of visually inspecting the signal and deciding the cutoff.

    Slider/spinbox remain for fine-grained numeric control and are kept in sync
    with the draggable markers.  Live acceptance/rejection statistics update as
    the threshold changes.
    """

    _THRESHOLD_SCALE = 10000

    def __init__(self, suggestion, current_threshold_uv: float, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Exclusion Tuning")
        self.resize(860, 560)

        self.suggestion = suggestion
        raw_current_threshold_uv = float(current_threshold_uv)
        self.current_threshold_uv = _clamp_artifact_threshold(raw_current_threshold_uv)
        if self.current_threshold_uv != raw_current_threshold_uv:
            log.debug(
                "Clamped exclusion tuning threshold from %.6f to %.6f µV",
                raw_current_threshold_uv,
                self.current_threshold_uv,
            )
        peak_values = np.asarray(self.suggestion.peak_values_uv, dtype=float)
        peak_max = float(np.max(peak_values)) if peak_values.size else self.current_threshold_uv
        self.max_threshold_uv = max(
            ARTIFACT_THRESHOLD_MIN_UV * 2,
            peak_max * 1.1,
            float(self.suggestion.suggested_threshold_uv) * 1.2,
            self.current_threshold_uv * 1.2,
        )

        layout = QVBoxLayout(self)
        metric_label = QLabel(
            "Filtered signal preview — drag the ±T lines vertically to set the exclusion threshold."
        )
        metric_label.setWordWrap(True)
        layout.addWidget(metric_label)

        self.signal_plot = pg.PlotWidget()
        self.signal_plot.setBackground("k")
        self.signal_plot.showGrid(x=True, y=True, alpha=0.2)
        self.signal_plot.setLabel("bottom", "Time", "s")
        self.signal_plot.setLabel("left", "Amplitude", "µV")
        layout.addWidget(self.signal_plot, stretch=1)
        self._populate_signal_plot(peak_values)

        controls_layout = QHBoxLayout()
        controls_layout.addWidget(QLabel("Threshold (±µV):"))

        self.threshold_slider = QSlider(Qt.Orientation.Horizontal)
        self.threshold_slider.setRange(
            int(round(ARTIFACT_THRESHOLD_MIN_UV * self._THRESHOLD_SCALE)),
            max(
                int(round(ARTIFACT_THRESHOLD_MIN_UV * self._THRESHOLD_SCALE)),
                int(round(self.max_threshold_uv * self._THRESHOLD_SCALE)),
            ),
        )
        controls_layout.addWidget(self.threshold_slider, stretch=1)

        self.threshold_spin = QDoubleSpinBox()
        self.threshold_spin.setRange(ARTIFACT_THRESHOLD_MIN_UV, self.max_threshold_uv)
        self.threshold_spin.setDecimals(4)
        self.threshold_spin.setSingleStep(0.0005)
        controls_layout.addWidget(self.threshold_spin)
        layout.addLayout(controls_layout)

        self.value_label = QLabel()
        self.stats_label = QLabel()
        self.stats_label.setWordWrap(True)
        layout.addWidget(self.value_label)
        layout.addWidget(self.stats_label)

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Cancel
        )
        self.button_box.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

        self._syncing_threshold = False
        self.threshold_slider.valueChanged.connect(self._on_slider_changed)
        self.threshold_spin.valueChanged.connect(self._on_spin_changed)
        self._set_threshold(self.current_threshold_uv)

    def _populate_signal_plot(self, peak_values: np.ndarray) -> None:
        """Render the filtered signal trace and add threshold/reference markers."""

        filtered_signal = np.asarray(self.suggestion.filtered_signal_uv, dtype=float)
        sample_rate = float(self.suggestion.signal_sample_rate)

        if filtered_signal.size > 0 and sample_rate > 0:
            time_s = np.arange(filtered_signal.size, dtype=float) / sample_rate
            self.signal_plot.plot(
                time_s,
                filtered_signal,
                pen=pg.mkPen((0, 200, 120), width=1),
                autoDownsample=True,
                downsampleMethod="mean",
                clipToView=True,
            )
        else:
            # No signal data available — show a placeholder message.
            text = pg.TextItem(
                "No signal data available.\nRe-open the file to generate the preview.",
                color=(200, 200, 200),
                anchor=(0.5, 0.5),
            )
            self.signal_plot.addItem(text)
            text.setPos(0.5, 0.5)

        suggested = float(self.suggestion.suggested_threshold_uv)
        # Reference line: auto-suggested threshold (+)
        self.signal_plot.addItem(
            pg.InfiniteLine(
                pos=suggested,
                angle=0,
                pen=pg.mkPen((0, 170, 255), width=1, style=Qt.PenStyle.DashLine),
                label="Auto +T",
                labelOpts={"position": 0.02, "color": "#66ccff", "fill": (0, 0, 0, 160)},
            )
        )
        # Reference line: auto-suggested threshold (-)
        self.signal_plot.addItem(
            pg.InfiniteLine(
                pos=-suggested,
                angle=0,
                pen=pg.mkPen((0, 170, 255), width=1, style=Qt.PenStyle.DashLine),
                label="Auto −T",
                labelOpts={"position": 0.98, "color": "#66ccff", "fill": (0, 0, 0, 160)},
            )
        )
        # Reference line: current configured threshold (+)
        self.signal_plot.addItem(
            pg.InfiniteLine(
                pos=self.current_threshold_uv,
                angle=0,
                pen=pg.mkPen((180, 180, 180), width=1, style=Qt.PenStyle.DashLine),
                label="Current +T",
                labelOpts={"position": 0.10, "color": "#dddddd", "fill": (0, 0, 0, 160)},
            )
        )
        # Reference line: current configured threshold (-)
        self.signal_plot.addItem(
            pg.InfiniteLine(
                pos=-self.current_threshold_uv,
                angle=0,
                pen=pg.mkPen((180, 180, 180), width=1, style=Qt.PenStyle.DashLine),
                label="Current −T",
                labelOpts={"position": 0.90, "color": "#dddddd", "fill": (0, 0, 0, 160)},
            )
        )

        # Draggable selected-threshold lines.
        self.pos_threshold_line = pg.InfiniteLine(
            pos=self.current_threshold_uv,
            angle=0,
            pen=pg.mkPen((255, 190, 0), width=2),
            movable=True,
            label="Selected +T",
            labelOpts={"position": 0.05, "color": "#ffcc55", "fill": (0, 0, 0, 180)},
            bounds=[ARTIFACT_THRESHOLD_MIN_UV, self.max_threshold_uv],
        )
        self.neg_threshold_line = pg.InfiniteLine(
            pos=-self.current_threshold_uv,
            angle=0,
            pen=pg.mkPen((255, 190, 0), width=2),
            movable=True,
            label="Selected −T",
            labelOpts={"position": 0.95, "color": "#ffcc55", "fill": (0, 0, 0, 180)},
            bounds=[-self.max_threshold_uv, -ARTIFACT_THRESHOLD_MIN_UV],
        )
        self.signal_plot.addItem(self.pos_threshold_line)
        self.signal_plot.addItem(self.neg_threshold_line)

        self.pos_threshold_line.sigPositionChanged.connect(self._on_pos_line_dragged)
        self.neg_threshold_line.sigPositionChanged.connect(self._on_neg_line_dragged)

    def _on_pos_line_dragged(self) -> None:
        if self._syncing_threshold:
            return
        new_pos = float(self.pos_threshold_line.value())
        self._set_threshold(abs(new_pos))

    def _on_neg_line_dragged(self) -> None:
        if self._syncing_threshold:
            return
        new_pos = float(self.neg_threshold_line.value())
        self._set_threshold(abs(new_pos))

    def _threshold_from_slider(self, slider_value: int) -> float:
        """Convert the integer slider position to a threshold in microvolts."""

        return max(ARTIFACT_THRESHOLD_MIN_UV, slider_value / self._THRESHOLD_SCALE)

    def _slider_from_threshold(self, threshold_uv: float) -> int:
        """Convert a threshold in microvolts to the matching slider position."""

        return int(round(max(ARTIFACT_THRESHOLD_MIN_UV, threshold_uv) * self._THRESHOLD_SCALE))

    def _set_threshold(self, threshold_uv: float) -> None:
        """Synchronize the slider, spin box, draggable lines, and live stats."""

        threshold = min(_clamp_artifact_threshold(threshold_uv), self.max_threshold_uv)
        if self._syncing_threshold:
            return
        self._syncing_threshold = True
        try:
            self.threshold_spin.setValue(threshold)
            self.threshold_slider.setValue(self._slider_from_threshold(threshold))
            self.pos_threshold_line.setValue(threshold)
            self.neg_threshold_line.setValue(-threshold)
            self._update_stats(threshold)
        finally:
            self._syncing_threshold = False

    def _on_slider_changed(self, slider_value: int) -> None:
        if self._syncing_threshold:
            return
        self._set_threshold(self._threshold_from_slider(slider_value))

    def _on_spin_changed(self, threshold_uv: float) -> None:
        if self._syncing_threshold:
            return
        self._set_threshold(threshold_uv)

    def _update_stats(self, threshold_uv: float) -> None:
        """Refresh the threshold summary and whole-file accept/reject estimates."""

        stats = self.suggestion.stats_for_threshold(threshold_uv)
        self.value_label.setText(
            f"Selected threshold: <b>±{threshold_uv:.4f} µV</b> "
            f"(auto: ±{self.suggestion.suggested_threshold_uv:.4f} µV, "
            f"current: ±{self.current_threshold_uv:.4f} µV)"
        )
        self.stats_label.setText(
            f"Detected epochs: {stats.total_epochs}    "
            f"Accepted: {stats.accepted_epochs}    "
            f"Rejected: {stats.rejected_epochs} ({stats.rejected_percent:.1f}%)"
        )

    def selected_threshold_uv(self) -> float:
        """Return the threshold currently chosen by the user in the dialog."""

        return float(self.threshold_spin.value())


class ECGPreReportDialog(QDialog):
    """Dedicated pre-report review dialog for completed ECG analyses."""

    def __init__(self, report_data: dict, save_callback, parent=None):
        super().__init__(parent)
        self._report_data = report_data
        self._save_callback = save_callback
        self.setWindowTitle("ECG Pre-report Review")
        _screen = QApplication.primaryScreen()
        _avail = _screen.availableGeometry() if _screen else None
        _dlg_w = min(1200, int(_avail.width() * 0.90)) if _avail else 1200
        _dlg_h = min(900, int(_avail.height() * 0.90)) if _avail else 900
        self.resize(_dlg_w, _dlg_h)

        layout = QVBoxLayout(self)

        source_label = QLabel(report_data.get("source_label", "Completed analysis"))
        source_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(source_label)

        # Focus-state tracker: None = normal layout, 0/1/2 = panel index in focus.
        self._focused_panel: int | None = None

        # --- Full ECG panel (raw + filtered + optional R-peaks) ---
        _vb_ecg = _FocusableViewBox()
        _vb_ecg.sigDoubleClicked.connect(lambda: self._toggle_focus(0))
        self.plot_ecg = pg.PlotWidget(viewBox=_vb_ecg, title=_PRE_TITLE_ECG_NORMAL)
        self.plot_ecg.showGrid(x=True, y=True, alpha=0.3)
        self.plot_ecg.setLabel("bottom", "Time", "s")
        self.plot_ecg.setLabel("left", "Amplitude")
        _vb_ecg.setMouseEnabled(x=True, y=True)
        layout.addWidget(self.plot_ecg, stretch=2)

        # --- Heart-rate panel ---
        _vb_hr = _FocusableViewBox()
        _vb_hr.sigDoubleClicked.connect(lambda: self._toggle_focus(1))
        self.plot_hr = pg.PlotWidget(viewBox=_vb_hr, title=_PRE_TITLE_HR_NORMAL)
        self.plot_hr.showGrid(x=True, y=True, alpha=0.3)
        self.plot_hr.setLabel("bottom", "Time", "s")
        self.plot_hr.setLabel("left", "Heart Rate", "bpm")
        _vb_hr.setMouseEnabled(x=True, y=True)
        # Lock HR x-axis to the ECG plot so pan/zoom stays in sync
        self.plot_hr.setXLink(self.plot_ecg)
        layout.addWidget(self.plot_hr, stretch=1)

        # --- Individual beats panel ---
        _vb_beats = _FocusableViewBox()
        _vb_beats.sigDoubleClicked.connect(lambda: self._toggle_focus(2))
        self.plot_beats = pg.PlotWidget(viewBox=_vb_beats, title=_PRE_TITLE_BEATS_NORMAL)
        self.plot_beats.showGrid(x=True, y=True, alpha=0.3)
        self.plot_beats.setLabel("bottom", "Time around R-peak", "ms")
        self.plot_beats.setLabel("left", "Amplitude")
        _vb_beats.setMouseEnabled(x=True, y=True)
        layout.addWidget(self.plot_beats, stretch=1)

        self._beats_info_label = QLabel("")
        layout.addWidget(self._beats_info_label)

        button_row = QHBoxLayout()
        self.back_btn = QPushButton("Back to Analysis")
        self.save_btn = QPushButton("Save Reports")
        self.back_btn.clicked.connect(self.reject)
        self.save_btn.clicked.connect(self._save_reports)
        button_row.addWidget(self.back_btn)
        button_row.addWidget(self.save_btn)
        button_row.addStretch()
        layout.addLayout(button_row)

        self._populate_plots()

    def _populate_plots(self) -> None:
        frozen_debug_log.debug(
            "pre-report populate_plots start: frozen=%s report_keys=%s",
            getattr(sys, "frozen", False),
            sorted(self._report_data.keys()),
        )
        fs = float(self._report_data["sample_rate"])
        raw = np.asarray(self._report_data["raw_signal"], dtype=float)
        filt = np.asarray(self._report_data["filtered_signal"], dtype=float)
        if raw.size == 0:
            self._beats_info_label.setText("No signal data available.")
            return

        t = np.arange(raw.size, dtype=float) / fs
        self.plot_ecg.plot(t, raw, pen=pg.mkPen((150, 150, 150), width=1), name="Raw")
        self.plot_ecg.plot(t, filt, pen=pg.mkPen((0, 220, 120), width=1.5), name="Filtered")

        peak_idx = np.asarray(self._report_data["r_peak_indices"], dtype=int)
        if peak_idx.size:
            peak_idx = peak_idx[(peak_idx >= 0) & (peak_idx < filt.size)]
            if peak_idx.size:
                self.plot_ecg.plot(
                    t[peak_idx],
                    filt[peak_idx],
                    pen=None,
                    symbol="o",
                    symbolSize=6,
                    symbolBrush=pg.mkBrush(255, 80, 80, 200),
                )

        hr_t = np.asarray(self._report_data["hr_times_s"], dtype=float)
        hr_b = np.asarray(self._report_data["hr_bpm"], dtype=float)
        if hr_t.size and hr_b.size:
            self.plot_hr.plot(
                hr_t,
                hr_b,
                pen=pg.mkPen((255, 165, 0), width=2),
                symbol="o",
                symbolSize=5,
                symbolBrush=pg.mkBrush(255, 165, 0, 180),
                symbolPen=pg.mkPen(None),
            )

        # Beat overlays centered on R-peaks (practical first version).
        pre_n = int(round(_PRE_REPORT_BEAT_BEFORE_S * fs))
        post_n = int(round(_PRE_REPORT_BEAT_AFTER_S * fs))
        beat_segments = []
        for idx in peak_idx.tolist():
            left = idx - pre_n
            right = idx + post_n
            if left < 0 or right >= filt.size:
                continue
            beat_segments.append(filt[left:right])

        if beat_segments:
            beats = np.vstack(beat_segments)
            beat_t_ms = (np.arange(beats.shape[1], dtype=float) - pre_n) * (1000.0 / fs)
            first_beat_plot_item = None
            for i, beat in enumerate(beats):
                item = self.plot_beats.plot(
                    beat_t_ms,
                    beat,
                    pen=pg.mkPen((120, 120, 120, 80), width=1),
                    name=None,
                )
                if i == 0:
                    first_beat_plot_item = item
            mean_beat = np.mean(beats, axis=0)
            mean_item = self.plot_beats.plot(
                beat_t_ms,
                mean_beat,
                pen=pg.mkPen((255, 220, 0), width=3),
                name=None,
            )
            mean_item.setZValue(10)

            # Overlay P/Q/S/T landmark markers aligned to each beat window.
            # Each wave type: (report_data key, RGB colour tuple, legend label)
            wave_specs = [
                ("p_peak_indices", (100, 180, 255), "P"),
                ("q_peak_indices", (200,  80, 255), "Q"),
                ("s_peak_indices", (255, 180,  50), "S"),
                ("t_peak_indices", ( 60, 220, 160), "T"),
            ]
            t_min_ms, t_max_ms = beat_t_ms[0], beat_t_ms[-1]
            marker_items: list[tuple[pg.PlotDataItem, str]] = []
            for wave_key, color, wave_label in wave_specs:
                wave_idx = np.asarray(
                    self._report_data.get(wave_key, []), dtype=int
                )
                frozen_debug_log.debug(
                    "individual-beat markers source %s count=%d",
                    wave_key,
                    int(wave_idx.size),
                )
                if wave_idx.size == 0:
                    continue
                wave_idx = wave_idx[(wave_idx >= 0) & (wave_idx < filt.size)]
                w_t_ms: list[float] = []
                w_amp: list[float] = []
                for r_idx in peak_idx.tolist():
                    left = r_idx - pre_n
                    right = r_idx + post_n
                    if left < 0 or right >= filt.size:
                        continue
                    in_win = wave_idx[(wave_idx >= left) & (wave_idx < right)]
                    for w in in_win:
                        t_rel = (w - r_idx) * 1000.0 / fs
                        if t_min_ms <= t_rel <= t_max_ms:
                            w_t_ms.append(t_rel)
                            w_amp.append(float(filt[w]))
                if w_t_ms:
                    try:
                        marker_item = self.plot_beats.plot(
                            w_t_ms,
                            w_amp,
                            pen=None,
                            symbol="o",
                            symbolSize=_BEAT_MARKER_SYMBOL_SIZE,
                            symbolBrush=pg.mkBrush(*color, _BEAT_MARKER_ALPHA),
                            symbolPen=pg.mkPen(*_BEAT_MARKER_OUTLINE_RGBA),
                            name=None,
                        )
                        marker_item.setZValue(20)
                        marker_items.append((marker_item, wave_label))
                        frozen_debug_log.debug(
                            "marker item created: label=%s plotted_points=%d",
                            wave_label,
                            len(w_t_ms),
                        )
                    except (TypeError, ValueError) as exc:
                        frozen_debug_log.exception(
                            "marker creation failed for %s with %d points: %s",
                            wave_label,
                            len(w_t_ms),
                            exc,
                        )
                else:
                    frozen_debug_log.debug("marker item skipped: label=%s no in-window points", wave_label)

            legend = self.plot_beats.plotItem.legend
            if legend is not None:
                try:
                    # Remove stale legend instance before deterministic rebuild.
                    # Recreating the legend avoids stale entries across redraws.
                    legend.scene().removeItem(legend)
                    self.plot_beats.plotItem.legend = None
                except RuntimeError as exc:
                    frozen_debug_log.exception("legend removal failed before rebuild: %s", exc)
            try:
                legend = self.plot_beats.addLegend(offset=(10, 10))
                if first_beat_plot_item is not None:
                    legend.addItem(first_beat_plot_item, "Individual beats")
                legend.addItem(mean_item, "Average beat")
                for marker_item, wave_label in marker_items:
                    legend.addItem(marker_item, wave_label)
                frozen_debug_log.debug(
                    "legend built: has_individual=%s marker_labels=%s",
                    first_beat_plot_item is not None,
                    [label for _, label in marker_items],
                )
            except RuntimeError as exc:
                frozen_debug_log.exception("legend creation failed: %s", exc)

            self._beats_info_label.setText(
                f"Individual beats shown: {beats.shape[0]}  |  Mean beat overlay in gold."
            )
            frozen_debug_log.debug(
                "pre-report populate_plots complete: beats=%d markers=%d",
                beats.shape[0],
                len(marker_items),
            )
        else:
            self._beats_info_label.setText(
                "Individual beats panel unavailable for this run (not enough complete R-peak windows)."
            )
            frozen_debug_log.warning(
                "individual-beat plot skipped: no complete windows (peaks=%d pre_n=%d post_n=%d)",
                len(peak_idx),
                pre_n,
                post_n,
            )

    def _toggle_focus(self, panel_idx: int) -> None:
        """Toggle between normal three-panel layout and single-panel focused view.

        Double-click any graph panel to expand it to fill the graph area and
        hide the other two panels.  Double-click the same panel again to restore
        the normal three-panel layout.

        Args:
            panel_idx: Zero-based index of the panel being toggled.
                0 = Full ECG panel, 1 = Heart Rate panel, 2 = Individual beats panel.
        """
        panels = [self.plot_ecg, self.plot_hr, self.plot_beats]
        normal_titles = [_PRE_TITLE_ECG_NORMAL, _PRE_TITLE_HR_NORMAL, _PRE_TITLE_BEATS_NORMAL]
        focused_titles = [_PRE_TITLE_ECG_FOCUSED, _PRE_TITLE_HR_FOCUSED, _PRE_TITLE_BEATS_FOCUSED]

        if self._focused_panel == panel_idx:
            # Currently focused on this panel — restore normal layout.
            self._focused_panel = None
            for i, p in enumerate(panels):
                p.show()
                p.setTitle(normal_titles[i])
        else:
            # Focus the selected panel, hide the other two.
            self._focused_panel = panel_idx
            for i, p in enumerate(panels):
                if i == panel_idx:
                    p.show()
                    p.setTitle(focused_titles[i])
                else:
                    p.hide()

    def _save_reports(self) -> None:
        self._save_callback(self._report_data)


class AcquisitionWorker(QObject):
    sample_ready = pyqtSignal(object)
    eof_reached = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, source):
        super().__init__()
        self.source = source
        self._running = False
        self._paused = True
        self._batch_size = 8
        self._batch_max_latency_s = 0.03

    def run(self):
        try:
            self._running = True
            batch = []
            last_emit = time.perf_counter()
            for row in self.source.stream_samples():
                if not self._running:
                    break
                while self._paused and self._running:
                    if batch:
                        self.sample_ready.emit(np.vstack(batch))
                        batch = []
                    time.sleep(0.02)
                if not self._running:
                    break
                batch.append(np.asarray(row, dtype=float))
                now = time.perf_counter()
                if len(batch) >= self._batch_size or (now - last_emit) >= self._batch_max_latency_s:
                    self.sample_ready.emit(np.vstack(batch))
                    batch = []
                    last_emit = now
            if batch:
                self.sample_ready.emit(np.vstack(batch))
            self.eof_reached.emit()
        except Exception as exc:  # pragma: no cover
            log.exception("AcquisitionWorker unexpected error")
            self.error.emit(str(exc))
        finally:
            close_fn = getattr(self.source, "close", None)
            if callable(close_fn):
                close_fn()

    def start_stream(self):
        self._paused = False

    def pause_stream(self):
        self._paused = True

    def stop(self):
        self._running = False
        self._paused = False

# NOTE: ClassifierSettingsTab (VER-specific signal classifier UI) has been
# removed from the active ECG GUI path.  The underlying CLASSIFIER_CONFIG
# settings are still loaded and applied at analysis start via
# _refresh_runtime_classifier_settings, but can no longer be edited from the
# UI in this cleanup release.  The tab slot is now held by the ECG Processing
# Settings placeholder tab.

class VERMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings_manager = SettingsManager()
        self.setWindowTitle("ECG Analysis")
        _screen = QApplication.primaryScreen()
        _avail = _screen.availableGeometry() if _screen else None
        _win_w = min(1280, int(_avail.width() * 0.90)) if _avail else 1280
        _win_h = min(920, int(_avail.height() * 0.90)) if _avail else 920
        self.resize(_win_w, _win_h)

        self.data_file = None
        self.worker = None
        self.worker_thread = None
        self.acquisition_source_mode = ACQ_CONFIG.get("source_mode", "File")
        self.session_wavelets = []
        self.session_wavelet_freqs = None
        self.session_labels = []
        self.session_ver_peaks = []
        self.session_flash_counts = []
        self.session_flash_counts_accepted = []
        self.session_artifact_rejection_enabled = []
        self.session_artifact_exclusion_thresholds = []
        self._scope_panel_session = None

        # --- ECG processing config (loaded from JSON, updated by settings tab) ---
        self._ecg_proc_cfg = dict(ECG_PROCESSING_CONFIG)

        self.bandpass = BandpassFilter()
        self.scope = ECGScopeProcessor(self.bandpass)

        # ECG rolling processor for live USB serial processing
        self._ecg_rolling = self._build_ecg_rolling_processor()

        # Offline batch processor (whole-file / pre-report processing)
        self._ecg_offline = self._build_ecg_offline_processor()

        # TODO(ecg-transition): remove once inherited maximum-speed EOF branch in
        # _handle_eof is retired from the codebase.
        self._max_speed_raw_buffer: list[float] = []
        # Full raw USB session capture used to generate post-stop pre-report review.
        self._captured_serial_raw: list[float] = []
        # Cached most-recent pre-report payload for reopening without recomputation.
        self._latest_pre_report_data: dict | None = None

        self._build_ui()
        self._sync_artifact_settings_from_ui()
        self._build_menu()

    def _build_ecg_rolling_processor(self) -> ECGRollingProcessor:
        """Construct a fresh ECGRollingProcessor from the current processing config."""
        cfg = self._ecg_proc_cfg
        return ECGRollingProcessor(
            sample_rate=float(ACQ_CONFIG.get("sample_rate", 250)),
            window_s=float(cfg.get("rolling_window_s", 5.0)),
            detection_interval_s=float(cfg.get("detection_interval_s", 0.2)),
            boundary_guard_s=float(cfg.get("boundary_guard_s", 0.5)),
            filter_mode=cfg.get("filter_mode", ECG_FILTER_DEFAULT),
            lowcut_hz=float(cfg.get("lowcut_hz", 0.5)),
            highcut_hz=float(cfg.get("highcut_hz", 40.0)),
            filter_order=int(cfg.get("filter_order", 4)),
            notch_hz=float(cfg.get("notch_hz", 50.0)),
            detector_method=cfg.get("detector_method", ECG_DETECTOR_DEFAULT),
        )

    def _build_ecg_offline_processor(self) -> ECGOfflineProcessor:
        """Construct a fresh ECGOfflineProcessor from the current processing config."""
        cfg = self._ecg_proc_cfg
        return ECGOfflineProcessor(
            sample_rate=float(ACQ_CONFIG.get("sample_rate", 250)),
            filter_mode=cfg.get("filter_mode", ECG_FILTER_DEFAULT),
            lowcut_hz=float(cfg.get("lowcut_hz", 0.5)),
            highcut_hz=float(cfg.get("highcut_hz", 40.0)),
            filter_order=int(cfg.get("filter_order", 4)),
            notch_hz=float(cfg.get("notch_hz", 50.0)),
            detector_method=cfg.get("detector_method", ECG_DETECTOR_DEFAULT),
        )

    def _is_max_speed(self) -> bool:
        """Return True only for file mode when speed combo is set to maximum."""
        return self.acquisition_source_mode == "File" and "Maximum" in self.speed_combo.currentText()

    def _selected_species_value(self) -> str:
        """Legacy stub — species combo removed from ECG path; returns empty string."""
        return ""

    def _launch_usb_test(self):
        """Launches the dedicated USB test program directly within the application."""
        # Import the GUI class from your USB test file
        from ver_USB_test import WaveletAnalyzerGUI

        # We attach the window to 'self' so Python doesn't instantly close it
        if not hasattr(self, 'usb_test_window') or self.usb_test_window is None:
            self.usb_test_window = WaveletAnalyzerGUI()

        # Pop the window open and bring it to the front of the screen
        self.usb_test_window.show()
        self.usb_test_window.raise_()
        self.usb_test_window.activateWindow()

        self.display.set_status("Launched USB Test tool.")
        
    def _update_warning_visibility(self):
        """Centralized logic to show/hide the warning."""
        current_speed_text = self.speed_combo.currentText()
        is_running = self.worker is not None
        
        if is_running and self._is_max_speed():
            # Set a fixed size for the warning box
            self.max_speed_warning.resize(400, 100)
            # Center it relative to the current window size
            self.max_speed_warning.move(int((self.width() - 400) / 2), 150)
            self.max_speed_warning.show()
            self.max_speed_warning.raise_()
        else:
            self.max_speed_warning.hide()

    def resizeEvent(self, event):
        # Only update the position if the warning is actually visible
        if self.max_speed_warning.isVisible():
            self.max_speed_warning.move(int((self.width() - 400) / 2), 150)
        super().resizeEvent(event)

    def _build_ui(self):
        central = QWidget(self)
        root = QVBoxLayout(central)

        # Create a horizontal layout for our Top Bar of controls
        top_bar = QHBoxLayout()

        # ==========================================
        # INITIALIZE ALL WIDGETS & CONNECTIONS FIRST
        # ==========================================
        # --- Data File Widgets ---
        self.file_label = QLabel("No file selected")
        open_btn = QPushButton("Open ECG File (plain text)")
        open_btn.clicked.connect(lambda: self._select_data_file(initial=False))

        # --- Filter Widgets (ECG bandpass only) ---
        self.low_spin = QDoubleSpinBox()
        self.low_spin.setRange(0.1, 120.0)
        self.low_spin.setSingleStep(0.1)
        self.low_spin.setDecimals(1)
        # _ecg_proc_cfg is pre-populated with defaults from ECG_PROCESSING_CONFIG
        self.low_spin.setValue(float(self._ecg_proc_cfg["lowcut_hz"]))
        self.high_spin = QDoubleSpinBox()
        self.high_spin.setRange(0.2, 124.0)
        self.high_spin.setSingleStep(1.0)
        self.high_spin.setDecimals(1)
        self.high_spin.setValue(float(self._ecg_proc_cfg["highcut_hz"]))
        # Ensure high-cut minimum tracks low-cut so the pair always stays valid
        self.low_spin.valueChanged.connect(
            lambda v: self.high_spin.setMinimum(round(v + 0.1, 1))
        )

        # Filter mode dropdown — selects the cleaning strategy for peak detection
        self.filter_mode_combo = QComboBox()
        self.filter_mode_combo.addItems(ECG_FILTER_MODES)
        saved_mode = self._ecg_proc_cfg.get("filter_mode", ECG_FILTER_DEFAULT)
        if saved_mode in ECG_FILTER_MODES:
            self.filter_mode_combo.setCurrentText(saved_mode)
        else:
            # Saved value unrecognised; fall back to the built-in default explicitly
            self.filter_mode_combo.setCurrentText(ECG_FILTER_DEFAULT)
        self.filter_mode_combo.setToolTip(
            "Filter strategy used for ECG cleaning and R-peak detection.\n"
            "The display trace always uses the Butterworth causal filter for\n"
            "low-latency scrolling; the selected mode applies to peak detection."
        )
        self.filter_mode_combo.currentTextChanged.connect(self._on_filter_mode_changed)
        self.filter_mode_info_label = QLabel("")
        self.filter_mode_info_label.setWordWrap(True)
        self.filter_mode_info_label.setStyleSheet("color: #d0d0d0; font-size: 11px;")

        apply_filter_btn = QPushButton("Apply Filter")
        apply_filter_btn.clicked.connect(self._apply_filter_settings)

        # --- Control Widgets ---
        self.start_btn = QPushButton("Start")
        self.stop_btn = QPushButton("Stop")
        self.reset_btn = QPushButton("Reset")
        self.save_btn = QPushButton("Open Pre-report")
        self.start_btn.clicked.connect(self.start_acquisition)
        self.stop_btn.clicked.connect(self.stop_acquisition)
        self.reset_btn.clicked.connect(self.reset_all)
        self.save_btn.clicked.connect(self.open_pre_report)

        # --- Box 4 R-peak Detection Combo (mirrors ECG Processing Settings detector) ---
        self.box4_detector_combo = QComboBox()
        self.box4_detector_combo.addItems(ECG_DETECTOR_METHODS)
        _saved_detector = self._ecg_proc_cfg.get("detector_method", ECG_DETECTOR_DEFAULT)
        if _saved_detector in ECG_DETECTOR_METHODS:
            self.box4_detector_combo.setCurrentText(_saved_detector)
        else:
            self.box4_detector_combo.setCurrentText(ECG_DETECTOR_DEFAULT)
        self.box4_detector_combo.setToolTip(
            "NeuroKit2 R-peak detection method.  Changes here are\n"
            "automatically reflected in ECG Processing Settings."
        )

        # --- Speed Widget ---
        self.speed_combo = QComboBox()
        self.speed_combo.addItems(["Real-time (1×)", "Fast (10×)", "Maximum speed"])
        self.speed_combo.setToolTip(
            "File mode keeps these options for compatibility; analysis is run as "
            "full offline compute before pre-report."
        )
        self.speed_combo.currentTextChanged.connect(self._on_speed_changed)

        # --- Input Source Widgets ---
        self.source_combo = QComboBox()
        self.source_combo.addItems(["File Replay", "USB Serial (microcontroller)"])
        self.source_combo.currentTextChanged.connect(self._on_source_mode_changed)
        
        self.serial_port_combo = QComboBox()
        self.serial_port_combo.setMinimumWidth(130)
        self.serial_port_combo.setToolTip("USB serial port (e.g. COM3 or /dev/ttyUSB0)")
        self.serial_port_combo.setEditable(True)
        self.serial_port_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.serial_port_combo.setPlaceholderText("Select or type port")
        self.serial_port_combo.setEnabled(False)
        
        self.serial_refresh_btn = QPushButton("⟳")
        self.serial_refresh_btn.setFixedWidth(28)
        self.serial_refresh_btn.setToolTip("Refresh serial port list")
        self.serial_refresh_btn.setEnabled(False)
        self.serial_refresh_btn.clicked.connect(self._refresh_serial_ports)

        # ==========================================
        # ASSEMBLE THE 5 LOGICAL GROUPS
        # ==========================================
        
        # 1. FILE OR USB INPUT GROUP
        group1 = QGroupBox("1. File or USB Input")
        layout1 = QVBoxLayout() # Vertical stacking
        layout1.addWidget(self.source_combo)
        usb_layout = QHBoxLayout()
        usb_layout.addWidget(self.serial_port_combo)
        usb_layout.addWidget(self.serial_refresh_btn)
        layout1.addLayout(usb_layout)
        group1.setLayout(layout1)
        top_bar.addWidget(group1)

        # 2. DATA FILE GROUP — ECG plain text (.txt), one column of raw values
        group2 = QGroupBox("2. ECG Data File")
        layout2 = QVBoxLayout()
        layout2.addWidget(self.file_label)
        layout2.addWidget(open_btn)
        group2.setLayout(layout2)
        top_bar.addWidget(group2)

        # 3. FILTER SETTINGS GROUP — ECG bandpass + selectable filter mode
        group3 = QGroupBox("3. ECG Filter Settings")
        layout3 = QFormLayout()
        layout3.addRow("Filter mode:", self.filter_mode_combo)
        layout3.addRow("Low cut (Hz):", self.low_spin)
        layout3.addRow("High cut (Hz):", self.high_spin)
        layout3.addRow(apply_filter_btn)
        group3.setLayout(layout3)
        top_bar.addWidget(group3)
        
        # 4. R-PEAK DETECTION GROUP (replaces the legacy Display Speed group)
        group4 = QGroupBox("4. R-peak Detection")
        layout4 = QFormLayout()
        layout4.addRow("Method:", self.box4_detector_combo)
        group4.setLayout(layout4)
        top_bar.addWidget(group4)

        # 5. CONTROLS GROUP (Moved from 4 to 5)
        group5 = QGroupBox("5. Controls")
        layout5 = QVBoxLayout()
        btn_row1 = QHBoxLayout()
        btn_row1.addWidget(self.start_btn)
        btn_row1.addWidget(self.stop_btn)
        btn_row2 = QHBoxLayout()
        btn_row2.addWidget(self.reset_btn)
        btn_row2.addWidget(self.save_btn)
        layout5.addLayout(btn_row1)
        layout5.addLayout(btn_row2)
        group5.setLayout(layout5)
        top_bar.addWidget(group5)

        # Add a stretch so it doesn't expand crazily on wide monitors
        top_bar.addStretch()

        # Add top bar to root layout
        root.addLayout(top_bar)

        # --- PROGRESS LABEL ---
        seconds = int(EPOCH_CONFIG['flashes_per_session'] / 2.0)
        self.progress_label = QLabel(
            f"Block 1/{EPOCH_CONFIG['num_sessions']} ({seconds}s) | Trigger 0/{EPOCH_CONFIG['flashes_per_session']}"
        )
        self.progress_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress_label.setStyleSheet("font-weight: bold; margin-top: 5px; margin-bottom: 5px;")
        root.addWidget(self.progress_label)
        self.progress_label.hide() #Hides the information and thereby saves space

        # --- THE MAIN DISPLAY GRAPHS ---
        self.display = VERDisplayWidget(self)
        
        # 1. Create the Tab Manager
        self.tabs = QTabWidget()
        root.addWidget(self.tabs)
        
        # 2. Add the Main Display as Tab 1
        self.main_tab = QWidget()
        main_layout = QVBoxLayout(self.main_tab)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(self.display)
        self.tabs.addTab(self.main_tab, "Analysis View")

        # 3. ECG Processing Settings tab — populated with actual ECG processing options.
        # Settings are persisted to JSON via SettingsManager (key: ECG_PROCESSING_CONFIG).
        self.ecg_settings_tab = QWidget()
        ecg_settings_layout = QVBoxLayout(self.ecg_settings_tab)

        # --- Header ---
        header_label = QLabel("<b>ECG Processing Settings</b>")
        header_label.setStyleSheet("font-size: 13px; margin-bottom: 4px;")
        ecg_settings_layout.addWidget(header_label)

        # --- Detector group ---
        det_group = QGroupBox("R-peak Detector")
        det_form = QFormLayout(det_group)
        self.detector_combo = QComboBox()
        self.detector_combo.addItems(ECG_DETECTOR_METHODS)
        saved_det = self._ecg_proc_cfg.get("detector_method", ECG_DETECTOR_DEFAULT)
        if saved_det in ECG_DETECTOR_METHODS:
            self.detector_combo.setCurrentText(saved_det)
        else:
            # Saved value unrecognised; fall back to the built-in default explicitly
            self.detector_combo.setCurrentText(ECG_DETECTOR_DEFAULT)
        self.detector_combo.setToolTip(
            "NeuroKit2 peak-detection method.  'neurokit' (default) is the best\n"
            "general-purpose choice.  Other methods may suit noisier signals."
        )
        det_form.addRow("Method:", self.detector_combo)
        ecg_settings_layout.addWidget(det_group)

        # Bidirectional sync: Box 4 combo ↔ Settings tab combo
        self.box4_detector_combo.currentTextChanged.connect(self._sync_detector_from_box4)
        self.detector_combo.currentTextChanged.connect(self._sync_detector_from_settings)

        # --- Rolling window group ---
        win_group = QGroupBox("Rolling Window (USB streaming only — not used for offline file analysis)")
        win_form = QFormLayout(win_group)

        self.rolling_window_spin = QDoubleSpinBox()
        self.rolling_window_spin.setRange(2.0, 30.0)
        self.rolling_window_spin.setSingleStep(0.5)
        self.rolling_window_spin.setDecimals(1)
        self.rolling_window_spin.setSuffix(" s")
        self.rolling_window_spin.setValue(float(self._ecg_proc_cfg.get("rolling_window_s", 5.0)))
        self.rolling_window_spin.setToolTip("Length of the rolling buffer used for peak detection.")
        win_form.addRow("Window length:", self.rolling_window_spin)

        self.det_interval_spin = QDoubleSpinBox()
        self.det_interval_spin.setRange(0.05, 2.0)
        self.det_interval_spin.setSingleStep(0.05)
        self.det_interval_spin.setDecimals(2)
        self.det_interval_spin.setSuffix(" s")
        self.det_interval_spin.setValue(float(self._ecg_proc_cfg.get("detection_interval_s", 0.2)))
        self.det_interval_spin.setToolTip("How often peak detection is run on the rolling buffer.")
        win_form.addRow("Detection interval:", self.det_interval_spin)

        self.boundary_guard_spin = QDoubleSpinBox()
        self.boundary_guard_spin.setRange(0.1, 2.0)
        self.boundary_guard_spin.setSingleStep(0.1)
        self.boundary_guard_spin.setDecimals(1)
        self.boundary_guard_spin.setSuffix(" s")
        self.boundary_guard_spin.setValue(float(self._ecg_proc_cfg.get("boundary_guard_s", 0.5)))
        self.boundary_guard_spin.setToolTip(
            "Peaks within this distance of the right edge of the buffer are\n"
            "held back to avoid reporting incomplete QRS complexes."
        )
        win_form.addRow("Boundary guard:", self.boundary_guard_spin)
        ecg_settings_layout.addWidget(win_group)

        # --- Notch filter group ---
        notch_group = QGroupBox("Power-line Notch (Zero-phase IIR + Notch mode)")
        notch_form = QFormLayout(notch_group)
        self.notch_spin = QDoubleSpinBox()
        self.notch_spin.setRange(45.0, 65.0)
        self.notch_spin.setSingleStep(10.0)
        self.notch_spin.setDecimals(0)
        self.notch_spin.setSuffix(" Hz")
        self.notch_spin.setValue(float(self._ecg_proc_cfg.get("notch_hz", 50.0)))
        self.notch_spin.setToolTip("50 Hz (Europe) or 60 Hz (North America).")
        notch_form.addRow("Notch frequency:", self.notch_spin)
        ecg_settings_layout.addWidget(notch_group)

        # --- Extension points note ---
        note_label = QLabel(
            "<small><i>Deferred features (future PRs):<br>"
            "• ECG delineation (P/Q/S/T waves) via nk.ecg_delineate<br>"
            "• Signal quality index via nk.ecg_quality<br>"
            "• HRV metrics (RMSSD, SDNN)<br>"
            "• Arrhythmia classification</i></small>"
        )
        note_label.setWordWrap(True)
        note_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        ecg_settings_layout.addWidget(note_label)

        # --- Save / Apply button ---
        save_settings_btn = QPushButton("Save ECG Processing Settings")
        save_settings_btn.clicked.connect(self._save_ecg_processing_settings)
        ecg_settings_layout.addWidget(save_settings_btn)
        ecg_settings_layout.addStretch()

        self.tabs.addTab(self.ecg_settings_tab, "ECG Processing Settings")
        
        self.setCentralWidget(central)
        
        self._set_current_source_mode()

        # --- BIG BOLD WARNING LABEL ---
        self.max_speed_warning = QLabel("ANALYZING AT MAXIMUM SPEED \nGraphs are paused until finished", self)
        self.max_speed_warning.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.max_speed_warning.setStyleSheet("""
            QLabel {
                background-color: rgba(255, 165, 0, 255); /* Orange */
                color: black; 
                font-size: 16px; 
                font-weight: bold; 
                border-radius: 8px;
                padding: 10px;
            }
        """)
        self.max_speed_warning.hide()
        self.max_speed_warning.raise_()
        self._on_filter_mode_changed(self.filter_mode_combo.currentText())

    def _on_speed_changed(self, text: str):
        if self.worker is not None:
            if self._is_max_speed():
                self.display.set_status("⚡ Maximum Speed: Live graphs paused.")
            else:
                self.display.set_status("Running...")
        self._update_warning_visibility()

    def _filter_mode_uses_low_high(self, mode: str) -> bool:
        """Return True when low/high cut settings are active for *mode*."""
        return mode in _FILTER_MODES_WITH_LOW_HIGH

    def _on_filter_mode_changed(self, mode: str) -> None:
        uses_low_high = self._filter_mode_uses_low_high(mode)
        self.low_spin.setEnabled(uses_low_high)
        self.high_spin.setEnabled(uses_low_high)
    
    def _build_menu(self):
        menubar = self.menuBar()

        file_menu = menubar.addMenu("File")
        
        # 1. Create all the actions first
        open_action = QAction("Open Data File", self)
        open_action.triggered.connect(lambda: self._select_data_file(initial=False))
        
        save_action = QAction("Open Pre-report", self)
        save_action.triggered.connect(self.open_pre_report)
        
        # NOTE: "Downsample LabChart file" action has been removed from the ECG
        # UI path — it was VER-specific (LabChart 1000 Hz → 250 Hz conversion)
        # and is not part of the ECG workflow.  The ver_downsample module is
        # retained as legacy code but is no longer accessible from the menu.
        
        usb_test_action = QAction("USB Test", self)
        usb_test_action.setToolTip("Open the dedicated USB Serial Port testing tool")
        usb_test_action.triggered.connect(self._launch_usb_test)
        
        exit_action = QAction("Exit", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        
        # 2. Add them to the menu in the exact order you want them to appear!
        file_menu.addAction(open_action)
        file_menu.addAction(save_action)
        file_menu.addAction(usb_test_action)    
        file_menu.addSeparator()
        file_menu.addAction(exit_action)

        help_menu = menubar.addMenu("Help")
        about_action = QAction("About", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)
        
    def _show_about(self):
        QMessageBox.information(
            self,
            "About ECG Analysis",
            "ECG Analysis — modular signal workbench with real-time replay, "
            "trigger-locked averaging, wavelet analysis, and report export.\n\n"
            "Inherited from the VER-analyses codebase; ECG-specific analysis "
            "logic is in development.  See TRANSITION.md for details.",
        )

    def _select_data_file(self, initial: bool = False):
        default_path = str(Path.cwd())
        selected, _ = QFileDialog.getOpenFileName(
            self, "Select ECG File (plain text)", default_path,
            "Text Files (*.txt);;All Files (*)"
        )

        if selected:
            # Validate using ECGFileLoader before accepting the file
            loader = ECGFileLoader(selected, sample_rate=ACQ_CONFIG["sample_rate"])
            signal, errors = loader.load()
            if signal.size == 0:
                error_detail = "\n".join(errors[:5])
                if len(errors) > 5:
                    error_detail += f"\n… ({len(errors) - 5} more issue(s) not shown)"
                QMessageBox.warning(
                    self, "Invalid ECG File",
                    "The selected file contains no valid numeric data.\n\n"
                    "Expected: plain .txt file with one numeric value per line."
                    + (f"\n\n{error_detail}" if error_detail else ""),
                )
                return
            if errors:
                log.warning("ECG file validation issues: %s", errors)

            self.data_file = selected
            self.file_label.setText(f"Selected: \n\n{Path(selected).name}")
            self.display.set_status(
                f"Loaded: {Path(selected).name}  ({signal.size:,} samples)"
            )

            if not initial:
                self.reset_all()
            if self.worker is not None:
                self._restart_worker_with_file()

        elif initial:
            fallback = Path(__file__).with_name("RAW_files_combined.txt")
            if fallback.exists():
                self.data_file = str(fallback)
                self.file_label.setText(f"Selected: {fallback.name}")
                self.display.set_status(f"Loaded file: {fallback.name}")

    # _suggest_exclusion (VER-specific artifact threshold tuning dialog) has been
    # removed: it was never connected to any ECG UI element and referenced the
    # removed set_artifact_threshold widget.  ExclusionTuningDialog is kept in
    # this file for now as a transitional artifact; it will be removed or replaced
    # in a future PR when the ECG processing pipeline is introduced.

    def _restart_worker_with_file(self):
        self._shutdown_worker()
        self._start_worker(self._get_speed_factor())

    def _on_source_mode_changed(self, mode: str):
        if mode.startswith("USB Serial"):
            self.acquisition_source_mode = "Serial"
        else:
            self.acquisition_source_mode = "File"
        ACQ_CONFIG["source_mode"] = self.acquisition_source_mode
        is_file = self.acquisition_source_mode == "File"
        is_serial = self.acquisition_source_mode == "Serial"
        self.speed_combo.setEnabled(is_file)
        self.serial_port_combo.setEnabled(is_serial)
        self.serial_refresh_btn.setEnabled(is_serial)
        if is_serial:
            self._refresh_serial_ports()
            self.display.set_status("Source: USB Serial microcontroller")
        else:
            self.display.set_status("Source: File replay (full offline compute before pre-report)")
        if self.worker is not None:
            self._shutdown_worker()

    def _set_current_source_mode(self):
        if self.acquisition_source_mode == "Serial":
            self.source_combo.setCurrentText("USB Serial (microcontroller)")
        else:
            self.source_combo.setCurrentText("File Replay")

    def _get_speed_factor(self) -> float | None:
        speed_map = {"Real-time (1×)": 1.0, "Fast (10×)": 10.0, "Maximum speed": None}
        return speed_map.get(self.speed_combo.currentText(), 1.0)

    def _refresh_serial_ports(self) -> None:
        """Populate the serial port combo with currently available ports."""
        try:
            ports = sorted(
                (p.device for p in serial.tools.list_ports.comports() if getattr(p, "device", None)),
                key=str.casefold,
            )
        except Exception:
            ports = []
        current = self.serial_port_combo.currentText().strip()
        configured_port = str(SERIAL_CONFIG.get("port", "")).strip()
        if configured_port and configured_port not in ports:
            ports.append(configured_port)
        self.serial_port_combo.blockSignals(True)
        self.serial_port_combo.clear()
        self.serial_port_combo.addItems(ports)
        if current in ports:
            self.serial_port_combo.setCurrentText(current)
        elif current:
            self.serial_port_combo.setEditText(current)
        self.serial_port_combo.blockSignals(False)

    def _build_acquisition_source(self, speed_factor: float | None = 1.0):
        try:
            # 1. LIVE USB STREAMING
            if self.source_combo.currentText() == "USB Serial (microcontroller)":
                port = self.serial_port_combo.currentText().strip()
                if not port:
                    raise ValueError("No serial port selected. Please select a valid COM port.")
                return SerialAcquisitionSource(port)

            # 2. ECG FILE REPLAY (plain one-column .txt)
            else:
                if not hasattr(self, 'data_file') or not self.data_file:
                    raise ValueError("No ECG data file selected. Please open a .txt file first.")

                return ECGFileLoader(
                    self.data_file,
                    sample_rate=ACQ_CONFIG["sample_rate"],
                    speed_factor=speed_factor,
                )

        except Exception as e:
            QMessageBox.critical(self, "Acquisition Error", f"Failed to initialize data source:\n{str(e)}")
            self.display.set_status("Ready")
            self.start_btn.setText("Start")
            self._update_warning_visibility()
            return None
        
    def _start_worker(self, speed_factor: float | None = 1.0):
        source = self._build_acquisition_source(speed_factor)
        if source is None:
            return

        self.worker_thread = QThread(self)
        self.worker = AcquisitionWorker(source)
        self.worker.moveToThread(self.worker_thread)

        self.worker_thread.started.connect(self.worker.run)
        self.worker.sample_ready.connect(self._handle_sample)
        self.worker.eof_reached.connect(self._handle_eof)
        self.worker.error.connect(self._handle_worker_error)
        self.worker_thread.start()

    def _shutdown_worker(self):
        if self.worker:
            self.worker.stop()
        if self.worker_thread:
            self.worker_thread.quit()
            self.worker_thread.wait(2000)
        self.worker = None
        self.worker_thread = None
        
    def start_acquisition(self):
        current_speed = self._get_speed_factor()
        self._sync_artifact_settings_from_ui()
        _refresh_runtime_classifier_settings(self.settings_manager.settings.get("CLASSIFIER_CONFIG", {}))

        # File mode now runs as full offline analysis before visualization.
        if self.acquisition_source_mode == "File":
            self._run_file_analysis_offline()
            self.tabs.setCurrentIndex(0)
            return

        if self.worker is None:
            if self.scope.flash_count > 0 or self.scope.session_averages:
                resp = QMessageBox.question(
                    self, "Reset?",
                    "There is data from a previous run. Reset before starting?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes,
                )
                if resp == QMessageBox.StandardButton.Yes:
                    self.reset_all()
            
            self.display.suppress_updates = False
            self._captured_serial_raw = []
            self._latest_pre_report_data = None

            # Start a brand new worker with the current speed
            self._start_worker(current_speed)
            self.start_btn.setText("Running...")
            self._update_warning_visibility() # This checks the speed and shows the label
        
        else:
            # --- THE SPEED BUG FIX ---
            # The worker already exists. Update the speed on the fly before resuming!
            if hasattr(self.worker, 'source') and hasattr(self.worker.source, 'speed_factor'):
                self.worker.source.speed_factor = current_speed

        # --- NEW STATUS TEXT LOGIC (Moved here so it doesn't get erased!) ---
        self.start_btn.setText("Running...")
        self.display.set_status("Running...")
        # --------------------------------------------------------------------

        if self.worker is not None:
            self.worker.start_stream()

        # Auto-switch to the live analysis tab (index 0) so the user sees
        # the ongoing analysis without needing to switch tabs manually.
        self.tabs.setCurrentIndex(0)

    
    def stop_acquisition(self):
        if self.worker is not None:
            self.worker.pause_stream()
        self.start_btn.setText("Resume")
        if self.acquisition_source_mode == "Serial" and self._captured_serial_raw:
            resp = QMessageBox.question(
                self,
                "USB capture stopped",
                "Open pre-report review for the captured USB session?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if resp == QMessageBox.StandardButton.Yes:
                self._build_serial_pre_report()
            
    def reset_all(self):
        self.bandpass = BandpassFilter({
            "lowcut_hz": float(self.low_spin.value()),
            "highcut_hz": float(self.high_spin.value()),
            "sample_rate": ACQ_CONFIG["sample_rate"],
            "order": FILTER_CONFIG["order"],
        })
        self.scope = ECGScopeProcessor(self.bandpass)
        # Reset ECG rolling processor with current settings
        self._ecg_rolling = self._build_ecg_rolling_processor()
        self._ecg_offline = self._build_ecg_offline_processor()
        self._max_speed_raw_buffer = []
        self._captured_serial_raw = []
        self._latest_pre_report_data = None
        self.session_wavelets = []
        self.session_wavelet_freqs = None
        self.session_labels = []
        self.session_ver_peaks = []
        self.session_flash_counts = []
        self.session_flash_counts_accepted = []
        self.session_artifact_rejection_enabled = []
        self.session_artifact_exclusion_thresholds = []
        self._scope_panel_session = None
        self._sync_artifact_settings_from_ui()
        self.display.reset_all()
        self._set_progress(0, 0) 
        self.start_btn.setText("Start")
        self._shutdown_worker()
        self.worker = None

    def _sync_artifact_settings_from_ui(self, *_args):
        if not hasattr(self, "set_artifact_enabled") or not hasattr(self, "set_artifact_threshold"):
            return

        artifact_enabled = self.set_artifact_enabled.isChecked()
        artifact_threshold = float(self.set_artifact_threshold.value())

        self.settings_manager.settings["EPOCH_CONFIG"]["artifact_rejection_enabled"] = artifact_enabled
        self.settings_manager.settings["EPOCH_CONFIG"]["artifact_exclusion_uv"] = artifact_threshold
        EPOCH_CONFIG["artifact_rejection_enabled"] = artifact_enabled
        EPOCH_CONFIG["artifact_exclusion_uv"] = artifact_threshold

        if hasattr(self, "scope") and self.scope is not None:
            self.scope.config["artifact_rejection_enabled"] = artifact_enabled
            self.scope.config["artifact_exclusion_uv"] = artifact_threshold

    def _apply_exclusion_threshold(self, threshold_uv: float) -> None:
        """Apply, clamp, and persist the chosen artifact exclusion threshold.

        NOTE: The UI widget (set_artifact_threshold) was removed from the ECG
        GUI in the cleanup PR.  This method now updates EPOCH_CONFIG and the
        settings JSON directly without a widget interaction.
        """
        raw_threshold = float(threshold_uv)
        threshold = _clamp_artifact_threshold(raw_threshold)
        if threshold != raw_threshold:
            log.debug(
                "Clamped applied exclusion threshold from %.6f to %.6f µV",
                raw_threshold,
                threshold,
            )
        EPOCH_CONFIG["artifact_exclusion_uv"] = threshold
        self.settings_manager.settings["EPOCH_CONFIG"]["artifact_exclusion_uv"] = threshold
        if hasattr(self, "scope") and self.scope is not None:
            self.scope.config["artifact_exclusion_uv"] = threshold
        self.settings_manager.save_settings(self.settings_manager.settings)

    # _save_user_settings has been removed: the VER Analysis Settings and
    # Signal Classifier Settings tabs that hosted its save button have been
    # removed from the ECG GUI.  Settings are loaded from JSON on startup and
    # can be edited manually in user_settings.json between sessions.

    def _apply_filter_settings(self):
        """Apply the bandpass frequency settings and reconfigure the ECG processor."""
        mode = self.filter_mode_combo.currentText()
        uses_low_high = self._filter_mode_uses_low_high(mode)
        low = float(self.low_spin.value())
        high = float(self.high_spin.value())
        if low >= high:
            QMessageBox.warning(self, "Invalid filter", "Low cut must be less than high cut.")
            return
        # Update causal bandpass filter used for the scrolling display trace.
        # Keep this stable in non-bandpass analysis modes where low/high are disabled.
        if uses_low_high:
            self.bandpass.redesign(low, high)
        # Update ECG processing config and rebuild the rolling processor
        self._ecg_proc_cfg["lowcut_hz"] = low
        self._ecg_proc_cfg["highcut_hz"] = high
        self._ecg_proc_cfg["filter_mode"] = mode
        self._ecg_rolling.reconfigure(
            filter_mode=self._ecg_proc_cfg["filter_mode"],
            lowcut_hz=low,
            highcut_hz=high,
        )
        self._ecg_offline = self._build_ecg_offline_processor()
        if uses_low_high:
            self.display.set_status(
                f"Filter updated: {low:.1f}–{high:.1f} Hz  "
                f"[{self._ecg_proc_cfg['filter_mode']}]"
            )
        else:
            self.display.set_status(
                f"Filter mode updated: [{self._ecg_proc_cfg['filter_mode']}] "
                "(Low/High cut ignored for this mode)."
            )

    def _save_ecg_processing_settings(self) -> None:
        """Read values from the ECG Processing Settings tab and persist to JSON."""
        low = float(self.low_spin.value())
        high = float(self.high_spin.value())
        if low >= high:
            QMessageBox.warning(self, "Invalid filter", "Low cut must be less than high cut.")
            return

        self._ecg_proc_cfg["detector_method"] = self.detector_combo.currentText()
        self._ecg_proc_cfg["rolling_window_s"] = float(self.rolling_window_spin.value())
        self._ecg_proc_cfg["detection_interval_s"] = float(self.det_interval_spin.value())
        self._ecg_proc_cfg["boundary_guard_s"] = float(self.boundary_guard_spin.value())
        self._ecg_proc_cfg["notch_hz"] = float(self.notch_spin.value())
        # Also sync the filter settings from the top bar
        self._ecg_proc_cfg["filter_mode"] = self.filter_mode_combo.currentText()
        self._ecg_proc_cfg["lowcut_hz"] = low
        self._ecg_proc_cfg["highcut_hz"] = high

        # Persist to JSON
        self.settings_manager.settings["ECG_PROCESSING_CONFIG"] = dict(self._ecg_proc_cfg)
        self.settings_manager.save_settings(self.settings_manager.settings)

        # Rebuild processors with new config
        self._ecg_rolling = self._build_ecg_rolling_processor()
        self._ecg_offline = self._build_ecg_offline_processor()

        self.display.set_status("ECG processing settings saved.")
        log.info("ECG processing settings saved: %s", self._ecg_proc_cfg)

    def _sync_detector_from_box4(self, text: str) -> None:
        """Keep the ECG Processing Settings detector combo in sync with Box 4.

        Also updates the live processing config so the new method takes effect
        on the next analysis run without requiring a manual Settings save.
        """
        if self.detector_combo.currentText() != text:
            self.detector_combo.blockSignals(True)
            self.detector_combo.setCurrentText(text)
            self.detector_combo.blockSignals(False)
        # Apply immediately to the active config and rebuild processors
        if self._ecg_proc_cfg.get("detector_method") != text:
            self._ecg_proc_cfg["detector_method"] = text
            self._ecg_rolling = self._build_ecg_rolling_processor()
            self._ecg_offline = self._build_ecg_offline_processor()

    def _sync_detector_from_settings(self, text: str) -> None:
        """Keep the Box 4 detector combo in sync with the ECG Processing Settings tab."""
        if self.box4_detector_combo.currentText() != text:
            self.box4_detector_combo.blockSignals(True)
            self.box4_detector_combo.setCurrentText(text)
            self.box4_detector_combo.blockSignals(False)

    def _build_pre_report_data(
        self,
        raw_signal: np.ndarray,
        offline_result,
        source_label: str,
        source_mode: str,
        output_prefix: str,
        output_dir: Path,
    ) -> dict:
        """Create a normalized container used by the pre-report dialog and CSV export."""
        raw_arr = np.asarray(raw_signal, dtype=float)
        filtered = np.asarray(offline_result.filtered_signal, dtype=float)
        if filtered.size != raw_arr.size:
            filtered = raw_arr.copy()

        return {
            "sample_rate": float(ACQ_CONFIG.get("sample_rate", 250.0)),
            "raw_signal": raw_arr,
            "filtered_signal": filtered,
            "r_peak_indices": list(offline_result.r_peak_indices),
            "r_peak_times_s": list(offline_result.r_peak_times_s),
            "hr_times_s": list(offline_result.hr_times_s),
            "hr_bpm": list(offline_result.hr_bpm),
            "beat_count": int(offline_result.beat_count),
            "mean_hr_bpm": offline_result.mean_hr_bpm,
            "duration_s": float(offline_result.duration_s),
            "source_label": source_label,
            "source_mode": source_mode,
            "output_prefix": output_prefix,
            "output_dir": str(output_dir),
            "p_peak_indices": list(offline_result.p_peak_indices),
            "q_peak_indices": list(offline_result.q_peak_indices),
            "s_peak_indices": list(offline_result.s_peak_indices),
            "t_peak_indices": list(offline_result.t_peak_indices),
        }

    def _show_pre_report_dialog(self, report_data: dict) -> None:
        dlg = ECGPreReportDialog(report_data=report_data, save_callback=self._save_pre_report_csvs, parent=self)
        dlg.exec()

    def _serial_output_prefix(self) -> str:
        if self.worker is not None and hasattr(self.worker, "source"):
            raw_path = getattr(self.worker.source, "_raw_log_path", None)
            if raw_path:
                return Path(raw_path).stem
        return time.strftime("ECG_Serial_%Y%m%d_%H%M%S")

    def _run_file_analysis_offline(self) -> None:
        """Run full-file offline compute, then open the dedicated pre-report dialog."""
        if not self.data_file:
            QMessageBox.warning(self, "No ECG file", "Please select an ECG file first.")
            return

        selected_speed = self.speed_combo.currentText()
        self.start_btn.setText("Running...")
        self.max_speed_warning.setText(
            "PROCESSING FILE OFFLINE\nComputing full analysis before visualization"
        )
        self.max_speed_warning.resize(520, 100)
        self.max_speed_warning.move(int((self.width() - 520) / 2), 150)
        self.max_speed_warning.show()
        self.max_speed_warning.raise_()
        self.display.set_status(f"Processing file offline ({selected_speed} selected)…")
        QApplication.processEvents()

        try:
            loader = ECGFileLoader(
                self.data_file,
                sample_rate=float(ACQ_CONFIG.get("sample_rate", 250.0)),
                speed_factor=None,
            )
            raw_signal, warnings = loader.load()
            if raw_signal.size == 0:
                details = "\n".join(warnings) if warnings else "No valid numeric ECG samples found."
                QMessageBox.warning(self, "File load failed", details)
                return
            if warnings:
                QMessageBox.information(
                    self,
                    "File loaded with warnings",
                    "\n".join(warnings[:6]) + ("\n…" if len(warnings) > 6 else ""),
                )

            offline_result = self._ecg_offline.process(raw_signal)
            file_path = Path(self.data_file)
            self._latest_pre_report_data = self._build_pre_report_data(
                raw_signal=raw_signal,
                offline_result=offline_result,
                source_label=f"File analysis complete: {file_path.name}",
                source_mode="File",
                output_prefix=file_path.stem,
                output_dir=file_path.parent,
            )
            self.display.set_status(
                f"File analysis complete — {offline_result.beat_count} beats, "
                f"duration {offline_result.duration_s:.1f} s."
            )
            self._show_pre_report_dialog(self._latest_pre_report_data)
        except Exception as exc:
            log.exception("File offline analysis failed")
            QMessageBox.critical(self, "Analysis error", f"Failed to process file:\n{exc}")
            self.display.set_status("File analysis failed.")
        finally:
            self.max_speed_warning.hide()
            self.start_btn.setText("Start")

    def _build_serial_pre_report(self) -> bool:
        """Build and open a pre-report from captured USB serial samples."""
        raw_signal = np.asarray(self._captured_serial_raw, dtype=float)
        if raw_signal.size < _MIN_SAMPLES_FOR_PRE_REPORT:
            QMessageBox.information(
                self,
                "Not enough data",
                "Capture more USB data before opening pre-report.",
            )
            return False

        self.display.set_status("Preparing pre-report from captured USB session…")
        QApplication.processEvents()
        try:
            offline_result = self._ecg_offline.process(raw_signal)
            self._latest_pre_report_data = self._build_pre_report_data(
                raw_signal=raw_signal,
                offline_result=offline_result,
                source_label="USB serial capture pre-report",
                source_mode="Serial",
                output_prefix=self._serial_output_prefix(),
                output_dir=Path.cwd(),
            )
            self._show_pre_report_dialog(self._latest_pre_report_data)
            return True
        except Exception as exc:
            log.exception("Failed to build serial pre-report")
            QMessageBox.critical(self, "Pre-report error", f"Failed to prepare USB pre-report:\n{exc}")
            return False

    def open_pre_report(self) -> None:
        """Open the latest pre-report, or generate one from captured USB data."""
        if self._latest_pre_report_data is not None:
            self._show_pre_report_dialog(self._latest_pre_report_data)
            return

        if self.acquisition_source_mode == "Serial" and self._captured_serial_raw:
            self._build_serial_pre_report()
            return

        QMessageBox.information(
            self,
            "Pre-report unavailable",
            "Run a file analysis or capture USB data first.",
        )

    def _save_pre_report_csvs(self, report_data: dict) -> None:
        """Save the separated 4-file ECG CSV report set."""
        default_dir = str(report_data.get("output_dir", Path.cwd()))
        selected_dir = QFileDialog.getExistingDirectory(
            self,
            "Choose folder for report CSV files",
            default_dir,
        )
        if not selected_dir:
            return

        out_dir = Path(selected_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        default_stem = sanitize_output_stem(str(report_data.get("output_prefix", "")))
        source_mode = str(report_data.get("source_mode", "")).strip()
        output_stem = default_stem

        # Serial mode asks for a user label; file mode keeps source-file stem naming.
        if source_mode == "Serial":
            entered_stem, accepted = QInputDialog.getText(
                self,
                "Report base filename",
                "Enter a descriptive base filename:",
                QLineEdit.EchoMode.Normal,
                default_stem,
            )
            if not accepted:
                return
            output_stem = sanitize_output_stem(entered_stem, fallback=default_stem)

        report_paths = save_neurokit2_report_set(
            report_data=report_data,
            out_dir=out_dir,
            output_stem=output_stem,
        )
        saved_names = [path.name for path in report_paths.values() if path is not None]
        if source_mode == "Serial":
            raw_serial_path = out_dir / f"{output_stem}_raw_serial_data.csv"
            raw_signal = np.asarray(report_data.get("raw_signal", []), dtype=float)
            try:
                with raw_serial_path.open("w", newline="", encoding="utf-8") as fh:
                    writer = csv.writer(fh)
                    writer.writerow(["Raw_ECG_mV"])
                    for value in raw_signal.tolist():
                        writer.writerow([value])
                saved_names.append(raw_serial_path.name)
            except Exception as exc:
                log.warning("Raw serial CSV could not be written: %s", exc)

        if not saved_names:
            QMessageBox.warning(self, "Reports not saved", "No CSV files could be written. Check logs for details.")
            return
        QMessageBox.information(
            self,
            "Reports saved",
            f"Saved CSV reports:\n" + "\n".join(saved_names) + f"\n\nFolder:\n{out_dir}",
        )
        self.display.set_status(f"Saved pre-report CSVs to {out_dir}")

    def _handle_sample(self, row: np.ndarray):
        samples = np.asarray(row, dtype=float)
        if samples.ndim == 1:
            self._handle_single_sample(samples)
            return
        for sample in samples:
            self._handle_single_sample(sample)

    def _handle_single_sample(self, sample: np.ndarray):
        """Process one ECG sample from the acquisition worker.

        ECG path notes
        --------------
        * ``sample[0]`` (trigger) is always ``0.0`` in the active ECG path:
          - ECGFileLoader yields ``[0.0, ecg]`` (no hardware trigger).
          - SerialAcquisitionSource yields ``[0.0, ecg]`` (flash trigger discarded).
        * The inherited VER scope processor (ECGScopeProcessor) is still called for
          interface compatibility.  With trigger always False, it is a no-op — the
          epoch_complete / session_complete branches never fire.
        * ECG R-peak detection is now handled by :attr:`_ecg_rolling` (rolling window
          processor) for 1× / 10× / streaming modes, and buffered into
          :attr:`_max_speed_raw_buffer` for maximum-speed batch processing at EOF.
        """
        trigger = bool(sample[0])   # always False in ECG path
        ecg = float(sample[1])
        filtered = self.bandpass.process_sample(ecg)  # causal IIR for display trace
        if self.acquisition_source_mode == "Serial":
            self._captured_serial_raw.append(ecg)

        if self._is_max_speed():
            # Maximum-speed mode: buffer raw ECG samples, suppress all display updates.
            # The full batch is processed in _handle_eof after the file ends.
            self._max_speed_raw_buffer.append(ecg)
            # Still push to scroll buffer (without rendering) so the deque stays
            # populated — flushed to screen after analysis completes.
            self.display.update_scroll_panel(ecg, filtered)
            return

        # --- Streaming / 1× / 10× path: rolling R-peak detection ---

        # Update the scrolling display (render rate limited by FPS timer)
        self.display.update_scroll_panel(ecg, filtered)

        # Run rolling detector; it returns results every detection_interval_s
        rolling_result = self._ecg_rolling.add_sample(ecg)
        if rolling_result is not None and rolling_result.new_peak_times_s:
            self.display.add_r_peaks(
                rolling_result.new_peak_times_s,
                rolling_result.new_hr_times_s,
                rolling_result.new_hr_bpm,
            )

        # Legacy VER scope path — kept for compatibility; trigger=False means no-op
        scope_result = self.scope.process_sample(trigger, ecg)
        current_session = scope_result["session_number"]
        self._set_progress(current_session, scope_result["flash_count"], scope_result.get("flash_count_accepted"))

        # epoch_complete / session_complete are always False when trigger=0;
        # kept so the code compiles and the display stubs are still called.
        if scope_result["epoch_complete"]:
            if self._scope_panel_session != current_session:
                self.display.clear_scope_panel()
                self._scope_panel_session = current_session
            self.display.update_scope_panel(
                self.scope.epoch_time_ms,
                scope_result["completed_epoch"],
                scope_result["running_average"],
                scope_result["flash_count"],
                current_session,
                flash_count_accepted=scope_result.get("flash_count_accepted"),
            )

        if scope_result["session_complete"]:
            session_avg = scope_result["completed_session_average"]
            session_num = scope_result["completed_session_number"]
            self._record_session(
                session_avg,
                session_num,
                flash_count=scope_result.get("completed_session_flash_count"),
                flash_count_accepted=scope_result.get("completed_session_flash_count_accepted"),
                artifact_rejection_enabled=scope_result.get("artifact_rejection_enabled"),
                artifact_exclusion_threshold=scope_result.get("artifact_exclusion_threshold"),
            )
            self.display.clear_scope_panel()
            self._scope_panel_session = None

            if not self.scope.has_completed_all_sessions():
                self._set_progress(min(EPOCH_CONFIG["num_sessions"], session_num + 1), 0)

            if self.scope.has_completed_all_sessions():
                self.stop_acquisition()
                self.save_report()

    def _set_progress(self, session_number: int, flash_count: int, flash_count_accepted: int | None = None): 
        # Calculate how many seconds one block takes (flashes / 2 Hz)
        seconds_per_block = int(EPOCH_CONFIG['flashes_per_session'] / 2.0)
        flash_total = EPOCH_CONFIG['flashes_per_session']
        if flash_count_accepted is not None:
            rejected = flash_count - flash_count_accepted
            flash_text = f"Trigger {flash_count}/{flash_total} | Accepted {flash_count_accepted} | Rejected {rejected}"
        else:
            flash_text = f"Trigger {flash_count}/{flash_total}"
        self.progress_label.setText(
            f"Block {session_number}/{EPOCH_CONFIG['num_sessions']} ({seconds_per_block}s) | {flash_text}"
        )
    def _handle_eof(self):
        """Handle end-of-file for both normal and maximum-speed analysis.

        For maximum-speed mode:
        1. Process the collected raw buffer through ECGOfflineProcessor (batch).
        2. Load the results into the display (R-peaks, HR trace).
        3. Clear suppress_updates and call flush_display() for a single render.

        For 1× / 10× / streaming modes:
        The scroll display is already up to date; we just clean up and optionally
        prompt for further action.
        """
        self.max_speed_warning.hide()
        self.stop_acquisition()

        # --- Maximum-speed offline batch analysis ---
        if self._max_speed_raw_buffer:
            raw_arr = np.array(self._max_speed_raw_buffer, dtype=float)
            log.info(
                "_handle_eof (max speed): processing %d samples offline …", len(raw_arr)
            )
            try:
                self.display.set_status("Analyzing … (computing R-peaks and HR)")
                # Allow Qt to repaint the status label before blocking computation
                QApplication.processEvents()

                offline_result = self._ecg_offline.process(raw_arr)
                log.info(
                    "Offline result: %d beats detected, mean HR = %s bpm",
                    offline_result.beat_count,
                    f"{offline_result.mean_hr_bpm:.1f}" if offline_result.mean_hr_bpm else "N/A",
                )

                # Populate display buffers with offline R-peaks
                if offline_result.r_peak_times_s:
                    self.display.add_r_peaks(
                        offline_result.r_peak_times_s,
                        offline_result.hr_times_s,
                        offline_result.hr_bpm,
                    )

                # Replace the tachometer with the full-recording HR trace
                if offline_result.hr_times_s:
                    self.display.update_hr_full(
                        offline_result.hr_times_s,
                        offline_result.hr_bpm,
                    )

                # Build summary status message
                mean_hr_txt = (
                    f"{offline_result.mean_hr_bpm:.1f} bpm"
                    if offline_result.mean_hr_bpm else "—"
                )
                status = (
                    f"Analysis complete — {offline_result.beat_count} beats detected  |  "
                    f"Mean HR: {mean_hr_txt}  |  "
                    f"Duration: {offline_result.duration_s:.1f} s"
                )
            except Exception as exc:
                log.exception("Offline ECG processing failed")
                status = f"Analysis complete (offline processing error: {exc})"

            # Clear suppression flag and flush display
            self.display.suppress_updates = False
            self.display.flush_display()
            self.display.set_status(status)
            self._max_speed_raw_buffer = []

        else:
            # 1× / 10× path — display is already up to date; just set status
            partial_session = self.scope.save_partial_session(EPOCH_CONFIG["flashes_per_session"] // 2)
            if partial_session is not None:
                self._record_session(
                    partial_session["session_average"],
                    partial_session["session_number"],
                    flash_count=partial_session["flash_count"],
                    flash_count_accepted=partial_session.get("flash_count_accepted"),
                    artifact_rejection_enabled=partial_session.get("artifact_rejection_enabled"),
                    artifact_exclusion_threshold=partial_session.get("artifact_exclusion_threshold"),
                )

            if self.scope.session_averages:
                next_action = prompt_analysis_complete_action(self)
                if should_proceed_to_human_validation(next_action):
                    log.info("End-of-analysis dialog: proceeding to human validation.")
                    self.save_report()
                elif next_action == BACK_TO_ANALYSIS:
                    log.info("End-of-analysis dialog: returning to analysis for further adjustments.")
                else:
                    log.info("End-of-analysis dialog: validation canceled by user.")
            else:
                next_action = None

            self.display.set_status(
                status_message_for_analysis_complete_action(
                    next_action,
                    has_session_averages=bool(self.scope.session_averages),
                )
            )

        self.start_btn.setText("Start")
        self._shutdown_worker()
        self.max_speed_warning.hide()

    def _handle_worker_error(self, message: str):
        QMessageBox.critical(self, "Acquisition error", message)

    def _record_session(
        self,
        session_avg: np.ndarray,
        session_num: int,
        flash_count: int | None = None,
        flash_count_accepted: int | None = None,
        artifact_rejection_enabled: bool | None = None,
        artifact_exclusion_threshold: float | None = None,
    ):
        power, freqs = compute_wavelet_scalogram(session_avg)  # generic — keep for ECG
        self.session_wavelets.append(power)
        self.session_wavelet_freqs = freqs
        peak_idx = np.unravel_index(np.argmax(power), power.shape)
        peak_freq = float(freqs[peak_idx[0]])
        peak_latency_ms = float(self.scope.epoch_time_ms[peak_idx[1]])
        peak_power = float(power[peak_idx])

        # --- VER analysis engine call site (transitional) ---
        # detect_ver_peaks comes from ver_analysis_engine.py (REPLACEMENT TARGET 2).
        # Replace with detect_ecg_peaks() from ecg_peaks.py when ready.
        ver_peaks = detect_ver_peaks(session_avg, self.scope.epoch_time_ms)
        self.session_ver_peaks.append(ver_peaks)
        self.session_flash_counts.append(flash_count)
        self.session_flash_counts_accepted.append(flash_count_accepted)
        self.session_artifact_rejection_enabled.append(artifact_rejection_enabled)
        self.session_artifact_exclusion_thresholds.append(artifact_exclusion_threshold)

        seconds = int(session_num * (EPOCH_CONFIG["flashes_per_session"] / 2.0))
        label = f"{seconds} s"
        
        if flash_count_accepted is not None and flash_count is not None:
            label = f"{label} (Acc {flash_count_accepted}/{flash_count})"
        elif flash_count is not None and flash_count != EPOCH_CONFIG["flashes_per_session"]:
            label = f"{label} ({flash_count}/{EPOCH_CONFIG['flashes_per_session']})"
        self.session_labels.append(label)

        self.display.update_wavelet_panel(power, freqs, self.scope.epoch_time_ms, session_num)
        self.display.update_wavelet_stats(peak_freq, peak_latency_ms, peak_power, session_num, ver_peaks=ver_peaks)
        self.display.add_session_average(
            self.scope.epoch_time_ms,
            session_avg,
            session_num,
            session_label=label,
            ver_peaks=ver_peaks,
        )	

    def _on_format_changed(self, format_name: str):
        """No-op stub — SD-card / LabChart format selection removed from ECG path."""

    def _on_flash_count_changed(self, value: int):
        """No-op stub — Trigger/Avg concept removed from ECG top controls."""

    def _set_current_format(self):
        """No-op stub — file format auto-detection removed from ECG path."""

    def show_loading_screen(self, title, message):
        """Displays a borderless, un-clickable loading message that stays on screen."""
        loading_dialog = QDialog(self)
        loading_dialog.setWindowTitle(title)
        loading_dialog.setMinimumSize(450, 100)
        loading_dialog.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.CustomizeWindowHint | Qt.WindowType.WindowTitleHint)
        
        # 1. Explicitly parent the layout AND the label to the dialog
        layout = QVBoxLayout(loading_dialog)
        lbl = QLabel(message, loading_dialog) 
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet("font-size: 14px; font-weight: bold; padding: 10px; color: #333333;")
        layout.addWidget(lbl)
        
        loading_dialog.setModal(True)
        loading_dialog.show()
        
        # 2. THE HAMMER: Force the window AND the text to paint right now
        loading_dialog.repaint()
        lbl.repaint() 
        
        # 3. Flush the event queue twice to guarantee the graphics card catches up
        QApplication.processEvents() 
        QApplication.processEvents() 
        
        return loading_dialog
    
    def save_report(self):
        self.max_speed_warning.hide()
        report_input = self.data_file
        if report_input is None:
            report_input = str(Path.cwd() / "serial_live_report.txt")
            
        # --- NEW: Show loading screen for Pass 1 ---
        load_ui = self.show_loading_screen(
            "Processing...", 
            "Generating draft report and preparing the review module.\nThis may take a few moments..."
        )
        
        # ---------------------------------------------------------
        # PASS 1: Generate the Draft
        # --- ECG report engine call site (transitional) ---
        # save_ecg_report comes from ecg_report.py (REPLACEMENT TARGET 4).
        # Replace delegation inside ecg_report.py with real ECG report logic
        # after scope + peaks + classifier modules are replaced.
        # ---------------------------------------------------------
        try:
            result = save_ecg_report(
                report_input,
                self.scope.session_averages,
                self.scope.epoch_time_ms,
                session_wavelets=self.session_wavelets if self.session_wavelets else None,
                session_wavelet_freqs=self.session_wavelet_freqs,
                session_labels=self.session_labels if self.session_labels else None,
                session_ver_peaks=self.session_ver_peaks if self.session_ver_peaks else None,
                session_flash_counts=self.session_flash_counts if self.session_flash_counts else None,
                session_flash_counts_accepted=self.session_flash_counts_accepted if self.session_flash_counts_accepted else None,
                session_artifact_rejection_enabled=self.session_artifact_rejection_enabled if self.session_artifact_rejection_enabled else None,
                session_artifact_exclusion_thresholds=self.session_artifact_exclusion_thresholds if self.session_artifact_exclusion_thresholds else None,
            )
        except PermissionError:
            load_ui.accept()
            QMessageBox.warning(self, "File Access Denied", "Could not save the report because the PDF or CSV file is currently open.\n\nPlease close the file and try saving again.")
            return
        except Exception as e:
            log.exception("Failed to save report (pass 1)")
            load_ui.accept()
            QMessageBox.critical(self, "Error", f"Failed to save report:\n{e}")
            return

        if result is None:
            load_ui.accept() # Close loading box on error
            QMessageBox.information(self, "No data", "No completed analysis blocks available yet.")
            return
            
        # Extract the directory so we can force the overwrite later
        report_dir_str = result.get("report_dir", str(Path(result["png"]).parent))

        # --- CLOSE THE FIRST LOADING SCREEN! ---
        load_ui.accept()

        # ---------------------------------------------------------
        # PASS 2: Human Validation & Overwrite
        # ---------------------------------------------------------
        if self.session_wavelets is not None:
            overrides = launch_ml_logger(
                session_wavelets=self.session_wavelets,
                session_wavelet_freqs=self.session_wavelet_freqs,
                epoch_time_ms=self.scope.epoch_time_ms,
                session_ver_peaks=self.session_ver_peaks,
                labels=self.session_labels if self.session_labels else [],
                png_path=result.get("png"),
                parent=self,
                filename=Path(report_input).name,
                species=self._selected_species_value(),
            )
            
            # If the user clicked save, regenerate and overwrite the files!
            if overrides:
                
                # --- NEW: Show loading screen for Pass 2 ---
                save_ui = self.show_loading_screen(
                    "Saving Data...", 
                    "Applying your review decisions and rendering the final PDF reports.\nPlease wait..."
                )
                
                original_stem = Path(result["png"]).stem 
                try:
                    result = save_ecg_report(
                        report_input,
                        self.scope.session_averages,
                        self.scope.epoch_time_ms,
                        session_wavelets=self.session_wavelets if self.session_wavelets else None,
                        session_wavelet_freqs=self.session_wavelet_freqs,
                        session_labels=self.session_labels if self.session_labels else None,
                        session_ver_peaks=self.session_ver_peaks if self.session_ver_peaks else None,
                        session_flash_counts=self.session_flash_counts if self.session_flash_counts else None,
                        session_flash_counts_accepted=self.session_flash_counts_accepted if self.session_flash_counts_accepted else None,
                        session_artifact_rejection_enabled=self.session_artifact_rejection_enabled if self.session_artifact_rejection_enabled else None,
                        session_artifact_exclusion_thresholds=self.session_artifact_exclusion_thresholds if self.session_artifact_exclusion_thresholds else None,
                        human_overrides=overrides,
                        force_stem=original_stem 
                    )
                except Exception as e:
                    log.exception("Failed to save validated report (pass 2)")
                    save_ui.accept()
                    QMessageBox.critical(self, "Error", f"Failed to save validated report:\n{e}")
                    return
                
                # --- CLOSE THE SECOND LOADING SCREEN! ---
                save_ui.accept()

        # ---------------------------------------------------------
        # FINALIZATION: Move raw data and show ONE popup
        # ---------------------------------------------------------
        png_name = Path(result["png"]).name
        pdf_name = Path(result["pdf"]).name if "pdf" in result else "—"
        summary_csv_name = Path(result["summary_csv"]).name if "summary_csv" in result else "—"
        waveforms_csv_name = Path(result["waveforms_csv"]).name if "waveforms_csv" in result else "—"
            
        raw_file_name = "—"
        if hasattr(self, 'worker') and hasattr(self.worker, 'source'):
            if hasattr(self.worker.source, '_raw_log_path') and self.worker.source._raw_log_path:
                if hasattr(self.worker.source, '_raw_log_file') and self.worker.source._raw_log_file:
                    try:
                        self.worker.source._raw_log_file.close()
                        self.worker.source._raw_log_file = None
                    except Exception:
                        pass
                
                raw_path = Path(self.worker.source._raw_log_path)
                if raw_path.exists():
                    new_path = Path(report_dir_str) / raw_path.name
                    try:
                        shutil.move(str(raw_path), str(new_path))
                        raw_file_name = raw_path.name
                        self.worker.source._raw_log_path = None 
                    except Exception as e:
                        log.warning("Could not move raw file: %s", e)
        
        # The user only sees this AFTER they are completely done!
        QMessageBox.information(
            self,
            "Analysis Report Finalized",
            f"Reports generated, validated, and saved to:\n{report_dir_str}\n\n"
            f"PNG: {png_name}\n"
            f"PDF: {pdf_name}\n"
            f"Summary CSV: {summary_csv_name}\n"
            f"Waveforms CSV: {waveforms_csv_name}\n"
            f"RAW Data: {raw_file_name}"
        )

    def keyPressEvent(self, event):
        """Pass all key events to the default handler.

        The legacy Space-bar stop/resume shortcut from the VER application has
        been removed — it does not make sense for the ECG workflow and caused
        unexpected behaviour when users pressed Space in other contexts.
        """
        super().keyPressEvent(event)

    def closeEvent(self, event):
        self._shutdown_worker()
        super().closeEvent(event)


def main() -> None:
    """Backward-compatibility shim — delegates to ``ecg_main.main()``.

    ``ecg_main.py`` is the canonical ECG launcher.  This function is kept so
    that any code that calls ``ver_main.main()`` directly continues to work
    without changes.  Use ``ecg_main.py`` (``python ecg_main.py``) as the
    primary entrypoint for new usage.
    """
    import ecg_main as _ecg_main  # lazy import avoids circular-import at module level
    _ecg_main.main()


if __name__ == "__main__":
    main()
