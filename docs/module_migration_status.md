# Module Migration Status — ECG-analyses

This document records the current lifecycle state of every module in the
repository following the **Step 9 identity + shell UI migration** (PR #9).

> **See also:** [`docs/ecg-transition-priorities.md`](ecg-transition-priorities.md)
> for the full ranked replacement sequence and architectural risk analysis.

---

## Legend

| Symbol | Meaning |
|--------|---------|
| ✅ **active_ecg_path** | Used in the active ECG workflow; keep and maintain. |
| 🔀 **transitional_wrapper** | Thin ECG-named wrapper over a VER implementation; replace when the underlying module is rewritten. |
| 🛑 **legacy_ver_candidate** | VER-specific logic; not in the active ECG UI path; candidate for removal once any transitive callers are updated. |
| 🔧 **active_with_cleanup** | In the active path but contains VER naming or concepts to clean up in a later pass. |

---

## Active ECG path modules

| Module | Role | Status |
|--------|------|--------|
| `ecg_main.py` | **Canonical entrypoint** — `python ecg_main.py` | ✅ active_ecg_path |
| `ecg_config.py` | ECG-oriented config subset (re-exports from `ver_config`) | ✅ active_ecg_path |
| `ecg_loader.py` | One-column plain `.txt` ECG file loader + streamer | ✅ active_ecg_path |
| `ecg_scope.py` | ECG-named scope-processor boundary (delegates to `ver_scope`) | 🔀 transitional_wrapper |
| `ver_main.py` | Main window + workflow orchestration | 🔧 active_with_cleanup |
| `ver_display.py` | Live ECG + HR tachometer display (2-panel ECG layout) | 🔧 active_with_cleanup |
| `ver_filter.py` | Bandpass filter (Butterworth / FIR / Savitzky-Golay) | ✅ active_ecg_path |
| `ver_acquisition.py` | USB serial streaming; ECG file path now via `ecg_loader.py` | 🔧 active_with_cleanup |
| `ver_settings.py` | JSON-based settings persistence | ✅ active_ecg_path |
| `ver_logging.py` | Rotating-file logging setup | ✅ active_ecg_path |
| `ver_analysis_flow.py` | End-of-analysis action routing helpers | ✅ active_ecg_path |
| `ver_preflight.py` | Whole-file artifact threshold suggestion | 🔧 active_with_cleanup |
| `ver_analysis_engine.py` | Analysis engine adapter (wraps `ver_peaks`, `ver_report`) | 🔀 transitional_wrapper |

---

## Transitional wrappers / shims

| Module | Wraps | Notes |
|--------|-------|-------|
| `ver_main.py` | Main window | Class name `VERMainWindow` → rename to `ECGMainWindow` in next pass |
| `ver_display.py` | Display widget | Class name `VERDisplayWidget` → rename to `ECGDisplayWidget`; `flash_scatter` alias for `r_peak_scatter` |
| `ecg_scope.py` | `ver_scope.VERScopeProcessor` | Replace body with ECG R-peak trigger logic |
| `ver_analysis_engine.py` | `ver_peaks`, `ver_report`, `ver_classifier` | Replace `detect_ver_peaks` with `detect_ecg_peaks` |

---

## Legacy VER modules — candidates for removal

These modules are **not** in the active ECG UI path.  They remain so that
transitional call-sites in `ver_main.py` do not crash during the migration.
Remove them once the corresponding call-sites are updated.

| Module | Role | Why legacy | Transitive callers |
|--------|------|------------|-------------------|
| `ver_scope.py` | Flash-locked epoch extraction + session averaging | Designed for VER trigger-based epochs; ECG needs R-peak detection | `ecg_scope.py` (delegation) |
| `ver_peaks.py` | VER peak detection (P1/P2/P3 morphology) | Peak model is VER-specific; ECG needs P/Q/R/S/T detection | `ver_analysis_engine.py` |
| `ver_classifier.py` | VER SNR/latency/power classifier | Decision logic tuned to VER pass/fail; ECG classification TBD | `ver_analysis_engine.py` |
| `ver_report.py` | PDF + CSV VER report generation | Column headers, labels, and wording are VER-specific | `ver_analysis_engine.py` |
| `ver_ml_logger.py` | Human-in-the-loop ML training data collector | Schema targets VER labels | `ver_main.py` (save_report) |
| `ver_wavelet.py` | Morlet wavelet scalogram computation | Called from `_record_session`; scalogram panel removed from UI | `ver_main.py` (_record_session), `ver_report.py` |
| `ver_constants.py` | Scope filter mode string constants | Scope/Analysis filter removed from ECG UI; kept via `ver_filter.py` dependency | `ver_filter.py` |
| `ver_USB_test.py` | Standalone USB/serial diagnostic GUI | Reached via lazy import only; not statically bundled by PyInstaller | `ver_main.py` (_launch_usb_test, lazy) |

### Deleted in this PR

| Module | Why deleted |
|--------|-------------|
| ~~`ver_preflight.py`~~ | Not imported by any module in the ECG path.  `_suggest_exclusion()` was removed from `ver_main.py` in an earlier cleanup PR. |
| ~~`ver_downsample.py`~~ | Not imported by any module.  "Downsample LabChart file" menu action was removed from the ECG UI path; only referenced in comments. |

> See [`docs/ver_cleanup_audit.md`](ver_cleanup_audit.md) for the full import-graph-based
> classification of all `ver_*.py` files.

---

## Entrypoint transition

| Entrypoint | Status | Notes |
|------------|--------|-------|
| `ecg_main.py` | ✅ **Canonical ECG entrypoint** | `python ecg_main.py` — owns startup orchestration (logging, QApplication, window creation, splash teardown) |
| `ver_main.py` | 🔧 Still the module containing `VERMainWindow` | `main()` is now a backward-compat shim delegating to `ecg_main.main()` |

---

## What changed in Step 9 (this PR)

### New files
- `ecg_main.py` — canonical ECG entrypoint
- `ecg_config.py` — ECG-oriented config subset
- `ecg_loader.py` — one-column ECG `.txt` file loader with validation
- `docs/module_migration_status.md` — this document

### `ver_main.py` changes
- **Box 2 "ECG Data File"**: removed species combo, file-format combo
  (SD-card/LabChart), and "Set Exclusion" button; now shows a single
  "Open ECG File" button; validates via `ECGFileLoader` before accepting
- **Box 3 "ECG Filter Settings"**: removed Scope/Analysis filter dropdown;
  kept bandpass low/high cut with apply button
- **Box 4 "Display Speed"**: renamed from "Speed and Analysis Scope";
  removed Triggers/Avg spin-box
- **Settings tab**: removed Wavelet Tuning rows (scalogram removed from UI)
- `_build_acquisition_source`: switched from `FileAcquisitionSimulator` to
  `ECGFileLoader` for the file-replay path
- `_save_user_settings`: removed wavelet and species save logic
- Stubs: `_on_format_changed`, `_set_current_format`, `_on_flash_count_changed`
  are now no-ops so downstream crashes are avoided

### `ver_display.py` changes
- **Layout**: replaced 4-panel VER layout (Signal Evolution, Raw+Filtered,
  Scope View, Wavelet Scalogram) with a **2-panel ECG layout**:
  - Panel 1 (top): Raw ECG + Filtered ECG scrolling view
  - Panel 2 (bottom): Heart Rate tachometer (R-peak interval, placeholder)
- HR tachometer updates automatically from RR intervals when triggers
  (or future R-peak detections) are emitted
- `r_peak_scatter` replaces VER trigger scatter; `flash_scatter` kept as
  backward-compat alias
- `update_scope_panel`, `clear_scope_panel`, `update_wavelet_panel`,
  `update_wavelet_stats`, `add_session_average` → no-op stubs (callers
  in `ver_main.py` will not crash)

---

## What changed in this canonical-launcher PR

### `ecg_main.py` — promoted to real canonical launcher
- Now contains the full `main()` function (startup orchestration).
- Imports `VERMainWindow` from `ver_main` directly.
- Owns `pyi_splash.close()` call for packaged builds.

### `ver_main.py` — demoted to module + shim
- Removed `pyi_splash` module-level import (now in `ecg_main.py`).
- `main()` function replaced with a backward-compat shim that calls `ecg_main.main()`.
- Updated module docstring to reflect new role.

### Deleted files
- `ver_preflight.py` — not imported anywhere in ECG path.
- `ver_downsample.py` — not imported anywhere; menu action already removed.

### New documentation
- `docs/ver_cleanup_audit.md` — full import-graph-based keep/remove classification
  for every `ver_*.py` file in the repository.

---

## Recommended next cleanup targets (after canonical-launcher PR)

1. **Replace `ecg_scope.py` body** with real ECG R-peak detection (e.g. Pan-Tompkins).
   This will make the tachometer and R-peak scatter live.
2. **Replace `ver_analysis_engine.py`** with `ecg_analysis_engine.py` exposing
   `detect_ecg_peaks` and ECG-oriented report generation.
3. **Rename `VERMainWindow` → `ECGMainWindow`** and `VERDisplayWidget` →
   `ECGDisplayWidget`; update all imports.
4. **Remove** `ver_scope.py`, `ver_peaks.py`, `ver_classifier.py` once
   transitive callers are updated.
5. **Remove** `ver_report.py`, `ver_ml_logger.py` once ECG-oriented report
   generation is in place.
6. **Remove** `ver_constants.py` (scope filter constants no longer used in UI).
7. **Remove** `ver_wavelet.py` once confirmed not needed for ECG path.
