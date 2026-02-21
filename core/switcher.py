"""
Switcher
Orchestrates the full profile backup/restore flow:
  1. Checks which enabled modules are currently running
  2. Reports conflicts (apps that need to be closed)
  3. Auto-backs up current state before any restore
  4. Runs backup/restore per module
  5. Emits progress via callback for GUI updates
"""

from __future__ import annotations
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Any

from core.profile_manager import Profile, ProfileManager
from core.module_base import VRModule, ModuleStatus
from modules import get_module, MODULE_REGISTRY

logger = logging.getLogger(__name__)

# Callback type: (module_id, step, message)
ProgressCallback = Callable[[str, str, str], None]


@dataclass
class ModuleConflict:
    module_id: str
    display_name: str
    pids: list[int]
    can_reload: bool


@dataclass
class OperationResult:
    success: bool
    module_results: dict[str, tuple[bool, str]] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        ok = sum(1 for ok, _ in self.module_results.values() if ok)
        fail = len(self.module_results) - ok
        parts = [f"{ok} module(s) succeeded"]
        if fail:
            parts.append(f"{fail} failed")
        return ", ".join(parts)


class Switcher:
    """
    High-level coordinator for profile switching operations.
    All GUI interaction (blocking dialogs etc.) is handled by the GUI layer;
    this class only checks state and performs file operations.
    """

    def __init__(self, profile_manager: ProfileManager):
        self.pm = profile_manager

    # ------------------------------------------------------------------
    # Conflict detection
    # ------------------------------------------------------------------

    def check_conflicts(self, profile: Profile) -> list[ModuleConflict]:
        """
        Return a list of running-app conflicts for enabled modules
        that do NOT support live reload.
        """
        conflicts = []
        for mid in profile.enabled_modules():
            try:
                module = self._make_module(profile, mid)
                status = module.get_status()
                if status.is_running:
                    if module.can_reload_live():
                        # Will be handled automatically — not a conflict
                        logger.info(f"[{mid}] running but supports live reload")
                    else:
                        conflicts.append(ModuleConflict(
                            module_id=mid,
                            display_name=module.display_name,
                            pids=status.process_pids,
                            can_reload=False,
                        ))
            except Exception as e:
                logger.error(f"Conflict check failed for {mid}: {e}")
        return conflicts

    def get_all_statuses(self, profile: Profile) -> dict[str, ModuleStatus]:
        """Get runtime status for all enabled modules."""
        statuses = {}
        for mid in profile.enabled_modules():
            try:
                module = self._make_module(profile, mid)
                statuses[mid] = module.get_status()
            except Exception as e:
                logger.error(f"Status check failed for {mid}: {e}")
        return statuses

    # ------------------------------------------------------------------
    # Backup current state
    # ------------------------------------------------------------------

    def backup_to_profile(
        self,
        profile: Profile,
        progress: ProgressCallback | None = None,
    ) -> OperationResult:
        """
        Snapshot current live configs into the named profile.
        """
        result = OperationResult(success=True)
        dest_dir = self.pm.profile_dir(profile.name)

        for mid in profile.enabled_modules():
            if progress:
                progress(mid, "backup", f"Backing up {mid}...")
            try:
                module = self._make_module(profile, mid)
                ok, msg = module.backup(dest_dir)
                result.module_results[mid] = (ok, msg)
                if not ok:
                    result.success = False
                    result.errors.append(f"{module.display_name}: {msg}")
                    logger.warning(f"Backup failed for {mid}: {msg}")
                else:
                    logger.info(f"Backed up {mid}: {msg}")
            except Exception as e:
                result.module_results[mid] = (False, str(e))
                result.success = False
                result.errors.append(f"{mid}: {e}")
                logger.error(f"Backup exception for {mid}: {e}", exc_info=True)

        self.pm.save_profile_meta(profile)
        return result

    # ------------------------------------------------------------------
    # Load / restore a profile
    # ------------------------------------------------------------------

    def load_profile(
        self,
        profile: Profile,
        auto_backup_first: bool = True,
        progress: ProgressCallback | None = None,
    ) -> OperationResult:
        """
        Restore a profile's configs to their live locations.
        Optionally auto-backs up current state first (default: True).
        Modules that can live-reload will trigger reload instead of requiring a restart.
        """
        result = OperationResult(success=True)

        # Step 1: Auto-backup current state
        if auto_backup_first:
            if progress:
                progress("__auto_backup", "backup", "Auto-backing up current state...")
            self._auto_backup(profile, progress)

        # Step 2: Handle live-reloadable modules
        src_dir = self.pm.profile_dir(profile.name)

        for mid in profile.enabled_modules():
            if progress:
                progress(mid, "restore", f"Restoring {mid}...")
            try:
                module = self._make_module(profile, mid)

                # Validate backup exists
                ok, validation_msg = module.validate_backup(src_dir)
                if not ok:
                    result.module_results[mid] = (False, f"Validation failed: {validation_msg}")
                    result.warnings.append(f"{module.display_name}: {validation_msg}")
                    logger.warning(f"Skipping {mid} — {validation_msg}")
                    continue

                # Restore files
                ok, msg = module.restore(src_dir)
                result.module_results[mid] = (ok, msg)

                if ok:
                    logger.info(f"Restored {mid}: {msg}")
                    # If running and supports reload, trigger it
                    status = module.get_status()
                    if status.is_running and module.can_reload_live():
                        reloaded = module.trigger_reload()
                        if reloaded:
                            logger.info(f"{mid}: live reload triggered")
                        else:
                            result.warnings.append(f"{module.display_name}: reload trigger failed — may need manual restart")
                else:
                    result.success = False
                    result.errors.append(f"{module.display_name}: {msg}")
                    logger.error(f"Restore failed for {mid}: {msg}")

            except Exception as e:
                result.module_results[mid] = (False, str(e))
                result.success = False
                result.errors.append(f"{mid}: {e}")
                logger.error(f"Restore exception for {mid}: {e}", exc_info=True)

        if result.success:
            self.pm.touch_last_used(profile.name)

        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _make_module(self, profile: Profile, module_id: str) -> VRModule:
        options = profile.get_module_options(module_id)
        return get_module(module_id, options=options)

    def _auto_backup(self, profile: Profile, progress: ProgressCallback | None = None):
        """
        Save the current live state to a special __last_backup profile.
        This is a safety net so the user can undo a profile switch.
        """
        import json
        from datetime import datetime, timezone
        from core.profile_manager import Profile as P

        backup_dir = self.pm.auto_backup_dir()
        backup_dir.mkdir(parents=True, exist_ok=True)

        # Write a minimal profile.json for the auto-backup
        meta = P(
            name=ProfileManager.AUTO_BACKUP_NAME,
            notes=f"Auto-backup before loading '{profile.name}'",
            modules=profile.modules,  # Same modules as what we're about to load
        )
        (backup_dir / "profile.json").write_text(
            json.dumps(meta.to_dict(), indent=2),
            encoding="utf-8",
        )

        for mid in profile.enabled_modules():
            if progress:
                progress(mid, "auto_backup", f"Auto-backup: {mid}")
            try:
                module = self._make_module(profile, mid)
                module.backup(backup_dir)
            except Exception as e:
                logger.warning(f"Auto-backup failed for {mid}: {e}")
