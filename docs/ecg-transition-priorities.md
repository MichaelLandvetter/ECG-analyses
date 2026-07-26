# ECG Transition Priorities

> **Purpose:** Concrete, repository-specific sequencing plan for replacing
> inherited VER-specific modules while preserving stable generic infrastructure.
>
> **Scope:** This document guides the next ECG PRs by ranking module
> replacements and identifying safe sequencing order.  No ECG pipeline is
> implemented here.  See [TRANSITION.md](../TRANSITION.md) for the first-pass
> assessment that preceded this plan.

---

## 1. Module-by-module classification

### 🚀 Replace early — high domain mismatch, high user-facing confusion

| Module | Lines | Domain mismatch | Coupling | Replace rationale |
|--------|------:|-----------------|----------|-------------------|
| `ver_scope.py` | 169 | Flash-locked epoch model is wrong for ECG | **High** — imported by `ver_main.py`, `ver_preflight.py` | Core trigger paradigm must change first; everything downstream follows |
| `ver_peaks.py` | 265 | P1/P2/P3 VER morphology, not ECG P/Q/R/S/T | **High** — called from `ver_main.py`, `ver_report.py`, `ver_ml_logger.py` | Peak model shapes the entire analysis output and report |
| `ver_classifier.py` | 95 | VER SNR/latency gates, not ECG interval/arrhythmia logic | **Medium** — called from `ver_main.py`, `ver_report.py`, `ver_ml_logger.py` | Must be replaced together with `ver_peaks.py`; both feed the same downstream consumers |

### 🔧 Replace moderately — domain-specific wording and schema, contained risk

| Module | Lines | What is VER-specific | Replace rationale |
|--------|------:|----------------------|-------------------|
| `ver_report.py` | 574 | CSV headers (`VER_label`, `VER?`), PDF wording, plot titles | Replace after scope/peaks — report content depends on the new peak/classifier output schema |
| `ver_ml_logger.py` | 291 | CSV schema targets VER labels (`Confirmed`, `Species`), dialog wording | Replace after classifier — schema must align with new ECG labels and validation workflow |
| `ver_config.py` *(partial)* | 136 | `SPECIES` fish list, `flashes_per_session` key name, VER comments in `EPOCH_CONFIG` | Partial update: rename epoch keys + remove SPECIES when scope is replaced; preserve the config structure |

### ⚙️ Moderate refactor — structure reusable, internal naming needs cleanup

| Module | Lines | What needs refactoring | Risk |
|--------|------:|------------------------|------|
| `ver_main.py` | 1,770 | Class `VERMainWindow`, vars `session_ver_peaks`/`detect_ver_peaks`/`save_ver_report`, plus inherited internal VER naming | **Central orchestrator** — refactor incrementally alongside each module replacement; never in isolation |
| `ver_display.py` | 430 | Class `VERDisplayWidget`; one remaining `"No response"` string already updated | Rename class after the core logic replacements; structure is generic and reusable |
| `ver_preflight.py` | 160 | Imports `VERScopeProcessor` — will track the scope replacement | Update import + interface call when `ver_scope.py` is replaced |

### ✅ Keep for now — generic infrastructure, no VER domain logic

| Module | Lines | Role | Notes |
|--------|------:|------|-------|
| `ver_acquisition.py` | 232 | File replay + USB serial streaming | Entirely generic I/O. No VER domain logic. Rename prefix later. |
| `ver_filter.py` | 111 | Butterworth / FIR / Savitzky-Golay bandpass | Generic DSP. Directly reusable for ECG. |
| `ver_settings.py` | 167 | JSON-based settings persistence | Generic key-value store. Reusable unchanged. |
| `ver_logging.py` | 113 | Rotating-file logger setup | Generic. Already updated to `~/.ecg_analyses`. |
| `ver_constants.py` | 26 | Filter-mode string constants | Generic. No VER logic. |
| `ver_analysis_flow.py` | 40 | End-of-analysis action routing helpers | Generic control flow. Reusable unchanged. |
| `ver_downsample.py` | 88 | LabChart file downsample utility | Generic file tool. Reusable unchanged. |
| `ver_wavelet.py` | 50 | Morlet wavelet scalogram | Generic DSP. Useful for ECG frequency analysis (HRV, QRS width). |
| `ver_USB_test.py` | 271 | Standalone USB/serial diagnostic GUI | Generic hardware test. Reusable unchanged. |
| `Assets/` | — | Icons and splash images | Replace icons progressively; not blocking. |

---

## 2. Ranked early replacement list

### Rank 1 — `ver_scope.py` → `ecg_scope.py`

**Current transition status:** A minimal ECG placeholder boundary now exists in
`ecg_scope.py` (`ECGScopeProcessor`), and direct caller imports in
`ver_main.py`/`ver_preflight.py` route through that interface while inherited
`ver_scope.py` behavior remains underneath temporarily.

**Problem if left unchanged:**
Trigger logic based on external flash events will not fire correctly (or at
all) on ECG data.  All downstream averaging, artifact rejection, and reporting
will produce meaningless results.

**Replace vs. generalise:**
Full replacement.  The flash-locked paradigm is incompatible with ECG.
The replacement (`ecg_scope.py`) should detect R-peaks as the primary trigger
using a Pan-Tompkins-style algorithm, organise beats into configurable blocks
(replacing flash-count sessions), and expose the same key-based result dict so
`ver_main.py` callers require minimal changes.

**Dependencies / risks:**
`ver_main.py` and `ver_preflight.py` both import `VERScopeProcessor` directly.
The replacement must either provide a drop-in-compatible result-dict interface
or both callers must be updated in the same PR.  The interface contract
(`epoch_complete`, `session_complete`, `running_average`, etc.) is the critical
shared boundary.

**User-facing improvement:**
Real ECG epochs (beat-locked windows) instead of flash-triggered averages.
The application becomes usable with actual ECG recordings.

**Next target after this boundary PR:**
`ver_peaks.py` (Rank 2), then coordinated `ver_classifier.py` replacement.

---

### Rank 2 — `ver_peaks.py` → `ecg_peaks.py`

**Why early:**
Peak detection defines the measurement schema that flows into `ver_main.py`,
`ver_report.py`, and `ver_ml_logger.py`.  Leaving it as VER P1/P2/P3
detection means every ECG session is annotated with meaningless latencies and
amplitudes.

**Problem if left unchanged:**
VER peak windows (40–120 ms P2 range, etc.) will simply find local extrema
that have no ECG meaning.  The CSV report will contain `P1_Latency`, `P2_Latency`,
`P3_Latency` columns with arbitrary values.

**Replace vs. generalise:**
Full replacement.  Expose ECG-standard measurements: R-peak confirmation,
QRS duration, PR interval, QT interval, and per-beat amplitude.  The
`VERPeaksResult` TypedDict should be replaced with an `ECGPeaksResult` TypedDict
with ECG-specific keys.

**Dependencies / risks:**
Tightly coupled to `ver_classifier.py` — replace as a coordinated pair (see
Rank 3).  `ver_report.py` and `ver_ml_logger.py` consume the peak result dict;
their schemas must be updated in the same pass.

**User-facing improvement:**
Clinically meaningful ECG interval measurements in reports.

---

### Rank 3 — `ver_classifier.py` → `ecg_classifier.py`

**Current transition status:** ECG-named boundary established in
`ecg_classifier.py`.  The function `classify_ecg_signal()` with neutral
parameter and return names now routes all callers (`ver_ml_logger.py`,
`ver_report.py`, `ver_analysis_engine.py`) through this boundary.  Inherited
VER gate logic still runs underneath via delegation to `evaluate_ver_peak`.
`check_details` key names are still VER labels until the ECG logic is
implemented inside `ecg_classifier.py`.

**Why early:**
Must be replaced together with `ver_peaks.py`.  The classifier gates on VER
peak latency and SNR thresholds that have no ECG meaning.  Leaving it in place
will produce meaningless pass/fail labels on ECG sessions.

**Problem if left unchanged:**
Every ECG session will receive a VER-style classification label, creating a
false clinical impression.

**Replace vs. generalise:**
Full replacement.  Implement ECG-relevant decision logic (e.g. normal sinus
rhythm vs. arrhythmia detection, QRS duration within normal range, etc.) inside
`ecg_classifier.py`, replacing the delegation to `evaluate_ver_peak`.

**Dependencies / risks:**
`ecg_classifier.py` is now the single caller boundary; update only
`ecg_classifier.py` to switch all callers.  `ver_report.py` and
`ver_ml_logger.py` already use `classify_ecg_signal` and will follow
automatically.  Replace together with `ver_peaks.py`.

**User-facing improvement:**
Meaningful ECG classification labels instead of VER pass/fail.

---

### Rank 4 — `ver_config.py` (partial update)

**Why moderately early:**
`EPOCH_CONFIG` still uses `flashes_per_session` and VER-oriented comments.
`SPECIES` is a fish-specific list that appears in the file-load dropdown.
These are user-visible confusions that block ECG usability.

**What to change:**
- Rename `flashes_per_session` → `beats_per_block` (after scope replacement).
- Replace or remove the `SPECIES` list; replace with ECG-relevant metadata
  (patient ID, lead configuration, recording date) or simply remove.
- Update `EPOCH_CONFIG` comments to reference ECG beat-locked windows.
- Keep the config dict structure — settings persistence depends on it.

**Dependencies / risks:**
`SPECIES` removal will break the species dropdown in `ver_main.py`.
Update `ver_main.py` in the same PR.  Key renames in `EPOCH_CONFIG` will
invalidate existing `user_settings.json` files; add a migration note.

**User-facing improvement:**
Settings UI shows ECG-relevant labels; no fish species selector.

---

### Rank 5 — `ver_report.py` + `ver_ml_logger.py`

**Current transition status:** ECG-named boundary established in
`ecg_report.py`.  The function `save_ecg_report()` now routes the main
caller (`ver_main.py`) through this boundary.  `ver_report.py` internally
routes its classification calls through `ecg_classifier.py`.  VER-domain
CSV column headers (`VER_label`, `N_flashes_total`), PDF layout, and
waveform table structure remain unchanged underneath.

**Why after Rank 2–3:**
Report and ML schema content depends on the peak/classifier output format.
Updating them before the analysis modules are replaced just creates a mismatch
between the new headers and the old data.

**What to change (`ecg_report.py` / `ver_report.py`):**
- Replace delegation inside `ecg_report.py` with real ECG report generation.
- Replace CSV column headers (`VER_label`, `N_flashes_total`) with ECG metrics.
- Update PDF text, axis labels, and plot wording.

**What to change (`ver_ml_logger.py`):**
- Replace CSV schema (`Block`, `P1_Latency`, `P2_Latency`, `P3_Latency`,
  `Species`) with ECG-appropriate columns.
- Update the human validation dialog labels.

**Dependencies / risks:**
Low — these modules are primarily output-only.  Replace after the peak/scope
pair is stable.  `ver_ml_logger.py` already routes through `ecg_classifier.py`.

---

## 3. Safe ordered roadmap

Steps are tied to actual file names and import chains in this repository.

```
Step 1  (done)  Documentation + branding
                ├── README.md — repo origin and status
                ├── TRANSITION.md — module assessment + phased roadmap
                └── docs/ecg-transition-priorities.md — this document

Step 2  (done)  Replace ver_scope.py → ecg_scope.py (boundary established)
                ├── ecg_scope.py created — ECGScopeProcessor delegates to VERScopeProcessor
                ├── ver_main.py: swapped VERScopeProcessor → ECGScopeProcessor import
                ├── ver_preflight.py: swapped import + interface call
                └── Implement Pan-Tompkins R-peak trigger inside ecg_scope.py (NEXT)

Step 3  (next)  Replace ver_peaks.py → ecg_peaks.py
                ├── Implement P/Q/R/S/T detection (QRS, PR, QT intervals)
                ├── Define ECGPeaksResult TypedDict with ECG-standard keys
                └── Update ver_main.py: swap detect_ver_peaks → detect_ecg_peaks

Step 4  (boundary done)  Replace ver_classifier.py → ecg_classifier.py
                ├── ecg_classifier.py created — classify_ecg_signal() delegates to evaluate_ver_peak
                ├── ver_ml_logger.py, ver_report.py: switched to classify_ecg_signal import
                ├── ver_analysis_engine.py: routes through ecg_classifier boundary
                └── Implement ECG interval and rhythm classification inside ecg_classifier.py (NEXT)

Step 5  (boundary done)  Replace ver_report.py → ecg_report.py
                ├── ecg_report.py created — save_ecg_report() delegates to save_ver_report
                ├── ver_main.py: switched to save_ecg_report import and call sites
                ├── ver_analysis_engine.py: routes through ecg_report boundary
                └── Implement real ECG report logic inside ecg_report.py (NEXT)

Step 6          Config and UI cleanup
                ├── Remove SPECIES fish list from ver_config.py
                ├── Add ECG-relevant session metadata (lead, patient ID)
                └── Revisit transitional classifier-tab wording in ver_main.py once the ECG classifier exists

Step 7          Module rename pass  (defer until logic is stable)
                ├── ver_*.py → ecg_*.py  (all modules in one coordinated commit)
                ├── Update all imports across the codebase
                ├── Rename VERMainWindow → ECGMainWindow, VERDisplayWidget → ECGDisplayWidget
                └── Use sed/find-replace to minimise mistakes
```

**Key constraint for Step 2:** The replacement scope processor must expose the
same result-dict keys (`epoch_complete`, `session_complete`, `running_average`,
`flash_count`, `flash_count_accepted`, `session_number`) that `ver_main.py`
currently reads.  Either provide a compatible interface or update all read sites
in the same PR.  Never leave callers with a broken import mid-step.

---

## 4. Infrastructure to keep — do not replace prematurely

These modules are **generic signal-processing infrastructure**.  ECG-specific
work should build on top of them, not replace them.

| Module | Why keep | How ECG builds on it |
|--------|----------|----------------------|
| `ver_acquisition.py` | Handles all file I/O and USB serial; no domain logic | ECG scope processor receives samples from this unchanged |
| `ver_filter.py` | Generic Butterworth/FIR/SG bandpass | ECG needs bandpass (0.5–40 Hz typical); reuse as-is, just change default settings |
| `ver_settings.py` | JSON settings persistence | ECG settings (lead config, beat threshold) use the same mechanism |
| `ver_logging.py` | Rotating-file logger | Already pointed at `~/.ecg_analyses`; reuse unchanged |
| `ver_wavelet.py` | Morlet scalogram | Useful for ECG HRV frequency analysis and QRS time-frequency characterisation |
| `ver_analysis_flow.py` | End-of-analysis routing | Reuse for ECG post-session action dispatch |
| `ver_downsample.py` | LabChart file utility | Reuse unchanged for LabChart ECG recordings |
| `ver_USB_test.py` | Serial diagnostic GUI | Reuse unchanged for hardware bring-up |
| `ver_constants.py` | Filter-mode constants | Reuse unchanged |

---

## 5. Biggest architectural risk

> **Starting ECG development from `ver_scope.py` replacement without
> simultaneously updating all of its callers.**

`VERScopeProcessor` is currently imported and used in three places:

```
ver_main.py       — instantiation, reset_all(), process_sample() call chain
ver_preflight.py  — whole-file pre-scan (artifact threshold suggestion)
```

If `ecg_scope.py` changes the result-dict keys or the constructor signature
without updating both callers, the application will fail at import or runtime
with no graceful fallback.  The risk is that `ver_main.py` (1,770 lines) has
many read sites for scope results — a partial update that misses one read site
will produce a silent `KeyError` only visible when that code path is exercised.

**Mitigation:** In the Step 2 PR, update `ver_main.py` and `ver_preflight.py`
in the same commit as `ecg_scope.py`.  Write the new scope processor to return
the same result-dict key names under ECG semantics (e.g. keep `flash_count`
temporarily aliased as `beat_count`) until a later cleanup pass.

**Second-biggest risk — peak/classifier schema split:**
If `ver_peaks.py` is replaced (Step 3) without updating `ver_report.py` and
`ver_ml_logger.py` in the same pass, the new `ECGPeaksResult` TypedDict will
not match the column layout expected by those modules.  The CSV report will
either crash or silently write wrong data.  Replace Steps 3–5 as a
coordinated group when possible.

---

*Last updated: 2026-07-26 — generated after first-pass transition cleanup (PR #1).*
