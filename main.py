import logging
import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication

from config.version import __build_date__, __version__
from src.main_window import ChronicleAndroidBulkDataDownloader


def main():
    # Set up logging with proper path handling for app bundles
    log_file = "Chronicle_Android_bulk_data_downloader.log"
    if getattr(sys, "frozen", False):
        # Running as PyInstaller bundle
        bundle_dir = Path(sys.executable).parent
        if sys.platform.startswith("darwin"):
            # For macOS app bundles, ensure we use a writable location for logs
            # Using ~/Library/Logs/ChronicleAndroidBulkDataDownloader/
            log_dir = Path.home() / "Library" / "Logs" / "ChronicleAndroidBulkDataDownloader"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = log_dir / "Chronicle_Android_bulk_data_downloader.log"
        else:
            # For Windows, keep log in same directory as executable
            log_file = bundle_dir / log_file

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s.%(msecs)03d - %(process)d - %(thread)d - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(funcName)s - %(message)s",
        handlers=[logging.FileHandler(log_file), logging.StreamHandler()],
    )

    LOGGER = logging.getLogger(__name__)
    LOGGER.info(f"Application starting, version {__version__}, build date {__build_date__}")
    LOGGER.info(f"Platform: {sys.platform}, Python: {sys.version}")
    LOGGER.info(f"Working directory: {Path.cwd()}")
    LOGGER.info(f"Log file location: {log_file}")

    # Use OS-specific platform plugin
    if sys.platform.startswith("win"):
        sys.argv += ["-platform", "windows:darkmode=1"]
    elif sys.platform.startswith("darwin"):
        # Ensure we're using the correct platform for macOS
        sys.argv += ["-platform", "cocoa"]
        LOGGER.info("Using cocoa platform for macOS")

    app = QApplication(sys.argv)
    ex = ChronicleAndroidBulkDataDownloader()
    ex.show()
    sys.exit(app.exec())  # No underscore in PyQt6


if __name__ == "__main__":
    main()
