from pathlib import Path
import importlib
import pytest

ROOT = Path(__file__).resolve().parents[1]

ECG_MAIN_WINDOW_FILE = ROOT / "src/ecg_analyses/ecg/ecg_main_window.py"
ECG_ANALYSIS_ENGINE_FILE = ROOT / "src/ecg_analyses/ecg/ecg_analysis_engine.py"


def test_ecg_main_window_boundary_import():
    if not ECG_MAIN_WINDOW_FILE.exists():
        pytest.skip("ecg_main_window boundary not present on this branch")
    mod = importlib.import_module("src.ecg_analyses.ecg.ecg_main_window")
    assert hasattr(mod, "ECGMainWindow")


def test_ecg_analysis_engine_boundary_exports():
    if not ECG_ANALYSIS_ENGINE_FILE.exists():
        pytest.skip("ecg_analysis_engine boundary not present on this branch")
    mod = importlib.import_module("src.ecg_analyses.ecg.ecg_analysis_engine")
    for name in (
        "detect_ecg_peaks",
        "refresh_ecg_analysis_config",
        "detect_ver_peaks",
        "refresh_analysis_config",
    ):
        assert hasattr(mod, name), f"Missing export: {name}"
