# VRProfile Switcher

A modular user profile switcher for VR tracking software. Instantly save and restore per-user configurations for SlimeVR, SteamVR, Resonite, and more.

## Features

- **Per-user profiles** — each profile stores its own config snapshots
- **Module system** — choose which apps to include in each profile (SlimeVR, SteamVR, Resonite, EyeTrackVR, Project Babble)
- **Safety-first** — detects running apps before switching; auto-backups current state before every restore
- **Undo** — one-click restore of the state before the last switch
- **SteamVR driver selection** — per-profile driver config (e.g. cyberfinger vs handtracking)
- **Live status** — green/grey dots show which apps are currently running

## Quick Start (Windows)

1. Install [Python 3.10+](https://python.org) and ensure it's on PATH
2. Double-click `launch.bat` — it will install dependencies and start the app
3. Or manually: `pip install -r requirements.txt` then `python main.py`

## Usage

1. **Create a profile** — click "＋ New", name it (e.g. "Alice"), toggle which modules to include
2. **Save current config** — with your apps configured how you like, click "💾 Save Current → Profile"
3. **Switch profiles** — click a profile, then "▶ Load This Profile"
   - If any apps are still running, a dialog will prompt you to close them
   - Your current state is auto-backed up before the restore
4. **Undo** — if something goes wrong, click "↩ Undo Last Switch"

## Module Details

| Module | What's saved | Requires close? |
|--------|-------------|-----------------|
| SlimeVR | vrconfig.yml, calibration, bone lengths | ✅ Yes |
| SteamVR | steamvr.vrsettings, controller bindings, driver config | ⚡ Soft restart via API |
| Resonite | Login session, game settings, user data | ✅ Yes |
| EyeTrackVR | Camera settings, calibration *(Step 2)* | ✅ Yes |
| Project Babble | Camera config, model settings *(Step 2)* | ✅ Yes |

## Adding a New Module

1. Create `modules/yourapp.py` subclassing `VRModule`:
```python
from core.module_base import VRModule
from pathlib import Path
import os

class YourAppModule(VRModule):
    id = "yourapp"
    display_name = "Your App"
    icon = "🎯"
    description = "What this module saves"

    def get_config_paths(self) -> list[Path]:
        appdata = os.environ.get("APPDATA", "")
        return [Path(appdata) / "YourApp" / "config.json"]

    def get_process_names(self) -> list[str]:
        return ["yourapp.exe"]
```

2. Register in `modules/__init__.py`:
```python
from modules.yourapp import YourAppModule
MODULE_REGISTRY["yourapp"] = YourAppModule
```

That's it — the GUI picks it up automatically.

## Data Location

All data is stored locally in the `data/` folder next to `main.py`:
```
data/
  config.json          ← app settings
  vrprofile.log        ← log file
  profiles/
    Alice/
      profile.json     ← profile metadata
      slimevr/         ← SlimeVR config snapshot
      steamvr/         ← SteamVR config snapshot
      resonite/        ← Resonite config snapshot
    __last_backup/     ← auto-backup (for Undo)
```

## Security Note

Resonite login tokens are saved as part of the profile (the same files Resonite itself writes). No passwords are stored in plaintext — only the session token files. Keep your `data/profiles/` folder secure.

## Requirements

- Windows 10/11
- Python 3.10+
- PyQt6
- psutil
