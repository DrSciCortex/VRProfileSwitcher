"""
SteamVR Module
Manages SteamVR configuration: global settings, driver manifests, and controller bindings.
Supports per-profile driver selection (e.g. cyberfinger vs handtracking).

Key paths:
  Steam/config/steamvr.vrsettings          — main SteamVR settings
  Steam/config/controller_base/            — default controller bindings
  Steam/config/controller_user/            — user-customized controller bindings
  Steam/config/drivers/                    — active driver list / manifests

Options (stored in profile.json modules.steamvr.options):
  active_driver: null | "cyberfinger" | "handtracking" | ...
    → written into steamvr.vrsettings under [driver_*] section on restore
"""

from __future__ import annotations
import os
import json
import shutil
import logging
from pathlib import Path
from core.module_base import VRModule, ModuleStatus

logger = logging.getLogger(__name__)


def _find_steam_dir() -> Path | None:
    """Locate Steam installation directory."""
    candidates = [
        Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)")) / "Steam",
        Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "Steam",
        Path("C:/Steam"),
        Path("D:/Steam"),
        Path("E:/Steam"),
    ]
    for c in candidates:
        if (c / "steam.exe").exists():
            return c
        if (c / "config" / "steamvr.vrsettings").exists():
            return c
    # Try registry
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam")
        path = winreg.QueryValueEx(key, "SteamPath")[0]
        winreg.CloseKey(key)
        return Path(path)
    except Exception:
        pass
    return None


class SteamVRModule(VRModule):
    id = "steamvr"
    display_name = "SteamVR"
    icon = "🎮"
    description = "SteamVR settings, driver config, and controller bindings"

    def _steam_dir(self) -> Path | None:
        override = self.options.get("steam_dir")
        if override:
            return Path(override)
        return _find_steam_dir()

    def _config_dir(self) -> Path | None:
        steam = self._steam_dir()
        if steam:
            return steam / "config"
        return None

    def get_config_paths(self) -> list[Path]:
        cfg = self._config_dir()
        if not cfg:
            return []
        return [
            cfg / "steamvr.vrsettings",
            cfg / "controller_base",
            cfg / "controller_user",
            cfg / "drivers",
        ]

    def get_process_names(self) -> list[str]:
        return ["vrserver.exe", "vrmonitor.exe", "steam.exe"]

    def get_status(self) -> ModuleStatus:
        import psutil
        pids = []
        try:
            for proc in psutil.process_iter(["pid", "name"]):
                name = (proc.info.get("name") or "").lower()
                if name in ("vrserver.exe", "vrmonitor.exe"):
                    pids.append(proc.info["pid"])
        except Exception:
            pass
        cfg = self._config_dir()
        configs_exist = bool(cfg and (cfg / "steamvr.vrsettings").exists())
        return ModuleStatus(
            is_running=bool(pids),
            process_pids=pids,
            config_paths_exist=configs_exist,
        )

    def can_reload_live(self) -> bool:
        # SteamVR has a local REST API that can trigger a restart
        # We implement a best-effort restart via HTTP
        return True

    def trigger_reload(self) -> bool:
        """Ask SteamVR to restart via its local REST API (port 27062)."""
        try:
            import urllib.request
            # This endpoint requests VR server to restart
            req = urllib.request.Request(
                "http://localhost:27062/vrsystem/restart",
                method="POST",
                data=b"{}",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                return resp.status == 200
        except Exception as e:
            logger.warning(f"SteamVR reload failed: {e}")
            return False

    def backup(self, dest_dir: Path) -> tuple[bool, str]:
        ok, msg = super().backup(dest_dir)
        # Also save the current active driver setting
        if ok:
            active_driver = self.options.get("active_driver")
            if active_driver:
                meta = {"active_driver": active_driver}
                (dest_dir / self.id / "_vrprofile_meta.json").write_text(
                    json.dumps(meta, indent=2)
                )
        return ok, msg

    def restore(self, src_dir: Path) -> tuple[bool, str]:
        ok, msg = super().restore(src_dir)
        if ok:
            # Apply active_driver override if present in backup meta
            meta_file = src_dir / self.id / "_vrprofile_meta.json"
            if meta_file.exists():
                try:
                    meta = json.loads(meta_file.read_text())
                    driver = meta.get("active_driver")
                    if driver:
                        self._apply_driver_setting(driver)
                except Exception as e:
                    logger.warning(f"Could not apply driver setting: {e}")
        return ok, msg

    def _apply_driver_setting(self, driver_name: str):
        """Enable/disable specific SteamVR drivers by modifying steamvr.vrsettings."""
        cfg = self._config_dir()
        if not cfg:
            return
        settings_path = cfg / "steamvr.vrsettings"
        if not settings_path.exists():
            return
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
            # SteamVR uses "driver_<name>" sections with "enable" key
            # Disable all known custom drivers first
            known_drivers = ["cyberfinger", "handtracking", "leapmotion", "ultraleap"]
            for d in known_drivers:
                key = f"driver_{d}"
                if key in settings:
                    settings[key]["enable"] = False
            # Enable the desired one
            target_key = f"driver_{driver_name}"
            if target_key not in settings:
                settings[target_key] = {}
            settings[target_key]["enable"] = True
            settings_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
            logger.info(f"SteamVR: enabled driver '{driver_name}'")
        except Exception as e:
            logger.error(f"Failed to apply driver setting: {e}")
