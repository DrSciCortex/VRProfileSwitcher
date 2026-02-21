"""
EyeTrackVR Module (Step 2)
Stub implementation — ready to flesh out when needed.
"""

from __future__ import annotations
import os
from pathlib import Path
from core.module_base import VRModule


class EyeTrackVRModule(VRModule):
    id = "eyetrackvr"
    display_name = "EyeTrackVR"
    icon = "👁️"
    description = "EyeTrackVR eye tracking — saves camera settings and calibration"

    def _config_dir(self) -> Path:
        appdata = os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")
        return Path(appdata) / "EyeTrackVR"

    def get_config_paths(self) -> list[Path]:
        base = self._config_dir()
        return [
            base / "settings.json",
            base / "calibration",
            base / "config.json",
        ]

    def get_process_names(self) -> list[str]:
        return ["eyetrackvr.exe", "eyetrackapp.exe"]

    def can_reload_live(self) -> bool:
        return False
