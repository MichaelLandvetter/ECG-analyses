from pathlib import Path


def test_docs_include_ecg_and_ver_terminology():
    text = Path("docs/ecg-compat-aliases.md").read_text().lower()

    assert "ecg" in text, "Docs should mention ECG terminology."
    assert "ver" in text, "Docs should mention VER terminology."
