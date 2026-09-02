import pytest


def test_ver_wrapper_public_symbols_are_callables():
    mod = pytest.importorskip("ver_analysis_engine")

    required = [
        "detect_ecg_peaks",
        "refresh_ecg_analysis_config",
        "detect_ver_peaks",
        "refresh_analysis_config",
    ]

    missing = [name for name in required if not hasattr(mod, name)]
    assert not missing, f"Missing required wrapper symbols: {missing}"

    non_callable = [name for name in required if not callable(getattr(mod, name))]
    assert not non_callable, f"Non-callable wrapper symbols: {non_callable}"
