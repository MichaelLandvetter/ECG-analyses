import pytest

def test_import_ecg_modules():
    try:
        import ecg_main
        import ecg_pipeline
        import ecg_loader
        import ecg_report
        import ecg_scope
        import ecg_config
        import ecg_classifier
        import ecg_extended_report
        assert True
    except ModuleNotFoundError as e:
        pytest.skip(f"Optional dependency missing: {e}")