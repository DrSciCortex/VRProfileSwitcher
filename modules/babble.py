"""
Project Babble Module
Manages Project Babble mouth/face tracking app configuration.

Confirmed config location (from user):
  C:/Program Files (x86)/Project Babble/babble_settings.json

Also saves the VRCFT Babble module config if present:
  %APPDATA%/VRCFaceTracking/CustomLibs/VRCFaceTracking.Babble.json
"""

from __future__ import annotations
import os
import json
import shutil
import logging
from pathlib import Path
from core.module_base import VRModule, ModuleStatus

logger = logging.getLogger(__name__)

DEFAULT_BABBLE_DIR = Path("C:/Program Files (x86)/Project Babble")
CONFIG_FILENAME = "babble_settings.json"


def _find_babble_dir() -> Path | None:
    candidates = [
        DEFAULT_BABBLE_DIR,
        Path("C:/Program Files/Project Babble"),
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Project Babble",
        Path(os.environ.get("APPDATA", "")) / "ProjectBabble",
    ]
    for c in candidates:
        if (c / CONFIG_FILENAME).exists():
            return c
    return None


def _vrcft_babble_config() -> Path:
    appdata = os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
    return Path(appdata) / "VRCFaceTracking" / "CustomLibs" / "VRCFaceTracking.Babble.json"


class BabbleModule(VRModule):
    id = "babble"
    display_name = "Project Babble"
    icon = "💬"
    description = "Project Babble face tracking -- saves babble_settings.json and optional VRCFT module config"

    def _babble_dir(self) -> Path:
        override = self.options.get("babble_dir")
        if override:
            return Path(override)
        return _find_babble_dir() or DEFAULT_BABBLE_DIR

    def _include_vrcft(self) -> bool:
        return bool(self.options.get("include_vrcft_module", True))

    def get_config_paths(self) -> list[Path]:
        paths = [self._babble_dir() / CONFIG_FILENAME]
        if self._include_vrcft():
            paths.append(_vrcft_babble_config())
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
        config = self._babble_dir() / CONFIG_FILENAME
        return ModuleStatus(
            is_running=bool(pids),
            process_pids=pids,
            config_paths_exist=config.exists(),
        )

    def backup(self, dest_dir: Path) -> tuple[bool, str]:
        module_dest = dest_dir / self.id
        module_dest.mkdir(parents=True, exist_ok=True)
        saved = []
        errors = []

        # Main settings file
        src = self._babble_dir() / CONFIG_FILENAME
        if src.exists():
            try:
                shutil.copy2(src, module_dest / CONFIG_FILENAME)
                saved.append(CONFIG_FILENAME)
            except Exception as e:
                errors.append(f"{CONFIG_FILENAME}: {e}")
        else:
            return False, f"Config not found: {src}"

        # VRCFT module config (optional)
        if self._include_vrcft():
            vrcft_src = _vrcft_babble_config()
            if vrcft_src.exists():
                try:
                    shutil.copy2(vrcft_src, module_dest / vrcft_src.name)
                    saved.append(vrcft_src.name)
                except Exception as e:
                    errors.append(f"{vrcft_src.name}: {e}")

        manifest = {
            "babble_dir": str(self._babble_dir()),
            "include_vrcft": self._include_vrcft(),
        }
        (module_dest / "_manifest.json").write_text(json.dumps(manifest, indent=2))

        msg = f"Backed up: {', '.join(saved)}"
        if errors:
            msg += f" | Errors: {'; '.join(errors)}"
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

        babble_dir = Path(manifest.get("babble_dir", str(self._babble_dir())))
        restored = []
        errors = []

        src = module_src / CONFIG_FILENAME
        if src.exists():
            try:
                babble_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, babble_dir / CONFIG_FILENAME)
                restored.append(CONFIG_FILENAME)
            except Exception as e:
                errors.append(f"{CONFIG_FILENAME}: {e}")

        # Restore VRCFT module config
        vrcft_dst = _vrcft_babble_config()
        vrcft_src = module_src / vrcft_dst.name
        if vrcft_src.exists() and manifest.get("include_vrcft", True):
            try:
                vrcft_dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(vrcft_src, vrcft_dst)
                restored.append(vrcft_dst.name)
            except Exception as e:
                errors.append(f"{vrcft_dst.name}: {e}")

        if not restored:
            return False, "Nothing restored"
        msg = f"Restored: {', '.join(restored)}"
        if errors:
            msg += f" | Errors: {'; '.join(errors)}"
        return True, msg

    def validate_backup(self, profile_dir: Path) -> tuple[bool, str]:
        module_src = profile_dir / self.id
        if not module_src.exists():
            return False, "No Project Babble backup in this profile"
        if not (module_src / CONFIG_FILENAME).exists():
            return False, f"Backup missing {CONFIG_FILENAME}"
        return True, f"{CONFIG_FILENAME} found in backup"

    def can_reload_live(self) -> bool:
        return False
