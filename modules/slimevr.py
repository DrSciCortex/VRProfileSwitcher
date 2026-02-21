"""
SlimeVR Module
Manages SlimeVR Server configuration files on Windows.
Config location: %APPDATA%/SlimeVR-Server/ (Java app via SteamVR or standalone)
"""

from __future__ import annotations
import os
from pathlib import Path
from core.module_base import VRModule


class SlimeVRModule(VRModule):
    id = "slimevr"
    display_name = "SlimeVR"
    icon = "🦴"
    description = "Full-body tracking server — saves tracker calibration, bone lengths, and server settings"

    # Known config filenames within the SlimeVR config directory
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
        appdata = os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")
        # SlimeVR stores config here when launched via standalone or Steam
        return Path(appdata) / "SlimeVR-Server"

    def get_config_paths(self) -> list[Path]:
        base = self._config_dir()
        paths = []
        for fname in self.CONFIG_FILES:
            paths.append(base / fname)
        # Also include any extra .yml/.json files dynamically present
        if base.exists():
            for f in base.iterdir():
                if f.suffix in (".yml", ".json") and f.name not in self.CONFIG_FILES:
                    paths.append(f)
        return paths

    def get_process_names(self) -> list[str]:
        # SlimeVR server is a Java app; also check for the wrapper exe
        return ["slimevr.exe", "slimevr-server.exe", "java.exe"]

    def get_status(self):
        """
        Override: java.exe is too generic, so we try to match by cmdline.
        """
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
        # SlimeVR does not expose a reload API
        return False
