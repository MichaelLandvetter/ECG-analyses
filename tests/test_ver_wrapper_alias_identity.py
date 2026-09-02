import pytest


def test_legacy_aliases_point_to_ecg_first_functions():
    mod = pytest.importorskip("ver_analysis_engine")

    assert hasattr(mod, "detect_ecg_peaks")
    assert hasattr(mod, "detect_ver_peaks")
    assert hasattr(mod, "refresh_ecg_analysis_config")
    assert hasattr(mod, "refresh_analysis_config")

    # Identity guardrails: aliases should point to same callable objects.
    assert mod.detect_ver_peaks is mod.detect_ecg_peaks
    assert mod.refresh_analysis_config is mod.refresh_ecg_analysis_config
