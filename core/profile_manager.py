"""
Profile Manager
Handles creation, deletion, listing, and serialization of user profiles.

Profile storage layout:
  data/profiles/
    <profile_name>/
      profile.json        ← metadata and module config
      slimevr/            ← SlimeVR config snapshot
      steamvr/            ← SteamVR config snapshot
      resonite/           ← Resonite config snapshot
      ...
"""

from __future__ import annotations
import json
import shutil
import logging
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Any

logger = logging.getLogger(__name__)

# Default module config for new profiles
DEFAULT_MODULE_CONFIG = {
    "slimevr":    {"enabled": True,  "options": {}},
    "steamvr":    {"enabled": True,  "options": {"active_driver": None}},
    "resonite":   {"enabled": True,  "options": {}},
    "eyetrackvr": {"enabled": False, "options": {}},
    "babble":     {"enabled": False, "options": {}},
}


@dataclass
class ProfileModuleConfig:
    enabled: bool = True
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class Profile:
    name: str
    created: str = ""
    last_used: str = ""
    notes: str = ""
    modules: dict[str, dict] = field(default_factory=dict)

    def __post_init__(self):
        if not self.created:
            self.created = _now_iso()
        # Ensure all known modules have an entry
        for mid, defaults in DEFAULT_MODULE_CONFIG.items():
            if mid not in self.modules:
                self.modules[mid] = dict(defaults)

    def is_module_enabled(self, module_id: str) -> bool:
        return self.modules.get(module_id, {}).get("enabled", False)

    def set_module_enabled(self, module_id: str, enabled: bool):
        if module_id not in self.modules:
            self.modules[module_id] = dict(DEFAULT_MODULE_CONFIG.get(module_id, {"enabled": False, "options": {}}))
        self.modules[module_id]["enabled"] = enabled

    def get_module_options(self, module_id: str) -> dict:
        return self.modules.get(module_id, {}).get("options", {})

    def set_module_option(self, module_id: str, key: str, value: Any):
        if module_id not in self.modules:
            self.modules[module_id] = {"enabled": False, "options": {}}
        self.modules[module_id].setdefault("options", {})[key] = value

    def enabled_modules(self) -> list[str]:
        return [mid for mid, cfg in self.modules.items() if cfg.get("enabled", False)]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Profile":
        return cls(
            name=data["name"],
            created=data.get("created", ""),
            last_used=data.get("last_used", ""),
            notes=data.get("notes", ""),
            modules=data.get("modules", {}),
        )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProfileManager:
    """Manages profiles stored on disk under a base directory."""

    PROFILE_JSON = "profile.json"
    AUTO_BACKUP_NAME = "__last_backup"

    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def list_profiles(self) -> list[Profile]:
        """Return all profiles sorted by last_used descending, auto-backup excluded."""
        profiles = []
        for d in sorted(self.base_dir.iterdir()):
            if not d.is_dir():
                continue
            if d.name.startswith("__"):
                continue
            pf = self._load_profile_dir(d)
            if pf:
                profiles.append(pf)
        profiles.sort(key=lambda p: p.last_used or p.created, reverse=True)
        return profiles

    def get_profile(self, name: str) -> Profile | None:
        d = self._profile_dir(name)
        return self._load_profile_dir(d)

    def create_profile(self, name: str, notes: str = "") -> Profile:
        """Create a new empty profile. Raises ValueError if name already exists."""
        name = self._sanitize_name(name)
        d = self._profile_dir(name)
        if d.exists():
            raise ValueError(f"Profile '{name}' already exists")
        d.mkdir(parents=True)
        profile = Profile(name=name, notes=notes)
        self._save_profile_json(profile)
        logger.info(f"Created profile: {name}")
        return profile

    def delete_profile(self, name: str) -> bool:
        d = self._profile_dir(name)
        if not d.exists():
            return False
        shutil.rmtree(d)
        logger.info(f"Deleted profile: {name}")
        return True

    def rename_profile(self, old_name: str, new_name: str) -> Profile:
        new_name = self._sanitize_name(new_name)
        old_dir = self._profile_dir(old_name)
        new_dir = self._profile_dir(new_name)
        if not old_dir.exists():
            raise FileNotFoundError(f"Profile '{old_name}' not found")
        if new_dir.exists():
            raise ValueError(f"Profile '{new_name}' already exists")
        old_dir.rename(new_dir)
        profile = self._load_profile_dir(new_dir)
        profile.name = new_name
        self._save_profile_json(profile)
        return profile

    def save_profile_meta(self, profile: Profile):
        """Persist profile metadata changes (name, notes, module config)."""
        self._save_profile_json(profile)

    def touch_last_used(self, name: str):
        profile = self.get_profile(name)
        if profile:
            profile.last_used = _now_iso()
            self._save_profile_json(profile)

    def profile_dir(self, name: str) -> Path:
        return self._profile_dir(name)

    def auto_backup_dir(self) -> Path:
        return self.base_dir / self.AUTO_BACKUP_NAME

    def get_auto_backup(self) -> Profile | None:
        return self._load_profile_dir(self.auto_backup_dir())

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _profile_dir(self, name: str) -> Path:
        return self.base_dir / name

    def _load_profile_dir(self, d: Path) -> Profile | None:
        if not d.is_dir():
            return None
        json_file = d / self.PROFILE_JSON
        if not json_file.exists():
            return None
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            return Profile.from_dict(data)
        except Exception as e:
            logger.error(f"Failed to load profile from {d}: {e}")
            return None

    def _save_profile_json(self, profile: Profile):
        d = self._profile_dir(profile.name)
        d.mkdir(parents=True, exist_ok=True)
        json_file = d / self.PROFILE_JSON
        json_file.write_text(
            json.dumps(profile.to_dict(), indent=2),
            encoding="utf-8",
        )

    def _sanitize_name(self, name: str) -> str:
        name = name.strip()
        if not name:
            raise ValueError("Profile name cannot be empty")
        # Remove chars unsafe for directory names
        invalid = set(r'\/:*?"<>|')
        sanitized = "".join(c for c in name if c not in invalid)
        if not sanitized:
            raise ValueError("Profile name contains only invalid characters")
        return sanitized
