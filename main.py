"""
VRProfile Switcher — Entry Point
Run with: python main.py
"""

import sys
import logging
from pathlib import Path

# Resolve root so imports work regardless of CWD
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon

from core.profile_manager import ProfileManager
from core.settings import AppSettings
from gui.app import MainWindow

# Paths
DATA_DIR     = ROOT / "data"
PROFILES_DIR = DATA_DIR / "profiles"
CONFIG_FILE  = DATA_DIR / "config.json"


def _app_icon() -> QIcon:
    """
    Resolve the app icon whether running from source or as a PyInstaller exe.
    PyInstaller sets sys._MEIPASS to the unpacked bundle directory at runtime,
    so assets live there instead of next to main.py.
    """
    base = Path(getattr(sys, "_MEIPASS", ROOT))
    for name in ("icon.ico", "icon_64.ico"):
        candidate = base / "assets" / name
        if candidate.exists():
            return QIcon(str(candidate))
    return QIcon()


def setup_logging(level_name: str = "INFO"):
    level = getattr(logging, level_name.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(DATA_DIR / "vrprofile.log", encoding="utf-8"),
        ],
    )


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    settings = AppSettings(CONFIG_FILE)
    setup_logging(settings.get("log_level", "INFO"))

    logger = logging.getLogger(__name__)
    logger.info("VRProfile Switcher starting")

    pm = ProfileManager(PROFILES_DIR)

    app = QApplication(sys.argv)
    app.setApplicationName("VRProfile Switcher")
    app.setOrganizationName("VRProfile")

    icon = _app_icon()
    app.setWindowIcon(icon)          # taskbar + all windows

    window = MainWindow(pm, settings)
    window.setWindowIcon(icon)       # title bar (redundant but explicit)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
