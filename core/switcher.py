"""
Switcher
Orchestrates the profile stack: multiple non-overlapping profiles can be
active simultaneously. For each module, the highest-priority active profile
that includes it wins. If no active profile covers a module, the module's
built-in default behaviour applies (e.g. Resonite uses its default data path).

Stack model:
  - active_stack is an ordered list of profile names, index 0 = lowest priority
  - resolve_stack() returns module_id → Profile for the winning profile per module
  - Loading a new profile detects overlapping modules with existing stack entries;
    the GUI decides whether to proceed (the new profile wins, overriding lower ones)
  - Unloading re-applies the next lower profile that covers each affected module,
    or reverts to module defaults if nothing in the remaining stack covers it
"""

from __future__ import annotations
import logging
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from core.profile_manager import Profile, ProfileManager
from core.module_base import VRModule, ModuleStatus
from modules import get_module, MODULE_REGISTRY

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[str, str, str], None]


@dataclass
class ModuleConflict:
    """A module whose owning app is currently running and can't live-reload."""
    module_id: str
    display_name: str
    pids: list[int]
    can_reload: bool


@dataclass
class StackConflict:
    """A module claimed by both the incoming profile and an already-active one."""
    module_id: str
    display_name: str
    incoming_profile: str
    active_profile: str   # name of the already-active profile that claims this module


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
    Coordinates profile stack operations.
    The GUI owns the active_stack list (persisted in AppSettings).
    This class receives stack state as parameters so the GUI remains
    the single source of truth.
    """

    def __init__(self, profile_manager: ProfileManager):
        self.pm = profile_manager

    # ------------------------------------------------------------------ #
    # Stack resolution                                                     #
    # ------------------------------------------------------------------ #

    def resolve_stack(self, stack: list[Profile]) -> dict[str, Profile]:
        """
        Given an ordered stack (index 0 = lowest priority, last = highest),
        return module_id → winning Profile.
        """
        result: dict[str, Profile] = {}
        for profile in stack:          # low → high; later entries overwrite
            for mid in profile.enabled_modules():
                result[mid] = profile
        return result

    def check_stack_conflicts(
        self, incoming: Profile, stack: list[Profile]
    ) -> list[StackConflict]:
        """
        Return overlapping modules between `incoming` and every already-active
        profile in `stack`. The incoming profile would win (highest priority),
        but we surface these so the GUI can warn the user.
        """
        conflicts = []
        incoming_mods = set(incoming.enabled_modules())
        for active in stack:
            if active.name == incoming.name:
                continue
            for mid in active.enabled_modules():
                if mid in incoming_mods:
                    display = (MODULE_REGISTRY[mid].display_name
                               if mid in MODULE_REGISTRY else mid)
                    conflicts.append(StackConflict(
                        module_id=mid,
                        display_name=display,
                        incoming_profile=incoming.name,
                        active_profile=active.name,
                    ))
        return conflicts

    def check_conflicts(self, profile: Profile) -> list[ModuleConflict]:
        """Return running-app conflicts for modules that don't support live reload."""
        conflicts = []
        for mid in profile.enabled_modules():
            try:
                module = self._make_module(profile, mid)
                status = module.get_status()
                if status.is_running and not module.can_reload_live():
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
        statuses = {}
        for mid in profile.enabled_modules():
            try:
                module = self._make_module(profile, mid)
                statuses[mid] = module.get_status()
            except Exception as e:
                logger.error(f"Status check failed for {mid}: {e}")
        return statuses

    # ------------------------------------------------------------------ #
    # Backup                                                               #
    # ------------------------------------------------------------------ #

    def backup_to_profile(
        self,
        profile: Profile,
        progress: ProgressCallback | None = None,
    ) -> OperationResult:
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
                else:
                    logger.info(f"Backed up {mid}: {msg}")
            except Exception as e:
                result.module_results[mid] = (False, str(e))
                result.success = False
                result.errors.append(f"{mid}: {e}")
                logger.error(f"Backup exception for {mid}: {e}", exc_info=True)

        self.pm.save_profile_meta(profile)
        return result

    # ------------------------------------------------------------------ #
    # Load into stack                                                      #
    # ------------------------------------------------------------------ #

    def load_profile(
        self,
        profile: Profile,
        auto_backup_first: bool = True,
        progress: ProgressCallback | None = None,
    ) -> OperationResult:
        """Legacy single-profile load (no existing stack). Used by undo etc."""
        return self.load_into_stack(
            incoming=profile,
            current_stack=[],
            auto_backup_first=auto_backup_first,
            progress=progress,
        )

    def load_into_stack(
        self,
        incoming: Profile,
        current_stack: list[Profile],
        auto_backup_first: bool = True,
        progress: ProgressCallback | None = None,
    ) -> OperationResult:
        """
        Apply `incoming` on top of `current_stack`.
        Only restores modules that `incoming` enables — other modules are
        left exactly as they are (owned by their current stack entry).
        Caller updates the stack list after this returns successfully.
        """
        result = OperationResult(success=True)

        if auto_backup_first:
            if progress:
                progress("__auto_backup", "backup", "Auto-backing up affected modules...")
            self._auto_backup_affected(incoming, current_stack, progress)

        src_dir = self.pm.profile_dir(incoming.name)

        for mid in incoming.enabled_modules():
            if progress:
                progress(mid, "restore", f"Restoring {mid}...")
            try:
                module = self._make_module(incoming, mid)
                ok, validation_msg = module.validate_backup(src_dir)
                if not ok:
                    result.module_results[mid] = (False, f"No backup: {validation_msg}")
                    result.warnings.append(f"{module.display_name}: {validation_msg}")
                    logger.warning(f"Skipping {mid} — {validation_msg}")
                    continue

                ok, msg = module.restore(src_dir)
                result.module_results[mid] = (ok, msg)
                if ok:
                    logger.info(f"Restored {mid} from '{incoming.name}': {msg}")
                    status = module.get_status()
                    if status.is_running and module.can_reload_live():
                        if not module.trigger_reload():
                            result.warnings.append(
                                f"{module.display_name}: reload trigger failed — may need restart"
                            )
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
            self.pm.touch_last_used(incoming.name)

        return result

    # ------------------------------------------------------------------ #
    # Unload from stack                                                    #
    # ------------------------------------------------------------------ #

    def unload_from_stack(
        self,
        profile: Profile,
        remaining_stack: list[Profile],
        progress: ProgressCallback | None = None,
    ) -> OperationResult:
        """
        Unload `profile`. For each module it owns:
          - If remaining_stack has a lower-priority profile covering it → re-apply that
          - Otherwise → revert module to its built-in default (e.g. Resonite default path)
        `remaining_stack` must already exclude `profile`.
        """
        result = OperationResult(success=True)
        resolution = self.resolve_stack(remaining_stack)

        for mid in profile.enabled_modules():
            fallback = resolution.get(mid)
            if fallback:
                if progress:
                    progress(mid, "restore", f"Re-applying {mid} from '{fallback.name}'...")
                try:
                    module = self._make_module(fallback, mid)
                    src_dir = self.pm.profile_dir(fallback.name)
                    ok, validation_msg = module.validate_backup(src_dir)
                    if ok:
                        ok, msg = module.restore(src_dir)
                        result.module_results[mid] = (ok, msg)
                        if not ok:
                            result.warnings.append(f"{module.display_name}: {msg}")
                    else:
                        result.warnings.append(
                            f"{module.display_name}: fallback '{fallback.name}' has no backup — {validation_msg}"
                        )
                except Exception as e:
                    result.warnings.append(f"{mid}: {e}")
                    logger.error(f"Fallback restore for {mid}: {e}", exc_info=True)
            else:
                # Nothing in the remaining stack covers this module → revert to defaults
                if progress:
                    progress(mid, "cleanup", f"Reverting {mid} to defaults...")
                self._revert_module_to_default(mid, result)

        return result

    # ------------------------------------------------------------------ #
    # Module default revert                                                #
    # ------------------------------------------------------------------ #

    def _revert_module_to_default(self, mid: str, result: OperationResult):
        """
        Called when a module falls off the stack entirely (no profile covers it).
        Each module that manages external state needs an explicit revert here.
        Most file-copy modules need nothing — the files simply stay where they are.
        """
        if mid == "resonite":
            try:
                from modules.resonite import ResoniteModule
                rm = ResoniteModule(options={})
                if hasattr(rm, "remove_launch_args"):
                    ok, msg = rm.remove_launch_args()
                    result.module_results[mid + "_cleanup"] = (ok, msg)
                    if ok:
                        logger.info(f"[resonite] Reverted to default data path: {msg}")
                    else:
                        result.warnings.append(f"Resonite cleanup: {msg}")
            except Exception as e:
                result.warnings.append(f"Resonite cleanup failed: {e}")
        # All other modules: file-copy only, no external state to revert

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _make_module(self, profile: Profile, module_id: str) -> VRModule:
        options = profile.get_module_options(module_id)
        return get_module(module_id, options=options)

    def _auto_backup_affected(
        self,
        incoming: Profile,
        current_stack: list[Profile],
        progress: ProgressCallback | None = None,
    ):
        """
        Back up current live state for every module that `incoming` will overwrite.
        The backup is stored in __last_backup so the user can undo.
        """
        backup_dir = self.pm.auto_backup_dir()
        backup_dir.mkdir(parents=True, exist_ok=True)

        # Which profile currently owns each module incoming will touch?
        resolution = self.resolve_stack(current_stack)
        mods = incoming.enabled_modules()

        # Build synthetic modules dict for the auto-backup profile.json
        synthetic_modules = {}
        for mid in mods:
            owner = resolution.get(mid, incoming)
            synthetic_modules[mid] = owner.modules.get(mid, {"enabled": True, "options": {}})

        meta = Profile(
            name=ProfileManager.AUTO_BACKUP_NAME,
            notes=f"Auto-backup before loading '{incoming.name}'",
            modules=synthetic_modules,
        )
        (backup_dir / "profile.json").write_text(
            json.dumps(meta.to_dict(), indent=2), encoding="utf-8"
        )

        for mid in mods:
            if progress:
                progress(mid, "auto_backup", f"Auto-backup: {mid}")
            owner = resolution.get(mid, incoming)
            try:
                module = self._make_module(owner, mid)
                module.backup(backup_dir)
            except Exception as e:
                logger.warning(f"Auto-backup failed for {mid}: {e}")
