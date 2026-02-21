"""
Resolute Module
Manages the Resolute Resonite mod manager — saves both:
  1. Resolute's own app settings (Tauri app data in %APPDATA%\\Resolute/
  2. The actual installed RML mod DLLs (rml_mods/ and rml_libs/)

Why save the DLL files?
  Different users may want completely different mod loadouts.
  Saving the DLL files means switching profiles truly swaps which mods are
  active — not just their settings. Resolute's own JSON state is also saved
  so the app's "installed mods" list matches reality after a restore.

IMPORTANT: This module saves/restores large DLL files. Profile directories
  for this module may be tens of MB. Consider whether you need full mod
  DLL backup or just the Resolute state file.
  Option: set options["save_dlls"] = False to only save Resolute's state.

Paths:
  Resolute app data:  %APPDATA%\\Resolite/  (Tauri default on Windows)
  Mod DLLs:          <Resonite install>/rml_mods/
  Mod libraries:     <Resonite install>/rml_libs/
"""

from __future__ import annotations
import os
import json
import shutil
import logging
from pathlib import Path
from core.module_base import VRModule, ModuleStatus
from modules.resonite_mod_settings import _find_resonite_install

logger = logging.getLogger(__name__)


def _resolute_appdata() -> Path:
    """Resolute is a Tauri app; on Windows it stores data in %APPDATA%\\Resolute."""
    appdata = os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
    return Path(appdata) / "Resolute"


class ResoluteModule(VRModule):
    id = "resolute"
    display_name = "Resolute (Mod Manager)"
    icon = "📦"
    description = (
        "Saves Resolute mod manager state + installed RML mod DLLs (rml_mods/ & rml_libs/). "
        "Switching profiles truly changes which mods are active."
    )

    def _resonite_dir(self) -> Path | None:
        override = self.options.get("resonite_install_dir")
        if override:
            return Path(override)
        return _find_resonite_install()

    def _save_dlls(self) -> bool:
        """Whether to save/restore the actual mod DLL files."""
        return bool(self.options.get("save_dlls", True))

    def get_config_paths(self) -> list[Path]:
        paths = [_resolute_appdata()]
        if self._save_dlls():
            base = self._resonite_dir()
            if base:
                paths.append(base / "rml_mods")
                paths.append(base / "rml_libs")
        return paths

    def get_process_names(self) -> list[str]:
        return ["resolute.exe", "resonite.exe"]

    def get_status(self) -> ModuleStatus:
        import psutil
        pids = []
        try:
            for proc in psutil.process_iter(["pid", "name"]):
                name = (proc.info.get("name") or "").lower()
                if name in ("resolute.exe", "resonite.exe"):
                    pids.append(proc.info["pid"])
        except Exception:
            pass
        appdata = _resolute_appdata()
        return ModuleStatus(
            is_running=bool(pids),
            process_pids=pids,
            config_paths_exist=appdata.exists(),
        )

    def backup(self, dest_dir: Path) -> tuple[bool, str]:
        module_dest = dest_dir / self.id
        module_dest.mkdir(parents=True, exist_ok=True)
        summary = []
        errors = []

        # 1. Resolute app data (settings, mod manifest cache, etc.)
        resolute_appdata = _resolute_appdata()
        resolute_dest = module_dest / "resolute_appdata"
        if resolute_appdata.exists():
            if resolute_dest.exists():
                shutil.rmtree(resolute_dest)
            shutil.copytree(resolute_appdata, resolute_dest)
            summary.append("Resolute settings")
            logger.info(f"[{self.id}] Backed up Resolute app data from {resolute_appdata}")
        else:
            summary.append("Resolute settings (not found — may not be installed)")

        # 2. Mod DLLs (optional)
        if self._save_dlls():
            base = self._resonite_dir()
            if base:
                for subdir in ("rml_mods", "rml_libs"):
                    src = base / subdir
                    dst = module_dest / subdir
                    if src.exists():
                        if dst.exists():
                            shutil.rmtree(dst)
                        shutil.copytree(src, dst)
                        count = len(list(src.iterdir()))
                        summary.append(f"{subdir}/ ({count} files)")
                        logger.info(f"[{self.id}] Backed up {src} ({count} files)")
                    else:
                        summary.append(f"{subdir}/ (not found)")
            else:
                errors.append("Resonite install directory not found — mod DLLs not backed up")

        # Write a manifest of what was saved
        manifest = {
            "save_dlls": self._save_dlls(),
            "resonite_dir": str(self._resonite_dir()) if self._resonite_dir() else None,
            "summary": summary,
        }
        (module_dest / "_manifest.json").write_text(json.dumps(manifest, indent=2))

        if errors:
            return True, f"Backed up: {', '.join(summary)} (warnings: {'; '.join(errors)})"
        return True, f"Backed up: {', '.join(summary)}"

    def restore(self, src_dir: Path) -> tuple[bool, str]:
        module_src = src_dir / self.id
        if not module_src.exists():
            return False, "No Resolute backup found in this profile"

        # Read manifest
        manifest = {}
        manifest_file = module_src / "_manifest.json"
        if manifest_file.exists():
            try:
                manifest = json.loads(manifest_file.read_text())
            except Exception:
                pass

        summary = []
        errors = []

        # 1. Resolute app data
        resolute_src = module_src / "resolute_appdata"
        if resolute_src.exists():
            resolute_dst = _resolute_appdata()
            try:
                resolute_dst.mkdir(parents=True, exist_ok=True)
                if resolute_dst.exists():
                    shutil.rmtree(resolute_dst)
                shutil.copytree(resolute_src, resolute_dst)
                summary.append("Resolute settings restored")
            except Exception as e:
                errors.append(f"Resolute settings: {e}")

        # 2. Mod DLLs
        if self._save_dlls():
            base = self._resonite_dir()
            # Fall back to manifest-stored path
            if not base and manifest.get("resonite_dir"):
                base = Path(manifest["resonite_dir"])

            if base:
                for subdir in ("rml_mods", "rml_libs"):
                    src_sub = module_src / subdir
                    if src_sub.exists():
                        dst_sub = base / subdir
                        try:
                            if dst_sub.exists():
                                shutil.rmtree(dst_sub)
                            shutil.copytree(src_sub, dst_sub)
                            count = len(list(src_sub.iterdir()))
                            summary.append(f"{subdir}/ ({count} files)")
                        except Exception as e:
                            errors.append(f"{subdir}: {e}")
            else:
                errors.append("Resonite install not found — mod DLLs not restored")

        if errors:
            return len(summary) > 0, f"Partial restore: {', '.join(summary)}; errors: {'; '.join(errors)}"
        return True, f"Restored: {', '.join(summary)}"

    def validate_backup(self, profile_dir: Path) -> tuple[bool, str]:
        module_src = profile_dir / self.id
        if not module_src.exists():
            return False, "No Resolute backup found in this profile"
        has_appdata = (module_src / "resolute_appdata").exists()
        has_mods = (module_src / "rml_mods").exists()
        if not has_appdata and not has_mods:
            return False, "Backup exists but appears empty"
        parts = []
        if has_appdata:
            parts.append("Resolute settings")
        if has_mods:
            parts.append("mod DLLs")
        return True, f"Backup contains: {', '.join(parts)}"

    def can_reload_live(self) -> bool:
        # Mods are loaded at Resonite startup; must restart
        return False
