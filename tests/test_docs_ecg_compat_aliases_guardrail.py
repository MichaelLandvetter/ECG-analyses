from pathlib import Path


def test_ecg_compat_aliases_doc_exists_and_mentions_contract():
    p = Path("docs/ecg-compat-aliases.md")
    assert p.exists(), "Missing docs/ecg-compat-aliases.md"

    s = p.read_text()

    required = [
        "detect_ecg_peaks",
        "refresh_ecg_analysis_config",
        "detect_ver_peaks",
        "refresh_analysis_config",
    ]
    for token in required:
        assert token in s, f"Missing token in docs/ecg-compat-aliases.md: {token}"
