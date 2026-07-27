# ECG-analyses

> **Transition status:** This repository is an ECG-oriented derivative of the
> [VER-analyses](https://github.com/MichaelLandvetter/VER-analyses) codebase.
> It is currently in **first-pass transition**. The inherited infrastructure is
> preserved and functional; ECG-specific analysis logic has not yet been
> implemented.

## What this application does (current state)

The application provides a modular signal-analysis workbench with:

- **File analysis (offline-first)** — load ECG text files, compute full-file analysis,
  then review complete-duration results in a pre-report window
- **Live USB acquisition** — stream data from a serial microcontroller in real time
- **Bandpass filtering** — configurable Butterworth / FIR / Savitzky-Golay filter
- **Pre-report workflow** — full ECG/HR plots + individual beats/mean beat with
  Back to Analysis and Save Reports actions
- **Trigger-locked epoch averaging** — detect trigger events and average aligned
  windows (currently tuned to the VER paradigm; ECG trigger logic TBD)
- **Wavelet scalogram** — continuous Morlet wavelet transform visualisation
- **Report export** — PDF + CSV summary reports (wording still VER-oriented)
- **Human-in-the-loop validation** — manual accept/reject workflow for averaged
  epochs; feeds an ML training CSV
- **Settings persistence** — external `user_settings.json` so compiled EXEs can
  be reconfigured without recompiling

## Repository origin

This repository was created by copying
[MichaelLandvetter/VER-analyses](https://github.com/MichaelLandvetter/VER-analyses),
which implements a Visually Evoked Response (VER) analysis pipeline for fish
electrophysiology. The module structure, UI framework, acquisition layer, filter
utilities, and settings system are all inherited from that codebase.

## Current VER-oriented placeholders

The following areas still contain VER-specific logic or wording and are
**intentional placeholders** pending ECG implementation:

| Area | Placeholder detail |
|------|--------------------|
| `ver_scope.py` | Epoch trigger model is flash-locked (VER). ECG will need R-peak or arrhythmia trigger. |
| `ver_peaks.py` | Peak detection targets P1/P2/P3 VER morphology. ECG morphology (P, Q, R, S, T) TBD. |
| `ver_classifier.py` | VER-specific SNR + latency classifier. ECG classifier TBD. |
| `ver_report.py` | CSV headers and several report/statistics labels still reflect the inherited VER workflow. |
| `ver_config.py` | `SPECIES` list is fish-specific. `EPOCH_CONFIG` comments reference flashes. |
| `ver_ml_logger.py` | ML training schema still targets the inherited response/no-response review flow and fish metadata. |
| UI labels | Trigger/block wording still derives from the inherited flash-based workflow; species metadata and Peak-1/2/3 labels remain transitional placeholders. |
| `ver_main.py` | `session_ver_peaks`, `detect_ver_peaks`, `save_ver_report` — internal VER naming. |

## Module overview

See [TRANSITION.md](TRANSITION.md) for a detailed module-by-module assessment
and classification (reusable / moderate refactoring needed / VER-specific).

## Running the application

```bash
pip install -r requirements.txt   # if a requirements file is present
python ver_main.py
```

The application will start with the inherited VER infrastructure. All existing
features (file replay, live USB, report export) remain functional.

## Next steps

See [TRANSITION.md — Recommended roadmap](TRANSITION.md#recommended-roadmap)
for the first-pass assessment and phased roadmap, and
[docs/ecg-transition-priorities.md](docs/ecg-transition-priorities.md)
for the ranked module replacement list and safe sequencing plan.
