"""
SlimeVR Module
Manages SlimeVR Server configuration files on Windows.

Correct config path (confirmed from official SlimeVR release notes):
  %APPDATA%\dev.slimevr.SlimeVR\

Key files inside that directory:
  vrconfig.yml       -- main server config (network, OSC, tracker settings)
  calibration.json   -- IMU calibration data per tracker
  bonelengths.json   -- skeleton bone length measurements
  osc.json           -- OSC output settings
  vmc.json           -- VMC protocol settings
  filtering.json     -- tracker filtering/smoothing settings
  tapDetection.json  -- tap gesture detection settings
  overlayconfig.yml  -- SteamVR overlay settings
"""

from __future__ import annotations
import os
from pathlib import Path
from core.module_base import VRModule


class SlimeVRModule(VRModule):
    id = "slimevr"
    display_name = "SlimeVR"
    icon = "🦴"
    description = "Full-body tracking server -- saves tracker calibration, bone lengths, and server settings"

    CONFIG_FILES = [
        "vrconfig.yml",
        "calibration.json",
        "bonelengths.json",
        "osc.json",
        "vmc.json",
        "filtering.json",
        "tapDetection.json",
        "overlayconfig.yml",
    ]

    def _config_dir(self) -> Path:
        # Official path from SlimeVR release notes:
        #   "back up your vrconfig.yml at %AppData%\dev.slimevr.SlimeVR"
        appdata = os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
        return Path(appdata) / "dev.slimevr.SlimeVR"

    def get_config_paths(self) -> list[Path]:
        base = self._config_dir()
        paths = [base / fname for fname in self.CONFIG_FILES]
        # Also pick up any extra .yml/.json files that may exist (e.g. from newer versions)
        if base.exists():
            for f in base.iterdir():
                if f.suffix in (".yml", ".json") and f.name not in self.CONFIG_FILES:
                    paths.append(f)
        return paths

    def get_process_names(self) -> list[str]:
        return ["slimevr.exe", "slimevr-server.exe", "java.exe"]

    def get_status(self):
        """java.exe is too generic; match by cmdline too."""
        import psutil
        from core.module_base import ModuleStatus
        pids = []
        try:
            for proc in psutil.process_iter(["pid", "name", "cmdline"]):
                name = (proc.info.get("name") or "").lower()
                cmdline = " ".join(proc.info.get("cmdline") or []).lower()
                if name in ("slimevr.exe", "slimevr-server.exe"):
                    pids.append(proc.info["pid"])
                elif name == "java.exe" and "slimevr" in cmdline:
                    pids.append(proc.info["pid"])
        except Exception:
            pass
        config_paths = self.get_config_paths()
        return ModuleStatus(
            is_running=bool(pids),
            process_pids=pids,
            config_paths_exist=any(p.exists() for p in config_paths),
        )

    def can_reload_live(self) -> bool:
        return False
