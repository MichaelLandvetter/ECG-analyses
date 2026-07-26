"""PyQtGraph display components for live signal visualization.

NOTE (transition): Class name ``VERDisplayWidget`` and some plot titles
are inherited from the VER-analyses codebase.  They will be updated when
the analysis modules are replaced.  See TRANSITION.md.
"""

from __future__ import annotations

from collections import deque
import math
import time
from typing import List, Optional

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QTransform
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ver_config import ACQ_CONFIG, DISPLAY_CONFIG, EPOCH_CONFIG

# Qt's QWIDGETSIZE_MAX (16 777 215) used to effectively remove size constraints
# from QGraphicsGridLayout columns/rows when restoring the normal layout.
_LAYOUT_UNCONSTRAINED = 16_777_215.0

_RAW_TITLE_NORMAL = "Raw + Filtered Signal  \u00b7 double-click to enlarge"
_RAW_TITLE_FOCUSED = "Raw + Filtered Signal  \u00b7 double-click to restore"

# Hint-only strings appended to the dynamic flash-count title in update_scope_panel.
_SCOPE_HINT_NORMAL = "  \u00b7 double-click to enlarge"
_SCOPE_HINT_FOCUSED = "  \u00b7 double-click to restore"
# Full static titles used when no flash data is present (initial state, reset, toggle).
_SCOPE_TITLE_NORMAL = "Analysis Scope  \u00b7 double-click to enlarge"
_SCOPE_TITLE_FOCUSED = "Analysis Scope  \u00b7 double-click to restore"


class _FocusableViewBox(pg.ViewBox):
    """ViewBox that emits *sigDoubleClicked* on a left-button double-click.

    PyQtGraph routes physical double-clicks through :py:meth:`mouseClickEvent`
    (with ``ev.double() == True``), so that hook is used rather than the raw
    Qt ``mouseDoubleClickEvent``.
    """

    sigDoubleClicked = pyqtSignal()

    def mouseClickEvent(self, ev):
        if ev.double() and ev.button() == Qt.MouseButton.LeftButton:
            ev.accept()
            self.sigDoubleClicked.emit()
        else:
            super().mouseClickEvent(ev)


class VERDisplayWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.sample_rate = ACQ_CONFIG["sample_rate"]
        self.scroll_seconds = DISPLAY_CONFIG["scroll_seconds"]
        self.max_scroll_samples = int(self.scroll_seconds * self.sample_rate)

        self.raw_buffer = deque(maxlen=self.max_scroll_samples)
        self.filtered_buffer = deque(maxlen=self.max_scroll_samples)
        self.time_buffer = deque(maxlen=self.max_scroll_samples)
        self.flash_times = deque(maxlen=500)
        self.sample_index = 0
        self._last_scroll_draw = 0.0
        self._scroll_min_interval = 1.0 / max(1, DISPLAY_CONFIG.get("scroll_max_fps", 30))
        self._raw_focused = False
        self._scope_focused = False

        self.session_colors = [
            "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
            "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
        ]

        layout = QVBoxLayout(self)
        self.status_label = QLabel("No data loaded")
        layout.addWidget(self.status_label)
        self.status_label.hide()  # Hides it and frees up the space!

        self.graphics = pg.GraphicsLayoutWidget()
        layout.addWidget(self.graphics)

        self.wavelet_stats_label = QLabel("Peak: — Hz | — ms | Power: —")
        self.wavelet_stats_label.setStyleSheet("color: white; font-size: 11px;")
        layout.addWidget(self.wavelet_stats_label)

        self._init_panels()

    def _reset_sessions_panel(self) -> None:
        self.plot_sessions.clear()
        self.plot_sessions.showGrid(x=True, y=False, alpha=0.3)
        self.plot_sessions.setLabel("bottom", "Time", "ms")
        #self.plot_sessions.setLabel("left", "Minute")
        self.plot_sessions.setTitle("Signal Evolution")
        self.plot_sessions.setXRange(-200, 400, padding=0)
        self.plot_sessions.enableAutoRange('y', True)
        self.plot_sessions.getAxis("left").setTicks([[]])
        self._offset_step = None
        self._session_ticks: List[tuple[float, str]] = []
        self._sessions_y_min = None
        self._sessions_y_max = None

    def _init_panels(self):
        self.plot_sessions = self.graphics.addPlot(row=0, col=0, rowspan=3, title="Signal Evolution")
        self.plot_sessions.getViewBox().setMouseEnabled(x=False, y=True)
        self._reset_sessions_panel()

        _vb = _FocusableViewBox()
        _vb.sigDoubleClicked.connect(self.toggle_raw_focus)
        self.plot_raw = self.graphics.addPlot(row=0, col=1, viewBox=_vb, title=_RAW_TITLE_NORMAL)
        self.plot_raw.getViewBox().setMouseEnabled(x=False, y=True)
        self.plot_raw.showGrid(x=True, y=True, alpha=0.3)
        self.plot_raw.setLabel("bottom", "Time", "s")
        self.plot_raw.setLabel("left", "Amplitude")
        self.plot_raw.setXRange(0, DISPLAY_CONFIG["scroll_seconds"], padding=0)
        #self.plot_raw.setYRange(-1, 1, padding=0)
        self.plot_raw.enableAutoRange(y=True)
        self.curve_raw = self.plot_raw.plot(pen=pg.mkPen((170, 170, 170), width=1), autoDownsample=True)
        self.curve_filtered = self.plot_raw.plot(pen=pg.mkPen((0, 220, 120), width=1.5), autoDownsample=True)
        self.flash_scatter = pg.ScatterPlotItem(size=6, brush=pg.mkBrush(255, 0, 0, 180), pen=pg.mkPen(None))
        self.plot_raw.addItem(self.flash_scatter)

        scope_viewbox = _FocusableViewBox()
        scope_viewbox.sigDoubleClicked.connect(self.toggle_scope_focus)
        self.plot_scope = self.graphics.addPlot(row=1, col=1, viewBox=scope_viewbox, title=_SCOPE_TITLE_NORMAL)
        self.plot_scope.getViewBox().setMouseEnabled(x=False, y=True)
        self.plot_scope.showGrid(x=True, y=True, alpha=0.3)
        self.plot_scope.setLabel("bottom", "Time", "ms")
        self.plot_scope.setLabel("left", "Amplitude")
        self.plot_scope.setXRange(-EPOCH_CONFIG["pre_stim_ms"], EPOCH_CONFIG["post_stim_ms"], padding=0)
        self.plot_scope.enableAutoRange('y', True)
        self.scope_avg_curve = self.plot_scope.plot(pen=pg.mkPen((255, 200, 0), width=3))
        self.scope_avg_curve.setZValue(10)
        self.scope_overlay_curves: List[pg.PlotCurveItem] = []

        self.plot_wavelet = self.graphics.addPlot(row=2, col=1, title="Wavelet Scalogram (all analysis blocks)")
        self.plot_wavelet.getViewBox().setMouseEnabled(x=False, y=True)
        self.plot_wavelet.setLabel("bottom", "Time", "ms")
        self.plot_wavelet.setLabel("left", "Frequency", "Hz")
        self.plot_wavelet.setXRange(-EPOCH_CONFIG["pre_stim_ms"], EPOCH_CONFIG["post_stim_ms"], padding=0)
        #self.plot_wavelet.setYRange(0, 50, padding=0)
        self.plot_wavelet.enableAutoRange(y=True)
        self.wavelet_image = pg.ImageItem()
        self.plot_wavelet.addItem(self.wavelet_image)

        self.graphics.ci.layout.setColumnStretchFactor(0, 1)
        self.graphics.ci.layout.setColumnStretchFactor(1, 1)

    def set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def toggle_raw_focus(self) -> None:
        """Toggle the Raw + Filtered Signal panel between normal and focused (enlarged) view.

        Double-click the panel to enlarge it; double-click again to restore the
        standard multi-panel layout.  Only layout/visibility state is changed —
        no data is reprocessed and no extra filtering passes are triggered.
        """
        self._raw_focused = not self._raw_focused
        layout = self.graphics.ci.layout

        if self._raw_focused:
            # Collapse the VER-evolution column (col 0) and the lower two rows
            # (Scope View and Wavelet Scalogram) so plot_raw fills the view.
            layout.setColumnMaximumWidth(0, 0)
            layout.setRowMaximumHeight(1, 0)
            layout.setRowMaximumHeight(2, 0)
            self.plot_sessions.hide()
            self.plot_scope.hide()
            self.plot_wavelet.hide()
            self.wavelet_stats_label.hide()
            self.plot_raw.setTitle(_RAW_TITLE_FOCUSED)
        else:
            # Restore all panels by removing size constraints and showing items.
            layout.setColumnMaximumWidth(0, _LAYOUT_UNCONSTRAINED)
            layout.setRowMaximumHeight(1, _LAYOUT_UNCONSTRAINED)
            layout.setRowMaximumHeight(2, _LAYOUT_UNCONSTRAINED)
            self.plot_sessions.show()
            self.plot_scope.show()
            self.plot_wavelet.show()
            self.wavelet_stats_label.show()
            self.plot_raw.setTitle(_RAW_TITLE_NORMAL)

    def toggle_scope_focus(self) -> None:
        """Toggle the Scope View panel between normal and focused (enlarged) view.

        Double-click the panel to enlarge it; double-click again to restore the
        standard multi-panel layout.  Only layout/visibility state is changed —
        no data is reprocessed and no extra filtering passes are triggered.
        """
        self._scope_focused = not self._scope_focused
        layout = self.graphics.ci.layout

        if self._scope_focused:
            # Collapse the VER-evolution column (col 0) and the adjacent rows
            # (Raw EEG at row 0 and Wavelet Scalogram at row 2) so plot_scope fills the view.
            layout.setColumnMaximumWidth(0, 0)
            layout.setRowMaximumHeight(0, 0)
            layout.setRowMaximumHeight(2, 0)
            self.plot_sessions.hide()
            self.plot_raw.hide()
            self.plot_wavelet.hide()
            self.wavelet_stats_label.hide()
            self.plot_scope.setTitle(_SCOPE_TITLE_FOCUSED)
        else:
            # Restore all panels by removing size constraints and showing items.
            layout.setColumnMaximumWidth(0, _LAYOUT_UNCONSTRAINED)
            layout.setRowMaximumHeight(0, _LAYOUT_UNCONSTRAINED)
            layout.setRowMaximumHeight(2, _LAYOUT_UNCONSTRAINED)
            self.plot_sessions.show()
            self.plot_raw.show()
            self.plot_wavelet.show()
            self.wavelet_stats_label.show()
            self.plot_scope.setTitle(_SCOPE_TITLE_NORMAL)

    def update_scroll_panel(self, raw_sample: float, filtered_sample: float, trigger_detected: bool) -> None:
        t = self.sample_index / self.sample_rate
        self.sample_index += 1

        self.time_buffer.append(t)
        self.raw_buffer.append(float(raw_sample))
        self.filtered_buffer.append(float(filtered_sample))

        if trigger_detected:
            self.flash_times.append(t)

        now = time.perf_counter()
        if now - self._last_scroll_draw < self._scroll_min_interval:
            return
        self._last_scroll_draw = now

        x = np.asarray(self.time_buffer, dtype=float)
        y_raw = np.asarray(self.raw_buffer, dtype=float)
        y_filt = np.asarray(self.filtered_buffer, dtype=float)

        self.curve_raw.setData(x, y_raw)
        self.curve_filtered.setData(x, y_filt)
        self.plot_raw.setXRange(float(x[0]), float(x[-1]), padding=0.02)

        if self.flash_times:
            if len(y_filt) > 0:
                filt_max = float(np.max(y_filt))
                filt_min = float(np.min(y_filt))
                filt_range = filt_max - filt_min
                if filt_range > 0:
                    y_dot = filt_max + 0.1 * filt_range
                elif filt_max != 0:
                    y_dot = filt_max + 0.1 * abs(filt_max)
                else:
                    y_dot = 1.0
            else:
                y_dot = 1.0
            visible = [ft for ft in self.flash_times if x[0] <= ft <= x[-1]]
            if visible:
                fx = np.array(visible, dtype=float)
                fy = np.full(len(visible), y_dot, dtype=float)
                self.flash_scatter.setData(x=fx, y=fy)
            else:
                self.flash_scatter.setData(x=[], y=[])

    def update_scope_panel(self, epoch_time_ms: np.ndarray, latest_epoch: np.ndarray, running_average: Optional[np.ndarray], flash_count: int, session_number: int, flash_count_accepted: Optional[int] = None) -> None:
        curve = self.plot_scope.plot(epoch_time_ms, latest_epoch, pen=pg.mkPen((180, 180, 180, 120), width=1))
        self.scope_overlay_curves.append(curve)
        if len(self.scope_overlay_curves) > DISPLAY_CONFIG["max_epoch_overlays"]:
            old = self.scope_overlay_curves.pop(0)
            self.plot_scope.removeItem(old)

        if running_average is not None:
            self.scope_avg_curve.setData(epoch_time_ms, running_average)

        if flash_count_accepted is not None:
            rejected = flash_count - flash_count_accepted
            title = (
                f"Analysis Scope - Trigger {flash_count}/{EPOCH_CONFIG['flashes_per_session']} "
                f"| Acc {flash_count_accepted} Rej {rejected} "
                f"| {session_number}/{EPOCH_CONFIG['num_sessions']}"
            )
        else:
            title = (
                f"Analysis Scope - Trigger {flash_count}/{EPOCH_CONFIG['flashes_per_session']} "
                f"| {session_number}/{EPOCH_CONFIG['num_sessions']}"
            )
        # Append the double-click hint to the title regardless of which branch was taken.
        hint = _SCOPE_HINT_FOCUSED if self._scope_focused else _SCOPE_HINT_NORMAL
        self.plot_scope.setTitle(title + hint)

    def clear_scope_panel(self):
        for curve in self.scope_overlay_curves:
            self.plot_scope.removeItem(curve)
        self.scope_overlay_curves = []
        self.scope_avg_curve.setData([], [])

    def update_wavelet_panel(self, power: np.ndarray, freqs: np.ndarray, epoch_time_ms: np.ndarray, session_number: int) -> None:
        display_power = np.asarray(power, dtype=float)
        power_max = float(np.max(display_power)) if display_power.size else 0.0
        if power_max > 0:
            display_power = display_power / power_max
        self.wavelet_image.setImage(display_power.T, autoLevels=True)
        x0 = float(epoch_time_ms[0])
        y0 = float(freqs[0])
        dx = float(epoch_time_ms[-1] - epoch_time_ms[0]) / max(1, power.shape[1] - 1)
        dy = float(freqs[-1] - freqs[0]) / max(1, power.shape[0] - 1)
        tr = QTransform()
        tr.translate(x0, y0)
        tr.scale(dx, dy)
        self.wavelet_image.setTransform(tr)
        self.plot_wavelet.setTitle("Wavelet Scalogram - (All Analysis Blocks)")

    def update_wavelet_stats(self, peak_freq: float, peak_latency_ms: float, peak_power: float, session_number: int, ver_peaks=None) -> None:
        wavelet_text = f"M{session_number} — Wavelet peak: {peak_freq:.1f} Hz | {peak_latency_ms:.0f} ms | Power: {peak_power:.3e}"
        if ver_peaks:
            def fmt(p): return f"{p['latency_ms']:.0f} ms ({p['amplitude']:.4f})" if p.get('found') else "\u2014"
            # Transitional mapping: internal keys remain Peak-* for compatibility,
            # while user-visible labels use neutral Feature-* wording.
            peaks_text = (f"  |  Feature-1: {fmt(ver_peaks.get('Peak-1', {}))}  "
                          f"Feature-2: {fmt(ver_peaks.get('Peak-2', {}))}  "
                          f"Feature-3: {fmt(ver_peaks.get('Peak-3', {}))}")
            wavelet_text += peaks_text
        self.wavelet_stats_label.setText(wavelet_text)

    def _compute_offset_step(self, session_avg: np.ndarray) -> float:
        if self._offset_step is None:
            peak_to_peak = float(np.ptp(session_avg)) if len(session_avg) else 0.0
            if peak_to_peak > 0:
                self._offset_step = 2.5 * peak_to_peak
            else:
                self._offset_step = 1.0
        return self._offset_step

    def add_session_average(
        self,
        epoch_time_ms: np.ndarray,
        session_avg: np.ndarray,
        session_number: int,
        session_label: str | None = None,
        ver_peaks: Optional[dict] = None,
    ) -> None:
        offset_step = self._compute_offset_step(session_avg)
        offset = (EPOCH_CONFIG["num_sessions"] - session_number) * offset_step
        color = self.session_colors[(session_number - 1) % len(self.session_colors)]
        short_label = f"{session_number}"
        label_text = session_label or short_label

        ref_line = pg.InfiniteLine(
            pos=offset,
            angle=0,
            pen=pg.mkPen((80, 80, 80), style=Qt.PenStyle.DashLine),
        )
        self.plot_sessions.addItem(ref_line)
        self.plot_sessions.plot(
            epoch_time_ms,
            session_avg + offset,
            pen=pg.mkPen(color, width=2),
        )
        if ver_peaks:
            peak_styles = {
                "Peak-1": {"color": "#4488FF"},
                "Peak-2": {"color": "#FF4444"},
                "Peak-3": {"color": "#44FF88"},
            }
            for peak_name, style in peak_styles.items():
                peak = ver_peaks.get(peak_name)
                if peak and peak.get("found"):
                    marker_x = float(peak["latency_ms"])
                    marker_y = float(peak["amplitude"]) + offset
                    if math.isnan(marker_x) or math.isnan(marker_y):
                        continue
                    symbol = 't' if peak["amplitude"] >= 0 else 't1'
                    if peak.get("above_threshold", False):
                        brush = pg.mkBrush(style["color"])
                        pen = pg.mkPen(None)
                    else:
                        brush = pg.mkBrush(None)
                        pen = pg.mkPen("#888888", width=1)
                    scatter = pg.ScatterPlotItem(
                        x=[marker_x],
                        y=[marker_y],
                        symbol=symbol,
                        size=10,
                        brush=brush,
                        pen=pen,
                    )
                    self.plot_sessions.addItem(scatter)
            if not ver_peaks.get("VER_detected", False):
                no_ver_text = pg.TextItem("No response", color="#888888", anchor=(0.0, 0.5))
                no_ver_text.setPos(5.0, offset)
                self.plot_sessions.addItem(no_ver_text)
        text = pg.TextItem(label_text, color=color, anchor=(1, 0.5))
        text.setPos(float(epoch_time_ms[0]) - 5.0, offset)
        self.plot_sessions.addItem(text)

        self._session_ticks.append((offset, short_label))
        self.plot_sessions.getAxis("left").setTicks([sorted(self._session_ticks, key=lambda tick: tick[0])])

        shifted = session_avg + offset
        session_min = float(np.min(shifted))
        session_max = float(np.max(shifted))
        self._sessions_y_min = session_min if self._sessions_y_min is None else min(self._sessions_y_min, session_min)
        self._sessions_y_max = session_max if self._sessions_y_max is None else max(self._sessions_y_max, session_max)
        margin = offset_step * 0.6
        self.plot_sessions.setYRange(self._sessions_y_min - margin, self._sessions_y_max + margin, padding=0)

    def reset_all(self):
        # Restore normal layout if the raw panel was enlarged.
        if self._raw_focused:
            self.toggle_raw_focus()
        # Restore normal layout if the scope panel was enlarged.
        if self._scope_focused:
            self.toggle_scope_focus()
        self._offset_step = None
        self.raw_buffer.clear()
        self.filtered_buffer.clear()
        self.time_buffer.clear()
        self.flash_times.clear()
        self.sample_index = 0
        self._last_scroll_draw = 0.0
        self.curve_raw.setData([], [])
        self.curve_filtered.setData([], [])
        self.flash_scatter.setData(x=[], y=[])
        self.clear_scope_panel()
        self.wavelet_image.setImage(np.zeros((2, 2)))
        self.wavelet_stats_label.setText("Peak: — Hz | — ms | Power: —")
        self._reset_sessions_panel()
        self.plot_raw.setXRange(0, self.scroll_seconds, padding=0)
        #self.plot_raw.setYRange(-1, 1, padding=0)
        self.plot_raw.enableAutoRange(y=True)
        self.plot_scope.setXRange(-EPOCH_CONFIG["pre_stim_ms"], EPOCH_CONFIG["post_stim_ms"], padding=0)
        self.plot_scope.enableAutoRange('y', True)
        self.plot_scope.setTitle(_SCOPE_TITLE_NORMAL)
        self.plot_wavelet.setXRange(-EPOCH_CONFIG["pre_stim_ms"], EPOCH_CONFIG["post_stim_ms"], padding=0)
        self.plot_wavelet.enableAutoRange(y=True)
        
