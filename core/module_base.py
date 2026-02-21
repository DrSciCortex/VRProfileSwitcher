"""
VRProfile Switcher — Module Base Class
All application modules (SlimeVR, SteamVR, Resonite, etc.) implement this interface.
Adding a new module = subclass VRModule + register in modules/__init__.py
"""

from __future__ import annotations
import shutil
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ModuleStatus:
    """Runtime status snapshot for a module."""
    is_running: bool = False
    process_pids: list[int] = field(default_factory=list)
    config_paths_exist: bool = False
    notes: str = ""


class VRModule(ABC):
    """
    Abstract base class for a profile-managed application module.

    Subclasses must implement:
      - id, display_name, icon (class attributes)
      - get_config_paths()
      - get_process_names()

    Subclasses may override:
      - can_reload_live() → True if hot-reload is supported
      - trigger_reload()  → send reload signal to running app
      - backup() / restore() for custom logic beyond simple file copy
      - validate_backup()  → sanity check before restore
    """

    # --- Class-level identity (override in subclass) ---
    id: str = ""
    display_name: str = ""
    icon: str = "📦"
    description: str = ""

    def __init__(self, options: dict[str, Any] | None = None):
        self.options: dict[str, Any] = options or {}

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abstractmethod
    def get_config_paths(self) -> list[Path]:
        """
        Return list of files/directories that belong to this module's config.
        Paths that don't exist are silently skipped during backup.
        """
        ...

    @abstractmethod
    def get_process_names(self) -> list[str]:
        """
        Return list of process executable names (lowercase, no path).
        e.g. ["slimevr-server.exe", "java.exe"]
        Used for running-process detection.
        """
        ...

    # ------------------------------------------------------------------
    # Hot-reload support (optional override)
    # ------------------------------------------------------------------

    def can_reload_live(self) -> bool:
        """Return True if the module supports reloading config without restart."""
        return False

    def trigger_reload(self) -> bool:
        """
        Attempt to signal the running app to reload its config.
        Only called if can_reload_live() is True.
        Returns True on success.
        """
        return False

    # ------------------------------------------------------------------
    # Backup / Restore (default implementation — file copy)
    # ------------------------------------------------------------------

    def backup(self, dest_dir: Path) -> tuple[bool, str]:
        """
        Snapshot current config files into dest_dir/{self.id}/.
        Returns (success, message).
        """
        module_dest = dest_dir / self.id
        module_dest.mkdir(parents=True, exist_ok=True)

        copied = 0
        missing = 0
        errors = []

        for src_path in self.get_config_paths():
            if not src_path.exists():
                missing += 1
                logger.debug(f"[{self.id}] backup: path not found: {src_path}")
                continue
            try:
                rel = src_path.name
                dst = module_dest / rel
                if src_path.is_dir():
                    if dst.exists():
                        shutil.rmtree(dst)
                    shutil.copytree(src_path, dst)
                else:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src_path, dst)
                copied += 1
                logger.debug(f"[{self.id}] backed up: {src_path} → {dst}")
            except Exception as e:
                errors.append(str(e))
                logger.error(f"[{self.id}] backup error for {src_path}: {e}")

        if errors:
            return False, f"Backup partially failed: {'; '.join(errors)}"
        if copied == 0 and missing > 0:
            return False, f"Nothing to back up — {missing} config path(s) not found"
        return True, f"Backed up {copied} item(s)"

    def restore(self, src_dir: Path) -> tuple[bool, str]:
        """
        Restore config files from src_dir/{self.id}/ to their live locations.
        Returns (success, message).
        """
        module_src = src_dir / self.id
        if not module_src.exists():
            return False, f"No backup found for module '{self.id}' in profile"

        config_paths = self.get_config_paths()
        # Build name → destination mapping
        dest_map = {p.name: p for p in config_paths}

        restored = 0
        errors = []

        for item in module_src.iterdir():
            dst = dest_map.get(item.name)
            if dst is None:
                # Fallback: use same filename in same parent as first config path
                if config_paths:
                    dst = config_paths[0].parent / item.name
                else:
                    logger.warning(f"[{self.id}] restore: no destination for {item.name}")
                    continue
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                if item.is_dir():
                    if dst.exists():
                        shutil.rmtree(dst)
                    shutil.copytree(item, dst)
                else:
                    shutil.copy2(item, dst)
                restored += 1
                logger.debug(f"[{self.id}] restored: {item} → {dst}")
            except Exception as e:
                errors.append(str(e))
                logger.error(f"[{self.id}] restore error for {item}: {e}")

        if errors:
            return False, f"Restore partially failed: {'; '.join(errors)}"
        if restored == 0:
            return False, "Nothing was restored"
        return True, f"Restored {restored} item(s)"

    def validate_backup(self, profile_dir: Path) -> tuple[bool, str]:
        """
        Check that a profile's backup for this module looks valid before restore.
        Override for more thorough checks.
        """
        module_src = profile_dir / self.id
        if not module_src.exists():
            return False, "No backup directory found"
        items = list(module_src.iterdir())
        if not items:
            return False, "Backup directory is empty"
        return True, "OK"

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def get_status(self) -> ModuleStatus:
        """Check if the module's app is currently running."""
        import psutil
        pids = []
        process_names = [n.lower() for n in self.get_process_names()]
        try:
            for proc in psutil.process_iter(["pid", "name"]):
                if proc.info["name"] and proc.info["name"].lower() in process_names:
                    pids.append(proc.info["pid"])
        except Exception as e:
            logger.error(f"[{self.id}] process scan error: {e}")

        config_paths = self.get_config_paths()
        configs_exist = any(p.exists() for p in config_paths)

        return ModuleStatus(
            is_running=bool(pids),
            process_pids=pids,
            config_paths_exist=configs_exist,
        )

    def __repr__(self) -> str:
        return f"<VRModule id={self.id!r} name={self.display_name!r}>"
