# VRProfile Switcher

A modular user profile switcher for VR software. Instantly switch between per-user configurations for SlimeVR, SteamVR, Resonite, EyeTrackVR, Project Babble, Virtual Desktop, and more.

## Features

- **Per-user profiles** — each profile stores its own config snapshots
- **Module system** — choose which apps to include per profile
- **Safety-first** — detects running apps before switching; auto-backups current state before every restore
- **Soft delete** — deleted profiles go to a rolling history (last 5 kept), recoverable at any time
- **Import** — pull profiles from another VRProfileSwitcher data directory (network share, USB, backup)
- **Undo** — one-click restore of the state before the last switch
- **Live status** — green/grey dots show which apps are currently running

## Quick Start (Windows)

1. Install [Python 3.10+](https://python.org) and ensure it's on PATH
2. Double-click `launch.bat` — it will install dependencies and start the app
3. Or manually: `pip install -r requirements.txt` then `python main.py`

## Usage

1. **Create a profile** — click "＋ New", name it (e.g. "Alice"), toggle which modules to include
2. **Save current config** — with your apps configured how you like, click "💾 Save Current → Profile"
3. **Switch profiles** — click a profile, then "▶ Load This Profile"
   - If any apps are still running, a dialog will prompt you to close them first
   - Your current state is auto-backed up before every restore
4. **Undo** — if something goes wrong, click "↩ Undo Last Switch"

## Module Details

| Module | Approach | What's saved / managed | Requires close? |
|--------|----------|------------------------|-----------------|
| SlimeVR | File copy | vrconfig.yml, calibration, bone lengths, OSC/VMC/filtering | ✅ Yes |
| SteamVR | File copy | steamvr.vrsettings, controller bindings, driver config | ⚡ Soft restart |
| Resonite | Steam launch args | Per-profile data+cache directory pair — see note below | ✅ Yes + Steam closed |
| Resonite Mod Settings | File copy | RML mod config JSONs from `rml_config/` | ✅ Yes |
| Resolute | File copy + DLLs | Resolute app state; optionally mod DLLs from `rml_mods/` | ✅ Yes |
| EyeTrackVR | File copy | Camera settings, calibration, optional VRCFT module config | ✅ Yes |
| Project Babble | File copy | Camera config, model settings, optional VRCFT module config | ✅ Yes |
| Virtual Desktop | File copy | GameSettings.json, StreamerSettings.json, BindingSettings.json | Streamer restart |

## Resonite Module — How it Works & Limitations

The Resonite module takes a fundamentally different approach from the other modules: instead of copying the live database around, **each profile gets its own permanent Resonite data+cache directory pair**.

On profile switch, the module edits Steam's launch options for Resonite (app `2519830`) to inject `-DataPath` and `-CachePath` pointing at that profile's directory. Resonite then boots straight into the right account, session, and settings — no file copying, no database corruption risk.

### Directory layout

```
data/
  resonite_data/
    Alice/
      Data/     ← Resonite's full data dir for this profile (database, LocalStorage, etc.)
      Cache/    ← Resonite's cache dir for this profile
    Bob/
      Data/
      Cache/
  profiles/
    Alice/
      profile.json
      slimevr/
      ...
```

### Requirements for switching

- **Resonite must be closed** — the module blocks if Resonite is running
- **Steam must be closed** — Steam overwrites `localconfig.vdf` while running, so launch option edits require Steam to be closed first. After switching, start Steam normally and launch Resonite from there.

> **Tip:** A future improvement would launch Resonite directly via `Resonite.exe -DataPath ... -CachePath ...` from within the switcher, bypassing Steam entirely and removing the "close Steam" requirement. If you always want to launch Resonite from the switcher rather than from Steam, this would make switching fully seamless.

### ⚠️ New profiles start with a blank Resonite state

When you create a new profile and enable the Resonite module, that profile's `Data/` directory starts **completely empty**. This means:

- Resonite will run the intro tutorial on first launch (you can skip it with `-SkipIntroTutorial` in additional launch options)
- You will need to log in again
- Your Local Home will be empty (cloud inventory is unaffected — that syncs from the cloud)

**Why can't we copy an existing profile's data as a starting point?**
Resonite's LiteDB database stores absolute file paths internally — the `Cache/` directory is referenced by full path from within `Data/`. Copying the database to a new directory would leave it full of dead links pointing at the old cache location. Fixing this would require parsing and rewriting LiteDB internals, which is unsupported and fragile.

**The intended workflow:**
- Create a profile, enable Resonite, log in once, and let it sync. That's your baseline.
- From then on, switching to that profile brings you back to that account's full state instantly.
- Profiles are long-lived — create them once, use them indefinitely.

### What is preserved per-profile

Everything Resonite writes locally: account session/credentials, all in-game settings, Local Home contents, locally saved items, face/body calibration stored locally, and the full `LocalStorage/` directory. Cloud inventory and worlds are always synced from the Resonite cloud regardless of which profile you're in.

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

```
data/
  config.json              ← app settings
  vrprofile.log            ← log file
  resonite_data/           ← per-profile Resonite data+cache dirs (see above)
    Alice/
      Data/
      Cache/
  profiles/
    Alice/
      profile.json         ← profile metadata
      slimevr/             ← SlimeVR config snapshot
      steamvr/             ← SteamVR config snapshot
    __last_backup/         ← auto-backup before last switch (for Undo)
    __deleted__/           ← soft-deleted profiles (rolling last 5)
```

## Security Note

The Resonite `Data/` directory contains your local session token and login credentials (the same files Resonite itself writes — no passwords in plaintext). Keep your `data/resonite_data/` folder secure, especially if sharing the machine or syncing to cloud storage.

## Requirements

- Windows 10/11
- Python 3.10+
- PyQt6
- psutil
