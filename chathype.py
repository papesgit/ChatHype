import sys
import os
import json
import subprocess
import pandas as pd
import numpy as np
from scipy.signal import find_peaks, savgol_filter
from scipy.interpolate import make_interp_spline
from datetime import timedelta
import webbrowser
import re
import logging
import tempfile
import shutil 

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QLabel, QPushButton,
    QLineEdit, QFileDialog, QMessageBox, QHBoxLayout, QDoubleSpinBox,
    QProgressBar, QToolTip, QSlider, QCheckBox, QListWidget, QListWidgetItem, QComboBox,
    QTextEdit  # Imported for log display
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QPalette, QColor, QFont
import pyqtgraph as pg

# Configure logging
logging.basicConfig(
    filename='app_debug.log',
    filemode='w',
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Path to twitch-dl.pyz executable
if getattr(sys, 'frozen', False):
    # If the application is run as a bundle
    BASE_DIR = sys._MEIPASS
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Path to the twitch-dl.pyz file
twitch_dl_pyz = os.path.join(BASE_DIR, 'twitch-dl.pyz')

# Function to check if twitch-dl.pyz exists
def is_twitch_dl_available():
    return os.path.exists(twitch_dl_pyz)

# Function to check if Python is available
def is_python_available():
    # Skip Python check if running as a bundled application
    if getattr(sys, 'frozen', False):
        return True  # Assume Python is available when bundled

    # Otherwise, check for Python as originally intended
    try:
        subprocess.run([sys.executable, '--version'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return True
    except Exception:
        return False


if not is_python_available() or not is_twitch_dl_available():
    # Initialize a temporary QApplication to show the QMessageBox before exiting
    # Initialize a QApplication if none exists for showing error message
    if QApplication.instance() is None:
        temp_app = QApplication(sys.argv)

    QMessageBox.critical(
        None, "Error",
        f"twitch-dl.pyz not found or Python is not available.\n"
        f"Please ensure twitch-dl.pyz is in {BASE_DIR} and Python is installed."
    )
    sys.exit(1)

def select_existing_chatlog(self):
    options = QFileDialog.Options()
    files, _ = QFileDialog.getOpenFileNames(
        self, "Select Existing Chat Log Files", "", "JSON Files (*.json)", options=options
    )
    if files:
        for file_name in files:
            self.chat_files.append(file_name)  # Append each selected file to chat_files
            self.process_chatlog(file_name)    # Process each file independently
            
        # Set chat_file_path to the first loaded file as the default
        self.chat_file_path = self.chat_files[0] if self.chat_files else None

        # Update instructions if a chat file is successfully loaded
        self.instruction_label.setText("Chat log loaded. You can adjust the time interval or other settings.")
    else:
        # Inform the user if no files were selected
        QMessageBox.warning(
            self, "No Files Selected",
            "No chat log files were selected. Please select at least one file to proceed."
        )

    


class DownloadChatThread(QThread):
    """
    Thread to download the chat log using TwitchDownloaderCLI.
    """
    progress_signal = pyqtSignal(int)
    finished_signal = pyqtSignal(str)
    error_signal = pyqtSignal(str)
    log_signal = pyqtSignal(str)

    def __init__(self, vod_id, output_filename):
        super().__init__()
        self.vod_id = vod_id
        self.output_filename = output_filename

    def run(self):
        try:
            command = [
                'TwitchDownloaderCLI',  # Replace with full path if necessary
                '--mode', 'ChatDownload',
                '--id', self.vod_id,
                '--output', self.output_filename
            ]
            self.log_signal.emit(f"Executing command: {' '.join(command)}")

            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                bufsize=1,
                encoding='utf-8',
                errors='replace'
            )

            progress_pattern = re.compile(r'Progress:\s*(\d+)%')
            self.progress_signal.emit(-1)

            while True:
                line = process.stdout.readline()
                if not line:
                    break
                self.log_signal.emit(line.strip())
                match = progress_pattern.search(line)
                if match:
                    percentage = int(match.group(1))
                    if 0 <= percentage <= 100:
                        self.progress_signal.emit(percentage)
                else:
                    self.progress_signal.emit(-1)

            process.wait()
            if process.returncode != 0:
                stderr = process.stderr.read()
                error_message = stderr.strip() if stderr.strip() else "Unknown error occurred."
                self.error_signal.emit(error_message)
                self.log_signal.emit(f"Chat log download failed with error: {error_message}")
            else:
                self.finished_signal.emit(self.output_filename)
                self.log_signal.emit("Chat log downloaded successfully.")
        except Exception as e:
            self.error_signal.emit(str(e))
            self.log_signal.emit(f"Exception occurred during chat log download: {e}")


# Path to the cache directory in the root folder of the app
cache_dir = os.path.join(BASE_DIR, 'vod_cache')

# Ensure the cache directory exists
os.makedirs(cache_dir, exist_ok=True)

class DownloadVODThread(QThread):
    """
    Thread to download the VOD video using twitch-dl.
    """
    progress_signal = pyqtSignal(int)
    finished_signal = pyqtSignal(str)
    error_signal = pyqtSignal(str)
    log_signal = pyqtSignal(str)

    def __init__(self, vod_id, output_filename, chapter, start_time, end_time, quality, rate_limit=None):
        super().__init__()
        self.vod_id = vod_id
        self.output_filename = re.sub(r'[^\w\-_. ]', '_', output_filename)
        self.chapter = chapter
        self.start_time = start_time
        self.end_time = end_time
        self.quality = quality
        self.rate_limit = rate_limit  # New parameter for rate limit

    def run(self):
        try:
            command = [
                sys.executable, '-X', 'utf8',  # Enforce UTF-8
                twitch_dl_pyz,
                'download', '-q', self.quality,
                self.vod_id,
                '--cache-dir', cache_dir,
                '--no-join'
            ]

            if self.chapter:
                command.extend(['-c', self.chapter])
            if self.start_time:
                command.extend(['-s', self.start_time])
            if self.end_time:
                command.extend(['-e', self.end_time])

            # Add rate limit to command if specified
            if self.rate_limit:
                command.extend(['-r', self.rate_limit])

            self.log_signal.emit(f"Executing command: {' '.join(command)}")

            env = os.environ.copy()
            env['PYTHONIOENCODING'] = 'utf-8'
            env['LC_ALL'] = 'en_US.UTF-8'

            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                bufsize=1,
                encoding='utf-8',
                errors='replace',
                env=env
            )

            progress_pattern = re.compile(r'Downloading video\.\.\.\s*(\d+)%')
            self.progress_signal.emit(-1)

            while True:
                line = process.stdout.readline()
                if not line:
                    break
                self.log_signal.emit(line.strip())
                match = progress_pattern.search(line)
                if match:
                    percentage = int(match.group(1))
                    if 0 <= percentage <= 100:
                        self.progress_signal.emit(percentage)
                else:
                    self.progress_signal.emit(-1)

            process.wait()
            if process.returncode != 0:
                stderr = process.stderr.read()
                error_message = stderr.strip() if stderr.strip() else "Unknown error occurred."
                self.error_signal.emit(error_message)
                self.log_signal.emit(f"VOD download failed with error: {error_message}")
            else:
                self.finished_signal.emit(self.output_filename)
                self.log_signal.emit("VOD downloaded successfully.")
        except Exception as e:
            self.error_signal.emit(str(e))
            self.log_signal.emit(f"Exception occurred during VOD download: {e}")



# Removed DownloadFFmpegThread since twitch-dl does not handle FFmpeg downloads

class ProcessThread(QThread):
    """
    Thread to process the chat log file.
    """
    finished_signal = pyqtSignal(pd.DataFrame)  # Emitting processed DataFrame with rates
    error_signal = pyqtSignal(str)

    def __init__(self, chat_file_path, time_interval, emotes_to_track):
        super().__init__()
        self.chat_file_path = chat_file_path
        self.time_interval = time_interval  # Time interval in seconds
        self.emotes_to_track = emotes_to_track  # List of emotes to filter

    def run(self):
        try:
            # Load chat data
            with open(self.chat_file_path, 'r', encoding='utf-8') as chat_file:
                chat_data = json.load(chat_file)

            # Normalize JSON to DataFrame
            if isinstance(chat_data, list):
                # If chat_data is a list of comments
                chat_df = pd.json_normalize(chat_data)
            elif isinstance(chat_data, dict) and 'comments' in chat_data:
                # If chat_data has a 'comments' key
                chat_df = pd.json_normalize(chat_data['comments'])
            else:
                raise ValueError("Invalid chat log format.")

            chat_df['vod_offset'] = chat_df['content_offset_seconds']

            # Define the hype emotes to track or user-specified emotes
            if self.emotes_to_track:
                hype_emotes = self.emotes_to_track
            else:
                hype_emotes = [
                    "PogChamp", "Pog", "PogU", "Poggers", "KEKW", "EZ", "HYPERS", "POGGERS", "LETSGO", 
                    "CATJAM", "OMEGALUL", "WeirdChamp", "AYAYA", "PepeJAM", "HYPE", "LULW", 
                    "WIDEPEEPOHAPPY", "Clap", "KomodoHype", "5Head", "POGSLIDE", "PepeLaugh", 
                    "PepoG", "peepoClap", "POGCRAZY", "FeelsWowMan", "PartyParrot", 
                    "peepoWow", "monkaS", "TriHard", "popCat", "POGGIN", "widepeepoHappy", 
                    "POGGIES", "monkaW", "NOPERS", "COGGERS", "blobDance", "POGGY", "Wowee"
                ]

            # Create a regex pattern to match the hype emotes (non-capturing, case-insensitive)
            pattern = re.compile(r'\b(?:' + '|'.join(map(re.escape, hype_emotes)) + r')\b', re.IGNORECASE)

            # Process General Chat Rate
            general_chat_rate_df = chat_df.copy()

            # Group and calculate chat rate
            time_interval = self.time_interval  # Use the passed time_interval
            max_offset = general_chat_rate_df['vod_offset'].max()
            bins = np.arange(0, max_offset + time_interval, time_interval)
            general_chat_rate_df['time_bin'] = pd.cut(
                general_chat_rate_df['vod_offset'],
                bins=bins,
                right=False,
                labels=bins[:-1]
            ).astype(float)  # Cast to float to avoid dtype issues

            general_chat_rate = general_chat_rate_df.groupby('time_bin', observed=False).size().reset_index(name='chat_count')
            # Retain base rates without smoothing
            general_chat_rate['chat_rate'] = general_chat_rate['chat_count']

            # Process Pogs Rate
            pogs_chat_rate_df = chat_df[chat_df['message.body'].str.contains(pattern, na=False)].copy()
            pogs_chat_rate_df['time_bin'] = pd.cut(
                pogs_chat_rate_df['vod_offset'],
                bins=bins,
                right=False,
                labels=bins[:-1]
            ).astype(float)  # Cast to float to avoid dtype issues
            pogs_chat_rate = pogs_chat_rate_df.groupby('time_bin', observed=False).size().reset_index(name='pogs_count')
            # Retain base rates without smoothing
            pogs_chat_rate['pogs_rate'] = pogs_chat_rate['pogs_count']

            # Compute Average Rate with Scaling Factor
            POGS_SCALING_FACTOR = 10  # Adjust this factor as needed
            combined_rate = pd.merge(
                general_chat_rate[['time_bin', 'chat_rate']],
                pogs_chat_rate[['time_bin', 'pogs_rate']],
                on='time_bin',
                how='left'
            )
            combined_rate['pogs_rate'] = combined_rate['pogs_rate'].fillna(0)  # Replace NaN with 0 for intervals with no pogs
            combined_rate['average_rate'] = combined_rate['chat_rate'] + (combined_rate['pogs_rate'] * POGS_SCALING_FACTOR)  # Adjusted average rate

            # Emit the combined DataFrame
            self.finished_signal.emit(combined_rate)

        except Exception as e:
            self.error_signal.emit(str(e))

class TwitchHighlighterApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ChatHype")
        self.setGeometry(100, 100, 500, 600)  # Increased height to accommodate new button and log display

        self.chart_windows = {}  # Dictionary to store each chart window by file path

        self.chat_files = []  # To store multiple chat log file paths
        self.process_threads = {}  # To store threads for each chat log
        self.processed_data = {}  # To store processed data for each chat log
        self.current_chat_index = 0  # Track currently selected chat log index


        # Initialize offset_seconds
        self.offset_seconds = 0

        # Initialize chat_file_path and vod_file_path
        self.chat_file_path = None
        self.vod_file_path = None

        # Initialize chart_window
        self.chart_window = None

        # Initialize rates
        self.general_chat_rate = None
        self.pogs_rate = None
        self.average_rate = None  # New attribute for average rate

        # Initialize smoothing window
        self.smoothing_window = 50  # Default smoothing window

        # Initialize emotes to track
        self.emotes_to_track = []

        # Main widget and layout
        self.main_widget = QWidget()
        self.setCentralWidget(self.main_widget)
        self.layout = QVBoxLayout(self.main_widget)

        # VOD URL input
        self.vod_label = QLabel("Enter Twitch VOD URL:")
        self.vod_label.setStyleSheet("color: white;")
        self.layout.addWidget(self.vod_label)

        self.vod_input = QLineEdit()
        self.vod_input.setPlaceholderText("https://www.twitch.tv/videos/123456789")
        self.layout.addWidget(self.vod_input)

        # **Chapter Selection**
        self.chapter_label = QLabel("Download Specific Chapter (Optional):")
        self.chapter_label.setStyleSheet("color: white;")
        self.layout.addWidget(self.chapter_label)

        self.chapter_input = QLineEdit()
        self.chapter_input.setPlaceholderText("Enter chapter number or leave empty to prompt")
        self.layout.addWidget(self.chapter_input)

        # **Start Time Input**
        self.start_label = QLabel("Start Time (hh:mm:ss, Optional):")
        self.start_label.setStyleSheet("color: white;")
        self.layout.addWidget(self.start_label)

        self.start_input = QLineEdit()
        self.start_input.setPlaceholderText("Enter start time, e.g., 00:10:00")
        self.layout.addWidget(self.start_input)

        # **End Time Input**
        self.end_label = QLabel("End Time (hh:mm:ss, Optional):")
        self.end_label.setStyleSheet("color: white;")
        self.layout.addWidget(self.end_label)

        self.end_input = QLineEdit()
        self.end_input.setPlaceholderText("Enter end time, e.g., 01:00:00")
        self.layout.addWidget(self.end_input)

        # **Quality Selection**
        self.quality_label = QLabel("Select Video Quality:")
        self.quality_label.setStyleSheet("color: white;")
        self.layout.addWidget(self.quality_label)

        self.quality_input = QLineEdit()
        self.quality_input.setPlaceholderText("e.g., 1080p, 720p60, source")
        self.layout.addWidget(self.quality_input)

        # Rate Limit Input
        rate_limit_layout = QHBoxLayout()
        rate_limit_label = QLabel("Rate Limit (3m=3MB/s 500k=500KB/s):")
        rate_limit_label.setStyleSheet("color: white;")
        rate_limit_layout.addWidget(rate_limit_label)

        self.rate_limit_input = QLineEdit()
        self.rate_limit_input.setPlaceholderText("Enter rate limit, e.g., 500k")
        rate_limit_layout.addWidget(self.rate_limit_input)

        self.layout.addLayout(rate_limit_layout)

        # Buttons Layout
        buttons_layout = QHBoxLayout()

        # Download Chat Log button
        self.download_chat_button = QPushButton("Download Chat Log")
        self.download_chat_button.clicked.connect(self.download_chat_log)
        buttons_layout.addWidget(self.download_chat_button)

        # Download VOD button
        self.download_vod_button = QPushButton("Download VOD")
        self.download_vod_button.clicked.connect(self.download_vod)
        buttons_layout.addWidget(self.download_vod_button)

        self.layout.addLayout(buttons_layout)

        # Download FFMPEG button
        self.download_ffmpeg_button = QPushButton("Download FFMPEG")
        self.download_ffmpeg_button.clicked.connect(self.download_ffmpeg)
        self.layout.addWidget(self.download_ffmpeg_button)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        self.layout.addWidget(self.progress_bar)

        # Select Existing Chat Log button
        self.select_chatlog_button = QPushButton("Select Existing Chat Log")
        self.select_chatlog_button.clicked.connect(lambda: select_existing_chatlog(self))
        self.layout.addWidget(self.select_chatlog_button)


        # Emote Filtering Section
        self.emote_filter_label = QLabel("Emotes to Track (comma-separated):")
        self.emote_filter_label.setStyleSheet("color: white;")
        self.layout.addWidget(self.emote_filter_label)

        self.emote_filter_input = QLineEdit()
        self.emote_filter_input.setPlaceholderText("e.g., PogChamp, KEKW, LUL")
        self.layout.addWidget(self.emote_filter_input)

        # Instructions label
        self.instruction_label = QLabel(
            "Please enter a valid Twitch VOD URL and press 'Download Chat Log' or 'Download VOD' to start, "
            "or select an existing chat log."
        )
        self.instruction_label.setWordWrap(True)
        self.instruction_label.setStyleSheet("color: white;")
        self.layout.addWidget(self.instruction_label)

        # Configuration Management
        self.config_label = QLabel("Configuration Management:")
        self.config_label.setStyleSheet("color: white;")
        self.layout.addWidget(self.config_label)

        config_layout = QHBoxLayout()

        self.config_name_input = QLineEdit()
        self.config_name_input.setPlaceholderText("Configuration Name")
        config_layout.addWidget(self.config_name_input)

        self.save_config_button = QPushButton("Save Configuration")
        self.save_config_button.clicked.connect(self.save_configuration)
        config_layout.addWidget(self.save_config_button)

        self.load_config_button = QPushButton("Load Configuration")
        self.load_config_button.clicked.connect(self.load_configuration)
        config_layout.addWidget(self.load_config_button)

        self.layout.addLayout(config_layout)

        self.config_list = QListWidget()
        self.config_list.itemClicked.connect(self.select_config_item)
        self.layout.addWidget(self.config_list)

        # Initialize configurations directory
        self.config_dir = os.path.join(BASE_DIR, 'configurations')
        os.makedirs(self.config_dir, exist_ok=True)
        self.load_configurations_list()

        # Initialize resolution_spinbox to ensure it exists early
        self.resolution_spinbox = QDoubleSpinBox()
        self.resolution_spinbox.setDecimals(3)
        self.resolution_spinbox.setRange(0.001, 10.0)
        self.resolution_spinbox.setSingleStep(0.1)
        self.resolution_spinbox.setValue(1.0)  # Default value

        # Add Log Display Widget
        self.log_display = QTextEdit()
        self.log_display.setReadOnly(True)
        self.log_display.setStyleSheet("background-color: #1e1e1e; color: white;")
        self.layout.addWidget(QLabel("Application Logs:"))
        self.layout.addWidget(self.log_display)

    def closeEvent(self, event):
        """
        Ensure that all threads are properly terminated when closing the application.
        """
        # Terminate download_chat_thread if running
        if hasattr(self, 'download_chat_thread') and self.download_chat_thread.isRunning():
            self.download_chat_thread.terminate()
            self.download_chat_thread.wait()

        # Terminate download_vod_thread if running
        if hasattr(self, 'download_vod_thread') and self.download_vod_thread.isRunning():
            self.download_vod_thread.terminate()
            self.download_vod_thread.wait()

        # Terminate process_thread if running
        if hasattr(self, 'process_thread') and self.process_thread.isRunning():
            self.process_thread.terminate()
            self.process_thread.wait()

        event.accept()

    def download_ffmpeg(self):
        """
        Downloads FFmpeg into the root directory using TwitchDownloaderCLI.
        """
        # Define the path for FFmpeg in the root directory
        ffmpeg_path = os.path.join(BASE_DIR, "ffmpeg.exe")

        # Check if FFmpeg already exists
        if os.path.exists(ffmpeg_path):
            QMessageBox.information(self, "FFMPEG Download", "FFMPEG is already downloaded in the root directory.")
            return

        # Show a message to indicate the download has started
        QMessageBox.information(self, "FFMPEG Download", "Downloading FFMPEG. This may take a few moments...")

        # Define the command to download FFMPEG using TwitchDownloaderCLI with the correct command for ffmpeg
        command = [
            'TwitchDownloaderCLI', 'ffmpeg', '--download'
        ]

        try:
            # Run the command to download FFMPEG
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True
            )

            # Monitor progress in the console/logs
            for line in process.stdout:
                self.append_log(line.strip())

            process.wait()
            if process.returncode == 0:
                QMessageBox.information(self, "FFMPEG Download", "FFMPEG downloaded successfully.")
            else:
                QMessageBox.critical(self, "FFMPEG Download Failed", "Failed to download FFMPEG. Please check the logs.")
                error_log = process.stderr.read().strip()
                self.append_log(error_log)

        except Exception as e:
            QMessageBox.critical(self, "Error", f"An error occurred while downloading FFMPEG: {e}")
            self.append_log(f"FFMPEG Download Error: {e}")

    def download_chat_log(self):
        """
        Initiates the download of the chat log using twitch-dl.
        """
        vod_url = self.vod_input.text().strip()
        if not vod_url:
            QMessageBox.critical(self, "Error", "Please enter a valid Twitch VOD URL.")
            return

        # Extract VOD ID from URL
        vod_id_match = re.search(r'/videos/(\d+)', vod_url)
        if not vod_id_match:
            QMessageBox.critical(self, "Error", "Invalid VOD URL format.")
            return

        vod_id = vod_id_match.group(1)
        output_filename = f"chatlog_{vod_id}.json"

        # Show the progress bar
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)  # Set range for percentage-based progress
        self.progress_bar.setValue(0)

        # Disable buttons while downloading
        self.download_chat_button.setEnabled(False)
        self.download_vod_button.setEnabled(False)
        self.select_chatlog_button.setEnabled(False)
        # Removed FFmpeg button

        # Start the download thread
        self.download_chat_thread = DownloadChatThread(vod_id, output_filename)
        self.download_chat_thread.progress_signal.connect(self.update_progress)
        self.download_chat_thread.finished_signal.connect(self.chat_download_finished)
        self.download_chat_thread.error_signal.connect(self.download_error)
        self.download_chat_thread.log_signal.connect(self.append_log)  # Connect log signal
        self.download_chat_thread.start()

    def download_vod(self):
        """
        Initiates the download of the VOD video using twitch-dl.
        """
        vod_url = self.vod_input.text().strip()
        if not vod_url:
            QMessageBox.critical(self, "Error", "Please enter a valid Twitch VOD URL.")
            return

        # Extract VOD ID from URL
        vod_id_match = re.search(r'/videos/(\d+)', vod_url)
        if not vod_id_match:
            QMessageBox.critical(self, "Error", "Invalid VOD URL format.")
            return

        vod_id = vod_id_match.group(1)
        output_filename = f"vod_{vod_id}.mp4"  # Assuming mp4 format

        # **Get optional parameters**
        chapter = self.chapter_input.text().strip()
        start_time = self.start_input.text().strip()
        end_time = self.end_input.text().strip()
        quality = self.quality_input.text().strip()
        rate_limit = self.rate_limit_input.text().strip()  # Get rate limit from user input

        # Show the progress bar
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)  # Set range for percentage-based progress
        self.progress_bar.setValue(0)

        # Disable buttons while downloading
        self.download_chat_button.setEnabled(False)
        self.download_vod_button.setEnabled(False)
        self.select_chatlog_button.setEnabled(False)

        # **Start the VOD download thread**
        self.download_vod_thread = DownloadVODThread(
            vod_id, output_filename, chapter, start_time, end_time, quality, rate_limit=rate_limit
        )
        self.download_vod_thread.progress_signal.connect(self.update_progress)
        self.download_vod_thread.finished_signal.connect(self.vod_download_finished)
        self.download_vod_thread.error_signal.connect(self.download_error)
        self.download_vod_thread.log_signal.connect(self.append_log)  # Connect log signal
        self.download_vod_thread.start()


    def update_progress(self, value):
        """
        Updates the progress bar based on the emitted value.
        """
        if value == -1:
            # Indeterminate progress
            self.progress_bar.setRange(0, 0)  # Makes the progress bar marquee
        else:
            # Determinate progress
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(value)

    def chat_download_finished(self, output_filename):
        """
        Handles the completion of the chat log download.
        """
        # Hide the progress bar
        self.progress_bar.setVisible(False)
        self.progress_bar.setValue(0)

        # Re-enable buttons
        self.download_chat_button.setEnabled(True)
        self.download_vod_button.setEnabled(True)
        self.select_chatlog_button.setEnabled(True)
        # Removed FFmpeg button

        QMessageBox.information(
            self, "Success", f"Chat log downloaded successfully as {output_filename}."
        )

        # Set the chat_file_path and start processing
        self.process_chatlog(output_filename)

    def vod_download_finished(self, output_filename):
        """
        Handles the completion of the VOD download.
        """
        # Hide the progress bar
        self.progress_bar.setVisible(False)
        self.progress_bar.setValue(0)

        # Re-enable buttons
        self.download_chat_button.setEnabled(True)
        self.download_vod_button.setEnabled(True)
        self.select_chatlog_button.setEnabled(True)

        # Set the vod_file_path for future use
        self.vod_file_path = output_filename

        # Step 1: Create a temporary file list for the .ts files
        try:
            # List all .ts files in the cache directory and sort them
            ts_files = sorted([os.path.join(cache_dir, f) for f in os.listdir(cache_dir) if f.endswith('.ts')])

            if not ts_files:
                raise FileNotFoundError("No .ts files found in the cache directory.")

            # Write the list of .ts files to a temporary text file
            with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as temp_file:
                for ts_file in ts_files:
                    temp_file.write(f"file '{ts_file}'\n")
                file_list_path = temp_file.name  # Get the name of the temporary file

            self.append_log("File list created for concatenation.")

        except Exception as e:
            error_msg = f"Error during file list creation: {e}"
            QMessageBox.critical(self, "File List Error", error_msg)
            self.append_log(error_msg)
            return  # Exit if file list creation fails

        # Step 2: Use ffmpeg to concatenate and convert to mp4
        try:
            ffmpeg_command = [
                "ffmpeg",
                "-f", "concat",
                "-safe", "0",
                "-i", file_list_path,
                "-c", "copy",
                os.path.abspath(output_filename)
            ]

            self.append_log(f"Executing FFmpeg command: {' '.join(ffmpeg_command)}")

            # Run the FFmpeg command to join .ts files to output mp4
            subprocess.run(ffmpeg_command, check=True)
            self.append_log("FFmpeg joining and conversion to MP4 completed successfully.")
            QMessageBox.information(self, "Success", f"VOD saved as {output_filename}.")

            # Step 3: Delete the cache directory if conversion was successful
            shutil.rmtree(cache_dir)  # Delete all files and folders in the cache directory
            self.append_log("Cache directory deleted after successful conversion.")

        except subprocess.CalledProcessError as e:
            error_msg = f"FFmpeg joining failed: {e}"
            QMessageBox.critical(self, "FFmpeg Error", error_msg)
            self.append_log(error_msg)
        finally:
            # Clean up the temporary file
            if os.path.exists(file_list_path):
                os.remove(file_list_path)

    def download_error(self, error_message):
        """
        Handles any errors during the download process.
        """
        # Hide the progress bar
        self.progress_bar.setVisible(False)
        self.progress_bar.setValue(0)

        # Re-enable buttons
        self.download_chat_button.setEnabled(True)
        self.download_vod_button.setEnabled(True)
        self.select_chatlog_button.setEnabled(True)
        # Removed FFmpeg button

        QMessageBox.critical(
            self, "Download Error",
            f"Failed to download:\n{error_message}\nPlease ensure the VOD URL is correct and twitch-dl is functioning properly."
        )
    def initialize_chart_window(self, chat_file_path):
        """
        Creates a new chart window for a specific chat log.
        """
        chart_window = QWidget()
        chart_window.setWindowTitle(f"Chat Activity for {os.path.basename(chat_file_path)}")
        chart_window.setGeometry(100, 100, 1000, 800)
        chart_layout = QVBoxLayout()
        chart_window.setLayout(chart_layout)
        
        # Resolution Control
        resolution_layout = QHBoxLayout()
        resolution_label = QLabel("Time Interval (seconds):")
        resolution_label.setStyleSheet("color: white;")
        resolution_layout.addWidget(resolution_label)

        resolution_layout.addWidget(self.resolution_spinbox)
        chart_layout.addLayout(resolution_layout)

        # Emote Filtering Section in Chart Window
        emote_filter_label = QLabel("Emotes to Track (comma-separated):")
        emote_filter_label.setStyleSheet("color: white;")
        chart_layout.addWidget(emote_filter_label)

        emote_filter_input = QLineEdit()
        emote_filter_input.setPlaceholderText("e.g., PogChamp, KEKW, LUL")
        emote_filter_input.setText(', '.join(self.emotes_to_track))
        chart_layout.addWidget(emote_filter_input)
        self.emote_filter_input_chart = emote_filter_input  # To access in methods

        # Create controls and plot
        self.create_controls(chart_layout)

        # Add Export and Offset Controls
        settings_layout = QHBoxLayout()
        
        export_button = QPushButton("Export Highlights")
        export_button.clicked.connect(self.export_highlights)
        settings_layout.addWidget(export_button)

        offset_label = QLabel("Timestamp Offset (seconds):")
        offset_label.setStyleSheet("color: white;")
        settings_layout.addWidget(offset_label)

        self.offset_input = QLineEdit()
        self.offset_input.setPlaceholderText("Enter offset, e.g., -10 or 15")
        self.offset_input.setText("0")  # Default to zero offset
        self.offset_input.setFixedWidth(60)  # Set a fixed width for the offset input box
        settings_layout.addWidget(self.offset_input)

        settings_layout.addStretch()
        chart_layout.addLayout(settings_layout)

        # Extract VOD ID from the provided chat log filename
        vod_id_match = re.search(r'chatlog_(\d+)\.json', os.path.basename(chat_file_path))
        if vod_id_match:
            vod_id = vod_id_match.group(1)
            self.vod_input.setText(f"https://www.twitch.tv/videos/{vod_id}")
        else:
            logging.error("VOD ID not found in chat log filename.")
            QMessageBox.warning(
                self, "VOD ID Not Found",
                "Unable to extract VOD ID from chat log filename. Please enter it manually in the VOD URL field."
            )

        # Update plot with the current selections
        self.update_plot()

        # Connect signals
        self.resolution_spinbox.valueChanged.connect(self.on_resolution_changed)
        self.emote_filter_input_chart.textChanged.connect(self.on_emote_filter_changed)

        # Show the new chart window
        chart_window.show()

        # Return the new chart window
        return chart_window


    def processing_finished(self, combined_rate, chat_file_path):
        """
        Receives the processed chat rate data for each chat log and opens a new chart window.
        """
        # Store the processed data in `processed_data` with `chat_file_path` as the key
        self.processed_data[chat_file_path] = combined_rate

        # Update the current chat rate data with this new file's data
        self.general_chat_rate = combined_rate[['time_bin', 'chat_rate']].copy()
        self.pogs_rate = combined_rate[['time_bin', 'pogs_rate']].copy()
        self.average_rate = combined_rate[['time_bin', 'average_rate']].copy()

        # Recalculate the maximum chat rate to account for new data
        self.max_chat_rate = max(
            self.general_chat_rate['chat_rate'].max(),
            self.pogs_rate['pogs_rate'].max(),
            self.average_rate['average_rate'].max()
        )

        # Set initial threshold and prominence parameters based on max chat rate
        self.initial_threshold = 0.2 * self.max_chat_rate
        self.initial_prominence = 0.1 * self.max_chat_rate
        self.initial_width = 1.0
        self.initial_distance = 5.0
        
        # Apply initial smoothing
        self.apply_initial_smoothing()
        
        # Open a new chart window for this chat log
        new_window = self.initialize_chart_window(chat_file_path)
        self.chart_windows[chat_file_path] = new_window  # Store the window in the dictionary

        # Display success message for each file processed
        QMessageBox.information(self, "Processing Completed", f"Chat log {os.path.basename(chat_file_path)} processed successfully.")



    def apply_initial_smoothing(self):
        """
        Applies initial smoothing to chat_rate, pogs_rate, and average_rate based on the default smoothing window.
        """
        # Define parameters for the Savitzky-Golay filter
        window_length = self.smoothing_window if self.smoothing_window % 2 != 0 else self.smoothing_window + 1
        polyorder = 3       # Polynomial order, adjust as needed

        # Ensure window_length is not greater than the data size
        if len(self.general_chat_rate) < window_length:
            window_length = len(self.general_chat_rate) if len(self.general_chat_rate) % 2 != 0 else len(self.general_chat_rate) - 1
            if window_length < 3:
                window_length = 3  # Minimum window length for savgol_filter

        try:
            # Apply smoothing to chat_rate using Savitzky-Golay filter
            self.general_chat_rate['chat_rate_smooth'] = savgol_filter(
                self.general_chat_rate['chat_rate'].values, window_length, polyorder
            )

            # Apply smoothing to pogs_rate using Savitzky-Golay filter
            self.pogs_rate['pogs_rate_smooth'] = savgol_filter(
                self.pogs_rate['pogs_rate'].values, window_length, polyorder
            )

            # Apply smoothing to average_rate using Savitzky-Golay filter
            self.average_rate['average_rate_smooth'] = savgol_filter(
                self.average_rate['average_rate'].values, window_length, polyorder
            )
        except Exception as e:
            QMessageBox.critical(
                self.chart_window, "Smoothing Error",
                f"An error occurred while applying initial smoothing:\n{e}"
            )
            logging.error(f"Initial Smoothing Error: {e}")

    def apply_smoothing_and_update(self):
        """
        Applies smoothing based on the current smoothing window and updates the plot.
        """
        if not all([df is not None and not df.empty for df in [self.general_chat_rate, self.pogs_rate, self.average_rate]]):
            logging.warning("One or more DataFrames are not initialized or are empty.")
            return  # Exit early if data is not ready

        # Define parameters for the Savitzky-Golay filter
        window_length = self.smoothing_window if self.smoothing_window % 2 != 0 else self.smoothing_window + 1
        polyorder = 3  # Polynomial order

        # Ensure window_length is appropriate for the data size
        if len(self.general_chat_rate) < window_length:
            window_length = len(self.general_chat_rate) if len(self.general_chat_rate) % 2 != 0 else len(self.general_chat_rate) - 1
            if window_length < 3:
                window_length = 3  # Minimum window length for savgol_filter

        try:
            # Apply smoothing to chat_rate using Savitzky-Golay filter
            self.general_chat_rate['chat_rate_smooth'] = savgol_filter(
                self.general_chat_rate['chat_rate'].values, window_length, polyorder
            )

            # Apply smoothing to pogs_rate using Savitzky-Golay filter
            self.pogs_rate['pogs_rate_smooth'] = savgol_filter(
                self.pogs_rate['pogs_rate'].values, window_length, polyorder
            )

            # Apply smoothing to average_rate using Savitzky-Golay filter
            self.average_rate['average_rate_smooth'] = savgol_filter(
                self.average_rate['average_rate'].values, window_length, polyorder
            )

            # Update the plot with new smoothing
            self.update_plot()
        except Exception as e:
            QMessageBox.critical(
                self.chart_window, "Smoothing Error",
                f"An error occurred while applying smoothing:\n{e}"
            )
            logging.error(f"Smoothing Error: {e}")

    def processing_error(self, error_message):
        """
        Handles any errors during chat log processing.
        """
        QMessageBox.critical(
            self, "Processing Error",
            f"Failed to process chat log:\n{error_message}"
        )

    def process_chatlog(self, chat_file_path):
        """
        Starts the ProcessThread for a given chat log file.
        """
        time_interval = self.resolution_spinbox.value()
        emotes_to_track = [emote.strip() for emote in self.emote_filter_input.text().split(',') if emote.strip()]
        
        process_thread = ProcessThread(chat_file_path, time_interval, emotes_to_track)
        process_thread.finished_signal.connect(lambda df, path=chat_file_path: self.processing_finished(df, path))
        process_thread.error_signal.connect(self.processing_error)
        
        self.process_threads[chat_file_path] = process_thread  # Store the thread for later reference
        process_thread.start()


    def create_controls(self, chart_layout):
        """
        Creates the interactive controls and plot.
        """
        # Define custom TimeAxisItem for hh:mm:ss format
        class TimeAxisItem(pg.AxisItem):
            def tickStrings(self, values, scale, spacing):
                return [str(timedelta(seconds=int(value))) for value in values]

        # PlotWidget
        self.plot_widget = pg.PlotWidget(axisItems={'bottom': TimeAxisItem(orientation='bottom')})
        self.plot_widget.setBackground('#2b2b2b')  # Dark background
        self.plot_widget.getAxis('left').setTextPen('w')
        self.plot_widget.getAxis('bottom').setTextPen('w')
        self.plot_widget.getAxis('left').setPen('w')
        self.plot_widget.getAxis('bottom').setPen('w')
        self.plot_widget.setLabel('left', 'Chat Rate (Messages per Interval)', color='w')
        self.plot_widget.setLabel('bottom', 'Time (hh:mm:ss)', color='w')
        chart_layout.addWidget(self.plot_widget)

        # Initialize highlight periods
        self.highlight_periods = []
        self.highlight_values = []  # To store chat rates at highlights

        # Create sliders, spin boxes, and labels
        control_layout = QHBoxLayout()

        # Define scaling factors for sliders
        threshold_scale = 1000  # For mapping slider to threshold value
        prominence_scale = 100  # For mapping slider to prominence value
        width_scale = 100       # For mapping slider to width value
        distance_scale = 100    # For mapping slider to distance value

        # Threshold Control
        threshold_layout = QVBoxLayout()
        threshold_label = QLabel("Highlight Threshold:")
        threshold_label.setStyleSheet("color: white;")
        threshold_layout.addWidget(threshold_label)
        threshold_control_layout = QHBoxLayout()

        threshold_slider = QSlider(Qt.Horizontal)
        threshold_slider.setMinimum(0)
        threshold_slider.setMaximum(int(self.max_chat_rate * threshold_scale) if self.max_chat_rate else 1000)
        threshold_slider.setValue(int(self.initial_threshold * threshold_scale))
        threshold_control_layout.addWidget(threshold_slider)

        threshold_spinbox = QDoubleSpinBox()
        threshold_spinbox.setDecimals(2)
        threshold_spinbox.setRange(0, self.max_chat_rate if self.max_chat_rate else 1000)
        threshold_spinbox.setValue(self.initial_threshold)
        threshold_control_layout.addWidget(threshold_spinbox)

        threshold_layout.addLayout(threshold_control_layout)
        control_layout.addLayout(threshold_layout)

        # Establish connections between threshold_slider and threshold_spinbox
        threshold_slider.valueChanged.connect(lambda value: threshold_spinbox.setValue(value / threshold_scale))
        threshold_spinbox.valueChanged.connect(lambda value: threshold_slider.setValue(int(value * threshold_scale)))
        # Connect to plot update
        threshold_slider.valueChanged.connect(self.update_plot)
        threshold_spinbox.valueChanged.connect(self.update_plot)

        # Prominence Control
        prominence_layout = QVBoxLayout()
        prominence_label = QLabel("Prominence:")
        prominence_label.setStyleSheet("color: white;")
        prominence_layout.addWidget(prominence_label)
        prominence_control_layout = QHBoxLayout()

        prominence_slider = QSlider(Qt.Horizontal)
        prominence_slider.setMinimum(0)
        prominence_slider.setMaximum(int(self.max_chat_rate * prominence_scale) if self.max_chat_rate else 1000)
        prominence_slider.setValue(int(self.initial_prominence * prominence_scale))
        prominence_control_layout.addWidget(prominence_slider)

        prominence_spinbox = QDoubleSpinBox()
        prominence_spinbox.setDecimals(2)
        prominence_spinbox.setRange(0, self.max_chat_rate if self.max_chat_rate else 1000)
        prominence_spinbox.setValue(self.initial_prominence)
        prominence_control_layout.addWidget(prominence_spinbox)

        prominence_layout.addLayout(prominence_control_layout)
        control_layout.addLayout(prominence_layout)

        # Establish connections between prominence_slider and prominence_spinbox
        prominence_slider.valueChanged.connect(lambda value: prominence_spinbox.setValue(value / prominence_scale))
        prominence_spinbox.valueChanged.connect(lambda value: prominence_slider.setValue(int(value * prominence_scale)))
        # Connect to plot update
        prominence_slider.valueChanged.connect(self.update_plot)
        prominence_spinbox.valueChanged.connect(self.update_plot)

        # Width Control
        width_layout = QVBoxLayout()
        width_label = QLabel("Width:")
        width_label.setStyleSheet("color: white;")
        width_layout.addWidget(width_label)
        width_control_layout = QHBoxLayout()

        width_slider = QSlider(Qt.Horizontal)
        width_slider.setMinimum(0)
        width_slider.setMaximum(5000)  # Adjusted for finer control
        width_slider.setValue(int(self.initial_width * width_scale))
        width_control_layout.addWidget(width_slider)

        width_spinbox = QDoubleSpinBox()
        width_spinbox.setDecimals(2)
        width_spinbox.setRange(0, 50)
        width_spinbox.setValue(self.initial_width)
        width_control_layout.addWidget(width_spinbox)

        width_layout.addLayout(width_control_layout)
        control_layout.addLayout(width_layout)

        # Establish connections between width_slider and width_spinbox
        width_slider.valueChanged.connect(lambda value: width_spinbox.setValue(value / width_scale))
        width_spinbox.valueChanged.connect(lambda value: width_slider.setValue(int(value * width_scale)))
        # Connect to plot update
        width_slider.valueChanged.connect(self.update_plot)
        width_spinbox.valueChanged.connect(self.update_plot)

        # Distance Control
        distance_layout = QVBoxLayout()
        distance_label = QLabel("Distance:")
        distance_label.setStyleSheet("color: white;")
        distance_layout.addWidget(distance_label)
        distance_control_layout = QHBoxLayout()

        distance_slider = QSlider(Qt.Horizontal)
        distance_slider.setMinimum(0)
        distance_slider.setMaximum(10000)  # Adjusted for finer control
        distance_slider.setValue(int(self.initial_distance * distance_scale))
        distance_control_layout.addWidget(distance_slider)

        distance_spinbox = QDoubleSpinBox()
        distance_spinbox.setDecimals(2)
        distance_spinbox.setRange(0, 100)
        distance_spinbox.setValue(self.initial_distance)
        distance_control_layout.addWidget(distance_spinbox)

        distance_layout.addLayout(distance_control_layout)
        control_layout.addLayout(distance_layout)

        # Establish connections between distance_slider and distance_spinbox
        distance_slider.valueChanged.connect(lambda value: distance_spinbox.setValue(value / distance_scale))
        distance_spinbox.valueChanged.connect(lambda value: distance_slider.setValue(int(value * distance_scale)))
        # Connect to plot update
        distance_slider.valueChanged.connect(self.update_plot)
        distance_spinbox.valueChanged.connect(self.update_plot)

        # Pogs per Interval Checkbox
        self.pogs_checkbox = QCheckBox("Pogs per interval")
        self.pogs_checkbox.setStyleSheet("color: white;")
        control_layout.addWidget(self.pogs_checkbox)

        # Average Rate Checkbox (New Toggle)
        self.average_checkbox = QCheckBox("Average Rate")
        self.average_checkbox.setStyleSheet("color: white;")
        control_layout.addWidget(self.average_checkbox)

        # Interpolation Toggle Checkbox
        self.interpolation_checkbox = QCheckBox("Enable Interpolation")
        self.interpolation_checkbox.setStyleSheet("color: white;")
        self.interpolation_checkbox.setChecked(True)  # Default to enabled
        control_layout.addWidget(self.interpolation_checkbox)

        # Connect the interpolation checkbox state change to update the plot
        self.interpolation_checkbox.stateChanged.connect(self.update_plot)

        # Connect the pogs checkbox state change to update the plot
        self.pogs_checkbox.stateChanged.connect(self.update_plot)

        # Connect the average checkbox state change to update the plot
        self.average_checkbox.stateChanged.connect(self.update_plot)

        # Smoothing Window Slider
        smoothing_layout = QVBoxLayout()
        smoothing_label = QLabel("Smoothing Window:")
        smoothing_label.setStyleSheet("color: white;")
        smoothing_layout.addWidget(smoothing_label)
        smoothing_slider = QSlider(Qt.Horizontal)
        smoothing_slider.setMinimum(1)
        smoothing_slider.setMaximum(200)
        smoothing_slider.setValue(int(self.smoothing_window))
        smoothing_layout.addWidget(smoothing_slider)
        smoothing_value_label = QLabel(f"{smoothing_slider.value()}")
        smoothing_value_label.setStyleSheet("color: white;")
        smoothing_layout.addWidget(smoothing_value_label)
        control_layout.addLayout(smoothing_layout)

        chart_layout.addLayout(control_layout)

        # Store spin boxes and sliders as instance variables
        self.threshold_spinbox = threshold_spinbox
        self.prominence_spinbox = prominence_spinbox
        self.width_spinbox = width_spinbox
        self.distance_spinbox = distance_spinbox
        self.smoothing_slider = smoothing_slider

        # Create a checkbox to toggle between peak and valley detection modes
        self.valley_detection_checkbox = QCheckBox("Detect Valleys Instead of Peaks")
        self.valley_detection_checkbox.setStyleSheet("color: white;")
        self.valley_detection_checkbox.stateChanged.connect(self.update_plot)
        chart_layout.addWidget(self.valley_detection_checkbox)

        # Peak/Valley Labels
        self.label_checkbox = QCheckBox("Show Peak/Valley Labels")
        self.label_checkbox.setStyleSheet("color: white;")
        self.label_checkbox.setChecked(True)
        self.label_checkbox.stateChanged.connect(self.update_plot)
        control_layout.addWidget(self.label_checkbox)

        # Smoothing Slider
        smoothing_slider.valueChanged.connect(lambda value: [
            smoothing_value_label.setText(f"{value}"),
            setattr(self, 'smoothing_window', value),
            self.apply_smoothing_and_update()
        ])


        # Initialize vertical line and text item
        self.vLine = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen('y', width=1))
        self.vLine.hide()
        self.plot_widget.addItem(self.vLine)

        self.text_item = pg.TextItem("", anchor=(0.5, 1.0), color='w')
        self.plot_widget.addItem(self.text_item, ignoreBounds=True)  # Prevent plot from adjusting bounds

        # Set up mouse events
        self.plot_item = self.plot_widget.getPlotItem()
        self.view_box = self.plot_item.getViewBox()
        self.plot_widget.setMouseTracking(True)
        self.plot_widget.scene().sigMouseMoved.connect(self.on_mouse_moved)
        self.plot_widget.scene().sigMouseClicked.connect(self.on_mouse_clicked)

    def append_log(self, message):
        """
        Appends log messages to the log_display widget.
        """
        self.log_display.append(message)

    def save_configuration(self):
        """
        Saves the current configuration with a given name.
        """
        config_name = self.config_name_input.text().strip()
        if not config_name:
            QMessageBox.warning(self, "Input Required", "Please enter a configuration name.")
            return

        config = {
            'threshold_value': self.threshold_spinbox.value(),
            'prominence_value': self.prominence_spinbox.value(),
            'width_value': self.width_spinbox.value(),
            'distance_value': self.distance_spinbox.value(),
            'smoothing_value': self.smoothing_slider.value(),
            'detect_valleys': self.valley_detection_checkbox.isChecked(),
            'pogs_per_interval': self.pogs_checkbox.isChecked(),
            'average_rate': self.average_checkbox.isChecked(),
            'enable_interpolation': self.interpolation_checkbox.isChecked(),
            'time_interval': self.resolution_spinbox.value(),
            'emotes_to_track': self.emotes_to_track
        }

        config_path = os.path.join(self.config_dir, f"{config_name}.json")
        try:
            with open(config_path, 'w') as f:
                json.dump(config, f, indent=4)
            QMessageBox.information(self, "Configuration Saved", f"Configuration '{config_name}' has been saved.")
            self.load_configurations_list()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save configuration:\n{e}")

    def load_configuration(self, config_path):
        """
        Loads a configuration from a given path.
        """
        try:
            with open(config_path, 'r') as f:
                config = json.load(f)

            # Apply configuration settings
            self.threshold_spinbox.setValue(config.get('threshold_value', self.initial_threshold))
            self.prominence_spinbox.setValue(config.get('prominence_value', self.initial_prominence))
            self.width_spinbox.setValue(config.get('width_value', self.initial_width))
            self.distance_spinbox.setValue(config.get('distance_value', self.initial_distance))
            self.smoothing_slider.setValue(config.get('smoothing_value', self.smoothing_window))
            self.valley_detection_checkbox.setChecked(config.get('detect_valleys', False))
            self.pogs_checkbox.setChecked(config.get('pogs_per_interval', False))
            self.average_checkbox.setChecked(config.get('average_rate', False))
            self.interpolation_checkbox.setChecked(config.get('enable_interpolation', True))
            self.resolution_spinbox.setValue(config.get('time_interval', 1.0))
            self.emotes_to_track = config.get('emotes_to_track', [])
            self.emote_filter_input.setText(', '.join(self.emotes_to_track))
            if self.chart_window:
                self.emote_filter_input_chart.setText(', '.join(self.emotes_to_track))

            # Reprocess data based on the loaded configuration
            if self.chat_file_path:
                self.process_chatlog(self.chat_file_path)

            QMessageBox.information(self, "Configuration Loaded", f"Configuration '{os.path.basename(config_path)}' has been loaded.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load configuration:\n{e}")

    def load_configurations_list(self):
        """
        Loads the list of available configurations into the QListWidget.
        """
        self.config_list.clear()
        for file in os.listdir(self.config_dir):
            if file.endswith('.json'):
                item = QListWidgetItem(file.replace('.json', ''))
                self.config_list.addItem(item)

    def select_config_item(self, item):
        """
        Handles the selection of a configuration from the list.
        """
        config_name = item.text()
        config_path = os.path.join(self.config_dir, f"{config_name}.json")
        self.load_configuration(config_path)

    def export_highlights(self):
        """
        Exports the detected highlights to a CSV file.
        """
        if not self.highlight_periods:
            QMessageBox.information(self.chart_window, "No Highlights", "No highlights to export.")
            return

        # Ask user where to save the CSV
        options = QFileDialog.Options()
        file_path, _ = QFileDialog.getSaveFileName(
            self.chart_window, "Save Highlights", "", "CSV Files (*.csv)", options=options
        )
        if not file_path:
            return  # User cancelled

        try:
            # Prepare data for export
            export_data = []
            for (start, end, rate_name), value in zip(self.highlight_periods, self.highlight_values):
                export_data.append({
                    'Start Time (s)': start,
                    'End Time (s)': end,
                    'Rate Type': rate_name,
                    'Rate Value': value,
                    'Start Time (hh:mm:ss)': str(timedelta(seconds=int(start))),
                    'End Time (hh:mm:ss)': str(timedelta(seconds=int(end)))
                })
            export_df = pd.DataFrame(export_data)
            export_df.to_csv(file_path, index=False)
            QMessageBox.information(self.chart_window, "Export Successful", f"Highlights have been exported to {file_path}.")
        except Exception as e:
            QMessageBox.critical(self.chart_window, "Export Error", f"Failed to export highlights:\n{e}")

    def update_plot(self):
        """
        Updates the PyQtGraph plot with the latest parameters.
        """
        # Check if all necessary DataFrames are initialized and not empty
        if not all([df is not None and not df.empty for df in [self.general_chat_rate, self.pogs_rate, self.average_rate]]):
            logging.warning("One or more DataFrames are not initialized or are empty.")
            return  # Exit early if data is not ready

        # Retrieve current settings
        threshold_value = self.threshold_spinbox.value()
        prominence_value = self.prominence_spinbox.value()
        width_value = self.width_spinbox.value()
        distance_value = self.distance_spinbox.value()

        # Clear the existing plot
        self.plot_widget.clear()

        # Re-add the vertical line and text item
        self.plot_widget.addItem(self.vLine)
        self.plot_widget.addItem(self.text_item, ignoreBounds=True)

        # Compute highlight periods
        self.compute_highlight_periods(threshold_value, prominence_value, width_value, distance_value)

        # Determine which rates to plot based on the toggles
        rates_to_plot = []
        if self.average_checkbox.isChecked():
            rates_to_plot.append(('average_rate', 'average_rate_smooth', 'y', 'Average Rate'))
        else:
            if self.pogs_checkbox.isChecked():
                rates_to_plot.append(('pogs_rate', 'pogs_rate_smooth', 'm', 'Pogs Rate'))
            else:
                rates_to_plot.append(('chat_rate', 'chat_rate_smooth', 'c', 'Chat Rate'))

        # Plot each selected rate
        for rate_name, smoothed_rate_name, color, label in rates_to_plot:
            if rate_name == 'pogs_rate':
                data = self.pogs_rate[smoothed_rate_name].values
                time_bin = self.pogs_rate['time_bin'].astype(float).values
            elif rate_name == 'chat_rate':
                data = self.general_chat_rate[smoothed_rate_name].values
                time_bin = self.general_chat_rate['time_bin'].astype(float).values
            elif rate_name == 'average_rate':
                data = self.average_rate[smoothed_rate_name].values
                time_bin = self.average_rate['time_bin'].astype(float).values
            else:
                continue  # Unknown rate, skip

            interpolation_enabled = self.interpolation_checkbox.isChecked()

            if interpolation_enabled and len(time_bin) >= 4:
                try:
                    # Create a smooth spline
                    x_new = np.linspace(time_bin.min(), time_bin.max(), 500)  # Increase the number for smoother curve
                    spline = make_interp_spline(time_bin, data, k=3)  # Cubic spline
                    y_new = spline(x_new)

                    # Clip negative values to zero
                    y_new = np.maximum(y_new, 0)

                    # Plot the interpolated data
                    self.plot_widget.plot(
                        x_new,
                        y_new,
                        pen=pg.mkPen(color, width=2),
                        name=label
                    )
                except Exception as e:
                    # In case interpolation fails, plot original data
                    QMessageBox.warning(
                        self.chart_window, "Interpolation Error",
                        f"An error occurred during interpolation for {label}:\n{e}\nPlotting raw data instead."
                    )
                    self.plot_widget.plot(
                        time_bin,
                        data,
                        pen=pg.mkPen(color, width=2),
                        name=label
                    )
            else:
                # Plot without interpolation
                self.plot_widget.plot(
                    time_bin,
                    data,
                    pen=pg.mkPen(color, width=2),
                    name=label
                )

        # Highlight peaks or valleys based on original data (unsmoothed)
        highlight_color = 'r'  # Red for highlights
        for (start, end, rate_name), value in zip(self.highlight_periods, self.highlight_values):
            scatter = pg.ScatterPlotItem(
                x=[start],
                y=[value],
                pen=pg.mkPen(None),
                brush=pg.mkBrush(highlight_color),  # Use the highlight color
                size=10,
                symbol='o'  # Circle for highlighting
            )
            scatter.sigClicked.connect(self.on_peak_clicked)
            self.plot_widget.addItem(scatter)

            # Add labels if enabled
            if self.label_checkbox.isChecked():
                label_text = f"{str(timedelta(seconds=int(start)))}\n{value:.2f}"
                label = pg.TextItem(
                    label_text,
                    anchor=(0.5, 1.5),
                    color='w'
                )
                label.setPos(start, value)
                self.plot_widget.addItem(label)

    def compute_highlight_periods(self, threshold, prominence_value, width_value, distance_value):
        """
        Detects peaks or valleys based on the selected detection mode, using original data for peak detection.
        """
        # Ensure smoothing columns exist before accessing them
        if 'chat_rate_smooth' not in self.general_chat_rate.columns:
            self.apply_initial_smoothing()

        # Proceed with your existing logic
        # Define parameters for peak or valley merging
        merge_window = 10  # seconds to merge close highlights

        # Clear previous highlights
        self.highlight_periods.clear()
        self.highlight_values.clear()

        # Define parameters for peak or valley merging
        merge_window = 10  # seconds to merge close highlights

        # List to keep track of which rates are being plotted
        rates_to_plot = []
        if self.average_checkbox.isChecked():
            rates_to_plot.append(('average_rate', 'average_rate_smooth'))
        else:
            if self.pogs_checkbox.isChecked():
                rates_to_plot.append(('pogs_rate', 'pogs_rate_smooth'))
            else:
                rates_to_plot.append(('chat_rate', 'chat_rate_smooth'))

        for rate_name, smoothed_rate_name in rates_to_plot:
            if rate_name == 'pogs_rate':
                data = self.pogs_rate[smoothed_rate_name]
                time_bin = self.pogs_rate['time_bin']
            elif rate_name == 'chat_rate':
                data = self.general_chat_rate[smoothed_rate_name]
                time_bin = self.general_chat_rate['time_bin']
            elif rate_name == 'average_rate':
                data = self.average_rate[smoothed_rate_name]
                time_bin = self.average_rate['time_bin']
            else:
                continue  # Unknown rate, skip

            if not self.valley_detection_checkbox.isChecked():
                # Peak detection
                adjusted_threshold = threshold

                # Detect peaks
                peaks, properties = find_peaks(
                    data,
                    height=adjusted_threshold,
                    prominence=prominence_value,
                    width=width_value,
                    distance=distance_value
                )

                peak_times = time_bin.iloc[peaks].values
                peak_values = data.iloc[peaks].values

                # Merge close peaks
                merged_peaks = []
                merged_values = []
                current_peak = None
                current_value = None

                for idx, peak_time in enumerate(peak_times):
                    peak_value = peak_values[idx]
                    if current_peak is None:
                        current_peak = [peak_time, peak_time]
                        current_value = peak_value
                    elif peak_time - current_peak[1] <= merge_window:
                        current_peak[1] = peak_time
                        current_value = max(current_value, peak_value)
                    else:
                        merged_peaks.append(current_peak)
                        merged_values.append(current_value)
                        current_peak = [peak_time, peak_time]
                        current_value = peak_value

                if current_peak is not None:
                    merged_peaks.append(current_peak)
                    merged_values.append(current_value)

                for (start, end), value in zip(merged_peaks, merged_values):
                    self.highlight_periods.append((start, end, rate_name))  # Include rate name
                    self.highlight_values.append(value)

            else:
                # Valley detection
                adjusted_threshold = threshold

                # Detect peaks first
                peaks, properties = find_peaks(
                    data,
                    height=adjusted_threshold,
                    prominence=prominence_value,
                    width=width_value,
                    distance=distance_value
                )

                peak_times = time_bin.iloc[peaks].values
                peak_values = data.iloc[peaks].values

                # For each peak, find a valley before it within the valley_search_window
                valleys = []
                valley_values = []

                for peak_time in peak_times:
                    # Define the search window
                    search_start = peak_time - 30  # 30 seconds before the peak
                    search_end = peak_time

                    # Get indices within the window
                    window_df = pd.DataFrame({
                        'time_bin': time_bin,
                        'rate_smooth': data
                    })
                    window_df = window_df[
                        (window_df['time_bin'] >= search_start) &
                        (window_df['time_bin'] < search_end)
                    ]

                    if window_df.empty:
                        continue  # No data in window

                    # Find the minimum in the window
                    min_idx = window_df['rate_smooth'].idxmin()
                    min_time = window_df.loc[min_idx, 'time_bin']
                    min_value = window_df.loc[min_idx, 'rate_smooth']

                    valleys.append(min_time)
                    valley_values.append(min_value)

                # Merge close valleys
                merged_valleys = []
                merged_valley_values = []
                current_valley = None
                current_valley_value = None

                for idx, valley_time in enumerate(valleys):
                    valley_value = valley_values[idx]
                    if current_valley is None:
                        current_valley = [valley_time, valley_time]
                        current_valley_value = valley_value
                    elif valley_time - current_valley[1] <= merge_window:
                        current_valley[1] = valley_time
                        current_valley_value = min(current_valley_value, valley_value)
                    else:
                        merged_valleys.append(current_valley)
                        merged_valley_values.append(current_valley_value)
                        current_valley = [valley_time, valley_time]
                        current_valley_value = valley_value

                if current_valley is not None:
                    merged_valleys.append(current_valley)
                    merged_valley_values.append(current_valley_value)

                for (start, end), value in zip(merged_valleys, merged_valley_values):
                    self.highlight_periods.append((start, end, rate_name))  # Include rate name
                    self.highlight_values.append(value)

    def on_peak_clicked(self, scatter, points):
        """
        Handles clicks on detected peaks or valleys.
        """
        for point in points:
            x = point.pos()[0]
            timestamp_seconds = int(x)

            # Read offset from the offset input box, handling errors gracefully
            try:
                offset_value = int(self.offset_input.text().strip())
            except ValueError:
                offset_value = 0  # Default to zero if input is invalid

            # Adjust timestamp with the offset
            adjusted_timestamp = max(0, timestamp_seconds + offset_value)

            # Extract VOD URL from the input field
            vod_id_match = re.search(r'/videos/(\d+)', self.vod_input.text().strip())
            if vod_id_match:
                vod_id = vod_id_match.group(1)
                vod_url = f"https://www.twitch.tv/videos/{vod_id}"
            else:
                vod_url = None

            if not vod_url:
                QMessageBox.critical(self, "Error", "VOD URL is not available.")
                return

            link = f"{vod_url}?t={adjusted_timestamp}s"
            webbrowser.open(link)


    def on_mouse_clicked(self, event):
        """
        Handles shift-clicks on the plot to open the VOD at the hovered timestamp.
        """
        if event.isAccepted():
            return  # Do not proceed if the event was handled elsewhere

        if event.button() == Qt.LeftButton:
            modifiers = QApplication.keyboardModifiers()
            if modifiers == Qt.ShiftModifier:
                pos = event.scenePos()
                if self.plot_widget.sceneBoundingRect().contains(pos):
                    mouse_point = self.plot_item.vb.mapSceneToView(pos)
                    x = mouse_point.x()
                    timestamp_seconds = int(x)

                    # Read offset from the offset input box
                    try:
                        offset_value = int(self.offset_input.text().strip())
                    except ValueError:
                        offset_value = 0  # Default to zero if input is invalid

                    # Adjust timestamp with offset
                    adjusted_timestamp = max(0, timestamp_seconds + offset_value)

                    # Extract VOD URL from the input field
                    vod_id_match = re.search(r'/videos/(\d+)', self.vod_input.text().strip())
                    if vod_id_match:
                        vod_id = vod_id_match.group(1)
                        vod_url = f"https://www.twitch.tv/videos/{vod_id}"
                    else:
                        vod_url = None

                    if not vod_url:
                        QMessageBox.critical(self, "Error", "VOD URL is not available.")
                        return

                    link = f"{vod_url}?t={adjusted_timestamp}s"
                    webbrowser.open(link)


    def on_mouse_moved(self, pos):
        """
        Updates the vertical line and timestamp when the mouse is moved over the plot.
        """
        if self.plot_widget.sceneBoundingRect().contains(pos):
            mouse_point = self.plot_item.vb.mapSceneToView(pos)
            x = mouse_point.x()
            y_range = self.plot_item.vb.viewRange()[1]
            y_max = y_range[1]
            y_min = y_range[0]
            margin = (y_max - y_min) * 0.05  # 5% margin
            y = y_max - margin

            # Update the vertical line position
            self.vLine.setPos(x)
            self.vLine.show()

            # Update the text item position and content
            timestamp = str(timedelta(seconds=int(x)))
            self.text_item.setText(f"Time: {timestamp}")
            self.text_item.setPos(x, y)  # Place it slightly below the top of the plot
            self.text_item.show()
        else:
            self.vLine.hide()
            self.text_item.hide()

    def on_resolution_changed(self):
        """
        Handles changes to the time interval resolution and updates the current plot.
        """
        # Check if there is a chat log currently loaded
        if not self.chat_file_path:
            QMessageBox.warning(
                self, "No Chat Log",
                "Please download or select a chat log before changing the resolution."
            )
            return  # Exit the function early if no chat log is loaded

        # If a chat log is available, proceed with reprocessing the data
        new_interval = self.resolution_spinbox.value()
        self.reprocess_chat_data(self.chat_file_path, new_interval)

    def reprocess_chat_data(self, chat_file_path, time_interval):
        """
        Reprocesses the chat log data with a new time interval without creating a new window.
        """
        emotes_to_track = [emote.strip() for emote in self.emote_filter_input.text().split(',') if emote.strip()]
        
        # If there is an existing thread, ensure it has finished before starting a new one
        if getattr(self, 'process_thread', None) and self.process_thread.isRunning():
            self.process_thread.wait()  # Wait for the current thread to finish

        # Initialize ProcessThread with the new time interval and reprocess data
        self.process_thread = ProcessThread(chat_file_path, time_interval, emotes_to_track)
        self.process_thread.finished_signal.connect(lambda df: self.update_processed_data(df, chat_file_path))
        self.process_thread.error_signal.connect(self.processing_error)

        # Ensure cleanup after the thread is finished
        self.process_thread.finished.connect(self.cleanup_thread)

        # Start reprocessing
        self.process_thread.start()

    def cleanup_thread(self):
        """
        Cleans up the process_thread after it has finished.
        """
        self.process_thread = None


    def update_processed_data(self, combined_rate, chat_file_path):
        """
        Updates the processed data with the new time interval and refreshes the plot.
        """
        # Update the processed data with new rate data
        self.processed_data[chat_file_path] = combined_rate

        # Update current data in self.general_chat_rate, self.pogs_rate, and self.average_rate
        self.general_chat_rate = combined_rate[['time_bin', 'chat_rate']].copy()
        self.pogs_rate = combined_rate[['time_bin', 'pogs_rate']].copy()
        self.average_rate = combined_rate[['time_bin', 'average_rate']].copy()

        # Refresh the plot with the updated data
        self.update_plot()

    def closeEvent(self, event):
        """
        Ensure that all threads are properly terminated when closing the application.
        """
        if hasattr(self, 'process_thread') and self.process_thread.isRunning():
            self.process_thread.terminate()  # Terminate the thread safely
            self.process_thread.wait()       # Wait for the thread to finish before closing
        super().closeEvent(event)


    def on_emote_filter_changed(self, text):
        """
        Handles changes to the emote filter input in the chart window.
        """
        self.emotes_to_track = [emote.strip() for emote in text.split(',') if emote.strip()]
        if self.chat_file_path:
            self.process_chatlog(self.chat_file_path)

if __name__ == '__main__':
    app = QApplication(sys.argv)

    # Set the application style to Fusion
    app.setStyle('Fusion')

    # Apply dark palette
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(53, 53, 53))
    palette.setColor(QPalette.WindowText, Qt.white)
    palette.setColor(QPalette.Base, QColor(25, 25, 25))
    palette.setColor(QPalette.AlternateBase, QColor(53, 53, 53))
    palette.setColor(QPalette.ToolTipBase, Qt.white)
    palette.setColor(QPalette.ToolTipText, Qt.white)
    palette.setColor(QPalette.Text, Qt.white)
    palette.setColor(QPalette.Button, QColor(53, 53, 53))
    palette.setColor(QPalette.ButtonText, Qt.white)
    palette.setColor(QPalette.BrightText, Qt.red)
    palette.setColor(QPalette.Link, QColor(42, 130, 218))
    palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
    palette.setColor(QPalette.HighlightedText, Qt.black)
    app.setPalette(palette)

    # Set PyQtGraph background to match
    pg.setConfigOption('background', '#2b2b2b')
    pg.setConfigOption('foreground', 'w')

    # Set tooltip font color
    QToolTip.setFont(QFont('SansSerif', 10))
    app.setStyleSheet("QToolTip { color: white; background-color: #2b2b2b; border: 1px solid white; }")

    main_window = TwitchHighlighterApp()
    main_window.show()
    sys.exit(app.exec_())
