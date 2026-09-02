import importlib
import pytest

MODULES = [
    "ecg_main", "ecg_pipeline", "ecg_loader", "ecg_report", "ecg_scope",
    "ecg_config", "ecg_classifier", "ecg_extended_report", "ecg_acquisition",
    "ecg_analysis_engine",
]

OPTIONAL_DEP_KEYWORDS = (
    "PyQt6", "scipy", "matplotlib", "pywt", "serial", "pyqtgraph"
)

@pytest.mark.parametrize("module_name", MODULES)
def test_wrapper_modules_import(module_name):
    try:
        mod = importlib.import_module(module_name)
        assert mod is not None
    except ModuleNotFoundError as e:
        if any(k in str(e) for k in OPTIONAL_DEP_KEYWORDS):
            pytest.skip(f"Optional dependency missing for {module_name}: {e}")
        raise