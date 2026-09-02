from pathlib import Path
import re

import pytest


SYMBOL_PATTERN = re.compile(r"`([a-zA-Z_][a-zA-Z0-9_]*)`")


def test_doc_symbols_exist_in_wrapper_module():
    doc = Path("docs/ecg-compat-aliases.md").read_text()
    symbols = {m.group(1) for m in SYMBOL_PATTERN.finditer(doc)}

    # Scope this test to known API names we care about in this transition doc.
    expected = {
        "detect_ecg_peaks",
        "refresh_ecg_analysis_config",
        "detect_ver_peaks",
        "refresh_analysis_config",
    }
    documented = symbols & expected
    assert documented == expected, (
        f"Doc is missing expected symbol(s): {sorted(expected - documented)}"
    )

    mod = pytest.importorskip("ver_analysis_engine")
    missing = sorted(name for name in documented if not hasattr(mod, name))
    assert not missing, f"Documented symbol(s) missing from wrapper: {missing}"
