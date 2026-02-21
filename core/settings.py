"""
App-level settings persisted to config.json alongside the profiles directory.
"""

from __future__ import annotations
import json
from pathlib import Path


DEFAULT_SETTINGS = {
    "auto_backup_before_restore": True,
    "confirm_before_restore": True,
    "log_level": "INFO",
    "window_geometry": "",
    "last_profile": "",
}


class AppSettings:
    def __init__(self, config_path: Path):
        self.config_path = config_path
        self._data: dict = dict(DEFAULT_SETTINGS)
        self.load()

    def load(self):
        if self.config_path.exists():
            try:
                loaded = json.loads(self.config_path.read_text(encoding="utf-8"))
                self._data.update(loaded)
            except Exception:
                pass

    def save(self):
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(
            json.dumps(self._data, indent=2),
            encoding="utf-8",
        )

    def get(self, key: str, default=None):
        return self._data.get(key, default)

    def set(self, key: str, value):
        self._data[key] = value
        self.save()

    def __getitem__(self, key):
        return self._data[key]

    def __setitem__(self, key, value):
        self.set(key, value)
