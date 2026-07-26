# ECG Analysis Plan

> **Document type:** Design/planning  
> **Status:** First ECG-specific requirements and module plan  
> **Preceded by:** `TRANSITION.md` (passes 1–5) and `docs/ecg-transition-priorities.md`  
> **Purpose:** Define the first real ECG-specific analysis requirements, module
> boundaries, data contracts, and implementation sequence so future PRs can
> proceed against a concrete target.

---

## 1. Executive Summary

The repository has completed five transition passes that:

1. oriented the application toward ECG (branding, labels, docs),
2. isolated the highest-priority inherited VER analysis modules behind
   ECG-named placeholder boundaries (`ecg_scope.py`, `ecg_classifier.py`,
   `ecg_report.py`, `ver_analysis_engine.py`), and
3. documented the module-by-module replacement sequence.

The boundaries are in place. The next work is to fill them with real ECG logic.
This document answers: *what should the first ECG implementation actually do,
how should it be structured, and in what order should it be built?*

**Recommended first ECG scope** (smallest credible pipeline):

1. Load an ECG recording from a file **or** stream from USB
2. Apply ECG-standard bandpass filtering (0.5–40 Hz)
3. Detect R-peaks using a threshold-based QRS detector
4. Compute beat-level HR and RR-interval metrics
5. Display the filtered ECG trace with beat markers
6. Export a basic CSV report (beat timestamps, RR intervals, HR)

This scope avoids full P/Q/S/T morphology analysis (which can follow), while
establishing a genuine, clinically meaningful ECG pipeline end-to-end.

---

## 2. First ECG Analysis Scope

### 2.1 What to support first

| Feature | Rationale |
|---------|-----------|
| ECG file loading (text/CSV/LabChart) | `ver_acquisition.py` already handles this; zero new infrastructure needed |
| Live USB ECG streaming | `ver_acquisition.py` already handles serial input; no new work needed |
| Bandpass filtering (0.5–40 Hz) | `ver_filter.py` is generic; only the default frequency parameters change |
| R-peak (QRS) detection | First clinically meaningful ECG output; drives all downstream metrics |
| RR interval and heart rate | Derived directly from R-peak timestamps; very low implementation risk |
| Beat marker overlay on signal display | Extension of the existing `ver_display.py` signal trace; same render loop |
| Basic CSV export (beat list + HR summary) | Subset of the existing report infrastructure; straightforward to add |

### 2.2 What to defer

| Feature | Deferral rationale |
|---------|--------------------|
| P-wave / T-wave detection | Requires validated morphology detection; high algorithm complexity |
| QRS duration / PR / QT interval measurement | Depends on stable P/T detection; defer to the following PR |
| Arrhythmia classification | Requires robust beat-to-beat analysis; Phase 2 work |
| Full human-in-the-loop beat review | Extend the existing ML-logger workflow; Phase 2 |
| PDF report | Defer until ECG-specific metrics stabilise; CSV is sufficient for Phase 1 |

### 2.3 Why this scope is ECG-specific (not a VER rename)

| VER pipeline | ECG pipeline (Phase 1) |
|-------------|------------------------|
| External flash trigger fires epoch | R-peak in the signal itself is the trigger |
| Fixed pre/post-flash window (0–200 ms) | Beat-centred window around R-peak (~−150 to +350 ms) |
| P1/P2/P3 latency detection | R-peak amplitude + beat timestamp only (Phase 1) |
| Flash-count session structure | Beat-count or time-duration block structure |
| `VER_detected` pass/fail label | Beat detected / artefact flag |
| Species metadata | Lead configuration + patient/session ID |

---

## 3. Target ECG User Workflow

### 3.1 Step-by-step workflow (first ECG version)

```
1. Launch application
   └── Load data source
       ├── Open ECG file  (text/CSV/LabChart — uses ver_acquisition.py)
       └── Connect USB ECG device  (serial stream — uses ver_acquisition.py)

2. Configure signal
   ├── Set sampling rate (Hz)                    — already in settings
   ├── Set bandpass filter (default: 0.5–40 Hz)  — ver_filter.py, change default
   └── Set R-peak detection threshold             — new ECG config key

3. View incoming or loaded ECG trace
   └── Scrolling filtered signal display          — ver_display.py, existing

4. Run ECG analysis
   ├── Detect R-peaks in the signal               — ecg_scope.py (new logic)
   ├── Compute RR intervals and HR per beat       — ecg_metrics.py (new)
   └── Display beat markers on the signal trace   — ver_display.py extension

5. Review detected events
   ├── Inspect beat list (timestamp, RR, HR)      — simple table in existing UI
   └── Adjust detection threshold if needed       — settings dialog

6. Export results
   └── Save CSV: beat timestamps, RR intervals, HR summary
       └── ecg_report.py  (filled with ECG logic, not VER delegation)
```

### 3.2 Key differences from inherited VER workflow

| VER workflow | ECG workflow difference |
|-------------|------------------------|
| Flash counter drives session progress | Beat count or wall-clock duration drives block progress |
| Pre-stimulus baseline + post-stimulus epoch | Pre-R and post-R window (configurable; ~−150 to +350 ms) |
| Per-session averaged waveform is the primary output | Per-beat timestamps and RR intervals are the primary output |
| P1/P2/P3 detected within the averaged epoch | R-peak detected in the raw/filtered stream |
| VER pass/fail classification | Beat-detected / artefact classification |
| Species dropdown in file-load dialog | Lead configuration + session metadata |
| CSV: P1_Latency, P2_Latency, P3_Latency | CSV: beat_timestamp_ms, rr_interval_ms, hr_bpm |

---

## 4. ECG-Specific Module Boundaries

### 4.1 Module map

```
ver_acquisition.py  ──────────────────────────────┐
(reuse unchanged)                                  │ raw ECG samples
                                                   ▼
ver_filter.py  ───────────────────────────►  filtered ECG samples
(reuse; change default 0.5–40 Hz)                  │
                                                   ▼
ecg_scope.py  ◄────── REPLACEMENT TARGET 1  ── ECGScopeProcessor
  - detect R-peaks (Pan-Tompkins / threshold)      │
  - manage beat-count block structure              │
  - produce beat-locked epoch windows              │ ECGScopeResult dict
                                                   ▼
ecg_peaks.py  ◄────── REPLACEMENT TARGET 2  ── detect_ecg_peaks()
  - R-peak amplitude extraction                    │
  - (Phase 2: QRS width, PR, QT)                  │ ECGPeaksResult TypedDict
                                                   ▼
ecg_metrics.py  ◄──── NEW MODULE            ── compute_ecg_metrics()
  - HR, RR intervals, SDNN                         │ ECGMetrics TypedDict
                                                   ▼
ecg_classifier.py  ◄── REPLACEMENT TARGET 3 ── classify_ecg_signal()
  - beat-quality / artefact gate (Phase 1)         │ (is_valid, check_details)
  - (Phase 2: rhythm / interval classification)   │
                                                   ▼
ecg_report.py  ◄───── REPLACEMENT TARGET 4  ── save_ecg_report()
  - CSV: beat list + HR summary                    │
  - (Phase 2: full PDF)                            │
                                                   ▼
ver_display.py  ──────────────────────────────► beat marker overlay
(extend; add R-peak marker rendering)
```

### 4.2 Module-by-module description

#### `ecg_scope.py` — ECG scope processor (REPLACEMENT TARGET 1)

| | |
|---|---|
| **Responsibility** | Detect R-peaks in the incoming ECG sample stream; organise beats into configurable blocks; expose beat-locked epoch windows for downstream analysis |
| **Inputs** | Raw filtered ECG samples (float array, sample rate Hz) from `ver_acquisition.py` + `ver_filter.py` |
| **Outputs** | `ECGScopeResult` dict — see §5.1 |
| **Replaces** | Delegation to `VERScopeProcessor` inside the current placeholder |
| **Reuses** | Ring buffer logic from `VERScopeProcessor` (carry forward); artifact rejection threshold logic (carry forward) |
| **Algorithm** | Threshold-based QRS detection: compute signal envelope (moving RMS or absolute value), detect crossings above `r_peak_threshold` (configurable, default 2 SD above baseline), apply refractory period of 200 ms to reject double-detections |
| **Dependencies** | `ver_acquisition.py` (sample delivery), `ver_filter.py` (pre-filtering), `ver_config.py` (block size, threshold) |

#### `ecg_peaks.py` — ECG peak detector (REPLACEMENT TARGET 2)

| | |
|---|---|
| **Responsibility** | Extract ECG waveform features from a beat-centred epoch; Phase 1 scope is R-peak confirmation and amplitude; Phase 2 extends to QRS/PR/QT |
| **Inputs** | Beat-centred epoch array (1-D numpy, µV or mV), sampling rate Hz, time axis ms |
| **Outputs** | `ECGPeaksResult` TypedDict — see §5.2 |
| **Replaces** | `ver_peaks.detect_ver_peaks` via `ver_analysis_engine.py` |
| **Reuses** | `scipy.signal.find_peaks` (already used in `ver_peaks.py`); epoch time vector from `ecg_scope.py` |
| **Dependencies** | `ecg_scope.py` epoch output, `scipy.signal` |

#### `ecg_metrics.py` — ECG metrics calculator (NEW MODULE)

| | |
|---|---|
| **Responsibility** | Compute session-level heart rate and RR-interval metrics from a list of beat timestamps |
| **Inputs** | List of R-peak timestamps in ms (or sample indices + sample rate) |
| **Outputs** | `ECGMetrics` TypedDict — see §5.3 |
| **Replaces** | Nothing — pure addition |
| **Reuses** | NumPy (already in environment) |
| **Dependencies** | None (standalone utility) |

#### `ecg_classifier.py` — ECG signal classifier (REPLACEMENT TARGET 3, boundary exists)

| | |
|---|---|
| **Responsibility** | Phase 1: classify each beat as `valid` or `artefact` based on amplitude bounds and refractory plausibility; Phase 2: rhythm classification (normal sinus, bradycardia, tachycardia, ectopic) |
| **Inputs** | `ECGPeaksResult` fields (amplitude, RR interval, `beat_detected`) |
| **Outputs** | `(is_valid: bool, check_details: dict[str, bool])` — ECG-labelled keys replace VER keys |
| **Replaces** | Delegation to `_evaluate_ver_peak` from `ver_classifier.py` |
| **Reuses** | Function signature contract preserved from placeholder |
| **Dependencies** | `ecg_peaks.py` output schema |

#### `ecg_report.py` — ECG report generator (REPLACEMENT TARGET 4, boundary exists)

| | |
|---|---|
| **Responsibility** | Write per-beat CSV and (Phase 2) a PDF summary report with ECG-standard metrics and labelling |
| **Inputs** | `ECGReportData` struct — see §5.4 |
| **Outputs** | `{"summary_csv": path, "waveforms_csv": path, "pdf": path or None}` |
| **Replaces** | Delegation to `_save_ver_report` from `ver_report.py` |
| **Reuses** | File-path conventions and `force_stem` logic from placeholder signature |
| **Dependencies** | `ecg_metrics.py`, `ecg_peaks.py`, `pathlib`, `csv` |

#### `ver_display.py` — signal display (extend, not replace)

| | |
|---|---|
| **Responsibility** | Add R-peak marker overlay to the existing scrolling ECG trace display |
| **Change** | Add a `set_beat_markers(timestamps_ms)` method to `VERDisplayWidget`; render as vertical dashed lines or scatter markers on the signal plot |
| **Replaces** | Nothing — additive change |
| **Risk** | Low; the `pyqtgraph` plot item already supports adding plot items |

---

## 5. First Outputs and Data Contracts

### 5.1 `ECGScopeResult` — result dict from `ECGScopeProcessor`

Replaces the current VER-epoch result dict.  Key names are chosen to be parallel
to the inherited dict so `ver_main.py` read sites can be updated one-by-one.

```python
# ECGScopeResult  (dict — same delivery mechanism as current VERScopeProcessor)
{
    # Beat detection state
    "beat_detected":     bool,           # True when a new R-peak was just confirmed
    "beat_count":        int,            # Total confirmed beats this block
    "beat_count_accepted": int,          # Beats that passed artefact threshold

    # Beat timing
    "rr_interval_ms":    float | None,   # Most recent RR interval (ms); None for first beat
    "beat_timestamp_ms": float,          # Timestamp of most recent R-peak (ms from start)

    # Block / session structure  (replaces flash_count / session_complete)
    "block_complete":    bool,           # True when beats_per_block threshold reached
    "session_complete":  bool,           # True when all blocks done (if configured)
    "block_number":      int,            # Current 1-based block index

    # Epoch window (replaces epoch_complete / running_average)
    "epoch_complete":    bool,           # True when a new beat-centred epoch is ready
    "running_average":   np.ndarray | None,  # Beat-averaged ECG epoch (same shape as before)

    # Artefact gate
    "artefact_rejected": bool,           # True if this beat was rejected by threshold
}
```

**Migration note for `ver_main.py`:** Keep `"flash_count"` as a temporary alias
for `"beat_count"` in the result dict until all read sites in `ver_main.py` are
updated.  Remove the alias in the subsequent cleanup pass.

### 5.2 `ECGPeaksResult` — TypedDict from `ecg_peaks.detect_ecg_peaks`

Replaces `VERPeaksResult` from `ver_peaks.py`.

```python
from typing import TypedDict, Optional

class ECGPeaksResult(TypedDict):
    # R-peak (Phase 1 — required)
    r_peak_sample:       int             # Sample index of the R peak in the epoch
    r_peak_amplitude:    float           # Signal amplitude at R peak (µV or mV)
    beat_detected:       bool            # True if an R peak was found in the epoch

    # QRS complex (Phase 2 — may be None initially)
    qrs_onset_sample:    Optional[int]   # Q-wave onset sample index
    qrs_offset_sample:   Optional[int]   # S-wave offset sample index
    qrs_duration_ms:     Optional[float] # QRS complex width (ms)

    # P and T waves (Phase 2 — may be None initially)
    p_peak_sample:       Optional[int]
    t_peak_sample:       Optional[int]
    pr_interval_ms:      Optional[float] # P-onset to Q-onset (ms)
    qt_interval_ms:      Optional[float] # Q-onset to T-offset (ms)

    # Signal quality
    noise_rms:           float           # RMS of the pre-beat baseline segment
    snr_db:              Optional[float] # Signal-to-noise ratio (dB) at R peak
```

### 5.3 `ECGMetrics` — TypedDict from `ecg_metrics.compute_ecg_metrics`

```python
class ECGMetrics(TypedDict):
    beat_count:          int             # Total valid beats in session
    mean_hr_bpm:         float           # Mean heart rate (beats per minute)
    min_hr_bpm:          float
    max_hr_bpm:          float
    mean_rr_ms:          float           # Mean RR interval (ms)
    rr_sd_ms:            float           # SDNN — std dev of RR intervals (ms)
    min_rr_ms:           float
    max_rr_ms:           float
    artefact_count:      int             # Number of beats rejected as artefacts
```

### 5.4 `ECGReportData` — input to `ecg_report.save_ecg_report`

Replaces the current parameter list that mirrors the VER report API.

```python
class ECGReportData(TypedDict):
    data_file_path:      str                    # Source ECG file path (for report header)
    session_beats:       List[ECGPeaksResult]   # One entry per detected beat
    session_metrics:     ECGMetrics             # Session-level summary
    epoch_time_ms:       np.ndarray             # Time axis for beat-centred epochs
    session_averages:    List[np.ndarray]       # Beat-averaged epochs per block
    lead_id:             Optional[str]          # Lead label (e.g. "Lead II") or None
    force_stem:          Optional[str]          # Override output filename stem
```

### 5.5 First CSV report columns (Phase 1)

**Per-beat CSV** (`ecg_beats.csv`):

| Column | Description |
|--------|-------------|
| `beat_index` | 1-based beat number |
| `timestamp_ms` | R-peak time from recording start (ms) |
| `rr_interval_ms` | Interval from previous R-peak (ms); blank for first beat |
| `hr_bpm` | Instantaneous HR derived from RR interval |
| `r_amplitude` | R-peak amplitude (µV or mV) |
| `artefact` | `True` / `False` |
| `block` | Block number (1-based) |

**Summary CSV** (`ecg_summary.csv`):

| Column | Description |
|--------|-------------|
| `block` | Block number |
| `beat_count` | Valid beats in block |
| `mean_hr_bpm` | Mean HR for block |
| `mean_rr_ms` | Mean RR interval (ms) |
| `rr_sd_ms` | SDNN (ms) |
| `artefact_count` | Rejected beats |

---

## 6. Reuse vs. Replacement Plan

### 6.1 Infrastructure — reuse as-is

| Module | Decision | Rationale |
|--------|----------|-----------|
| `ver_acquisition.py` | **Reuse unchanged** | Generic serial + file I/O; no VER domain logic |
| `ver_filter.py` | **Reuse; change default parameters** | Generic DSP; ECG needs 0.5–40 Hz bandpass instead of VER defaults |
| `ver_settings.py` | **Reuse unchanged** | Generic JSON key-value store |
| `ver_logging.py` | **Reuse unchanged** | Already updated to `~/.ecg_analyses` |
| `ver_constants.py` | **Reuse unchanged** | Filter-mode string constants; generic |
| `ver_analysis_flow.py` | **Reuse unchanged** | Generic post-session routing |
| `ver_wavelet.py` | **Reuse unchanged** | Morlet scalogram; useful for ECG HRV and QRS frequency analysis |
| `ver_downsample.py` | **Reuse unchanged** | Generic LabChart file utility |
| `ver_USB_test.py` | **Reuse unchanged** | Hardware diagnostic; generic |

### 6.2 Application structure — refactor incrementally

| Module | Decision | What to change |
|--------|----------|----------------|
| `ver_main.py` | **Moderate refactor (incremental)** | Update `session_ver_peaks` → `session_beats`, update read sites as scope/peaks are replaced; rename class in final rename pass |
| `ver_display.py` | **Extend; rename later** | Add `set_beat_markers()` method for R-peak overlay; rename class in final rename pass |
| `ver_preflight.py` | **Reuse; update import** | Will follow `ecg_scope.py` when the new scope processor changes its constructor signature |
| `ver_config.py` | **Partial update** | Remove `SPECIES` fish list; rename `flashes_per_session` → `beats_per_block`; add ECG filter defaults and R-peak threshold key |

### 6.3 Analysis modules — replace

| Module | Decision | Notes |
|--------|----------|-------|
| `ecg_scope.py` | **Replace delegation with ECG logic** | REPLACEMENT TARGET 1; boundary exists; implement Pan-Tompkins-style R-peak detector |
| `ver_peaks.py` | **Replace with `ecg_peaks.py`** | REPLACEMENT TARGET 2; introduce `ECGPeaksResult` TypedDict |
| `ecg_classifier.py` | **Replace delegation with ECG logic** | REPLACEMENT TARGET 3; boundary exists; Phase 1: artefact gate; Phase 2: rhythm classification |
| `ecg_report.py` | **Replace delegation with ECG logic** | REPLACEMENT TARGET 4; boundary exists; Phase 1: CSV; Phase 2: PDF |
| `ver_classifier.py` | **Remove dependency** | Can be deleted once `ecg_classifier.py` no longer delegates to it |
| `ver_report.py` | **Remove dependency** | Can be deleted once `ecg_report.py` no longer delegates to it |
| `ver_ml_logger.py` | **Schema update** | Replace VER columns with ECG beat columns; update validation dialog labels |

---

## 7. Recommended First Implementation Sequence

Steps are tied to actual file names and import chains in this repository.
Each step is designed to be a self-contained PR that leaves the app runnable.

```
Step A  ECG config and filter defaults
        ├── ver_config.py: rename flashes_per_session → beats_per_block
        ├── ver_config.py: add ecg_bandpass_hz = [0.5, 40.0]
        ├── ver_config.py: add r_peak_threshold_sd = 2.0  (detection gate)
        ├── ver_config.py: add beats_per_block = 20  (replaces flashes_per_session)
        ├── ver_config.py: remove SPECIES list; add ECG session metadata placeholder
        │   (lead_id: str = "Lead II", session_id: str = "")
        └── ver_main.py: remove species dropdown; add lead/session fields
            Risk: low; settings change breaks existing user_settings.json keys
            Migration: add a settings-migration shim in ver_settings.py

Step B  ecg_metrics.py — new standalone module
        ├── Define ECGMetrics TypedDict
        ├── Implement compute_ecg_metrics(r_peak_timestamps_ms) → ECGMetrics
        └── No callers yet; safe to ship ahead of the scope replacement
            Risk: none (pure addition)

Step C  ecg_peaks.py — replace ver_peaks.py (REPLACEMENT TARGET 2)
        ├── Define ECGPeaksResult TypedDict (§5.2)
        ├── Implement detect_ecg_peaks(epoch, sample_rate_hz) → ECGPeaksResult
        │   Phase 1: R-peak confirmation + amplitude only
        │   Phase 2 (later): add QRS/PR/QT detection
        ├── ver_analysis_engine.py: swap detect_ver_peaks → detect_ecg_peaks
        ├── ver_report.py: update column reads (remove P1/P2/P3 keys; add ECG keys)
        └── ver_ml_logger.py: update CSV schema
            Risk: medium — report and ML logger both consume peak dict;
            update all three in the same PR

Step D  ecg_scope.py — implement ECG R-peak trigger (REPLACEMENT TARGET 1)
        ├── Remove delegation to VERScopeProcessor
        ├── Implement threshold-based R-peak detector inline
        │   - moving RMS envelope over 50 ms window
        │   - threshold crossing above r_peak_threshold_sd * baseline_sd
        │   - 200 ms refractory period
        ├── Return ECGScopeResult dict (§5.1) with flash_count alias retained
        ├── ver_main.py: update result-dict read sites
        │   (flash_count → beat_count, epoch_complete keys etc.)
        └── ver_preflight.py: update constructor call if signature changes
            Risk: high — ver_main.py has many read sites; update all in same PR
            Test: replay a known ECG file; verify beat_count increments correctly

Step E  ecg_report.py — Phase 1 CSV (REPLACEMENT TARGET 4)
        ├── Remove delegation to _save_ver_report
        ├── Implement per-beat CSV writer using ECGReportData (§5.4)
        │   Columns: beat_index, timestamp_ms, rr_interval_ms, hr_bpm,
        │             r_amplitude, artefact, block
        ├── Implement summary CSV writer using ECGMetrics
        └── Defer PDF to Phase 2; return {"summary_csv": ..., "waveforms_csv": ...,
            "pdf": None, "report_dir": ...}
            Risk: low — output-only module; callers check for None pdf already

Step F  ver_display.py — beat marker overlay
        ├── Add set_beat_markers(timestamps_ms: list[float]) method to
        │   VERDisplayWidget (or ECGDisplayWidget once renamed)
        ├── Render R-peak markers as vertical dashed lines on the signal trace
        └── ver_main.py: call set_beat_markers() when ECGScopeProcessor fires
            beat_detected=True
            Risk: low — additive change to display widget

Step G  ecg_classifier.py — Phase 1 artefact gate (REPLACEMENT TARGET 3)
        ├── Remove delegation to _evaluate_ver_peak
        ├── Implement basic ECG artefact gate:
        │   - amplitude within [min_valid_amplitude, max_valid_amplitude]
        │   - RR interval within physiological range [200, 2000] ms
        │   - beat_detected flag from ECGPeaksResult
        ├── Return (is_valid, check_details) with ECG-labelled keys:
        │   "Amplitude Range", "RR Plausibility", "Beat Detected"
        └── Remove ver_classifier.py dependency entirely
            Risk: low — boundary already isolates all callers

Step H  Cleanup and remove VER delegation
        ├── Delete ver_classifier.py (if ecg_classifier.py no longer delegates)
        ├── Delete ver_report.py (if ecg_report.py no longer delegates)
        ├── Remove backward-compat aliases from ver_analysis_engine.py
        │   (evaluate_ver_peak, save_ver_report)
        └── Update ver_ml_logger.py labels to ECG terminology

Step I  Module rename pass  (when logic is stable — defer until after Step H)
        ├── ver_*.py → ecg_*.py  (all modules in one coordinated commit)
        ├── VERMainWindow → ECGMainWindow
        ├── VERDisplayWidget → ECGDisplayWidget
        └── Use sed / find-replace; update all imports in one pass
```

### 7.1 Minimum viable first PR after this plan

If only one PR can ship from this plan, it should be **Steps B + C** (new
`ecg_metrics.py` + new `ecg_peaks.py`), because:

- `ecg_metrics.py` is a standalone addition with zero risk
- `ecg_peaks.py` replaces the module most obviously wrong for ECG (VER P1/P2/P3)
- Together they establish the core ECG data structures that all other modules
  (`ecg_scope.py`, `ecg_classifier.py`, `ecg_report.py`) reference
- `ver_analysis_engine.py` already provides the swap boundary

---

## 8. Key Risks and Open Questions

### 8.1 Technical risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| `ver_main.py` has many VER result-dict read sites | **High** | In Step D, update all `flash_count` / `epoch_complete` / `session_complete` read sites in the same PR as the scope replacement; add a temporary alias `flash_count = beat_count` to catch missed sites at runtime |
| Peak schema change breaks report and ML logger simultaneously | **Medium** | Steps C (ecg_peaks.py) + report/ML schema update must ship as a single coordinated PR; never split them |
| Settings key rename (`flashes_per_session` → `beats_per_block`) invalidates existing `user_settings.json` | **Low** | Add a one-time migration shim in `ver_settings.py` that renames old keys on first load |
| R-peak detector false positives / missed beats | **Medium** | Use a 200 ms refractory period; expose threshold as a configurable setting; add a manual override UI in a later pass |
| ECG signal amplitude varies widely (µV vs mV) | **Medium** | Normalise to a consistent unit at the acquisition boundary; document the unit convention in `ver_acquisition.py` and `ecg_scope.py` |
| `ver_display.py` class name (`VERDisplayWidget`) is confused | **Low** | Rename in Step I; acceptable to work with the old name during Phase 1 |

### 8.2 Open questions

| Question | Impact | Suggested resolution |
|----------|--------|----------------------|
| What ECG file formats are used in practice? | Affects `ver_acquisition.py` parser | Survey the expected input files early; extend the text/CSV parser if LabChart or EDF is needed |
| What is the expected amplitude unit (µV, mV)? | Affects threshold defaults and report labels | Define the convention in the first `ecg_scope.py` implementation and propagate |
| Is a single-lead or multi-lead recording expected? | Affects UI and acquisition layer | Phase 1 supports single-channel; multi-lead can be added as a future enhancement |
| What arrhythmia types need detection? | Drives Phase 2 classifier complexity | Defer to Phase 2 planning once Phase 1 HR/RR pipeline is validated |
| Should `ver_ml_logger.py` be kept for ECG beat review? | Affects ML workflow | The human-in-the-loop review model is applicable to ECG; update schema in Step H |
| What should the default `beats_per_block` be? | Affects session structure UX | 20 beats is a practical default; expose as a settings parameter |
| Is the wavelet scalogram (`ver_wavelet.py`) needed for ECG Phase 1? | Affects display complexity | Keep it available but disable by default; it is directly useful for QRS frequency analysis in Phase 2 |

---

## 9. Summary of Recommended Changes to Existing Documentation

After this plan is accepted, the following existing documents should be updated
in the same PR as each implementation step:

| Step | Document update |
|------|-----------------|
| Step A | `TRANSITION.md` §6 entry for config cleanup |
| Step B | `docs/ecg-transition-priorities.md` §2 — mark `ecg_metrics.py` as added |
| Step C | `TRANSITION.md` §7 entry; mark Rank 2 as complete |
| Step D | `TRANSITION.md` §7 entry; mark Rank 1 as complete |
| Step E | `TRANSITION.md` §7 entry; mark Rank 5 partial complete |
| Step G | `TRANSITION.md` §7 entry; mark Rank 3 as complete |
| Step I | `README.md`, `TRANSITION.md`, `docs/ecg-transition-priorities.md` — update all module name references |

---

*Last updated: 2026-07-26 — ECG analysis planning pass (PR #8).*
