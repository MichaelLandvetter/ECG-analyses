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
| `ver_main.py` | Main UI window, all tab and workflow orchestration | Window title updated to ECG; About text updated; the classifier tab is now marked transitional. Internal VER naming (`session_ver_peaks`, `detect_ver_peaks`) should be refactored in a later pass. |
| `ver_display.py` | Live scrolling signal display + epoch overlay + wavelet panel | Plot title "VER Evolution" updated to "Signal Evolution". "No VER" overlay text updated to "No response". Raw/Scope panel wording now uses neutral signal/trigger terminology. Class name `VERDisplayWidget` can be renamed later. |
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
7. **`ver_report.py`** — plot title `"VER Evolution"` → `"Signal Evolution"` and
   statistics page title updated to `"ECG Transition — Peak Statistics"`.
8. **`ver_ml_logger.py`** — human validation dialog now uses neutral
   `"Response"` / `"No response"` wording in the review table.
9. **`ver_USB_test.py`** — standalone diagnostic window updated from EEG-only
   wording to neutral signal/trigger wording.

---

## What was changed in the second pass (VER workflow placeholder PR)

The following **minimal** changes replaced the most user-visible VER-specific
workflow elements with ECG-oriented or neutral placeholders:

- Tab names, graph titles, validation prompts, and progress text updated.
- Classifier tab labelled `"Signal Classifier Settings (Transitional)"`.
- Main analysis tab labelled `"Analysis View"` instead of VER-specific name.
- Group labels use neutral signal/trigger wording.
- See PR #2 for the full list of items changed and items intentionally left.

---

## What was changed in the third pass (VER analysis engine isolation PR)

The following **minimal structural improvements** were made to isolate the
inherited VER-specific analysis engine and improve module-by-module
replaceability, without changing any analysis logic or scientific behavior:

1. **`ver_analysis_engine.py` created (NEW)** — Thin adapter/facade module
   that is now the **single import boundary** between generic application
   orchestration and the inherited VER analysis functions.  It re-exports:
   - `detect_ver_peaks` from `ver_peaks.py` (REPLACEMENT TARGET 2)
   - `evaluate_ver_peak` from `ver_classifier.py` (REPLACEMENT TARGET 3)
   - `save_ver_report` from `ver_report.py` (REPLACEMENT TARGET 4)
   - `refresh_classifier_cfg` — propagates settings to both analysis modules
   
   **How to use this boundary for ECG replacement:**  implement the ECG
   analysis modules, update the imports *inside `ver_analysis_engine.py`*,
   and no other changes to `ver_main.py` are needed for those three modules.

2. **`ver_main.py` imports regrouped** — The scattered VER analysis imports
   (`import ver_classifier`, `import ver_peaks`, `from ver_peaks import …`,
   `from ver_report import …`) are replaced by a single clearly-commented
   import block from `ver_analysis_engine`.  A comment on `VERScopeProcessor`
   marks it as REPLACEMENT TARGET 1.  Call sites in `_record_session` and
   `save_report` are commented to identify them as VER engine call sites.

3. **`ver_scope.py` docstring enhanced** — Module-level docstring now lists:
   - all VER-specific logic (trigger model, flash-count sessions, epoch window)
   - both callers that must be updated together during replacement
   - the result-dict interface contract that must be preserved or updated
   - generic pieces (ring buffer, artifact rejection, averaging) worth keeping

4. **`ver_peaks.py` docstring enhanced** — Marks the module as REPLACEMENT
   TARGET 2, lists VER-specific logic (P1/P2/P3 model, 0–200 ms window,
   `VER_detected` flag), and specifies the ECG replacement output schema.

5. **`ver_classifier.py` docstring enhanced** — Marks the module as
   REPLACEMENT TARGET 3, lists VER-specific criteria (P2 latency gates,
   inter-peak intervals), and notes the coordinated replacement trio.

---

## What was changed in the fourth pass (first module placeholder boundary PR)

This pass performs a **single-module transition boundary** for the highest
priority inherited module:

1. **Chosen first replacement target: `ver_scope.py`**
   - strongest domain mismatch (flash-locked trigger model vs ECG beats)
   - highest user-facing confusion if left direct (scope/epochs drive all
     downstream analysis)
   - safest first boundary because only `ver_main.py` and `ver_preflight.py`
     imported it directly

2. **`ecg_scope.py` created (NEW)** — ECG-oriented placeholder interface
   exposing `ECGScopeProcessor`, currently delegating to inherited
   `VERScopeProcessor` to keep behavior stable and app runnable.

3. **Callers switched to ECG boundary** — `ver_main.py` and `ver_preflight.py`
   now import `ECGScopeProcessor` from `ecg_scope.py`, reducing direct caller
   coupling to `ver_scope.py`.

4. **Inherited behavior intentionally retained behind the boundary**
   - trigger model, flash-count sessions, and epoch extraction still come from
     `ver_scope.py` for now
   - future ECG implementation should replace delegation inside `ecg_scope.py`
     with beat-locked ECG logic while preserving (or explicitly migrating)
     the current result-dict contract

**Recommended next replacement target after this pass:**
`ver_peaks.py` (via `ver_analysis_engine.py`), followed by coordinated
classifier/report schema updates.

---

## What was changed in the fifth pass (report/classifier workflow boundary PR)

This pass establishes **ECG-named placeholder boundaries** for the inherited
VER classifier and report generator, reducing direct caller dependence on
``ver_classifier.py`` and ``ver_report.py`` without changing any analysis logic.

### Workflow target chosen
Both the classifier and report workflows were addressed together because they
are tightly linked: the report directly calls the classifier to produce per-block
labels.  Establishing both boundaries in the same pass prevents the callers from
being left straddling mixed VER/ECG naming.

### New ECG-oriented placeholder modules

1. **`ecg_classifier.py` created (NEW)** — ECG-named boundary for the
   inherited VER classifier.  Exposes `classify_ecg_signal()` with neutral
   parameter names (`feature1_latency`, `feature2_latency`, etc.) and a
   neutral return tuple `(is_detected, check_details)` instead of
   `(is_ver, failure_details)`.  Delegates entirely to inherited
   `evaluate_ver_peak` from `ver_classifier.py`; the VER-tuned gate logic
   and VER-labelled `check_details` keys remain unchanged underneath.

2. **`ecg_report.py` created (NEW)** — ECG-named boundary for the inherited
   VER report generator.  Exposes `save_ecg_report()` with the same
   parameters as `save_ver_report()`.  Delegates entirely to inherited
   `ver_report.save_ver_report`; PDF layout, CSV column headers
   (`VER_label`), and plot wording remain unchanged underneath.

### Updated callers

3. **`ver_analysis_engine.py` updated** — The adapter now imports from
   `ecg_classifier` and `ecg_report` instead of from the `ver_*` modules
   directly.  The ECG-named functions (`classify_ecg_signal`,
   `save_ecg_report`) are now the primary exports.  Backward-compat aliases
   (`evaluate_ver_peak = classify_ecg_signal`,
   `save_ver_report = save_ecg_report`) are retained temporarily for any
   remaining references and should be removed once all callers are updated.

4. **`ver_ml_logger.py` updated** — The direct `from ver_classifier import
   evaluate_ver_peak` is replaced by `from ecg_classifier import
   classify_ecg_signal`.  The call site uses `is_detected` /
   `check_details` variable names instead of `is_ver` / `failure_details`.

5. **`ver_report.py` updated** — The internal `from ver_classifier import
   evaluate_ver_peak` is replaced by `from ecg_classifier import
   classify_ecg_signal`.  Both internal call sites use `is_detected` /
   `check_details` variable names.  The CSV output column `VER_label` and
   inherited report structure are unchanged (still inherited VER behavior).

6. **`ver_main.py` updated** — The import `save_ver_report` from
   `ver_analysis_engine` is replaced by `save_ecg_report`.  Both call
   sites in `save_report()` now reference `save_ecg_report`.

### Inherited behavior still remaining temporarily

- All classification logic (SNR gates, latency windows, scale/power checks)
  still comes from `ver_classifier.py` via delegation.
- PDF figure layout, CSV column headers (`VER_label`, `N_flashes_total`,
  `N_flashes_accepted`), and waveform table structure are still VER-domain
  output from `ver_report.py`.
- `check_details` key names (`"Scale Range"`, `"Minimum Power"`,
  `"P2 Latency"`, `"Peak Structure"`, `"SNR"`) are still VER labels
  produced by the inherited logic.
- `session_ver_peaks` variable naming in `ver_main.py` and related
  orchestration code is unchanged.

**Recommended next replacement target after this pass:**
`ver_peaks.py` (via `ver_analysis_engine.py`), followed by coordinated
replacement of the classification/report logic inside `ecg_classifier.py`
and `ecg_report.py` once the peak output schema is defined.

---

## What was produced in the sixth pass (first ECG analysis planning pass)

This pass produces the first real ECG-specific requirements and module plan.
No analysis logic is implemented here; the deliverable is a design document
that answers what the ECG pipeline should do, how it should be structured, and
in what order it should be built.

1. **`ecg_analysis_plan.md` created (NEW)** — Comprehensive ECG-oriented design
   document covering:
   - Executive summary of the transition so far
   - First ECG analysis scope (R-peak detection, HR/RR metrics, beat CSV export)
   - Target ECG user workflow and how it differs from the inherited VER flow
   - ECG-specific module boundaries for `ecg_scope.py`, `ecg_peaks.py`,
     `ecg_metrics.py`, `ecg_classifier.py`, `ecg_report.py`, and `ver_display.py`
   - Reuse vs. replacement classification for every existing module
   - First outputs and data contracts (`ECGScopeResult`, `ECGPeaksResult`,
     `ECGMetrics`, `ECGReportData`, Phase 1 CSV columns)
   - Nine-step ordered implementation roadmap tied to actual file names and
     import chains
   - Key risks and open questions with mitigations

**Recommended next step after this pass:**
Implement Steps B and C from `ecg_analysis_plan.md`: create `ecg_metrics.py`
and `ecg_peaks.py` as the first real ECG-specific code, then follow with the
`ecg_scope.py` R-peak trigger replacement (Step D).

---

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
- `session_ver_peaks` variable names in `ver_main.py` — internal state names;
  refactor together with `ver_peaks.py` replacement.
- Peak-1 / Peak-2 / Peak-3 labels and fish `SPECIES` metadata — still inherited
  placeholders and should be replaced when the ECG scope/peak model is defined.

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
