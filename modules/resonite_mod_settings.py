"""
Resonite Mod Settings Module
Manages config files for all ResoniteModLoader (RML) mods.

RML writes per-mod JSON config files to:
  <Resonite Install>/rml_config/<ModName>.json

These configs are created by mods when they first run and contain
all user-tweakable settings for that mod (e.g. keybinds, toggles,
numerical values set via the ResoniteModSettings in-game UI).

This module saves and restores the entire rml_config/ directory,
preserving settings for all installed mods at once.

Also saves the RML loader config itself:
  <Resonite Install>/ResoniteModLoader.dll  ← not saved (binary)
  <Resonite Install>/rml_config/            ← SAVED (all mod JSON configs)
"""

from __future__ import annotations
import os
import logging
from pathlib import Path
from core.module_base import VRModule, ModuleStatus

logger = logging.getLogger(__name__)


def _find_resonite_install() -> Path | None:
    """Find the Resonite Steam installation directory."""
    import winreg
    steam_path = None
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam")
        steam_path = Path(winreg.QueryValueEx(key, "SteamPath")[0])
        winreg.CloseKey(key)
    except Exception:
        pass

    candidates = []
    if steam_path:
        candidates.append(steam_path / "steamapps" / "common" / "Resonite")

    # Common fallbacks
    for drive in ("C:", "D:", "E:"):
        candidates += [
            Path(f"{drive}/Program Files (x86)/Steam/steamapps/common/Resonite"),
            Path(f"{drive}/Program Files/Steam/steamapps/common/Resonite"),
            Path(f"{drive}/SteamLibrary/steamapps/common/Resonite"),
            Path(f"{drive}/Steam/steamapps/common/Resonite"),
        ]

    for c in candidates:
        if (c / "Resonite.exe").exists():
            return c
    return None


class ResoniteModSettingsModule(VRModule):
    id = "resonite_mod_settings"
    display_name = "Resonite Mod Settings"
    icon = "🔧"
    description = (
        "Saves all RML mod config files (rml_config/) — "
        "captures every mod's settings as configured via ResoniteModSettings"
    )

    def _resonite_dir(self) -> Path | None:
        override = self.options.get("resonite_install_dir")
        if override:
            return Path(override)
        return _find_resonite_install()

    def _rml_config_dir(self) -> Path | None:
        base = self._resonite_dir()
        if base:
            return base / "rml_config"
        return None

    def get_config_paths(self) -> list[Path]:
        cfg_dir = self._rml_config_dir()
        if not cfg_dir or not cfg_dir.exists():
            return []
        # Return individual JSON files so the base backup logic handles them cleanly
        return [f for f in cfg_dir.iterdir() if f.suffix == ".json"]

    def get_process_names(self) -> list[str]:
        return ["resonite.exe"]

    def get_status(self) -> ModuleStatus:
        import psutil
        pids = []
        try:
            for proc in psutil.process_iter(["pid", "name"]):
                if (proc.info.get("name") or "").lower() == "resonite.exe":
                    pids.append(proc.info["pid"])
        except Exception:
            pass
        cfg_dir = self._rml_config_dir()
        return ModuleStatus(
            is_running=bool(pids),
            process_pids=pids,
            config_paths_exist=bool(cfg_dir and cfg_dir.exists()),
        )

    def backup(self, dest_dir: Path) -> tuple[bool, str]:
        """Copy the entire rml_config/ directory as a unit."""
        import shutil
        cfg_dir = self._rml_config_dir()
        if not cfg_dir or not cfg_dir.exists():
            return False, f"rml_config not found — Resonite may not be installed or RML not set up (looked in: {cfg_dir})"

        mod_dest = dest_dir / self.id
        if mod_dest.exists():
            shutil.rmtree(mod_dest)
        shutil.copytree(cfg_dir, mod_dest)

        count = len(list(mod_dest.glob("*.json")))
        logger.info(f"[{self.id}] Backed up {count} mod config file(s) from {cfg_dir}")
        return True, f"Backed up {count} mod config file(s)"

    def restore(self, src_dir: Path) -> tuple[bool, str]:
        """Restore rml_config/ from backup, merging with any new mod configs."""
        import shutil
        module_src = src_dir / self.id
        if not module_src.exists():
            return False, "No mod settings backup found in this profile"

        cfg_dir = self._rml_config_dir()
        if not cfg_dir:
            return False, "Cannot find Resonite install directory"

        cfg_dir.mkdir(parents=True, exist_ok=True)

        restored = 0
        errors = []
        for src_file in module_src.glob("*.json"):
            try:
                shutil.copy2(src_file, cfg_dir / src_file.name)
                restored += 1
            except Exception as e:
                errors.append(str(e))

        if errors:
            return False, f"Restored {restored} file(s) with {len(errors)} error(s): {errors[0]}"
        return True, f"Restored {restored} mod config file(s)"

    def validate_backup(self, profile_dir: Path) -> tuple[bool, str]:
        module_src = profile_dir / self.id
        if not module_src.exists():
            return False, "No RML mod settings backup in this profile"
        count = len(list(module_src.glob("*.json")))
        if count == 0:
            return False, "Mod settings backup is empty (no .json files)"
        return True, f"{count} mod config file(s) ready to restore"

    def can_reload_live(self) -> bool:
        # RML reads configs at startup; Resonite must be closed
        return False
