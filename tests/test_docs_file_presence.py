from pathlib import Path


def test_ecg_compat_alias_doc_exists_and_nonempty():
    p = Path("docs/ecg-compat-aliases.md")
    assert p.exists(), "docs/ecg-compat-aliases.md should exist"

    content = p.read_text().strip()
    assert content, "docs/ecg-compat-aliases.md should not be empty"
