import pytest


def test_ver_wrapper_api_contract_symbols_present():
    mod = pytest.importorskip("ver_analysis_engine")

    required = {
        "detect_ecg_peaks",
        "refresh_ecg_analysis_config",
        "detect_ver_peaks",
        "refresh_analysis_config",
    }

    missing_attrs = sorted([name for name in required if not hasattr(mod, name)])
    assert not missing_attrs, f"Missing wrapper attrs: {missing_attrs}"


def test_ver_wrapper_all_includes_required_when_defined():
    mod = pytest.importorskip("ver_analysis_engine")
    exported = getattr(mod, "__all__", None)

    # Only enforce membership if __all__ is explicitly defined.
    if exported is not None:
        exported_set = set(exported)
        required = {
            "detect_ecg_peaks",
            "refresh_ecg_analysis_config",
            "detect_ver_peaks",
            "refresh_analysis_config",
        }
        missing = sorted(required - exported_set)
        assert not missing, f"Missing in __all__: {missing}"
