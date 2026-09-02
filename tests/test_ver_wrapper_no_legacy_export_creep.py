import pytest


def test_ver_wrapper_does_not_export_unapproved_legacy_names():
    mod = pytest.importorskip("ver_analysis_engine")
    exported = getattr(mod, "__all__", None)

    # If __all__ is not defined, skip strict export-surface enforcement.
    if exported is None:
        pytest.skip("__all__ not defined; no strict export surface to validate")

    exported_set = set(exported)

    # Canonical approved surface for this transition period.
    approved = {
        "detect_ecg_peaks",
        "refresh_ecg_analysis_config",
        "detect_ver_peaks",
        "refresh_analysis_config",
    }

    # Known-risk names we do NOT want exposed via wrapper exports.
    disallowed = {
        "detect_peaks",      # ambiguous legacy/generic
        "refresh_config",    # ambiguous legacy/generic
        "ver_detect_peaks",  # stale naming pattern
        "ver_refresh_config",
    }

    unexpected = sorted(exported_set - approved)
    present_disallowed = sorted(exported_set & disallowed)

    assert not present_disallowed, (
        f"Disallowed legacy names exported in __all__: {present_disallowed}"
    )
    assert not unexpected, (
        f"Unexpected export surface drift in __all__: {unexpected}; "
        f"approved={sorted(approved)}"
    )
