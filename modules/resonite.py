"""
Resonite Module
Manages Resonite account credentials, session tokens, and game settings.

Resonite stores its user data in:
  %USERPROFILE%/AppData/LocalLow/Yellow Dog Man Studios/Resonite/

Key files:
  userdata/          — per-user data directory (contains auth tokens)
  Settings/          — game settings
  Config/            — additional config files

SECURITY NOTE:
  We copy the auth token files as-is, just like any other config file.
  No passwords are extracted or stored in plaintext — we only swap
  the same token files that Resonite itself wrote.
  Users should be aware that profile data contains login tokens.
"""

from __future__ import annotations
import os
import json
import shutil
import logging
from pathlib import Path
from core.module_base import VRModule, ModuleStatus

logger = logging.getLogger(__name__)


def _resonite_base() -> Path:
    """Find the Resonite data directory."""
    # Primary location: AppData/LocalLow
    local_low = Path(os.environ.get("USERPROFILE", Path.home())) / "AppData" / "LocalLow"
    candidates = [
        local_low / "Yellow Dog Man Studios" / "Resonite",
        local_low / "Frooxius" / "NeosVR",  # Legacy Neos path as fallback
    ]
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]  # Return primary even if doesn't exist yet


class ResoniteModule(VRModule):
    id = "resonite"
    display_name = "Resonite"
    icon = "🌐"
    description = "Resonite account session, login credentials, and game settings"

    def _base(self) -> Path:
        override = self.options.get("resonite_dir")
        if override:
            return Path(override)
        return _resonite_base()

    def get_config_paths(self) -> list[Path]:
        base = self._base()
        return [
            base / "Settings",          # Game settings directory
            base / "Config",            # Config directory
            base / "userdata",          # Auth tokens and user-specific data
            base / "Logs",              # NOT included by default — too large
        ]

    def get_config_paths(self) -> list[Path]:
        """Return only the paths we actually want to save (no logs)."""
        base = self._base()
        paths = []
        for name in ("Settings", "Config", "userdata"):
            paths.append(base / name)
        # Also grab any top-level json files
        if base.exists():
            for f in base.iterdir():
                if f.is_file() and f.suffix in (".json", ".xml", ".cfg"):
                    paths.append(f)
        return paths

    def get_process_names(self) -> list[str]:
        return ["resonite.exe", "resonite-headless.exe"]

    def get_status(self) -> ModuleStatus:
        import psutil
        pids = []
        try:
            for proc in psutil.process_iter(["pid", "name"]):
                name = (proc.info.get("name") or "").lower()
                if name in ("resonite.exe", "resonite-headless.exe"):
                    pids.append(proc.info["pid"])
        except Exception:
            pass
        base = self._base()
        return ModuleStatus(
            is_running=bool(pids),
            process_pids=pids,
            config_paths_exist=base.exists(),
        )

    def get_current_username(self) -> str | None:
        """Try to read the currently logged-in Resonite username for display."""
        base = self._base()
        # Try known locations for stored credentials
        candidates = [
            base / "userdata" / "credentials.json",
            base / "Config" / "credentials.json",
            base / "credentials.json",
        ]
        for cred_file in candidates:
            if cred_file.exists():
                try:
                    data = json.loads(cred_file.read_text(encoding="utf-8"))
                    return (
                        data.get("username")
                        or data.get("Username")
                        or data.get("userId")
                        or data.get("UserId")
                    )
                except Exception:
                    pass
        return None

    def validate_backup(self, profile_dir: Path) -> tuple[bool, str]:
        module_src = profile_dir / self.id
        if not module_src.exists():
            return False, "No Resonite backup found in this profile"
        # Check for at least one meaningful file
        all_files = list(module_src.rglob("*"))
        if not all_files:
            return False, "Resonite backup is empty"
        return True, f"Found {len(all_files)} backed-up items"

    def can_reload_live(self) -> bool:
        return False  # Must restart Resonite to pick up new credentials
