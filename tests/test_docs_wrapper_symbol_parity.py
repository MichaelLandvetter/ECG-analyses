from pathlib import Path
import re

import pytest


SYMBOL_PATTERN = re.compile(r"`([a-zA-Z_][a-zA-Z0-9_]*)`")


def test_doc_symbols_exist_in_wrapper_module():
    doc = Path("docs/ecg-compat-aliases.md").read_text()
    symbols = {m.group(1) for m in SYMBOL_PATTERN.finditer(doc)}

    expected = {
        "detect_ecg_peaks",
        "refresh_ecg_analysis_config",
        "detect_ver_peaks",
        "refresh_analysis_config",
    }

    # Accept either markdown-code formatting (`name`) or plain text mentions.
    documented = {name for name in expected if (name in symbols) or (name in doc)}
    assert documented == expected, (
        f"Doc is missing expected symbol(s): {sorted(expected - documented)}"
    )

    mod = pytest.importorskip("ecg_analysis_engine")
    missing = sorted(name for name in documented if not hasattr(mod, name))
    assert not missing, f"Documented symbol(s) missing from wrapper: {missing}"