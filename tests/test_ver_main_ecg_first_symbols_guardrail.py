from pathlib import Path


def test_ver_main_uses_ecg_first_peak_symbol():
    p = Path("src/ecg_analyses/ver/ver_main.py")
    s = p.read_text()

    # Guardrail: ver_main should call ECG-first symbol name.
    assert "detect_ecg_peaks(" in s

    # Guardrail: avoid reintroducing legacy callsite usage in ver_main.
    assert "detect_ver_peaks(" not in s


def test_ver_main_boundary_points_to_ecg_engine_comment():
    p = Path("src/ecg_analyses/ver/ver_main.py")
    s = p.read_text()

    # Keep boundary comment aligned with transition intent.
    assert "REPLACEMENT BOUNDARY — see ecg_analysis_engine.py" in s
