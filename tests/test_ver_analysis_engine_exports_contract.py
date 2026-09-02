import pytest


def test_ver_analysis_engine_exports_contract():
    # Use top-level wrapper import pattern used by existing wrapper tests.
    mod = pytest.importorskip("ver_analysis_engine")

    required = {
        "detect_ecg_peaks",
        "refresh_ecg_analysis_config",
        "detect_ver_peaks",         # backward compatibility
        "refresh_analysis_config",  # backward compatibility
    }

    for name in required:
        assert hasattr(mod, name), f"Missing attribute: {name}"

    exported = set(getattr(mod, "__all__", []))
    # Enforce only when __all__ is explicitly defined.
    if exported:
        missing = required - exported
        assert not missing, f"Missing in __all__: {sorted(missing)}"