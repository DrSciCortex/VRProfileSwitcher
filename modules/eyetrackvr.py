"""
EyeTrackVR Module
Manages EyeTrackVR app configuration and calibration data.

EyeTrackVR (ETVR) is a Python-based app. Its config is stored relative to
its installation/working directory. On Windows the installer-based version
typically lands in:
  %LOCALAPPDATA%/Programs/eyetrackvr/
  OR %APPDATA%/eyetrackvr/
  OR next to EyeTrackVR.exe wherever the user installed it

The app saves:
  settings.json           -- camera sources, ROI, rotation, thresholds, OSC port
  EyeTrackVR.cfg          -- legacy config (older versions)

Additionally, the ETVR VRCFT module has its own config:
  %APPDATA%/VRCFaceTracking/CustomLibs/ETVRModuleConfig.json
  (if the user is using VRCFT integration)

Since install location varies, we search common places + allow override.
"""

from __future__ import annotations
import os
import json
import shutil
import logging
from pathlib import Path
from core.module_base import VRModule, ModuleStatus

logger = logging.getLogger(__name__)

ETVR_CONFIG_FILES = [
    "settings.json",
    "EyeTrackVR.cfg",
    "config.json",
    "eyetracking_config.cfg",
]


def _find_etvr_dir() -> Path | None:
    local = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
    appdata = os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
    userprofile = os.environ.get("USERPROFILE", str(Path.home()))

    candidates = [
        Path(local) / "Programs" / "eyetrackvr",
        Path(local) / "Programs" / "EyeTrackVR",
        Path(appdata) / "eyetrackvr",
        Path(appdata) / "EyeTrackVR",
        Path(userprofile) / "EyeTrackVR",
        Path("C:/EyeTrackVR"),
        Path("C:/Program Files/EyeTrackVR"),
        Path("C:/Program Files (x86)/EyeTrackVR"),
    ]
    for c in candidates:
        if c.exists() and any((c / f).exists() for f in ETVR_CONFIG_FILES):
            return c
    for c in candidates:
        if c.exists():
            return c
    return None


def _vrcft_appdata() -> Path:
    appdata = os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
    return Path(appdata) / "VRCFaceTracking"


class EyeTrackVRModule(VRModule):
    id = "eyetrackvr"
    display_name = "EyeTrackVR"
    icon = "👁️"
    description = (
        "EyeTrackVR eye tracking -- saves camera settings, ROI, "
        "calibration, OSC config, and VRCFT module config"
    )

    def _etvr_dir(self) -> Path | None:
        override = self.options.get("etvr_dir")
        if override:
            return Path(override)
        return _find_etvr_dir()

    def _include_vrcft(self) -> bool:
        return bool(self.options.get("include_vrcft_module", True))

    def get_config_paths(self) -> list[Path]:
        paths = []
        etvr = self._etvr_dir()
        if etvr:
            for fname in ETVR_CONFIG_FILES:
                paths.append(etvr / fname)
            for subdir in ("calibration", "calib", "data"):
                paths.append(etvr / subdir)
        if self._include_vrcft():
            vrcft = _vrcft_appdata()
            paths.append(vrcft / "CustomLibs" / "ETVRModuleConfig.json")
        return paths

    def get_process_names(self) -> list[str]:
        return ["eyetrackvr.exe", "eyetrackapp.exe", "etvr.exe", "python.exe"]

    def get_status(self) -> ModuleStatus:
        import psutil
        pids = []
        try:
            for proc in psutil.process_iter(["pid", "name", "cmdline"]):
                name = (proc.info.get("name") or "").lower()
                cmdline = " ".join(proc.info.get("cmdline") or []).lower()
                if name in ("eyetrackvr.exe", "eyetrackapp.exe", "etvr.exe"):
                    pids.append(proc.info["pid"])
                elif name == "python.exe" and "eyetrack" in cmdline:
                    pids.append(proc.info["pid"])
        except Exception:
            pass
        etvr = self._etvr_dir()
        configs_exist = bool(etvr and any((etvr / f).exists() for f in ETVR_CONFIG_FILES))
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
        etvr = self._etvr_dir()

        if etvr:
            for fname in ETVR_CONFIG_FILES:
                src = etvr / fname
                if src.exists():
                    try:
                        shutil.copy2(src, module_dest / fname)
                        saved.append(fname)
                    except Exception as e:
                        errors.append(f"{fname}: {e}")

            for subdir in ("calibration", "calib", "data"):
                src_dir = etvr / subdir
                if src_dir.exists() and src_dir.is_dir():
                    dst_dir = module_dest / subdir
                    if dst_dir.exists():
                        shutil.rmtree(dst_dir)
                    shutil.copytree(src_dir, dst_dir)
                    saved.append(f"{subdir}/")

        if self._include_vrcft():
            etvr_vrcft = _vrcft_appdata() / "CustomLibs" / "ETVRModuleConfig.json"
            if etvr_vrcft.exists():
                try:
                    shutil.copy2(etvr_vrcft, module_dest / "ETVRModuleConfig.json")
                    saved.append("ETVRModuleConfig.json")
                except Exception as e:
                    errors.append(f"ETVRModuleConfig.json: {e}")

        manifest = {
            "etvr_dir": str(etvr) if etvr else None,
            "include_vrcft": self._include_vrcft(),
        }
        (module_dest / "_manifest.json").write_text(json.dumps(manifest, indent=2))

        if not saved:
            return False, f"Nothing saved -- ETVR config not found (searched: {etvr})"
        msg = f"Saved: {', '.join(saved)}"
        if errors:
            msg += f" (errors: {'; '.join(errors)})"
        return True, msg

    def restore(self, src_dir: Path) -> tuple[bool, str]:
        module_src = src_dir / self.id
        if not module_src.exists():
            return False, "No EyeTrackVR backup found in this profile"

        manifest = {}
        manifest_file = module_src / "_manifest.json"
        if manifest_file.exists():
            try:
                manifest = json.loads(manifest_file.read_text())
            except Exception:
                pass

        etvr = self._etvr_dir()
        if not etvr and manifest.get("etvr_dir"):
            etvr = Path(manifest["etvr_dir"])

        restored = []
        errors = []

        if etvr:
            etvr.mkdir(parents=True, exist_ok=True)
            for fname in ETVR_CONFIG_FILES:
                src_file = module_src / fname
                if src_file.exists():
                    try:
                        shutil.copy2(src_file, etvr / fname)
                        restored.append(fname)
                    except Exception as e:
                        errors.append(f"{fname}: {e}")

            for subdir in ("calibration", "calib", "data"):
                src_sub = module_src / subdir
                if src_sub.exists():
                    dst_sub = etvr / subdir
                    try:
                        if dst_sub.exists():
                            shutil.rmtree(dst_sub)
                        shutil.copytree(src_sub, dst_sub)
                        restored.append(f"{subdir}/")
                    except Exception as e:
                        errors.append(f"{subdir}: {e}")

        etvr_vrcft_src = module_src / "ETVRModuleConfig.json"
        if etvr_vrcft_src.exists() and manifest.get("include_vrcft", True):
            vrcft_dst = _vrcft_appdata() / "CustomLibs" / "ETVRModuleConfig.json"
            try:
                vrcft_dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(etvr_vrcft_src, vrcft_dst)
                restored.append("ETVRModuleConfig.json (VRCFT)")
            except Exception as e:
                errors.append(f"ETVRModuleConfig.json: {e}")

        if not restored:
            return False, "Nothing restored"
        msg = f"Restored: {', '.join(restored)}"
        if errors:
            msg += f" (errors: {'; '.join(errors)})"
        return True, msg

    def validate_backup(self, profile_dir: Path) -> tuple[bool, str]:
        module_src = profile_dir / self.id
        if not module_src.exists():
            return False, "No EyeTrackVR backup in this profile"
        has_config = any((module_src / f).exists() for f in ETVR_CONFIG_FILES)
        has_vrcft = (module_src / "ETVRModuleConfig.json").exists()
        if not has_config and not has_vrcft:
            return False, "Backup exists but no config files found inside"
        parts = []
        if has_config:
            parts.append("ETVR settings")
        if has_vrcft:
            parts.append("VRCFT module config")
        return True, f"Contains: {', '.join(parts)}"

    def can_reload_live(self) -> bool:
        return False
