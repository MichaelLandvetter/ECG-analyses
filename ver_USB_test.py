import sys
import time
import struct
import numpy as np
import serial
import serial.tools.list_ports  
from PyQt6 import QtCore, QtWidgets
import pyqtgraph as pg

import cv2
from PIL import ImageGrab

BUFFER_SIZE = 15000  
PACKET_SIZE = 9  
HEADER = b'\xA5\x5A'


class SplitHardwareWorker(QtCore.QThread):
    frame_ready = QtCore.pyqtSignal(np.ndarray, np.ndarray)
    error_occurred = QtCore.pyqtSignal(str) 
    # New signal to pass the live data rate string to the GUI
    hz_updated = QtCore.pyqtSignal(str)

    def __init__(self, port, baud=921600):
        super().__init__()
        self.port = port
        self.baud = baud
        self.running = True

        self.eeg_win = np.zeros(BUFFER_SIZE, dtype=np.float32)
        self.trig_win = np.zeros(BUFFER_SIZE, dtype=np.int16)

    def run(self):
        try:
            ser = serial.Serial(self.port, self.baud, timeout=0.05)
            byte_stream = bytearray()

            last_time = time.perf_counter()
            packet_count = 0
            report_interval = 250  

            while self.running:
                if ser.in_waiting > 0:
                    byte_stream.extend(ser.read(ser.in_waiting))

                while len(byte_stream) >= PACKET_SIZE:
                    idx = byte_stream.find(HEADER)
                    if idx == -1:
                        byte_stream.clear()
                        break
                    if idx > 0:
                        del byte_stream[:idx]
                        if len(byte_stream) < PACKET_SIZE: break

                    if byte_stream[PACKET_SIZE - 1] != 0x01:
                        del byte_stream[0:1]
                        continue

                    packet = byte_stream[:PACKET_SIZE]
                    del byte_stream[:PACKET_SIZE]

                    _, trigger_state, raw_eeg, _ = struct.unpack('<2sHf1s', packet)

                    self.eeg_win = np.roll(self.eeg_win, -1)
                    self.trig_win = np.roll(self.trig_win, -1)

                    self.eeg_win[-1] = raw_eeg
                    self.trig_win[-1] = trigger_state

                    packet_count += 1
                    if packet_count >= report_interval:
                        current_time = time.perf_counter()
                        elapsed = current_time - last_time
                        actual_hz = packet_count / elapsed
                        
                        # EMIT DATA RATE TO GUI INSTEAD OF PRINTING TO TERMINAL
                        self.hz_updated.emit(f"Data Rate: {actual_hz:.2f} Hz")
                        
                        packet_count = 0
                        last_time = current_time

                self.frame_ready.emit(self.eeg_win, self.trig_win)
                time.sleep(0.004)  

            ser.close()
        except Exception as err:
            self.error_occurred.emit(str(err))


class WaveletAnalyzerGUI(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Live EEG & Trigger View")
        self.resize(800, 500) 

        self.worker = None 
#         self.is_recording = False
#         self.video_writer = None
#         self.record_timer = QtCore.QTimer()
#         self.record_timer.timeout.connect(self.capture_video_frame)

        # Main Layout Container
        central_widget = QtWidgets.QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QtWidgets.QVBoxLayout(central_widget)

        # Top Control Panel
        control_layout = QtWidgets.QHBoxLayout()
        
        # COM Port Selector Components
        control_layout.addWidget(QtWidgets.QLabel("COM Port:"))
        self.combo_ports = QtWidgets.QComboBox()
        self.combo_ports.setFixedWidth(120)
        control_layout.addWidget(self.combo_ports)
        
        self.btn_refresh = QtWidgets.QPushButton("🔄 Refresh")
        self.btn_refresh.clicked.connect(self.refresh_com_ports)
        control_layout.addWidget(self.btn_refresh)
        
        self.btn_connect = QtWidgets.QPushButton("🔌 Connect")
        self.btn_connect.clicked.connect(self.toggle_connection)
        control_layout.addWidget(self.btn_connect)
        
        # Recording Button
#         control_layout.addSpacing(30)
#         self.btn_record = QtWidgets.QPushButton("🔴 Start Recording")
#         self.btn_record.setFixedWidth(150)
#         self.btn_record.setEnabled(False) 
#         self.btn_record.clicked.connect(self.toggle_recording)
#         control_layout.addWidget(self.btn_record)
        
        # --- NEW VISUAL DATA RATE LABEL ---
        control_layout.addSpacing(30)
        self.lbl_hz = QtWidgets.QLabel("Data Rate: -- Hz")
        # Give it a slightly distinct style so it stands out
        self.lbl_hz.setStyleSheet("color: black; font-size: 13px;")
        control_layout.addWidget(self.lbl_hz)
        
        control_layout.addStretch() 
        main_layout.addLayout(control_layout)

        # Graph Area Canvas
        self.layout_canvas = pg.GraphicsLayoutWidget()
        main_layout.addWidget(self.layout_canvas)

        # Row 1: Raw EEG Plot
        self.p_eeg = self.layout_canvas.addPlot(row=0, col=0, title="EEG Signal")
        self.curve_eeg = self.p_eeg.plot(pen='w', name="EEG")
        self.p_eeg.setLabel('left', 'Amplitude (µV)')
        
        # Row 2: Trigger Plot
        self.p_trig = self.layout_canvas.addPlot(row=1, col=0, title="Digital Trigger Pulses")
        self.curve_trig = self.p_trig.plot(pen='r', name="Trigger")
        self.p_trig.setLabel('left', 'State (On/Off)')
        self.p_trig.setLabel('bottom', 'Samples (250 Hz)')

        self.p_trig.setXLink(self.p_eeg)

        self.refresh_com_ports()

    def refresh_com_ports(self):
        self.combo_ports.clear()
        ports = serial.tools.list_ports.comports()
        if not ports:
            self.combo_ports.addItem("No Ports Found")
            self.btn_connect.setEnabled(False)
            return
        for port in ports:
            self.combo_ports.addItem(port.device)
        self.btn_connect.setEnabled(True)

    def toggle_connection(self):
        if self.worker is None or not self.worker.isRunning():
            selected_port = self.combo_ports.currentText()
            if selected_port == "No Ports Found":
                return
                
            self.worker = SplitHardwareWorker(port=selected_port)
            self.worker.frame_ready.connect(self.process_live_data)
            self.worker.error_occurred.connect(self.handle_worker_error)
            
            # CONNECT THE NEW LIVE HZ UPDATER SIGNAL
            self.worker.hz_updated.connect(self.lbl_hz.setText)
            
            self.worker.start()
            
            self.btn_connect.setText("🔌 Disconnect")
            self.combo_ports.setEnabled(False)
            self.btn_refresh.setEnabled(False)
            #self.btn_record.setEnabled(True) 
        else:
            self.stop_worker()

    def stop_worker(self):
        if self.worker and self.worker.isRunning():
#             if self.is_recording:
#                 self.toggle_recording() 
            self.worker.running = False
            self.worker.wait()
            
        self.btn_connect.setText("🔌 Connect")
        self.combo_ports.setEnabled(True)
        self.btn_refresh.setEnabled(True)
#         self.btn_record.setEnabled(False)
        # Reset the label text when disconnecting
        self.lbl_hz.setText("Data Rate: -- Hz")

    def handle_worker_error(self, error_msg):
        self.stop_worker()
        QtWidgets.QMessageBox.critical(self, "Serial Error", f"Connection Lost:\n{error_msg}")

    def process_live_data(self, eeg_data, trigger_data):
        filtered_eeg = eeg_data - np.mean(eeg_data)
        self.curve_eeg.setData(filtered_eeg)
        self.curve_trig.setData(trigger_data)

#     def toggle_recording(self):
#         if not self.is_recording:
#             filename = f"EEG_Capture_{int(time.time())}.mp4"
#             fps = 20
#             fourcc = cv2.VideoWriter_fourcc(*'mp4v')
#             
#             geo = self.geometry()
#             self.recording_bbox = (geo.x(), geo.y(), geo.x() + geo.width(), geo.y() + geo.height())
#             self.video_writer = cv2.VideoWriter(filename, fourcc, fps, (geo.width(), geo.height()))
#             
#             self.record_timer.start(50) 
#             self.is_recording = True
#             self.btn_record.setText("⏹️ Stop Recording")
#             print(f"Recording saving to: {filename}")
#         else:
#             self.record_timer.stop()
#             if self.video_writer:
#                 self.video_writer.release()
#             self.is_recording = False
#             self.btn_record.setText("🔴 Start Recording")
#             print("Recording successfully saved.")

#     def capture_video_frame(self):
#         if self.is_recording and self.video_writer:
#             try:
#                 geo = self.geometry()
#                 scale = self.devicePixelRatio() 
#                 
#                 x1 = int(geo.x() * scale)
#                 y1 = int(geo.y() * scale)
#                 x2 = int((geo.x() + geo.width()) * scale)
#                 y2 = int((geo.y() + geo.height()) * scale)
#                 
#                 bbox = (x1, y1, x2, y2)
#                 img = ImageGrab.grab(bbox=bbox)
#                 frame = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
#                 
#                 if (frame.shape[1], frame.shape[0]) != (geo.width(), geo.height()):
#                     frame = cv2.resize(frame, (geo.width(), geo.height()))
#                 
#                 self.video_writer.write(frame)
#             except Exception as e:
#                 print(f"Error capturing frame: {e}")

    def closeEvent(self, event):
        self.stop_worker()
        event.accept()


if __name__ == '__main__':
    app = QtWidgets.QApplication(sys.argv)
    main_win = WaveletAnalyzerGUI()
    main_win.show()
    sys.exit(app.exec())