# Packaging ECG Analysis for Distribution

This guide explains how to build a standalone Windows executable from the ECG
Analysis codebase using [PyInstaller](https://pyinstaller.org/).

---

## Quick start

```bat
pip install pyinstaller
build_ecg.bat
```

Output: `dist\ECG_Analysis\ECG_Analysis.exe`

Distribute by copying the entire `dist\ECG_Analysis\` folder.  No Python
installation is required on the target machine.

---

## Mixed-module repository: what gets bundled?

This repository contains **both** `ecg_*.py` and `ver_*.py` modules.  The
question "do all files get bundled?" comes up when packaging from this mixed
codebase.

### Short answer

**Only modules reachable by import from `ecg_main.py`** are bundled.

PyInstaller performs static (and limited dynamic) import analysis starting from
the entrypoint.  It walks every `import` and `from … import` statement
transitively and includes only the discovered modules.

### What IS bundled

| Module | Reason |
|--------|--------|
| `ecg_main.py` | Entrypoint |
| `ver_main.py` | Imported by `ecg_main.py` → `from ver_main import main` |
| `ecg_config.py`, `ecg_loader.py`, `ecg_pipeline.py`, `ecg_scope.py`, `ecg_classifier.py`, `ecg_report.py` | Imported by `ver_main.py` |
| `ver_display.py`, `ver_filter.py`, `ver_acquisition.py`, `ver_config.py` | Imported by `ver_main.py` |
| `ver_settings.py`, `ver_logging.py`, `ver_analysis_flow.py`, `ver_preflight.py` | Imported by `ver_main.py` |
| `ver_analysis_engine.py`, `ver_peaks.py`, `ver_report.py`, `ver_classifier.py` | Transitively imported |
| `ver_wavelet.py`, `ver_ml_logger.py`, `ver_scope.py`, `ver_downsample.py` | Imported by `ver_main.py` |
| `ver_constants.py` | Imported by a transitional module |

### What is NOT bundled (auto-excluded)

| Module | Reason |
|--------|--------|
| `ver_USB_test.py` | Never imported from `ecg_main.py`; standalone VER test script |

The `ecg.spec` file explicitly lists `ver_USB_test` in `excludes` to document
this intent, though PyInstaller would skip it automatically anyway.

---

## Spec file details (`ecg.spec`)

The spec file lives at the repository root.  Key sections:

### Entry point

```python
a = Analysis(
    ['ecg_main.py'],
    ...
)
```

### Data files

The `Assets/` directory (icons and splash image) is bundled:

```python
datas=[
    ('Assets', 'Assets'),
],
```

### Hidden imports

PyInstaller's static analyser sometimes misses modules loaded via internal
C-extension mechanisms (notably `scipy` and `matplotlib`).  These are listed
explicitly in `hiddenimports`:

```python
hiddenimports=[
    'scipy.signal',
    'scipy.signal._upfirdn',
    'scipy._lib.messagestream',
    'matplotlib.backends.backend_agg',
    'matplotlib.backends.backend_pdf',
    ...
]
```

If you encounter a `ModuleNotFoundError` when launching the packaged `.exe`,
add the missing module name to `hiddenimports` in `ecg.spec` and rebuild.

### Splash screen

The spec configures a splash screen using `Assets/Please_wait.png` via
PyInstaller's built-in `Splash()` class.  To disable the splash, remove the
`Splash()` block and all references to `splash` / `splash.binaries` in the
spec, and also remove the `pyi_splash.close()` call in `ver_main.py::main()`.

---

## Build command reference

| Command | Description |
|---------|-------------|
| `pyinstaller ecg.spec` | Build using the spec file |
| `build_ecg.bat` | Convenience wrapper — cleans previous build, runs PyInstaller, reports result |

---

## Troubleshooting

### Missing module at runtime

```
ModuleNotFoundError: No module named 'scipy.signal._upfirdn'
```

**Fix:** add the module name to `hiddenimports` in `ecg.spec` and rebuild.

### Missing data file at runtime

```
FileNotFoundError: ... Assets/Please_wait.png
```

**Fix:** confirm the path in `datas` inside `ecg.spec` matches the actual file
location relative to the repo root.  PyInstaller copies listed data files to
the `_MEIPASS` temp directory; the app code must use `sys._MEIPASS` to locate
them at runtime if it accesses them by path.

### Antivirus false-positive

PyInstaller-generated executables are sometimes flagged by antivirus software.
If this is a problem, use `--key` (encryption) or consider a code-signing
certificate.

### Console window appears briefly on launch

Set `console=False` in `ecg.spec` (already the default).  If you need console
output for debugging, temporarily set `console=True` and rebuild.

---

## Auto-py-to-exe (GUI alternative)

If you prefer the GUI tool:

1. Install: `pip install auto-py-to-exe`
2. Run: `auto-py-to-exe`
3. Set **Script Location** to `ecg_main.py`.
4. Under **Advanced** → **Additional Files**, add the `Assets/` folder mapped
   to `Assets`.
5. Under **Advanced** → **Hidden Imports**, add each entry from the
   `hiddenimports` list in `ecg.spec`.
6. Click **Convert .py to .exe**.

The generated settings can be exported as a JSON for repeatable builds.

---

## Settings file at runtime

`user_settings.json` is read from the **current working directory** at launch
(see `ver_settings.SettingsManager`).  Place it alongside `ECG_Analysis.exe`
in the distribution folder so users can adjust settings without recompiling.

If no `user_settings.json` is present, the application creates one with
default values on first run.
