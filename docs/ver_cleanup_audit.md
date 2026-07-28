# `ver_*.py` Cleanup Audit

> **Purpose:** Classify every `ver_*.py` file in the repository as
> *required by ECG runtime*, *shared utility candidate*, or
> *not referenced by ECG path (deletion candidate)*.
>
> **Basis:** Static import graph starting from `ecg_main.py`, cross-checked
> against all `import` / `from … import` statements in every reachable module.
> Dynamic imports are flagged explicitly.
>
> **Last updated:** 2026-07-28 — produced in the canonical-launcher PR.

---

## Legend

| Symbol | Meaning |
|--------|---------|
| ✅ **required** | Reachable from `ecg_main.py` import graph; must be kept for app to run. |
| 🔀 **transitional** | Required now but contains VER-domain logic scheduled for ECG replacement. |
| 🔧 **shared_utility** | Generic infrastructure; no VER domain logic; good rename/move candidate later. |
| ⚠️ **lazy_import** | Not statically reachable at module load time; reached via a `def`-level `import` statement. |
| 🗑️ **deletion_candidate** | Not imported by any module in the ECG path; safe to delete. |
| ❌ **deleted** | Removed in this PR. |

---

## Import graph root

```
ecg_main.py  ←  canonical ECG launcher (python ecg_main.py)
     │
     └── ver_main.VERMainWindow  (main window + workflow orchestration)
           ├── ecg_loader, ecg_pipeline, ecg_config, ecg_scope (ECG-named modules)
           └── ver_*.py modules  (see table below)
```

---

## Classification table

### Required by ECG runtime — static import chain

| Module | Status | Why required | Caller(s) |
|--------|--------|--------------|-----------|
| `ver_main.py` | ✅ **required** | Contains `VERMainWindow`; imported by `ecg_main.py` | `ecg_main.py` |
| `ver_acquisition.py` | 🔧 **shared_utility** | `FileAcquisitionSimulator`, `SerialAcquisitionSource` — generic file/serial I/O, no VER domain logic | `ver_main.py` |
| `ver_config.py` | 🔧 **shared_utility** | `ACQ_CONFIG`, `FILTER_CONFIG`, `SERIAL_CONFIG`, `EPOCH_CONFIG` — generic config dicts | `ver_main.py`, `ver_acquisition.py`, `ecg_config.py`, `ver_preflight.py` (removed) |
| `ver_display.py` | 🔀 **transitional** | `VERDisplayWidget`, `_FocusableViewBox` — 2-panel ECG live display; class name needs rename | `ver_main.py` |
| `ver_filter.py` | 🔧 **shared_utility** | `BandpassFilter` — generic Butterworth/FIR/SG bandpass; no VER domain logic | `ver_main.py` |
| `ver_constants.py` | 🔧 **shared_utility** | `DEFAULT_SCOPE_FILTER_MODE`, `SCOPE_FILTER_FIR`, `SCOPE_FILTER_SAVGOL` — generic string constants | `ver_filter.py` |
| `ver_logging.py` | 🔧 **shared_utility** | `setup_logging()` — rotating-file logger; already writes to `~/.ecg_analyses` | `ecg_main.py`, `ver_main.py` |
| `ver_settings.py` | 🔧 **shared_utility** | `SettingsManager` — generic JSON key-value settings persistence | `ver_main.py`, `ecg_config.py` |
| `ver_analysis_flow.py` | 🔧 **shared_utility** | `BACK_TO_ANALYSIS`, `PROCEED_TO_VALIDATION`, routing helpers — generic control flow | `ver_main.py` |
| `ver_analysis_engine.py` | 🔀 **transitional** | Thin adapter layer isolating VER analysis boundary from `ver_main.py` | `ver_main.py` |
| `ver_peaks.py` | 🔀 **transitional** | `detect_ver_peaks` — VER P1/P2/P3 peak detection (REPLACEMENT TARGET 2) | `ver_analysis_engine.py` |
| `ver_classifier.py` | 🔀 **transitional** | VER SNR/latency classifier (REPLACEMENT TARGET 3); boundary established via `ecg_classifier.py` | `ecg_classifier.py` |
| `ver_report.py` | 🔀 **transitional** | VER PDF + CSV report (REPLACEMENT TARGET 4); boundary established via `ecg_report.py` | `ecg_report.py`, `ver_analysis_engine.py` |
| `ver_wavelet.py` | 🔀 **transitional** | `compute_wavelet_scalogram` — Morlet wavelet; generic DSP but called from `_record_session` in `ver_main.py` and `ver_report.py` | `ver_main.py`, `ver_report.py` |
| `ver_ml_logger.py` | 🔀 **transitional** | `launch_ml_logger` / `HumanValidationDialog` — human-in-the-loop ML data collector; VER schema but imported at top of `ver_main.py` | `ver_main.py` |
| `ver_scope.py` | 🔀 **transitional** | `VERScopeProcessor` — flash-locked epoch processor (REPLACEMENT TARGET 1); boundary established via `ecg_scope.py` | `ecg_scope.py` |

### Reached via dynamic (lazy) import — still required

| Module | Status | Why required | Where imported |
|--------|--------|--------------|----------------|
| `ver_USB_test.py` | ⚠️ **lazy_import** | `WaveletAnalyzerGUI` launched from File → USB Test menu item; imported inside `_launch_usb_test()` method body | `ver_main.py:_launch_usb_test()` |

> **Dynamic import note:** `ver_USB_test.py` is not reachable by PyInstaller's
> static analyser.  If the packaged EXE needs the USB Test tool, add
> `ver_USB_test` to `hiddenimports` in `ecg.spec`.  If the USB Test menu item
> is removed in a future cleanup PR, this file becomes a deletion candidate.

### Deleted in this PR

| Module | Why deleted |
|--------|-------------|
| `ver_preflight.py` | Not imported by any module in the ECG path.  The `_suggest_exclusion()` method that called it was removed from `ver_main.py` in an earlier cleanup PR.  `ExclusionTuningDialog` in `ver_main.py` is a retained transitional artifact that is currently unreachable from the UI. |
| `ver_downsample.py` | Not imported by any module.  The "Downsample LabChart file" menu action was removed from the ECG UI path; `ver_downsample` is referenced only in comments in `ver_main.py`. |

---

## Summary: what can be removed next

In addition to the two files deleted in this PR, the following are candidates
for removal once their specific blockers are addressed:

1. **`ver_scope.py`** — Remove after `ecg_scope.py` body is replaced with real
   R-peak detection (see `docs/ecg-transition-priorities.md` Rank 1).
2. **`ver_peaks.py`** — Remove after `ecg_peaks.py` is implemented (Rank 2).
3. **`ver_classifier.py`** — Remove after `ecg_classifier.py` implements real
   ECG classification logic (Rank 3, coordinated with ver_peaks).
4. **`ver_report.py`** — Remove after `ecg_report.py` generates real ECG reports
   (Rank 5).
5. **`ver_ml_logger.py`** — Remove after the ECG validation schema and dialog
   are implemented (Rank 5, after classifier/report).
6. **`ver_wavelet.py`** — Remove once confirmed not used in ECG path (or after
   an ECG-oriented HRV / frequency analysis module replaces it).
7. **`ver_USB_test.py`** — Remove when the USB Test menu item is removed from
   the ECG application or replaced with an ECG-named diagnostic tool.
8. **`ver_constants.py`**, **`ver_filter.py`**, **`ver_acquisition.py`**,
   **`ver_settings.py`**, **`ver_logging.py`**, **`ver_analysis_flow.py`**,
   **`ver_config.py`** — These are generic utilities with no VER domain logic.
   Rename to `ecg_*.py` (or `core_*.py`) in the Phase 7 rename pass once all
   analysis logic replacements are complete.

---

## How to verify this audit

Run the following one-liner from the repository root to list all `import`
statements reachable from `ecg_main.py` via Python's static module graph:

```bash
python -c "
import sys, importlib
# trace imports starting from ecg_main
import ecg_main
for name in sorted(m for m in sys.modules if m.startswith('ver_')):
    print(name)
"
```

This will print every `ver_*` module that was imported (directly or
transitively) during loading of `ecg_main`.  Any `ver_*` file NOT in this list
that is also not reached via a lazy/dynamic import is a deletion candidate.
