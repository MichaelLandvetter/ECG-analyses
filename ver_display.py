"""PyQtGraph display components for live ECG signal visualization.

ECG layout (step 9 migration)
-------------------------------
Graph 1 (top):    Raw ECG + Filtered ECG scrolling view.
Graph 2 (bottom): Heart-rate tachometer — R-peak interval view (placeholder;
                  will show live BPM once ECG R-peak detection is implemented).

Legacy notes
------------
- Class name ``VERDisplayWidget`` is kept during the naming-transition phase.
  Rename to ``ECGDisplayWidget`` in a subsequent cleanup pass.
- The ``update_scope_panel``, ``clear_scope_panel``, ``update_wavelet_panel``,
  ``update_wavelet_stats``, and ``add_session_average`` methods are preserved as
  no-op stubs so callers in ``ver_main.py`` do not crash during the transition.
  They can be removed once those call sites are updated for the ECG path.
- See ``docs/module_migration_status.md`` for the full lifecycle plan.
"""

from __future__ import annotations

from collections import deque
import time


import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ver_config import ACQ_CONFIG, DISPLAY_CONFIG, EPOCH_CONFIG

# Qt's QWIDGETSIZE_MAX (16 777 215) used to effectively remove size constraints
# from QGraphicsGridLayout rows when restoring the normal layout.
_LAYOUT_UNCONSTRAINED = 16_777_215.0

# History depth for R-peak and HR deque buffers.
_MAX_PEAK_HISTORY = 500

# Physiological sanity bounds for instantaneous RR-interval → BPM conversion.
# RR < 0.2 s → HR > 300 BPM (artefact / double detection).
# RR > 3.0 s → HR < 20 BPM (missed beat / asystole boundary).
_MIN_RR_INTERVAL_S = 0.2
_MAX_RR_INTERVAL_S = 3.0

_RAW_TITLE_NORMAL = "Raw ECG + Filtered ECG  \u00b7 double-click to enlarge"
_RAW_TITLE_FOCUSED = "Raw ECG + Filtered ECG  \u00b7 double-click to restore"
_TACHO_TITLE = "Heart Rate — R-peak tachometer (placeholder)"


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
        self.r_peak_times: deque = deque(maxlen=_MAX_PEAK_HISTORY)  # R-peak timestamps (s)
        # rr_times / rr_bpm: bounded to the same history depth as r_peak_times so
        # they do not grow unboundedly during long recordings.
        self.rr_times: deque = deque(maxlen=_MAX_PEAK_HISTORY)      # timestamps for HR curve
        self.rr_bpm: deque = deque(maxlen=_MAX_PEAK_HISTORY)        # instantaneous BPM values
        self._last_peak_time: float | None = None
        self.sample_index = 0
        self._last_scroll_draw = 0.0
        self._scroll_min_interval = 1.0 / max(1, DISPLAY_CONFIG.get("scroll_max_fps", 30))
        self._raw_focused = False
        # Legacy flag kept so inherited call-sites in ver_main.py do not crash.
        self._scope_focused = False

        layout = QVBoxLayout(self)
        self.status_label = QLabel("No data loaded")
        layout.addWidget(self.status_label)
        self.status_label.hide()

        self.graphics = pg.GraphicsLayoutWidget()
        layout.addWidget(self.graphics)

        self._init_panels()

    def _init_panels(self):
        # --- Panel 1 (row 0): Raw ECG + Filtered ECG scrolling view ---
        _vb = _FocusableViewBox()
        _vb.sigDoubleClicked.connect(self.toggle_raw_focus)
        self.plot_raw = self.graphics.addPlot(row=0, col=0, viewBox=_vb, title=_RAW_TITLE_NORMAL)
        self.plot_raw.getViewBox().setMouseEnabled(x=False, y=True)
        self.plot_raw.showGrid(x=True, y=True, alpha=0.3)
        self.plot_raw.setLabel("bottom", "Time", "s")
        self.plot_raw.setLabel("left", "Amplitude")
        self.plot_raw.setXRange(0, DISPLAY_CONFIG["scroll_seconds"], padding=0)
        self.plot_raw.enableAutoRange(y=True)
        self.curve_raw = self.plot_raw.plot(pen=pg.mkPen((170, 170, 170), width=1), autoDownsample=True)
        self.curve_filtered = self.plot_raw.plot(pen=pg.mkPen((0, 220, 120), width=1.5), autoDownsample=True)
        # R-peak markers (populated once R-peak detection is added)
        self.r_peak_scatter = pg.ScatterPlotItem(
            size=8, brush=pg.mkBrush(255, 80, 80, 200), pen=pg.mkPen(None)
        )
        self.plot_raw.addItem(self.r_peak_scatter)
        # Backward-compat alias: inherited code in ver_main.py / _handle_single_sample
        # passes trigger events as `trigger_detected`; the scatter will show them until
        # dedicated R-peak detection replaces the trigger-based path.
        self.flash_scatter = self.r_peak_scatter

        # --- Panel 2 (row 1): Heart-rate tachometer from R-peak intervals ---
        self.plot_tachometer = self.graphics.addPlot(row=1, col=0, title=_TACHO_TITLE)
        self.plot_tachometer.getViewBox().setMouseEnabled(x=False, y=True)
        self.plot_tachometer.showGrid(x=True, y=True, alpha=0.3)
        self.plot_tachometer.setLabel("bottom", "Time", "s")
        self.plot_tachometer.setLabel("left", "Heart Rate", "bpm")
        self.plot_tachometer.enableAutoRange(y=True)
        self.curve_hr = self.plot_tachometer.plot(
            pen=pg.mkPen((255, 165, 0), width=2), symbol="o",
            symbolSize=5, symbolBrush=pg.mkBrush(255, 165, 0, 180), symbolPen=pg.mkPen(None),
        )

        # Equal row stretch so both panels share vertical space.
        self.graphics.ci.layout.setRowStretchFactor(0, 1)
        self.graphics.ci.layout.setRowStretchFactor(1, 1)

    def set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def toggle_raw_focus(self) -> None:
        """Toggle the Raw ECG panel between enlarged and shared view.

        Double-click the panel to expand it (hiding the tachometer); double-click
        again to restore the two-panel layout.
        """
        self._raw_focused = not self._raw_focused
        layout = self.graphics.ci.layout

        if self._raw_focused:
            layout.setRowMaximumHeight(1, 0)
            self.plot_tachometer.hide()
            self.plot_raw.setTitle(_RAW_TITLE_FOCUSED)
        else:
            layout.setRowMaximumHeight(1, _LAYOUT_UNCONSTRAINED)
            self.plot_tachometer.show()
            self.plot_raw.setTitle(_RAW_TITLE_NORMAL)

    def toggle_scope_focus(self) -> None:
        """No-op stub — Scope View has been removed from the ECG layout.

        Kept so inherited call-sites in ``ver_main.py`` do not raise
        ``AttributeError`` during the transition.
        """

    def update_scroll_panel(self, raw_sample: float, filtered_sample: float, trigger_detected: bool) -> None:
        t = self.sample_index / self.sample_rate
        self.sample_index += 1

        self.time_buffer.append(t)
        self.raw_buffer.append(float(raw_sample))
        self.filtered_buffer.append(float(filtered_sample))

        if trigger_detected:
            # Record R-peak time and compute instantaneous HR from RR interval.
            self.r_peak_times.append(t)
            if self._last_peak_time is not None:
                rr_s = t - self._last_peak_time
                # Physiological sanity range: RR 0.2–3.0 s → 20–300 BPM.
                # Values outside this window are treated as missed/double detections.
                if _MIN_RR_INTERVAL_S < rr_s < _MAX_RR_INTERVAL_S:
                    bpm = 60.0 / rr_s
                    self.rr_times.append(t)
                    self.rr_bpm.append(bpm)
            self._last_peak_time = t

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

        # Draw R-peak (or trigger) markers on the raw panel
        if self.r_peak_times:
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
            visible = [pt for pt in self.r_peak_times if x[0] <= pt <= x[-1]]
            if visible:
                fx = np.array(visible, dtype=float)
                fy = np.full(len(visible), y_dot, dtype=float)
                self.r_peak_scatter.setData(x=fx, y=fy)
            else:
                self.r_peak_scatter.setData(x=[], y=[])

        # Draw HR tachometer
        if self.rr_times:
            visible_rr = [(t_, b) for t_, b in zip(self.rr_times, self.rr_bpm) if x[0] <= t_ <= x[-1]]
            if visible_rr:
                tx, bx = zip(*visible_rr)
                self.curve_hr.setData(np.array(tx), np.array(bx))
            else:
                self.curve_hr.setData([], [])

    # ------------------------------------------------------------------
    # No-op stubs for removed VER panels
    # These are preserved so call-sites in ver_main.py / _handle_single_sample
    # and _record_session do not raise AttributeError during the transition.
    # Remove these stubs once the call-sites are updated for the ECG path.
    # ------------------------------------------------------------------

    def update_scope_panel(self, *args, **kwargs) -> None:
        """No-op stub — Analysis Scope view removed from ECG layout."""

    def clear_scope_panel(self) -> None:
        """No-op stub — Analysis Scope view removed from ECG layout."""

    def update_wavelet_panel(self, *args, **kwargs) -> None:
        """No-op stub — Wavelet Scalogram removed from ECG layout."""

    def update_wavelet_stats(self, *args, **kwargs) -> None:
        """No-op stub — Wavelet Scalogram removed from ECG layout."""

    def add_session_average(self, *args, **kwargs) -> None:
        """No-op stub — Signal Evolution panel removed from ECG layout."""

    def reset_all(self):
        """Reset all display buffers and restore the default two-panel layout."""
        # Restore normal layout if the raw panel was enlarged.
        if self._raw_focused:
            self.toggle_raw_focus()
        self.raw_buffer.clear()
        self.filtered_buffer.clear()
        self.time_buffer.clear()
        self.r_peak_times.clear()
        self.rr_times.clear()
        self.rr_bpm.clear()
        self._last_peak_time = None
        self.sample_index = 0
        self._last_scroll_draw = 0.0
        self.curve_raw.setData([], [])
        self.curve_filtered.setData([], [])
        self.r_peak_scatter.setData(x=[], y=[])
        self.curve_hr.setData([], [])
        self.plot_raw.setXRange(0, self.scroll_seconds, padding=0)
        self.plot_raw.enableAutoRange(y=True)
        self.plot_tachometer.enableAutoRange(y=True)


