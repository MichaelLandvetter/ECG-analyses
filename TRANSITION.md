# Transition Status — ECG-analyses

This document records the first-pass transition assessment performed after
copying the [VER-analyses](https://github.com/MichaelLandvetter/VER-analyses)
codebase into this ECG-oriented repository.

> **See also:** [`docs/ecg-transition-priorities.md`](docs/ecg-transition-priorities.md)
> for the full ranked replacement list, safe sequencing roadmap, and
> architectural risk analysis produced in the second planning pass.

---

## Module-by-module classification

### ✅ Likely reusable for ECG as-is

| Module | Role | Notes |
|--------|------|-------|
| `ver_acquisition.py` | File replay + USB serial streaming | Entirely generic I/O. No VER-specific logic. Rename prefix later. |
| `ver_filter.py` | Bandpass filter (Butterworth / FIR / Savitzky-Golay) | Generic DSP utility. Reusable unchanged. |
| `ver_settings.py` | JSON-based settings persistence | Generic key-value store. Reusable unchanged. |
| `ver_logging.py` | Rotating-file logging setup | Generic. Home folder path updated to `~/.ecg_analyses`. |
| `ver_constants.py` | Filter mode string constants | Generic. No VER-specific logic. |
| `ver_analysis_flow.py` | End-of-analysis action routing helpers | Generic control flow. Reusable unchanged. |
| `ver_downsample.py` | LabChart file downsample utility | Generic file tool. Reusable unchanged. |
| `ver_wavelet.py` | Morlet wavelet scalogram computation | Generic DSP. Useful for ECG frequency analysis. |
| `ver_USB_test.py` | Standalone USB/serial diagnostic GUI | Generic hardware test. Reusable unchanged. |
| `Assets/` | Icons and splash images | Visual assets — update/replace progressively. |

---

### 🔧 Reusable with moderate refactoring

| Module | Role | What needs changing |
|--------|------|---------------------|
| `ver_main.py` | Main UI window, all tab and workflow orchestration | Window title updated to ECG; About text updated. Internal VER naming (`session_ver_peaks`, `detect_ver_peaks`, tab label "VER Classifier Settings") should be refactored in a later pass. |
| `ver_display.py` | Live scrolling signal display + epoch overlay + wavelet panel | Plot title "VER Evolution" updated to "Signal Evolution". "No VER" overlay text updated to "No response". Class name `VERDisplayWidget` can be renamed later. |
| `ver_config.py` | Application-wide configuration dictionaries | Docstring updated. `SPECIES` list is fish-specific — should be replaced or removed for ECG. `EPOCH_CONFIG` flash-count keys remain as inherited placeholders. |
| `ver_preflight.py` | Whole-file artifact threshold suggestion | Logic is generic. Imports `VERScopeProcessor` — will follow when scope is replaced. |

---

### ⚠️ VER-specific — likely to be replaced

| Module | Role | Why VER-specific |
|--------|------|-----------------|
| `ver_scope.py` | Trigger detection, epoch extraction, and session averaging | Designed around flash-locked epochs. ECG needs R-peak detection or arrhythmia-triggered epochs. |
| `ver_peaks.py` | Time-domain VER peak detection (P1, P2, P3 morphology) | Peak model is entirely VER-specific. ECG P/Q/R/S/T detection is fundamentally different. |
| `ver_classifier.py` | VER classifier (SNR, latency, power gates) | Decision logic tuned to VER pass/fail criteria. ECG classification logic TBD. |
| `ver_report.py` | PDF + CSV report generation | Wording, CSV column headers (`VER_label`, `VER?`), and plot titles are VER-specific. |
| `ver_ml_logger.py` | Human-in-the-loop ML training data collector | Schema targets VER labels. Column names, default reasons, and dialog wording are VER-specific. |

---

## What was changed in this first pass

The following **minimal** changes were made to present the repository as
ECG-oriented without breaking the inherited application:

1. **README.md created** — explains repo origin, transition status, and module overview.
2. **TRANSITION.md created** (this file) — records assessment and roadmap.
3. **`ver_main.py`**
   - Window title: `"VER Analysis"` → `"ECG Analysis"`
   - About dialog title and text updated to reference ECG.
   - Startup log message updated to `"ECG Analysis application starting"`.
   - Module docstring updated.
4. **`ver_config.py`** — module docstring updated from VER to ECG.
5. **`ver_logging.py`** — home-folder fallback path updated from
   `~/.ver_analyses/logs/` to `~/.ecg_analyses/logs/`.
6. **`ver_display.py`** — plot title `"VER Evolution"` → `"Signal Evolution"`;
   overlay text `"No VER"` → `"No response"`.
7. **`ver_report.py`** — plot title `"VER Evolution"` → `"Signal Evolution"`.

## What was intentionally left unchanged

- All module file names (`ver_*.py`) — renaming would break all imports and is
  a moderate risk change. Schedule as a dedicated rename pass.
- All class names (`VERMainWindow`, `VERDisplayWidget`, `VERScopeProcessor`) —
  same rationale.
- All analysis logic in `ver_scope.py`, `ver_peaks.py`, `ver_classifier.py` —
  these need ECG replacements, not renames.
- Report CSV column names and PDF wording — tied to analysis logic; replace
  together with the analysis modules.
- `SPECIES` list in `ver_config.py` — fish-specific content, but removing it
  now would break the existing UI dropdown. Schedule for replacement with
  ECG-relevant metadata fields (patient ID, lead configuration, etc.).
- "VER Classifier Settings" tab label — low risk but tied to the classifier
  module; rename when the classifier is replaced.
- `session_ver_peaks` variable names in `ver_main.py` — internal state names;
  refactor together with `ver_peaks.py` replacement.

---

## Recommended roadmap

### Phase 2 — ECG trigger and epoch model (highest priority)

Replace `ver_scope.py` with an ECG-specific epoch processor:
- R-peak detection as the primary trigger (e.g. Pan-Tompkins algorithm)
- Heart-rate based session/block structure instead of flash-count
- HRV or ST-segment epoch windows instead of pre/post-stimulus windows

**Risk:** `ver_scope.py` is used in `ver_main.py`, `ver_preflight.py`, and
`ver_report.py`. Replacement requires coordinated updates to all three.

---

### Phase 3 — ECG peak detection and classifier

Replace `ver_peaks.py` and `ver_classifier.py`:
- ECG morphology detection (P, Q, R, S, T waves)
- QRS duration, PR interval, QT interval measurements
- Arrhythmia classification logic

**Risk:** `ver_peaks.py` and `ver_classifier.py` are called from `ver_main.py`,
`ver_report.py`, and `ver_ml_logger.py`. Replace as a coordinated set.

---

### Phase 4 — Report and ML schema

Update `ver_report.py` and `ver_ml_logger.py`:
- Replace VER CSV headers with ECG metrics (RR interval, QRS width, etc.)
- Update PDF plot titles and axis labels
- Revise human validation dialog labels

**Risk:** Low; these modules are mostly output-only and do not affect core
signal processing.

---

### Phase 5 — Module rename pass

When ECG replacements are stable, rename `ver_*.py` → `ecg_*.py` and update
all imports in a single coordinated commit. Use a find-and-replace tool to
minimise mistakes.

**Risk:** Medium (many files touch the `ver_` prefix). Defer until logic is
stable to avoid renaming a moving target.

---

### Phase 6 — Config and species cleanup

- Replace `SPECIES` fish list with ECG-relevant patient/lead metadata.
- Update `EPOCH_CONFIG` key names (`flashes_per_session` → `beats_per_block`
  etc.) once the epoch model is replaced.

---

## Coupling risks identified

| Risk | Detail |
|------|--------|
| `ver_scope.py` is central | `ver_main.py`, `ver_preflight.py` both import `VERScopeProcessor` directly. Any replacement must provide the same interface or both callers must be updated together. |
| Peak/classifier co-dependency | `ver_peaks.py` and `ver_classifier.py` are tightly coupled; `ver_ml_logger.py` calls `evaluate_ver_peak` directly. Replace the pair together. |
| Report depends on peak output | `ver_report.py` consumes the `session_ver_peaks` data structure produced by `ver_peaks.py`. Changing the peak format will break the report. |
| Settings schema | `user_settings.json` keys mirror Python config dict names. Renaming keys is a breaking change for existing users with saved settings. |
