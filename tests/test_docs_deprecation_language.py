from pathlib import Path


def test_docs_include_deprecation_direction_for_legacy_aliases():
    text = Path("docs/ecg-compat-aliases.md").read_text().lower()

    # Must mention legacy/deprecated intent.
    assert ("deprecated" in text) or ("legacy" in text), (
        "Docs should describe legacy/deprecated alias status."
    )

    # Must show directional mapping intent (old -> new naming).
    required_terms = [
        "detect_ver_peaks",
        "detect_ecg_peaks",
        "refresh_analysis_config",
        "refresh_ecg_analysis_config",
    ]
    missing = [term for term in required_terms if term not in text]
    assert not missing, f"Docs missing expected alias terms: {missing}"

    # Minimal directionality wording check.
    direction_markers = ["use", "instead", "alias", "mapped", "points to", "prefer"]
    assert any(marker in text for marker in direction_markers), (
        "Docs should indicate which names to prefer/use instead."
    )
