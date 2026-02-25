"""
Virtual Desktop Streamer Module
Saves settings for the Virtual Desktop Streamer app (Quest/Pico wireless PCVR streaming).
Developer: Guy Godin / Virtual Desktop, Inc.  https://www.vrdesktop.net

Config files (confirmed from user's machine):

  %APPDATA%\\Virtual Desktop\\GameSettings.json
    -- Per-game VR settings: OpenXR runtime (VDXR/SteamVR), executable overrides,
       launch arguments, per-app bitrate hints, etc.

  %ALLUSERSPROFILE%\\Virtual Desktop\\StreamerSettings.json
    -- Global streamer settings: bitrate, codec, resolution, audio routing,
       network options, sliced encoding, passthrough, etc.

  %ALLUSERSPROFILE%\\Virtual Desktop\\BindingSettings.json
    -- Controller/input binding overrides.

Skipped (logs / updater state, not config):
  OpenXR.log, ServiceLog.txt, StreamerLog.txt, updates.aiu

Legacy path (saved only if present):
  %APPDATA%\\VirtualDesktop\\Settings.json
    -- Classic Steam VR version of Virtual Desktop (pre-Streamer era).

Process: VirtualDesktop.Streamer.exe
"""

from __future__ import annotations
import os
import shutil
import logging
from pathlib import Path
from core.module_base import VRModule, ModuleStatus

logger = logging.getLogger(__name__)

# Files to skip in %ALLUSERSPROFILE%\Virtual Desktop\ (logs / updater state)
SKIP_NAMES = {"OpenXR.log", "ServiceLog.txt", "StreamerLog.txt", "updates.aiu"}


def _appdata() -> Path:
    return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))


def _programdata() -> Path:
    return Path(os.environ.get("ALLUSERSPROFILE", "C:/ProgramData"))


def _config_files() -> dict[str, Path]:
    """
    Returns backup_filename -> live_path for all Virtual Desktop config files.
    backup_filename uses a prefix to avoid collisions between the two dirs.
    """
    appdata = _appdata()
    programdata = _programdata()
    return {
        # %APPDATA%\Virtual Desktop\
        "user__GameSettings.json":    appdata     / "Virtual Desktop" / "GameSettings.json",
        # %ALLUSERSPROFILE%\Virtual Desktop\
        "global__StreamerSettings.json": programdata / "Virtual Desktop" / "StreamerSettings.json",
        "global__BindingSettings.json":  programdata / "Virtual Desktop" / "BindingSettings.json",
        # Legacy
        "legacy__Settings.json":      appdata     / "VirtualDesktop"   / "Settings.json",
    }


class VirtualDesktopModule(VRModule):
    id = "virtual_desktop"
    display_name = "Virtual Desktop"
    icon = "🖥️"
    description = "Virtual Desktop Streamer — GameSettings, StreamerSettings, BindingSettings"

    def get_config_paths(self) -> list[Path]:
        return list(_config_files().values())

    def get_process_names(self) -> list[str]:
        return ["virtualdesktop.streamer.exe"]

    def get_status(self) -> ModuleStatus:
        try:
            import psutil
            pids = [
                p.info["pid"]
                for p in psutil.process_iter(["pid", "name"])
                if (p.info.get("name") or "").lower() == "virtualdesktop.streamer.exe"
            ]
        except Exception:
            pids = []

        config_exists = any(p.exists() for p in _config_files().values())
        return ModuleStatus(
            is_running=bool(pids),
            process_pids=pids,
            config_paths_exist=config_exists,
        )

    def backup(self, dest_dir: Path) -> tuple[bool, str]:
        module_dest = dest_dir / self.id
        module_dest.mkdir(parents=True, exist_ok=True)

        saved, missing, errors = [], [], []

        for backup_name, src_path in _config_files().items():
            if not src_path.exists():
                missing.append(src_path.name)
                logger.debug(f"[virtual_desktop] {src_path} not found, skipping")
                continue
            try:
                shutil.copy2(src_path, module_dest / backup_name)
                saved.append(src_path.name)
                logger.debug(f"[virtual_desktop] backed up: {src_path}")
            except Exception as e:
                errors.append(f"{src_path.name}: {e}")
                logger.error(f"[virtual_desktop] backup error for {src_path}: {e}")

        if not saved:
            return False, (
                "No Virtual Desktop config files found. Expected at least one of: "
                "%APPDATA%\\Virtual Desktop\\GameSettings.json, "
                "%ALLUSERSPROFILE%\\Virtual Desktop\\StreamerSettings.json"
            )

        msg = f"Backed up: {', '.join(saved)}"
        if errors:
            msg += f" | Errors: {'; '.join(errors)}"
        logger.info(f"[virtual_desktop] {msg}")
        return True, msg

    def restore(self, src_dir: Path) -> tuple[bool, str]:
        module_src = src_dir / self.id
        if not module_src.exists():
            return False, "No Virtual Desktop backup found in this profile"

        dest_map = _config_files()   # backup_name -> live path
        restored, errors = [], []

        for backup_file in module_src.glob("*.json"):
            dst = dest_map.get(backup_file.name)
            if dst is None:
                logger.warning(f"[virtual_desktop] restore: unknown file {backup_file.name}, skipping")
                continue
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup_file, dst)
                restored.append(dst.name)
                logger.debug(f"[virtual_desktop] restored: {backup_file.name} → {dst}")
            except Exception as e:
                errors.append(f"{dst.name}: {e}")
                logger.error(f"[virtual_desktop] restore error for {dst}: {e}")

        if not restored:
            return False, "Nothing was restored from Virtual Desktop backup"

        msg = f"Restored: {', '.join(restored)}"
        if errors:
            msg += f" | Errors: {'; '.join(errors)}"
        return True, msg

    def validate_backup(self, profile_dir: Path) -> tuple[bool, str]:
        module_src = profile_dir / self.id
        if not module_src.exists():
            return False, "No Virtual Desktop backup found in this profile"
        jsons = list(module_src.glob("*.json"))
        if not jsons:
            return False, "Virtual Desktop backup directory is empty"
        return True, f"Backup contains: {', '.join(f.name for f in jsons)}"
