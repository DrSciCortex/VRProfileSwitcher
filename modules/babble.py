"""
Project Babble Module (Step 2)
Stub implementation — ready to flesh out when needed.
"""

from __future__ import annotations
import os
from pathlib import Path
from core.module_base import VRModule


class BabbleModule(VRModule):
    id = "babble"
    display_name = "Project Babble"
    icon = "💬"
    description = "Project Babble face tracking — saves camera config and model settings"

    def _config_dir(self) -> Path:
        appdata = os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")
        return Path(appdata) / "ProjectBabble"

    def get_config_paths(self) -> list[Path]:
        base = self._config_dir()
        return [
            base / "config.json",
            base / "settings.json",
            base / "calibration.json",
        ]

    def get_process_names(self) -> list[str]:
        return ["babble.exe", "projectbabble.exe", "babbleapp.exe"]

    def can_reload_live(self) -> bool:
        return False
