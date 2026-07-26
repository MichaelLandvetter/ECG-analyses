"""Module for managing user settings via an external JSON file."""
import copy
import json
from pathlib import Path

class SettingsManager:
    def __init__(self):
        # The JSON file will live right next to the executable/script
        self.settings_file = Path.cwd() / "user_settings.json"
        
        # --- THE MASTER BLUEPRINT ---
        self.default_settings = {
            "ACQ_CONFIG": {
                "sample_rate": 250,
                "simulate_realtime": True,
                "source_mode": "File"
            },
            "FILE_FORMATS": {
                "SD-card": {
                    "delimiter": "\t",
                    "trigger_column": 0,
                    "eeg_column": 2,
                    "skip_header": 0,
                    "trigger_mode": "threshold",
                    "trigger_threshold": 0.5
                },
                "LabChart": {
                    "delimiter": "\t",
                    "trigger_column": 0,
                    "eeg_column": 1,
                    "skip_header": 0,
                    "trigger_mode": "interval",
                    "trigger_threshold": 0.1
                }
            },
            "FILTER_CONFIG": {
                "lowcut_hz": 12.0,
                "highcut_hz": 32.0,
                "order": 4,
                "sample_rate": 250
            },
            "EPOCH_CONFIG": {
                "pre_stim_ms": 100.0,
                "post_stim_ms": 400.0,
                "flashes_per_session": 120,
                "num_sessions": 10,
                "artifact_rejection_enabled": True,
                "artifact_exclusion_uv": 0.01
            },
            "PEAK_CONFIG": {
                "SNR_THRESHOLD": 2.0,
                "BASELINE_START_MS": -100,
                "BASELINE_END_MS": 0
            },
            "CLASSIFIER_CONFIG": {
                "min_scale": 8.0,
                "max_scale": 32.0,
                "min_power": 1.0e-7,
                "p2_min_latency": 40.0,
                "p2_max_latency": 120.0,
                "ipi_min": 20.0,
                "ipi_max": 85.0,
                "p3_p2_max": 120.0,
                "snr_threshold": 2.0,
                "peak_detection_mode": "legacy_top3"
            },
            "SERIAL_CONFIG": {
                "port": "COM4",
                "baud_rate": 921600,
                "timeout": 2.0,
                "trigger_high_threshold": 0.7,
                "trigger_low_threshold": 0.3
            },
            "WAVELET_CONFIG": {
                "bandwidth": 1.0,
                "center_freq": 1.0,
                "num_freqs": 320,
                "freq_min": 1.0,
                "freq_max": 100.0
            },
            "DISPLAY_CONFIG": {
                "scroll_seconds": 10,
                "max_epoch_overlays": 120,
                "scroll_max_fps": 30
            },
            "SPECIES": {
                "Rainbow trout": "Rainbow trout",
                "Atlantic salmon": "Atlantic salmon",
                "Nile tilapia": "Nile tilapia",
                "African sharptooth catfish": "African sharptooth catfish",
                "Channel catfish": "Channel catfish",
                "Gilthead seabream": "Gilthead seabream",
                "European seabass": "European seabass",
                "Coho salmon": "Coho salmon"
            },
            "METADATA_CONFIG": {
                "species": ""
            },
            "ML_LOGGER": {
                "observer_id": ""
            }
        }
        self.settings = self.load_settings()

    def _inject_missing_defaults(self, settings_dict):
        """Recursively fill missing keys from default_settings without overwriting user values."""
        def _merge_missing(target, defaults, parent_path=""):
            changed = False
            for key, default_value in defaults.items():
                key_path = f"{parent_path}.{key}" if parent_path else key
                if key not in target:
                    if isinstance(default_value, dict):
                        target[key] = copy.deepcopy(default_value)
                    else:
                        target[key] = default_value
                    changed = True
                elif isinstance(default_value, dict):
                    if isinstance(target[key], dict):
                        changed = _merge_missing(target[key], default_value, key_path) or changed
                    else:
                        actual_type = type(target[key]).__name__
                        print(
                            f"Warning: Resetting '{key_path}' to defaults - expected dict but found {actual_type}."
                        )
                        target[key] = copy.deepcopy(default_value)
                        changed = True
            return changed

        if isinstance(settings_dict, dict):
            return _merge_missing(settings_dict, self.default_settings)

        return False
        
    def load_settings(self):
        """Loads the settings from the JSON file, or creates it if missing."""
        if not self.settings_file.exists():
            initial_settings = copy.deepcopy(self.default_settings)
            self.save_settings(initial_settings)
            return initial_settings
        
        try:
            with open(self.settings_file, "r") as f:
                user_settings = json.load(f)
            
            # Smart Update: If we add new features later, this ensures old JSON files
            # don't crash the program. It safely injects missing keys.
            needs_save = self._inject_missing_defaults(user_settings)
            
            if needs_save:
                self.save_settings(user_settings)
                
            return user_settings
        except Exception as e:
            print(f"Warning: Could not read settings ({e}). Using defaults.")
            return copy.deepcopy(self.default_settings)

    def save_settings(self, settings_dict=None):
        """Saves the given dictionary to the JSON file. Defaults to self.settings."""
        # If no specific dictionary is passed, use the one stored in memory!
        if settings_dict is None:
            settings_dict = self.settings

        try:
            with open(self.settings_file, "w") as f:
                json.dump(settings_dict, f, indent=4)
        except Exception as e:
            print(f"Warning: Could not save settings ({e}).")