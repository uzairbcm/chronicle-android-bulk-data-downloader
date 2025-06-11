from __future__ import annotations

import asyncio
import datetime
import json
import logging
import shutil
import sys
from datetime import datetime as datetime_class
from pathlib import Path

import aiofiles
import httpx
import regex as re
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from config.version import __build_date__, __version__
from src.constants import (
    CONNECTION_TIMEOUT,
    MAX_RETRIES,
    RATE_LIMIT_DELAY,
    REQUEST_TIMEOUT,
)
from src.download_worker import DownloadThreadWorker
from src.enums import ChronicleDeviceType, ChronicleDownloadDataType
from src.utils import get_local_timezone, get_matching_files_from_folder

LOGGER = logging.getLogger(__name__)


class ChronicleBulkDataDownloader(QWidget):
    """
    A QWidget-based application for downloading bulk data from Chronicle.
    """

    @staticmethod
    def get_config_path() -> Path:
        """
        Gets the correct path for the config file, handling both script and PyInstaller EXE cases.
        """
        if getattr(sys, "frozen", False):
            # Running as PyInstaller EXE
            return Path(sys.executable).parent / "Chronicle_bulk_data_downloader_config.json"
        else:
            # Running as script
            return Path("Chronicle_bulk_data_downloader_config.json")

    def __init__(self) -> None:
        """
        Initializes the ChronicleBulkDataDownloader class.
        """
        super().__init__()

        # Initialize instance variables
        self.download_folder: Path | str = ""
        self.temp_download_file_pattern: str = r"[\s\S]*.csv"
        self.dated_file_pattern: str = r"([\s\S]*(\d{2}[\.|-]\d{2}[\.|-]\d{4})[\s\S]*.csv)"
        self.raw_data_file_pattern: str = r"[\s\S]*(Raw)[\s\S]*.csv"
        self.survey_data_file_pattern: str = r"[\s\S]*(Survey)[\s\S]*.csv"
        self.ios_sensor_data_file_pattern: str = r"[\s\S]*(IOSSensor)[\s\S]*.csv"
        self.preprocessed_download_data_file_pattern: str = r"[\s\S]*(Downloaded Preprocessed)[\s\S]*.csv"
        self.time_use_diary_download_data_file_pattern: str = r"[\s\S]*(Time Use Diary)[\s\S]*.csv"

        self.semaphore = asyncio.Semaphore(1)  # Ensure only one request at a time
        self.client_lock = asyncio.Lock()
        self.download_active = False
        self._http_client = None

        self.worker = None
        self.ios_sensor_warning_label: QLabel | None = None
        # Initialize UI
        self._init_UI()
        self._load_and_set_config()

    def _select_and_validate_download_folder(self) -> None:
        """
        Select and validate the download folder.
        """
        LOGGER.debug("Selecting download folder")
        current_download_folder_label = self.download_folder_label.text().strip()
        selected_folder = QFileDialog.getExistingDirectory(self, "Select Download Folder")

        if selected_folder and Path(selected_folder).is_dir():
            self.download_folder = selected_folder
            self.download_folder_label.setText(selected_folder)
            LOGGER.debug(f"Selected download folder: {selected_folder}")
        else:
            self.download_folder_label.setText(current_download_folder_label)
            LOGGER.debug("Invalid folder selected or no folder selected, reset to previous value")

    def _update_list_label_text(self) -> None:
        """
        Updates the label text based on the state of the inclusive filter checkbox.
        """
        if self.inclusive_filter_checkbox.isChecked():
            self.list_ids_label.setText("List of participant IDs to *include* (separated by commas):")
        else:
            self.list_ids_label.setText("List of participant IDs to *exclude* (separated by commas):")
        LOGGER.debug("Updated label text based on inclusive filter checkbox state")

    def _init_UI(self) -> None:
        """
        Initializes the user interface.
        """
        LOGGER.debug("Initializing UI")
        self.setWindowTitle(f"Chronicle Bulk Data Downloader v{__version__} Build {__build_date__}")
        self.setGeometry(100, 100, 500, 450)  # Made a bit taller for additional options

        main_layout = QVBoxLayout()

        # Add folder selection group
        main_layout.addWidget(self._create_folder_selection_group())
        main_layout.addSpacing(10)

        # Add token entry group
        main_layout.addWidget(self._create_authorization_token_entry_group())
        main_layout.addSpacing(10)

        # Add study ID entry group
        main_layout.addWidget(self._create_study_id_entry_group())
        main_layout.addSpacing(10)

        # Add participant IDs entry group
        main_layout.addWidget(self._create_participant_ids_entry_group())
        main_layout.addSpacing(10)

        # Add basic data checkbox layout
        main_layout.addLayout(self._create_basic_data_checkbox_layout())
        main_layout.addSpacing(10)

        # Add iOS sensor data checkbox layout
        main_layout.addLayout(self._create_ios_sensor_checkbox_layout())
        main_layout.addSpacing(10)

        # Add time use diary checkbox layout
        main_layout.addLayout(self._create_time_use_diary_checkbox_layout())
        main_layout.addSpacing(10)

        # Add options checkbox layout
        main_layout.addLayout(self._create_options_checkbox_layout())
        main_layout.addSpacing(10)

        # Add the progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%p% - %v")
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #bdc3c7;
                border-radius: 4px;
                text-align: center;
            }
            QProgressBar::chunk {
                background-color: #3498db;
                width: 1px;
            }
        """)

        main_layout.addWidget(self.progress_bar)
        main_layout.addSpacing(10)

        # Add button layout
        main_layout.addLayout(self._create_button_layout())
        main_layout.addSpacing(10)

        self.setLayout(main_layout)
        self._center_window()
        # self.adjustSize()
        LOGGER.debug("Initialized UI")

    def _create_folder_selection_group(self) -> QGroupBox:
        """
        Creates the folder selection group box.
        """
        group_box = QGroupBox("Folder Selection")
        group_layout = QVBoxLayout()

        # Add button for selecting download folder
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        self.select_download_folder_button = QPushButton("Select Download Folder")
        self.select_download_folder_button.clicked.connect(self._select_and_validate_download_folder)
        self.select_download_folder_button.setStyleSheet("QPushButton { padding: 10px; }")
        button_layout.addWidget(self.select_download_folder_button)
        button_layout.addStretch()
        group_layout.addLayout(button_layout)

        # Add label for download folder
        label_layout = QHBoxLayout()
        self.download_folder_label = QLabel("Select the folder to download the Chronicle data to")
        self.download_folder_label.setStyleSheet(
            """QLabel {
                font-size: 10pt;
                font-weight: bold;
                padding: 5px;
                border-radius: 4px;
                background-color: #f5f5f5;
                border: 1px solid #dcdcdc;
                color: #333;
            }"""
        )
        self.download_folder_label.setWordWrap(True)
        self.download_folder_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.download_folder_label.setMinimumWidth(400)
        self.download_folder_label.setFixedHeight(50)
        label_layout.addWidget(self.download_folder_label, 1)
        group_layout.addLayout(label_layout)

        group_box.setLayout(group_layout)
        return group_box

    def _create_authorization_token_entry_group(self) -> QGroupBox:
        """
        Creates the authorization token entry group box.
        """
        group_box = QGroupBox("Authorization Token Entry")
        group_layout = QVBoxLayout()

        # Add label for token entry
        label_layout = QHBoxLayout()
        label_layout.addStretch()
        self.authorization_token_label = QLabel("Please paste the temporary authorization token:")
        self.authorization_token_label.setWordWrap(True)
        self.authorization_token_label.setFixedWidth(250)
        label_layout.addWidget(self.authorization_token_label)
        label_layout.addStretch()
        group_layout.addLayout(label_layout)

        # Add text edit for token entry
        entry_layout = QHBoxLayout()
        entry_layout.addStretch()
        self.authorization_token_entry = QTextEdit()
        self.authorization_token_entry.setFixedSize(300, 50)
        self.authorization_token_entry.setStyleSheet("""
            QTextEdit {
                padding: 5px;
                border: 1px solid #bdc3c7;
                border-radius: 4px;
                background-color: white;
            }
            QTextEdit:focus {
                border: 1px solid #3498db;
            }
        """)
        entry_layout.addWidget(self.authorization_token_entry)
        entry_layout.addStretch()
        group_layout.addLayout(entry_layout)

        group_box.setLayout(group_layout)
        return group_box

    def _create_study_id_entry_group(self) -> QGroupBox:
        """
        Creates the study ID entry group box.
        """
        group_box = QGroupBox("Study ID Entry")
        group_layout = QVBoxLayout()

        # Add label for study ID entry
        label_layout = QHBoxLayout()
        label_layout.addStretch()
        self.study_id_label = QLabel("Please paste the study ID:")
        label_layout.addWidget(self.study_id_label)
        label_layout.addStretch()
        group_layout.addLayout(label_layout)

        # Add line edit for study ID entry
        entry_layout = QHBoxLayout()
        entry_layout.addStretch()
        self.study_id_entry = QLineEdit()
        self.study_id_entry.setFixedWidth(236)
        self.study_id_entry.setStyleSheet("""
            QLineEdit {
                padding: 5px;
                border: 1px solid #bdc3c7;
                border-radius: 4px;
            }
            QLineEdit:focus {
                border: 1px solid #3498db;
            }
        """)
        entry_layout.addWidget(self.study_id_entry)
        entry_layout.addStretch()
        group_layout.addLayout(entry_layout)

        group_box.setLayout(group_layout)
        return group_box

    def _create_participant_ids_entry_group(self) -> QGroupBox:
        """
        Creates the participant IDs entry group box.
        """
        group_box = QGroupBox("Participant IDs Entry")
        group_layout = QVBoxLayout()

        label_layout = QHBoxLayout()
        label_layout.addStretch()
        self.list_ids_label = QLabel("List of participant IDs to *exclude* (separated by commas):")
        label_layout.addWidget(self.list_ids_label)
        label_layout.addStretch()
        group_layout.addLayout(label_layout)

        checkbox_layout = QHBoxLayout()
        checkbox_layout.addStretch()
        self.inclusive_filter_checkbox = QCheckBox("Use *Inclusive* List Instead")
        self.inclusive_filter_checkbox.stateChanged.connect(self._update_list_label_text)
        checkbox_layout.addWidget(self.inclusive_filter_checkbox)
        checkbox_layout.addStretch()
        group_layout.addLayout(checkbox_layout)

        entry_layout = QHBoxLayout()
        entry_layout.addStretch()
        self.participant_ids_to_filter_list_entry = QTextEdit()
        self.participant_ids_to_filter_list_entry.setFixedSize(300, 75)
        self.participant_ids_to_filter_list_entry.setStyleSheet("""
            QTextEdit {
                padding: 5px;
                border: 1px solid #bdc3c7;
                border-radius: 4px;
                background-color: white;
            }
            QTextEdit:focus {
                border: 1px solid #3498db;
            }
        """)
        entry_layout.addWidget(self.participant_ids_to_filter_list_entry)
        entry_layout.addStretch()
        group_layout.addLayout(entry_layout)

        group_box.setLayout(group_layout)
        return group_box

    def _center_window(self):
        """
        Centers the application window on the screen.
        """
        frame_geometry = self.frameGeometry()
        screen = QApplication.primaryScreen()
        if screen is not None:
            center_point = screen.availableGeometry().center()
            frame_geometry.moveCenter(center_point)
            self.move(frame_geometry.topLeft())
            LOGGER.debug("Centered the window")
        else:
            LOGGER.warning("Could not center window - primary screen not available")

    def _create_basic_data_checkbox_layout(self) -> QVBoxLayout:
        """
        Creates the basic data checkbox layout.
        """
        main_layout = QVBoxLayout()

        self.ios_sensor_warning_label = QLabel("Uncheck iOS Sensor data download to download Android data types")
        self.ios_sensor_warning_label.setStyleSheet("color: #e74c3c; font-weight: bold;")
        self.ios_sensor_warning_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.ios_sensor_warning_label.hide()
        main_layout.addWidget(self.ios_sensor_warning_label)

        checkbox_layout = QHBoxLayout()
        checkbox_layout.addStretch()

        self.download_raw_data_checkbox = QCheckBox("Download Raw Data")
        self.download_raw_data_checkbox.setChecked(True)
        checkbox_layout.addWidget(self.download_raw_data_checkbox)

        self.download_preprocessed_data_checkbox = QCheckBox("Download Preprocessed Data")
        self.download_preprocessed_data_checkbox.setChecked(True)
        checkbox_layout.addWidget(self.download_preprocessed_data_checkbox)

        self.download_survey_data_checkbox = QCheckBox("Download Survey Data")
        self.download_survey_data_checkbox.setChecked(True)
        checkbox_layout.addWidget(self.download_survey_data_checkbox)

        checkbox_layout.addStretch()
        main_layout.addLayout(checkbox_layout)
        return main_layout

    def _create_ios_sensor_checkbox_layout(self) -> QHBoxLayout:
        """
        Creates the layout for the iOS sensor checkbox.
        """
        checkbox_layout = QHBoxLayout()
        checkbox_layout.addStretch()

        self.download_ios_sensor_checkbox = QCheckBox("Download iOS Sensor Data")
        self.download_ios_sensor_checkbox.stateChanged.connect(self._handle_ios_sensor_checkbox_state_changed)
        checkbox_layout.addWidget(self.download_ios_sensor_checkbox)

        checkbox_layout.addStretch()
        return checkbox_layout

    def _handle_ios_sensor_checkbox_state_changed(self):
        """
        Handles the state change of the iOS sensor checkbox.
        When checked, disables all other data type checkboxes.
        """
        is_checked = self.download_ios_sensor_checkbox.isChecked()
        if self.ios_sensor_warning_label is not None:
            self.ios_sensor_warning_label.setVisible(is_checked)

        if is_checked:
            # Disable other data type checkboxes
            self.download_raw_data_checkbox.setEnabled(False)
            self.download_preprocessed_data_checkbox.setEnabled(False)
            self.download_survey_data_checkbox.setEnabled(False)
            self.download_raw_data_checkbox.setChecked(False)
            self.download_preprocessed_data_checkbox.setChecked(False)
            self.download_survey_data_checkbox.setChecked(False)
        else:
            # Enable other data type checkboxes
            self.download_raw_data_checkbox.setEnabled(True)
            self.download_preprocessed_data_checkbox.setEnabled(True)
            self.download_survey_data_checkbox.setEnabled(True)

    def _create_time_use_diary_checkbox_layout(self) -> QHBoxLayout:
        """
        Creates the layout for the time use diary checkboxes.
        """
        checkbox_layout = QHBoxLayout()
        checkbox_layout.addStretch()

        self.download_time_use_diary_daytime_checkbox = QCheckBox("Download Daytime Time Use Diary")
        checkbox_layout.addWidget(self.download_time_use_diary_daytime_checkbox)

        self.download_time_use_diary_nighttime_checkbox = QCheckBox("Download Nighttime Time Use Diary")
        checkbox_layout.addWidget(self.download_time_use_diary_nighttime_checkbox)

        self.download_time_use_diary_summarized_checkbox = QCheckBox("Download Summarized Time Use Diary")
        checkbox_layout.addWidget(self.download_time_use_diary_summarized_checkbox)

        checkbox_layout.addStretch()
        return checkbox_layout

    def _create_options_checkbox_layout(self) -> QHBoxLayout:
        """
        Creates the layout for additional options checkboxes.
        """
        checkbox_layout = QHBoxLayout()
        checkbox_layout.addStretch()

        self.delete_zero_byte_files_checkbox = QCheckBox("Delete Zero-Byte Files After Download")
        checkbox_layout.addWidget(self.delete_zero_byte_files_checkbox)

        checkbox_layout.addStretch()
        return checkbox_layout

    def _create_button_layout(self) -> QHBoxLayout:
        """
        Creates the layout for the button.
        """
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        self.run_button = QPushButton("Run")
        self.run_button.clicked.connect(self._run)
        self.run_button.setStyleSheet("QPushButton { padding: 10px; }")
        button_layout.addWidget(self.run_button)
        button_layout.addStretch()
        return button_layout

    def _load_and_set_config(self) -> None:
        """
        Loads and sets the configuration from a JSON file.
        """
        try:
            with self.get_config_path().open("r") as f:
                config = json.load(f)
            LOGGER.debug("Loaded configuration from file")
        except FileNotFoundError:
            LOGGER.warning("Configuration file not found")
            return

        self.download_folder = config.get("download_folder", "")
        self.study_id_entry.setText(config.get("study_id", ""))
        self.participant_ids_to_filter_list_entry.setText(config.get("participant_ids_to_filter", ""))
        self.inclusive_filter_checkbox.setChecked(config.get("inclusive_checked", False))
        self.download_raw_data_checkbox.setChecked(config.get("raw_checked", False))
        self.download_preprocessed_data_checkbox.setChecked(config.get("preprocessed_checked", False))
        self.download_survey_data_checkbox.setChecked(config.get("survey_checked", False))
        self.download_ios_sensor_checkbox.setChecked(config.get("ios_sensor_checked", False))
        self.download_time_use_diary_daytime_checkbox.setChecked(config.get("time_use_diary_daytime_checked", False))
        self.download_time_use_diary_nighttime_checkbox.setChecked(config.get("time_use_diary_nighttime_checked", False))
        self.download_time_use_diary_summarized_checkbox.setChecked(config.get("time_use_diary_summarized_checked", False))
        self.delete_zero_byte_files_checkbox.setChecked(config.get("delete_zero_byte_files_checked", False))

        if self.download_folder:
            self.download_folder_label.setText(str(self.download_folder))

        self._handle_ios_sensor_checkbox_state_changed()

        LOGGER.debug("Set configuration from loaded file")

    @staticmethod
    def delete_zero_byte_file(file: str | Path) -> None:
        """
        Deletes a zero-byte file.
        """
        if Path(file).stat().st_size == 0:
            try:
                Path(file).unlink()
                LOGGER.debug(f"Deleted zero-byte file: {file}")
            except PermissionError:
                LOGGER.exception(f"The 0 byte file {file} could not be removed due to already being open, please close it and try again.")

    def archive_downloaded_data(self) -> None:
        """
        Archives outdated downloaded data.
        """
        Chronicle_dated_files = get_matching_files_from_folder(
            folder=self.download_folder,
            file_matching_pattern=self.dated_file_pattern,
            ignore_names=["Archive", ".png"],
        )

        for file in Chronicle_dated_files:
            re_file_date = re.search(r"(\d{2}[\.|-]\d{2}[\.|-]\d{4})", str(file))
            if not re_file_date:
                msg = f"File {file} possibly altered while script was running, please avoid doing this."
                LOGGER.error(msg)
                raise RuntimeError(msg)

            re_file_date = re_file_date[0]
            try:
                re_file_date_object = datetime_class.strptime(re_file_date, "%m-%d-%Y").replace(tzinfo=get_local_timezone())
            except ValueError:
                re_file_date_object = datetime_class.strptime(re_file_date, "%m.%d.%Y").replace(tzinfo=get_local_timezone())

            if re_file_date_object.date() < datetime_class.now(tz=get_local_timezone()).date():
                parent_dir_path = Path(file).parent
                parent_dir_name = Path(file).parent.name
                archive_dir = parent_dir_path / f"{parent_dir_name} Archive" / f"{parent_dir_name} Archive {re_file_date}"
                archive_dir.mkdir(parents=True, exist_ok=True)

                shutil.copy(src=file, dst=archive_dir / file.name)
                file.unlink()

        LOGGER.debug("Finished archiving outdated Chronicle data.")

    def organize_downloaded_data(self) -> None:
        """
        Organizes downloaded data into appropriate folders.
        """
        self.raw_data_folder = Path(self.download_folder) / "Chronicle Android Raw Data Downloads"
        self.survey_data_folder = Path(self.download_folder) / "Chronicle Android Survey Data Downloads"
        self.ios_sensor_data_folder = Path(self.download_folder) / "Chronicle iOS Sensor Data Downloads"
        self.downloaded_preprocessed_data_folder = Path(self.download_folder) / "Chronicle Android Preprocessed Data Downloads"
        self.time_use_diary_data_folder = Path(self.download_folder) / "Chronicle Time Use Diary Data Downloads"

        if self.download_raw_data_checkbox.isChecked():
            self.raw_data_folder.mkdir(parents=True, exist_ok=True)

        if self.download_survey_data_checkbox.isChecked():
            self.survey_data_folder.mkdir(parents=True, exist_ok=True)

        if self.download_ios_sensor_checkbox.isChecked():
            self.ios_sensor_data_folder.mkdir(parents=True, exist_ok=True)

        if self.download_preprocessed_data_checkbox.isChecked():
            self.downloaded_preprocessed_data_folder.mkdir(parents=True, exist_ok=True)

        if (
            self.download_time_use_diary_daytime_checkbox.isChecked()
            or self.download_time_use_diary_nighttime_checkbox.isChecked()
            or self.download_time_use_diary_summarized_checkbox.isChecked()
        ):
            self.time_use_diary_data_folder.mkdir(parents=True, exist_ok=True)

        unorganized_raw_data_files = get_matching_files_from_folder(
            folder=self.download_folder,
            file_matching_pattern=self.raw_data_file_pattern,
            ignore_names=["Archive", "Chronicle Android Raw Data Downloads"],
        )

        for file in unorganized_raw_data_files:
            shutil.copy(src=file, dst=self.raw_data_folder)
            file.unlink()

        unorganized_survey_data_files = get_matching_files_from_folder(
            folder=self.download_folder,
            file_matching_pattern=self.survey_data_file_pattern,
            ignore_names=["Archive", "Chronicle Android Survey Data Downloads"],
        )

        for file in unorganized_survey_data_files:
            shutil.copy(src=file, dst=self.survey_data_folder)
            file.unlink()

        unorganized_ios_sensor_data_files = get_matching_files_from_folder(
            folder=self.download_folder,
            file_matching_pattern=self.ios_sensor_data_file_pattern,
            ignore_names=["Archive", "Chronicle iOS Sensor Data Downloads"],
        )

        for file in unorganized_ios_sensor_data_files:
            shutil.copy(src=file, dst=self.ios_sensor_data_folder)
            file.unlink()

        unorganized_downloaded_preprocessed_files = get_matching_files_from_folder(
            folder=self.download_folder,
            file_matching_pattern=self.preprocessed_download_data_file_pattern,
            ignore_names=["Archive", "Chronicle Android Preprocessed Data Downloads"],
        )

        for file in unorganized_downloaded_preprocessed_files:
            shutil.copy(src=file, dst=self.downloaded_preprocessed_data_folder)
            file.unlink()

        unorganized_time_use_diary_data_files = get_matching_files_from_folder(
            folder=self.download_folder,
            file_matching_pattern=self.time_use_diary_download_data_file_pattern,
            ignore_names=["Archive", "Chronicle Time Use Diary Data Downloads"],
        )

        for file in unorganized_time_use_diary_data_files:
            shutil.copy(src=file, dst=self.time_use_diary_data_folder)
            file.unlink()

        if self.delete_zero_byte_files_checkbox.isChecked():
            LOGGER.debug("Checking for and deleting zero-byte files")
            all_csv_files = get_matching_files_from_folder(folder=self.download_folder, file_matching_pattern=r".*\.csv$", ignore_names=["Archive"])

            for file in all_csv_files:
                self.delete_zero_byte_file(file)

        LOGGER.debug("Finished organizing downloaded Chronicle data.")

    def _filter_participant_id_list(self, participant_id_list: list[str]) -> list[str]:
        """
        Filters the participant ID list based on the selected filter type.
        """
        cleaned_participant_id_list = [pid.strip() for pid in participant_id_list if pid.strip()]

        participant_ids_to_filter_list = self.participant_ids_to_filter_list_entry.toPlainText().split(",")
        cleaned_participant_ids_to_filter_list = [pid.strip() for pid in participant_ids_to_filter_list if pid.strip()]

        if self.inclusive_filter_checkbox.isChecked():
            LOGGER.debug("Using inclusive filter for participant ID list")
            return self._inclusive_filter_participant_id_list(cleaned_participant_id_list, cleaned_participant_ids_to_filter_list)
        else:
            LOGGER.debug("Using exclusive filter for participant ID list")
            return self._exclusive_filter_participant_id_list(cleaned_participant_id_list, cleaned_participant_ids_to_filter_list)

    def _exclusive_filter_participant_id_list(self, participant_id_list: list[str], participant_ids_to_filter: list[str]) -> list[str]:
        """
        Filters the participant ID list using an exclusive filter.
        """
        filtered_participant_id_list = [
            participant_id
            for participant_id in participant_id_list
            if participant_id is not None
            and not any(excluded_participant_id.lower() in participant_id.lower() for excluded_participant_id in participant_ids_to_filter)
        ]

        filtered_participant_id_list.sort()

        LOGGER.debug("Filtered participant ID list using exclusive filter")
        return filtered_participant_id_list

    def _inclusive_filter_participant_id_list(self, participant_id_list: list[str], participant_ids_to_filter: list[str]) -> list[str]:
        """
        Filters the participant ID list using an inclusive filter.
        """
        filtered_participant_id_list = [
            participant_id
            for participant_id in participant_id_list
            if participant_id is not None
            and any(included_participant_id.lower() in participant_id.lower() for included_participant_id in participant_ids_to_filter)
        ]

        filtered_participant_id_list.sort()

        LOGGER.debug("Filtered participant ID list using inclusive filter")
        return filtered_participant_id_list

    async def _get_client(self) -> httpx.AsyncClient:
        """
        Gets or creates an HTTP client with proper configuration.
        """
        async with self.client_lock:
            if self._http_client is None or self._http_client.is_closed:
                LOGGER.debug("Creating new HTTP client")
                self._http_client = httpx.AsyncClient(
                    http2=True,
                    timeout=httpx.Timeout(timeout=CONNECTION_TIMEOUT, read=REQUEST_TIMEOUT),
                    limits=httpx.Limits(max_keepalive_connections=1, max_connections=1, keepalive_expiry=CONNECTION_TIMEOUT),
                    follow_redirects=True,
                )
            return self._http_client

    async def _close_client(self) -> None:
        """
        Safely closes the HTTP client if it exists.
        """
        async with self.client_lock:
            if self._http_client is not None and not self._http_client.is_closed:
                try:
                    await self._http_client.aclose()
                    LOGGER.debug("HTTP client closed successfully")
                finally:
                    self._http_client = None

    async def _download_participant_Chronicle_data_type(
        self, worker: DownloadThreadWorker, participant_id: str, Chronicle_download_data_type: ChronicleDownloadDataType, retry_count: int = 0
    ) -> bool:
        """
        Downloads data of a specific type for a participant.
        Returns True if successful, False otherwise.
        """
        if worker.is_cancelled:
            LOGGER.debug(f"Download cancelled for {participant_id}, {Chronicle_download_data_type}")
            return False

        chronicle_device_type = None

        # Determine data type and URL
        match Chronicle_download_data_type:
            case ChronicleDownloadDataType.RAW:
                data_type_str = "Raw Data"
                url = f"https://api.getmethodic.com/chronicle/v3/study/{self.study_id_entry.text().strip()}/participants/data?participantId={participant_id}&dataType={Chronicle_download_data_type}&fileType=csv"
                chronicle_device_type = ChronicleDeviceType.ANDROID
            case ChronicleDownloadDataType.PREPROCESSED:
                data_type_str = "Preprocessed Data"
                url = f"https://api.getmethodic.com/chronicle/v3/study/{self.study_id_entry.text().strip()}/participants/data?participantId={participant_id}&dataType={Chronicle_download_data_type}&fileType=csv"
                chronicle_device_type = ChronicleDeviceType.ANDROID
            case ChronicleDownloadDataType.SURVEY:
                data_type_str = "Survey Data"
                url = f"https://api.getmethodic.com/chronicle/v3/study/{self.study_id_entry.text().strip()}/participants/data?participantId={participant_id}&dataType={Chronicle_download_data_type}&fileType=csv"
                chronicle_device_type = ChronicleDeviceType.ANDROID
            case ChronicleDownloadDataType.IOSSENSOR:
                data_type_str = "IOSSensor Data"
                url = f"https://api.getmethodic.com/chronicle/v3/study/{self.study_id_entry.text().strip()}/participants/data?participantId={participant_id}&dataType={Chronicle_download_data_type}&fileType=csv"
                chronicle_device_type = ChronicleDeviceType.IPHONE
            case ChronicleDownloadDataType.TIME_USE_DIARY_DAYTIME:
                data_type_str = "Time Use Diary Daytime Data"
                url = f"https://api.getmethodic.com/chronicle/v3/time-use-diary/{self.study_id_entry.text().strip()}/participants/data?participantId={participant_id}&dataType={Chronicle_download_data_type}"
            case ChronicleDownloadDataType.TIME_USE_DIARY_NIGHTTIME:
                data_type_str = "Time Use Diary Nighttime Data"
                url = f"https://api.getmethodic.com/chronicle/v3/time-use-diary/{self.study_id_entry.text().strip()}/participants/data?participantId={participant_id}&dataType={Chronicle_download_data_type}"
            case ChronicleDownloadDataType.TIME_USE_DIARY_SUMMARIZED:
                data_type_str = "Time Use Diary Summarized Data"
                url = f"https://api.getmethodic.com/chronicle/v3/time-use-diary/{self.study_id_entry.text().strip()}/participants/data?participantId={participant_id}&dataType={Chronicle_download_data_type}"
            case _:
                msg = f"Unrecognized Chronicle data download type {Chronicle_download_data_type}"
                raise ValueError(msg)

        try:
            # Get client and make request with proper rate limiting
            async with self.semaphore:
                if worker.is_cancelled:
                    return False

                # Get or create client
                client = await self._get_client()

                # Check for client validity
                if client.is_closed:
                    LOGGER.warning("Client was closed, creating a new one")
                    client = await self._get_client()

                # Make request with authorization header
                csv_response = await client.get(
                    url,
                    headers={"Authorization": f"Bearer {self.authorization_token_entry.toPlainText().strip()}"},
                    timeout=REQUEST_TIMEOUT,
                )
                csv_response.raise_for_status()

            # Prepare output location
            output_filepath = (
                Path(self.download_folder)
                / f"{participant_id} Chronicle{f' {chronicle_device_type.value}' if chronicle_device_type is not None else ''} {data_type_str} {datetime_class.now(get_local_timezone()).strftime('%m-%d-%Y')}.csv"
            )
            output_filepath.parent.mkdir(parents=True, exist_ok=True)

            # Write response to file
            async with aiofiles.open(output_filepath, "wb") as f:
                await f.write(csv_response.content)

            LOGGER.debug(f"Downloaded {data_type_str} for participant {participant_id}")

            # Add rate limiting delay
            await asyncio.sleep(RATE_LIMIT_DELAY)
            return True

        except httpx.HTTPStatusError as e:
            error_code = e.response.status_code
            if error_code in (429, 502, 503, 504) and retry_count < MAX_RETRIES:
                # Rate limiting or temporary server error, retry with backoff
                retry_delay = (2**retry_count) * RATE_LIMIT_DELAY
                LOGGER.warning(f"HTTP {error_code} error, retrying in {retry_delay}s (attempt {retry_count + 1}/{MAX_RETRIES})")
                await asyncio.sleep(retry_delay)
                return await self._download_participant_Chronicle_data_type(worker, participant_id, Chronicle_download_data_type, retry_count + 1)
            else:
                LOGGER.exception(f"HTTP error {error_code} when downloading {data_type_str} for {participant_id}")
                raise
        except httpx.RequestError as e:
            if retry_count < MAX_RETRIES:
                # Network error, retry with backoff
                retry_delay = (2**retry_count) * RATE_LIMIT_DELAY
                LOGGER.warning(f"Request error: {e}, retrying in {retry_delay}s (attempt {retry_count + 1}/{MAX_RETRIES})")

                # Recreate client on connection errors
                await self._close_client()

                await asyncio.sleep(retry_delay)
                return await self._download_participant_Chronicle_data_type(worker, participant_id, Chronicle_download_data_type, retry_count + 1)
            else:
                LOGGER.exception(f"Request error when downloading {data_type_str} for {participant_id}: {e}")
                raise
        except Exception as e:
            LOGGER.exception(f"Error downloading {data_type_str} for {participant_id}: {e}")
            raise

    async def download_participant_Chronicle_data_from_study(self, worker: DownloadThreadWorker) -> None:
        """
        Downloads data for all participants in the study.
        """
        self.download_active = True

        try:
            # Get client for initial participant stats request
            client = await self._get_client()

            # Get participant list
            participant_stats = await client.get(
                f"https://api.getmethodic.com/chronicle/v3/study/{self.study_id_entry.text().strip()}/participants/stats",
                headers={"Authorization": f"Bearer {self.authorization_token_entry.toPlainText().strip()}"},
                timeout=REQUEST_TIMEOUT,
            )
            participant_stats.raise_for_status()

            participant_id_list = [item["participantId"] for item in participant_stats.json().values()]
            filtered_participant_id_list = self._filter_participant_id_list(participant_id_list)

            if not filtered_participant_id_list:
                msg = "No participant IDs with data available to download were found after filtering. Please double check your filter and/or participants in your study on the Chronicle website."
                LOGGER.error(msg)
                raise ValueError(msg)

            # Calculate total downloads for progress tracking
            total_data_types = sum(
                [
                    self.download_raw_data_checkbox.isChecked(),
                    self.download_preprocessed_data_checkbox.isChecked(),
                    self.download_survey_data_checkbox.isChecked(),
                    self.download_ios_sensor_checkbox.isChecked(),
                    self.download_time_use_diary_daytime_checkbox.isChecked(),
                    self.download_time_use_diary_nighttime_checkbox.isChecked(),
                    self.download_time_use_diary_summarized_checkbox.isChecked(),
                ]
            )

            total_downloads = len(filtered_participant_id_list) * total_data_types
            downloads_completed = 0
            worker.update_progress(10, downloads_completed, total_downloads)  # Start at 10% with 0 completed

            # Download data for each participant
            for i, participant_id in enumerate(filtered_participant_id_list):
                # Check for cancellation
                if worker.is_cancelled:
                    LOGGER.info("Download process cancelled by user")
                    break

                # Download each selected data type
                if self.download_raw_data_checkbox.isChecked():
                    success = await self._download_participant_Chronicle_data_type(
                        worker=worker,
                        participant_id=participant_id,
                        Chronicle_download_data_type=ChronicleDownloadDataType.RAW,
                    )
                    if success:
                        downloads_completed += 1
                        progress_value = 10 + int((downloads_completed / total_downloads) * 80)
                        worker.update_progress(progress_value, downloads_completed, total_downloads)
                        LOGGER.debug(
                            f"Finished downloading {ChronicleDownloadDataType.RAW} data for device {participant_id} ({i + 1}/{len(filtered_participant_id_list)})"
                        )

                if worker.is_cancelled:
                    break

                if self.download_preprocessed_data_checkbox.isChecked():
                    success = await self._download_participant_Chronicle_data_type(
                        worker=worker,
                        participant_id=participant_id,
                        Chronicle_download_data_type=ChronicleDownloadDataType.PREPROCESSED,
                    )
                    if success:
                        downloads_completed += 1
                        progress_value = 10 + int((downloads_completed / total_downloads) * 80)
                        worker.update_progress(progress_value, downloads_completed, total_downloads)
                        LOGGER.debug(
                            f"Finished downloading {ChronicleDownloadDataType.PREPROCESSED} data for device {participant_id} ({i + 1}/{len(filtered_participant_id_list)})"
                        )

                if worker.is_cancelled:
                    break

                if self.download_survey_data_checkbox.isChecked():
                    success = await self._download_participant_Chronicle_data_type(
                        worker=worker,
                        participant_id=participant_id,
                        Chronicle_download_data_type=ChronicleDownloadDataType.SURVEY,
                    )
                    if success:
                        downloads_completed += 1
                        progress_value = 10 + int((downloads_completed / total_downloads) * 80)
                        worker.update_progress(progress_value, downloads_completed, total_downloads)
                        LOGGER.debug(
                            f"Finished downloading {ChronicleDownloadDataType.SURVEY} data for device {participant_id} ({i + 1}/{len(filtered_participant_id_list)})"
                        )

                if worker.is_cancelled:
                    break

                if self.download_ios_sensor_checkbox.isChecked():
                    success = await self._download_participant_Chronicle_data_type(
                        worker=worker,
                        participant_id=participant_id,
                        Chronicle_download_data_type=ChronicleDownloadDataType.IOSSENSOR,
                    )
                    if success:
                        downloads_completed += 1
                        progress_value = 10 + int((downloads_completed / total_downloads) * 80)
                        worker.update_progress(progress_value, downloads_completed, total_downloads)
                        LOGGER.debug(
                            f"Finished downloading {ChronicleDownloadDataType.IOSSENSOR} data for device {participant_id} ({i + 1}/{len(filtered_participant_id_list)})"
                        )

                if worker.is_cancelled:
                    break

                if self.download_time_use_diary_daytime_checkbox.isChecked():
                    success = await self._download_participant_Chronicle_data_type(
                        worker=worker,
                        participant_id=participant_id,
                        Chronicle_download_data_type=ChronicleDownloadDataType.TIME_USE_DIARY_DAYTIME,
                    )
                    if success:
                        downloads_completed += 1
                        progress_value = 10 + int((downloads_completed / total_downloads) * 80)
                        worker.update_progress(progress_value, downloads_completed, total_downloads)
                        LOGGER.debug(
                            f"Finished downloading {ChronicleDownloadDataType.TIME_USE_DIARY_DAYTIME} data for device {participant_id} ({i + 1}/{len(filtered_participant_id_list)})"
                        )

                if worker.is_cancelled:
                    break

                if self.download_time_use_diary_nighttime_checkbox.isChecked():
                    success = await self._download_participant_Chronicle_data_type(
                        worker=worker,
                        participant_id=participant_id,
                        Chronicle_download_data_type=ChronicleDownloadDataType.TIME_USE_DIARY_NIGHTTIME,
                    )
                    if success:
                        downloads_completed += 1
                        progress_value = 10 + int((downloads_completed / total_downloads) * 80)
                        worker.update_progress(progress_value, downloads_completed, total_downloads)
                        LOGGER.debug(
                            f"Finished downloading {ChronicleDownloadDataType.TIME_USE_DIARY_NIGHTTIME} data for device {participant_id} ({i + 1}/{len(filtered_participant_id_list)})"
                        )

                if worker.is_cancelled:
                    break

                if self.download_time_use_diary_summarized_checkbox.isChecked():
                    success = await self._download_participant_Chronicle_data_type(
                        worker=worker,
                        participant_id=participant_id,
                        Chronicle_download_data_type=ChronicleDownloadDataType.TIME_USE_DIARY_SUMMARIZED,
                    )
                    if success:
                        downloads_completed += 1
                        progress_value = 10 + int((downloads_completed / total_downloads) * 80)
                        worker.update_progress(progress_value, downloads_completed, total_downloads)
                        LOGGER.debug(
                            f"Finished downloading {ChronicleDownloadDataType.TIME_USE_DIARY_SUMMARIZED} data for device {participant_id} ({i + 1}/{len(filtered_participant_id_list)})"
                        )
        finally:
            # Ensure client is properly closed when done
            await self._close_client()
            self.download_active = False

    def _run(self):
        """
        Initiates the download process.
        """
        if self.download_active:
            LOGGER.warning("Download already in progress, ignoring request")
            return

        if self.worker is not None:
            if self.worker.isRunning():
                self.worker.cancel()
                self.worker.terminate()
                self.worker.wait()

            try:
                self.worker.finished.disconnect()
                self.worker.error.disconnect()
                self.worker.progress.disconnect()
                if hasattr(self.worker, "progress_text"):
                    self.worker.progress_text.disconnect()
                if hasattr(self.worker, "cancelled"):
                    self.worker.cancelled.disconnect()
            except (RuntimeError, TypeError):
                pass

            self.worker.deleteLater()

        self.worker = DownloadThreadWorker(self)
        self.worker.finished.connect(self.on_download_complete)
        self.worker.error.connect(self.on_download_error)
        self.worker.progress.connect(self.progress_bar.setValue)
        if hasattr(self.worker, "progress_text"):
            self.worker.progress_text.connect(self.progress_bar.setFormat)
        if hasattr(self.worker, "cancelled"):
            self.worker.cancelled.connect(lambda: LOGGER.info("Download cancelled"))

        self.download_active = True

        self._disable_ui_during_download()
        self.progress_bar.setValue(0)
        self.worker.start()

    def _disable_ui_during_download(self) -> None:
        """
        Disable UI controls during download.
        """
        self.select_download_folder_button.setEnabled(False)
        self.authorization_token_entry.setEnabled(False)
        self.study_id_entry.setEnabled(False)
        self.inclusive_filter_checkbox.setEnabled(False)
        self.participant_ids_to_filter_list_entry.setEnabled(False)
        self.download_raw_data_checkbox.setEnabled(False)
        self.download_survey_data_checkbox.setEnabled(False)
        self.download_preprocessed_data_checkbox.setEnabled(False)
        self.download_ios_sensor_checkbox.setEnabled(False)
        self.download_time_use_diary_daytime_checkbox.setEnabled(False)
        self.download_time_use_diary_nighttime_checkbox.setEnabled(False)
        self.download_time_use_diary_summarized_checkbox.setEnabled(False)
        self.delete_zero_byte_files_checkbox.setEnabled(False)
        # Change run button to cancel button
        self.run_button.setText("Cancel")
        self.run_button.clicked.disconnect()
        self.run_button.clicked.connect(self._cancel_download)
        self.run_button.setEnabled(True)

    def _enable_ui_after_download(self) -> None:
        """
        Enable UI controls after download completion or error.
        """
        self.select_download_folder_button.setEnabled(True)
        self.authorization_token_entry.setEnabled(True)
        self.study_id_entry.setEnabled(True)
        self.inclusive_filter_checkbox.setEnabled(True)
        self.participant_ids_to_filter_list_entry.setEnabled(True)

        # Re-enable checkboxes based on iOS sensor selection
        if self.download_ios_sensor_checkbox.isChecked():
            self._handle_ios_sensor_checkbox_state_changed()
        else:
            self.download_raw_data_checkbox.setEnabled(True)
            self.download_survey_data_checkbox.setEnabled(True)
            self.download_preprocessed_data_checkbox.setEnabled(True)
            self._handle_ios_sensor_checkbox_state_changed()

        self.download_ios_sensor_checkbox.setEnabled(True)
        self.download_time_use_diary_daytime_checkbox.setEnabled(True)
        self.download_time_use_diary_nighttime_checkbox.setEnabled(True)
        self.download_time_use_diary_summarized_checkbox.setEnabled(True)

        self.delete_zero_byte_files_checkbox.setEnabled(True)

        # Restore run button
        self.run_button.setText("Run")
        self.run_button.clicked.disconnect()
        self.run_button.clicked.connect(self._run)
        self.run_button.setEnabled(True)

    def _cancel_download(self) -> None:
        """
        Cancels the current download process.
        """
        if self.worker and self.worker.isRunning():
            LOGGER.info("Cancelling download process")

            # Disconnect from normal flow handlers
            try:
                self.worker.finished.disconnect(self.on_download_complete)
            except (RuntimeError, TypeError):
                pass

            try:
                self.worker.error.disconnect(self.on_download_error)
            except (RuntimeError, TypeError):
                pass

            # Setup direct connection for cancellation completion
            self.worker.finished.connect(self._handle_cancellation_complete)

            # Request worker to cancel
            self.worker.cancel()
            self.run_button.setEnabled(False)
            self.run_button.setText("Cancelling...")
            LOGGER.debug("Waiting for download process to gracefully terminate")

            # Absolute failsafe: Force UI reset after timeout no matter what
            QTimer.singleShot(3000, self._force_cancellation_if_needed)
        elif self.download_active:
            LOGGER.warning("Resetting inconsistent download_active state")
            self.download_active = False
            self._enable_ui_after_download()

    def _force_cancellation_if_needed(self) -> None:
        """
        Forcibly resets the UI if the worker is still running after cancellation timeout.
        """
        # Direct approach: Always reset UI if we're still in cancelling state
        if self.run_button.text() == "Cancelling...":
            LOGGER.warning("Cancellation timed out or signal was missed, forcing UI reset")

            # Reset download flag
            self.download_active = False

            # Reset button text immediately
            self.run_button.setText("Run")

            # Ensure all UI elements are enabled
            self._enable_ui_after_download()

            # Update progress bar
            self.progress_bar.setFormat("Download cancelled")

            # If worker is still running, try to terminate it
            if self.worker and self.worker.isRunning():
                try:
                    self.worker.terminate()
                    self.worker.wait(500)
                except Exception as e:
                    LOGGER.error(f"Error terminating worker: {e}")

    def _handle_cancellation_complete(self) -> None:
        """
        Handles the completion of cancellation process.
        """
        LOGGER.info("Cancellation complete, resetting UI")

        # Reset flags
        self.download_active = False

        # Reset UI
        self._enable_ui_after_download()
        self.progress_bar.setFormat("Download cancelled")

        # Clean up worker connections
        if self.worker:
            try:
                self.worker.finished.disconnect()
                self.worker.error.disconnect()
                self.worker.progress.disconnect()
                if hasattr(self.worker, "progress_text"):
                    self.worker.progress_text.disconnect()
                if hasattr(self.worker, "cancelled"):
                    self.worker.cancelled.disconnect()
            except Exception:
                pass

    def on_download_complete(self) -> None:
        """
        Handles the completion of the download process.
        """
        # Reset download_active flag
        self.download_active = False

        if self.worker:
            try:
                self.worker.finished.disconnect()
                self.worker.error.disconnect()
            except (RuntimeError, TypeError):
                pass

        self._enable_ui_after_download()
        if self.worker and self.worker.is_cancelled:
            self.progress_bar.setFormat("Download cancelled")
            LOGGER.info("Download process was cancelled")
        else:
            self.progress_bar.setFormat("Download complete!")
            LOGGER.info("Download process completed successfully")

    def on_download_error(self, error_message: str) -> None:
        """
        Handles errors that occur during the download process.
        """
        self.download_active = False

        if self.worker:
            try:
                self.worker.finished.disconnect()
                self.worker.error.disconnect()
            except (RuntimeError, TypeError):
                pass

        msg_box = QMessageBox()
        msg_box.setIcon(QMessageBox.Icon.Critical)
        msg_box.setWindowTitle("Download Error")
        msg_box.setText("An error occurred during the download process.")
        msg_box.setInformativeText(error_message)

        msg_box.exec()

        self._enable_ui_after_download()
        self.progress_bar.setFormat("Error: %p%")
        LOGGER.error("Download error occurred")

    def _get_config_file_path(self) -> Path:
        """Get the path to the config file based on whether app is frozen or not."""
        if getattr(sys, "frozen", False):
            # If the application is frozen (e.g., PyInstaller bundle)
            return Path(sys.executable).parent / "Chronicle_Bulk_Data_Downloader_config.json"
        else:
            # If running from script
            return Path("Chronicle_Bulk_Data_Downloader_config.json")
