@echo off
REM build_ecg.bat — Build the ECG Analysis executable using PyInstaller.
REM
REM Usage (from the repo root):
REM   build_ecg.bat
REM
REM Output: dist\ECG_Analysis\ECG_Analysis.exe
REM
REM Prerequisites:
REM   pip install pyinstaller
REM   pip install -r requirements.txt   (or install dependencies manually)
REM
REM MIXED REPO NOTE: this repository contains both ecg_*.py and ver_*.py
REM modules.  Only ecg_main.py (and the modules it imports transitively) are
REM bundled.  Standalone VER scripts (ver_USB_test.py, etc.) that are never
REM imported are excluded automatically.

echo.
echo === ECG Analysis — PyInstaller build ===
echo.

REM Verify Python / PyInstaller are available.
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found on PATH.  Ensure Python 3.10+ is installed.
    exit /b 1
)

pyinstaller --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: pyinstaller not found.  Run: pip install pyinstaller
    exit /b 1
)

REM Clean previous build artefacts (optional — comment out to reuse cached objects).
if exist "build\ECG_Analysis" (
    echo Removing previous build\ECG_Analysis ...
    rmdir /s /q "build\ECG_Analysis"
)
if exist "dist\ECG_Analysis" (
    echo Removing previous dist\ECG_Analysis ...
    rmdir /s /q "dist\ECG_Analysis"
)

echo Running PyInstaller with ecg.spec ...
pyinstaller ecg.spec

if errorlevel 1 (
    echo.
    echo BUILD FAILED.  Check the output above for errors.
    echo Common fixes:
    echo   - Add missing packages to hiddenimports in ecg.spec
    echo   - Add missing data files to datas in ecg.spec
    echo   - Re-run with "console=True" in ecg.spec for runtime error details
    exit /b 1
)

echo.
echo BUILD SUCCEEDED.
echo Executable: dist\ECG_Analysis\ECG_Analysis.exe
echo.
echo To distribute: copy the entire dist\ECG_Analysis\ folder.
echo The folder is self-contained; no Python installation is required on the
echo target machine.
