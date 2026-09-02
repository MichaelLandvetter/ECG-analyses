from pathlib import Path


CANONICAL = "docs/ecg-compat-aliases.md"


def test_doc_guardrails_reference_canonical_doc_path():
    tests_dir = Path("tests")
    guardrail_files = sorted(tests_dir.glob("test_docs*.py"))

    assert guardrail_files, "Expected doc guardrail test files matching tests/test_docs*.py"

    missing = []
    for file in guardrail_files:
        text = file.read_text()
        if CANONICAL not in text:
            missing.append(str(file))

    assert not missing, (
        "These doc guardrail tests do not reference canonical doc path "
        f"'{CANONICAL}': {missing}"
    )
