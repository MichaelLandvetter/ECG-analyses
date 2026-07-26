"""Module for collecting Human-in-the-Loop validation data for Machine Learning."""

import csv
from pathlib import Path
import numpy as np
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTableWidget,
                             QTableWidgetItem, QComboBox, QPushButton, QMessageBox,
                             QLabel, QScrollArea, QLineEdit)
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import Qt
from ver_classifier import evaluate_ver_peak
from ver_settings import SettingsManager

# Canonical 15-column header for training_data.csv (v2 schema).
# If an existing file has a different header, the user is warned before any
# append so that old and new rows are never silently mixed.
_NEW_CSV_HEADER = [
    "Block", "Power", "Scale_Hz", "P1_Latency", "P2_Latency", "P3_Latency", "SNR",
    "Computer_Label", "Computer_Reason",
    "Human_Label", "Human_Reason", "Observer_ID", "Review_Confidence",
    "File name", "Species",
]

# Practical defaults offered in the Human Reason drop-down.  The field is
# editable so observers can type free-form text when none of these apply.
_HUMAN_REASON_DEFAULTS = ["", "Confirmed", "Noise", "Artifact", "Unclear", "Other"]


class HumanValidationDialog(QDialog):
    def __init__(self, block_data, png_path=None, parent=None, filename="", species=""):
        super().__init__(parent)
        self.setWindowTitle("Machine Learning - Human Validation")
        self.resize(1400, 780)
        self.block_data = block_data
        self.filename = filename
        self.species = species
        self.human_overrides = []

        self._settings_manager = SettingsManager()
        _all_settings = self._settings_manager.load_settings()
        self._default_observer_id = _all_settings.get("ML_LOGGER", {}).get("observer_id", "")

        main_layout = QVBoxLayout(self)

        # --- 1. TOP: The Report Image ---
        if png_path and Path(png_path).exists():
            img_label = QLabel()
            pixmap = QPixmap(str(png_path))
            pixmap = pixmap.scaled(1350, 350, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            img_label.setPixmap(pixmap)
            img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

            scroll_area = QScrollArea()
            scroll_area.setWidget(img_label)
            scroll_area.setWidgetResizable(True)
            scroll_area.setMaximumHeight(370)
            main_layout.addWidget(scroll_area)
        else:
            lbl = QLabel("Report Image not found.")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            main_layout.addWidget(lbl)

        # --- 2. MIDDLE: Instructions ---
        lbl = QLabel("<b>Human-in-the-Loop Validation</b> &nbsp;&nbsp;|&nbsp;&nbsp; "
                     "1. Review the generated report above. &nbsp;&nbsp;|&nbsp;&nbsp; "
                     "2. Compare it with the computer's predictions below. &nbsp;&nbsp;|&nbsp;&nbsp; "
                     "3. Correct any mistakes. &nbsp;&nbsp;|&nbsp;&nbsp; "
                     "4. Click Save to append to your ML dataset.")
        lbl.setWordWrap(True)
        main_layout.addWidget(lbl)

        metadata_lbl = QLabel(
            f"<b>Source file:</b> {self.filename or '(not set)'}<br>"
            f"<b>Species:</b> {self.species or '(not set)'}"
        )
        metadata_lbl.setWordWrap(True)
        metadata_lbl.setStyleSheet("background-color: #f5f5f5; padding: 6px; border: 1px solid #d0d0d0;")
        main_layout.addWidget(metadata_lbl)

        # --- Observer ID (dialog-level — applied to every row in this session) ---
        observer_layout = QHBoxLayout()
        observer_layout.addWidget(QLabel("<b>Observer ID:</b>"))
        self.observer_id_input = QLineEdit()
        self.observer_id_input.setPlaceholderText("Enter your observer ID (applied to all rows)")
        self.observer_id_input.setMaximumWidth(300)
        if self._default_observer_id:
            self.observer_id_input.setText(self._default_observer_id)
        observer_layout.addWidget(self.observer_id_input)
        observer_layout.addStretch()
        main_layout.addLayout(observer_layout)

        # --- 3. Validation Table ---
        # Columns: Block | Peak Power | Scale (Hz) | P1 Latency | P2 Latency |
        #          P3 Latency | SNR | Computer Label | Computer Reason |
        #          Human Validation | Human Reason | Review Confidence
        self.table = QTableWidget()
        self.table.setColumnCount(12)
        self.table.setHorizontalHeaderLabels([
            "Block", "Peak Power", "Scale (Hz)", "P1 Latency", "P2 Latency",
            "P3 Latency", "SNR", "Computer Label", "Computer Reason",
            "Human Validation", "Human Reason", "Review Confidence",
        ])
        self.table.setRowCount(len(block_data))
        self.combos = []        # Human Validation (col 9)
        self.reason_combos = [] # Human Reason     (col 10)
        self.conf_combos = []   # Review Confidence (col 11)

        for row_idx, data in enumerate(block_data):
            self.table.setItem(row_idx, 0, QTableWidgetItem(str(data['block'])))
            self.table.setItem(row_idx, 1, QTableWidgetItem(f"{data['power']:.2e}"))
            self.table.setItem(row_idx, 2, QTableWidgetItem(f"{data['scale']:.1f}"))
            self.table.setItem(row_idx, 3, QTableWidgetItem(f"{data['p1_lat']:.1f}"))
            self.table.setItem(row_idx, 4, QTableWidgetItem(f"{data['p2_lat']:.1f}"))
            self.table.setItem(row_idx, 5, QTableWidgetItem(f"{data['p3_lat']:.1f}"))
            self.table.setItem(row_idx, 6, QTableWidgetItem(f"{data['snr']:.2f}"))

            comp_lbl = "VER" if data['computer_label'] else "No VER"
            self.table.setItem(row_idx, 7, QTableWidgetItem(comp_lbl))
            self.table.setItem(row_idx, 8, QTableWidgetItem(data['reason']))

            # Col 9 — Human Validation: defaults to the computer label
            combo = QComboBox()
            combo.addItems(["VER", "No VER"])
            combo.setCurrentText(comp_lbl)
            self.table.setCellWidget(row_idx, 9, combo)
            self.combos.append(combo)

            # Col 10 — Human Reason: editable combo with practical defaults
            reason_combo = QComboBox()
            reason_combo.setEditable(True)
            reason_combo.addItems(_HUMAN_REASON_DEFAULTS)
            reason_combo.setCurrentIndex(0)
            self.table.setCellWidget(row_idx, 10, reason_combo)
            self.reason_combos.append(reason_combo)

            # Col 11 — Review Confidence: 1 (low) / 2 (medium) / 3 (high)
            conf_combo = QComboBox()
            conf_combo.addItems(["1", "2", "3"])
            conf_combo.setCurrentIndex(1)  # default to 2
            self.table.setCellWidget(row_idx, 11, conf_combo)
            self.conf_combos.append(conf_combo)

        self.table.resizeColumnsToContents()
        self.table.resizeRowsToContents()
        self.table.horizontalHeader().setStretchLastSection(True)
        main_layout.addWidget(self.table)

        # --- 4. BOTTOM: Save Button ---
        btn_layout = QHBoxLayout()
        save_btn = QPushButton("💾 Save Validations to CSV and create the Report files")
        save_btn.setStyleSheet("font-weight: bold; background-color: #4472C4; color: white; padding: 10px;")
        save_btn.clicked.connect(self.save_data)
        btn_layout.addStretch()
        btn_layout.addWidget(save_btn)
        main_layout.addLayout(btn_layout)

    def save_data(self):
        csv_path = Path.cwd() / "training_data.csv"
        file_exists = csv_path.exists()
        self.human_overrides = []

        # --- Backward-compatibility guard ---
        # If the file already exists, verify its header matches the current schema.
        # A mismatch means the file was written by an older version of the app.
        # Rather than silently mixing incompatible rows we stop and tell the user
        # to rename or delete the old file first.
        if file_exists:
            try:
                with open(csv_path, newline="", encoding="utf-8") as check_f:
                    existing_header = next(csv.reader(check_f), None)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Could not read existing CSV header: {e}")
                return
            if existing_header != _NEW_CSV_HEADER:
                QMessageBox.warning(
                    self,
                    "Schema Mismatch — Action Required",
                    "The existing <b>training_data.csv</b> was created with an older column schema "
                    "and cannot be safely appended to.\n\n"
                    "Please rename or delete the old file, then save again.\n\n"
                    f"Expected columns: {', '.join(_NEW_CSV_HEADER)}\n"
                    f"Found columns:    {', '.join(existing_header or [])}",
                )
                return

        observer_id = self.observer_id_input.text().strip()

        # --- Pre-write validation: Human_Reason is required when labels differ ---
        # Collect all row data first so we can validate everything before
        # opening the CSV, preventing any partial writes on failure.
        rows_to_write = []
        for i, data in enumerate(self.block_data):
            is_ver = self.combos[i].currentText() == "VER"
            human_label = 1 if is_ver else 0
            comp_label = 1 if data['computer_label'] else 0
            human_reason = self.reason_combos[i].currentText().strip()
            review_confidence = self.conf_combos[i].currentText().strip()

            if human_label != comp_label and not human_reason:
                QMessageBox.warning(
                    self,
                    "Human Reason Required",
                    f"Row {i + 1} (Block: {data['block']}): <b>Human Reason</b> must be filled in "
                    f"when Human Label differs from Computer Label.\n\n"
                    f"Please select or enter a reason before saving.",
                )
                return

            rows_to_write.append((is_ver, human_label, comp_label, human_reason, review_confidence, data))

        try:
            with open(csv_path, mode="a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                if not file_exists:
                    writer.writerow(_NEW_CSV_HEADER)

                for is_ver, human_label, comp_label, human_reason, review_confidence, data in rows_to_write:
                    self.human_overrides.append(is_ver)
                    writer.writerow([
                        data['block'], data['power'], data['scale'],
                        data['p1_lat'], data['p2_lat'], data['p3_lat'], data['snr'],
                        comp_label, data['reason'],
                        human_label, human_reason, observer_id, review_confidence,
                        self.filename, self.species,
                    ])

            # Persist observer_id so the dialog is prefilled on the next run
            all_settings = self._settings_manager.load_settings()
            all_settings.setdefault("ML_LOGGER", {})["observer_id"] = observer_id
            self._settings_manager.save_settings(all_settings)

            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not save training data: {e}")


def launch_ml_logger(
    session_wavelets,
    session_wavelet_freqs,
    epoch_time_ms,
    session_ver_peaks,
    labels,
    png_path=None,
    parent=None,
    filename="",
    species="",
):
    """Helper function to extract features and launch the UI."""
    manager = SettingsManager()
    cfg = manager.load_settings().get("CLASSIFIER_CONFIG", {})
    snr_threshold = cfg.get("snr_threshold", 2.0)

    block_data = []
    
    for idx, wavelet in enumerate(session_wavelets):
        peak_idx = np.unravel_index(np.argmax(wavelet), wavelet.shape)
        peak_scale = float(session_wavelet_freqs[peak_idx[0]])
        peak_power = float(wavelet[peak_idx])

        ver_peaks = session_ver_peaks[idx] if session_ver_peaks and idx < len(session_ver_peaks) else None
        
        p1_lat = 0.0; p2_lat = 0.0; p3_lat = 0.0; p2_snr = 0.0
        if ver_peaks is not None:
            p1_d, p2_d, p3_d = ver_peaks.get('Peak-1',{}), ver_peaks.get('Peak-2',{}), ver_peaks.get('Peak-3',{})
            p1_lat = float(p1_d['latency_ms']) if p1_d.get('found') else 0.0
            p2_lat = float(p2_d['latency_ms']) if p2_d.get('found') else 0.0
            p3_lat = float(p3_d['latency_ms']) if p3_d.get('found') else 0.0
            p2_snr = float(p2_d['snr']) if p2_d.get('found') else 0.0
            
        # Look for this line inside launch_ml_logger:
        is_ver, failure_details = evaluate_ver_peak(peak_scale, peak_power, p1_lat if p1_lat else None, p2_lat if p2_lat else None, p3_lat if p3_lat else None, p2_snr)
        
        # --- NEW REASON LOGIC ---
        if is_ver:
            reason = "Passed"
        else:
            failed_tests = [test_name for test_name, passed in failure_details.items() if not passed]
            reason = "Failed:\n" + "\n".join(failed_tests)
        # ------------------------

        block_data.append({
            'block': labels[idx] if idx < len(labels) else f"Block {idx+1}",
            'power': peak_power, 'scale': peak_scale,
            'p1_lat': p1_lat, 'p2_lat': p2_lat, 'p3_lat': p3_lat, 'snr': p2_snr,
            'computer_label': is_ver, 'reason': reason
        })

    dialog = HumanValidationDialog(block_data, png_path, parent, filename=filename, species=species)
    
    if dialog.exec() == QDialog.DialogCode.Accepted:
        return dialog.human_overrides
    return None