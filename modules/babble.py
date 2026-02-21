"""
Project Babble Module
Manages Project Babble mouth tracking app configuration.

Project Babble stores its config in babble_settings.json.
The file lives in the app's working directory (usually the install dir).
On Windows with the installer build, that's typically:
  %LOCALAPPDATA%\\Programs\\ProjectBabble\
  OR %LOCALAPPDATA%/ProjectBabble/
  OR wherever the user installed/extracted it

Config file: babble_settings.json
  Contains: camera source, ROI, rotation, OSC port/address, 
            GPU acceleration setting, model path, calibration data

Also saves the VRCFT Babble module config if present:
  %APPDATA%/VRCFaceTracking/CustomLibs/VRCFaceTracking.Babble.json
  (or similar, depending on version)
"""

from __future__ import annotations
import os
import json
import shutil
import logging
from pathlib import Path
from core.module_base import VRModule, ModuleStatus

logger = logging.getLogger(__name__)

BABBLE_CONFIG_FILES = [
    "babble_settings.json",
    "settings.json",
    "config.json",
]


def _find_babble_dir() -> Path | None:
    local = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
    appdata = os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
    userprofile = os.environ.get("USERPROFILE", str(Path.home()))

    candidates = [
        Path(local) / "Programs" / "ProjectBabble",
        Path(local) / "Programs" / "project-babble",
        Path(local) / "ProjectBabble",
        Path(appdata) / "ProjectBabble",
        Path(userprofile) / "ProjectBabble",
        Path("C:/ProjectBabble"),
        Path("C:/Program Files/ProjectBabble"),
        Path("C:/Program Files (x86)/ProjectBabble"),
    ]
    for c in candidates:
        if c.exists() and any((c / f).exists() for f in BABBLE_CONFIG_FILES):
            return c
    for c in candidates:
        if c.exists():
            return c
    return None


def _vrcft_appdata() -> Path:
    appdata = os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
    return Path(appdata) / "VRCFaceTracking"


class BabbleModule(VRModule):
    id = "babble"
    display_name = "Project Babble"
    icon = "💬"
    description = (
        "Project Babble mouth/face tracking -- saves camera config, "
        "ROI calibration, OSC settings, and VRCFT module config"
    )

    def _babble_dir(self) -> Path | None:
        override = self.options.get("babble_dir")
        if override:
            return Path(override)
        return _find_babble_dir()

    def _include_vrcft(self) -> bool:
        return bool(self.options.get("include_vrcft_module", True))

    def get_config_paths(self) -> list[Path]:
        paths = []
        babble = self._babble_dir()
        if babble:
            for fname in BABBLE_CONFIG_FILES:
                paths.append(babble / fname)
        if self._include_vrcft():
            vrcft = _vrcft_appdata()
            # The VRCFT Babble module config (name varies by version)
            for fname in ("VRCFaceTracking.Babble.json", "Babble.json", "babble_module.json"):
                paths.append(vrcft / "CustomLibs" / fname)
        return paths

    def get_process_names(self) -> list[str]:
        return ["babble.exe", "projectbabble.exe", "babbleapp.exe", "python.exe"]

    def get_status(self) -> ModuleStatus:
        import psutil
        pids = []
        try:
            for proc in psutil.process_iter(["pid", "name", "cmdline"]):
                name = (proc.info.get("name") or "").lower()
                cmdline = " ".join(proc.info.get("cmdline") or []).lower()
                if name in ("babble.exe", "projectbabble.exe", "babbleapp.exe"):
                    pids.append(proc.info["pid"])
                elif name == "python.exe" and "babble" in cmdline:
                    pids.append(proc.info["pid"])
        except Exception:
            pass
        babble = self._babble_dir()
        configs_exist = bool(babble and any((babble / f).exists() for f in BABBLE_CONFIG_FILES))
        return ModuleStatus(
            is_running=bool(pids),
            process_pids=pids,
            config_paths_exist=configs_exist,
        )

    def backup(self, dest_dir: Path) -> tuple[bool, str]:
        module_dest = dest_dir / self.id
        module_dest.mkdir(parents=True, exist_ok=True)
        saved = []
        errors = []
        babble = self._babble_dir()

        if babble:
            for fname in BABBLE_CONFIG_FILES:
                src = babble / fname
                if src.exists():
                    try:
                        shutil.copy2(src, module_dest / fname)
                        saved.append(fname)
                    except Exception as e:
                        errors.append(f"{fname}: {e}")

        # VRCFT Babble module config
        if self._include_vrcft():
            vrcft_custom = _vrcft_appdata() / "CustomLibs"
            for fname in ("VRCFaceTracking.Babble.json", "Babble.json", "babble_module.json"):
                src = vrcft_custom / fname
                if src.exists():
                    try:
                        shutil.copy2(src, module_dest / fname)
                        saved.append(f"VRCFT/{fname}")
                    except Exception as e:
                        errors.append(f"{fname}: {e}")

        manifest = {
            "babble_dir": str(babble) if babble else None,
            "include_vrcft": self._include_vrcft(),
        }
        (module_dest / "_manifest.json").write_text(json.dumps(manifest, indent=2))

        if not saved:
            return False, f"Nothing saved -- Babble config not found (searched: {babble})"
        msg = f"Saved: {', '.join(saved)}"
        if errors:
            msg += f" (errors: {'; '.join(errors)})"
        return True, msg

    def restore(self, src_dir: Path) -> tuple[bool, str]:
        module_src = src_dir / self.id
        if not module_src.exists():
            return False, "No Project Babble backup found in this profile"

        manifest = {}
        manifest_file = module_src / "_manifest.json"
        if manifest_file.exists():
            try:
                manifest = json.loads(manifest_file.read_text())
            except Exception:
                pass

        babble = self._babble_dir()
        if not babble and manifest.get("babble_dir"):
            babble = Path(manifest["babble_dir"])

        restored = []
        errors = []

        if babble:
            babble.mkdir(parents=True, exist_ok=True)
            for fname in BABBLE_CONFIG_FILES:
                src_file = module_src / fname
                if src_file.exists():
                    try:
                        shutil.copy2(src_file, babble / fname)
                        restored.append(fname)
                    except Exception as e:
                        errors.append(f"{fname}: {e}")

        # Restore VRCFT Babble module config
        if manifest.get("include_vrcft", True):
            vrcft_custom = _vrcft_appdata() / "CustomLibs"
            for fname in ("VRCFaceTracking.Babble.json", "Babble.json", "babble_module.json"):
                src_file = module_src / fname
                if src_file.exists():
                    try:
                        vrcft_custom.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src_file, vrcft_custom / fname)
                        restored.append(f"VRCFT/{fname}")
                    except Exception as e:
                        errors.append(f"{fname}: {e}")

        if not restored:
            return False, "Nothing restored"
        msg = f"Restored: {', '.join(restored)}"
        if errors:
            msg += f" (errors: {'; '.join(errors)})"
        return True, msg

    def validate_backup(self, profile_dir: Path) -> tuple[bool, str]:
        module_src = profile_dir / self.id
        if not module_src.exists():
            return False, "No Project Babble backup in this profile"
        has_config = any((module_src / f).exists() for f in BABBLE_CONFIG_FILES)
        if not has_config:
            return False, "Backup exists but no config files found"
        return True, "Babble config backup found"

    def can_reload_live(self) -> bool:
        return False
