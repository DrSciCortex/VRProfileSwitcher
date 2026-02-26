"""
Diagnostic script for VRProfileSwitcher's Resonite module.
Usage: python debug_resonite.py [profile_name]
       python debug_resonite.py  (runs Steam/VDF discovery only)
"""
import sys
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from modules.resonite import (
    _read_vdf_text, _find_localconfig_vdfs, _get_launch_options,
    _strip_resonite_path_args, _build_path_arg,
    _data_path, _cache_path, _steam_root, _find_active_userid,
    RESONITE_APP_ID,
)
from core.profile_manager import ProfileManager

PROFILES_DIR = ROOT / "data" / "profiles"

def section(title):
    print()
    print(f"{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")

# ── Steam installation ──────────────────────────────────────────
section("Steam installation")
root = _steam_root()
print(f"  Steam root:       {root}")
print(f"  Root exists:      {root.exists() if root else 'N/A'}")

if root:
    userdata = root / "userdata"
    print(f"  userdata dir:     {userdata}")
    print(f"  userdata exists:  {userdata.exists()}")

    if userdata.exists():
        subdirs = list(userdata.iterdir())
        print(f"  userdata subdirs: {[d.name for d in subdirs]}")

    loginusers = root / "config" / "loginusers.vdf"
    print(f"  loginusers.vdf:   {loginusers}")
    print(f"  loginusers exists:{loginusers.exists()}")

    if loginusers.exists():
        active_id = _find_active_userid(root)
        print(f"  active userid:    {active_id}")
        if active_id:
            candidate = userdata / active_id / "config" / "localconfig.vdf"
            print(f"  candidate vdf:    {candidate}")
            print(f"  candidate exists: {candidate.exists()}")

# ── VDF discovery ───────────────────────────────────────────────
section("VDF discovery")
vdfs = _find_localconfig_vdfs()
print(f"  VDFs found: {len(vdfs)}")
for vdf in vdfs:
    print(f"  - {vdf}  (exists={vdf.exists()})")

if not vdfs:
    print()
    print("  *** No VDFs found — this is why loading does nothing. ***")
    print("  Check Steam root detection above.")
    sys.exit(1)

# ── Per-VDF inspection ──────────────────────────────────────────
for vdf in vdfs:
    section(f"VDF: {vdf.parent.parent.name}")
    text = _read_vdf_text(vdf)
    print(f"  File size: {len(text)} chars")

    marker = f'"{RESONITE_APP_ID}"'
    idx = text.find(marker)
    print(f"  Resonite block ({RESONITE_APP_ID}) at pos: {idx}")

    if idx >= 0:
        brace_start = text.find('{', idx)
        depth = 0
        end = -1
        for i in range(brace_start, len(text)):
            if text[i] == '{': depth += 1
            elif text[i] == '}':
                depth -= 1
                if depth == 0:
                    end = i
                    break
        raw_block = text[brace_start:end+1] if end > 0 else "(not found)"
        print(f"  Raw block ({len(raw_block)} chars):")
        print("    " + raw_block[:600].replace('\n', '\n    '))
    else:
        print("  *** Resonite app block not found — game may never have been launched ***")
        print("  *** Launch Resonite once from Steam, then retry. ***")

    current = _get_launch_options(vdf) or ""
    print(f"\n  Current LaunchOptions: {current!r}")

# ── Profile paths (if profile name given) ───────────────────────
profile_name = sys.argv[1] if len(sys.argv) > 1 else None
if profile_name:
    section(f"Profile: {profile_name}")
    pm = ProfileManager(PROFILES_DIR)
    src_dir = pm.profile_dir(profile_name)
    print(f"  src_dir:        {src_dir}")
    print(f"  src_dir exists: {src_dir.exists()}")
    data_dir = _data_path(src_dir)
    cache_dir = _cache_path(src_dir)
    print(f"  data_dir:       {data_dir}")
    print(f"  data_dir exists:{data_dir.exists()}")
    print(f"  cache_dir:      {cache_dir}")
    print(f"  is_absolute:    {data_dir.is_absolute()}")
    print()
    data_arg  = _build_path_arg("-DataPath",  data_dir)
    cache_arg = _build_path_arg("-CachePath", cache_dir)
    print(f"  data_arg:  {data_arg!r}")
    print(f"  cache_arg: {cache_arg!r}")
    print()
    for vdf in vdfs:
        current = _get_launch_options(vdf) or ""
        stripped = _strip_resonite_path_args(current)
        new_opts = (stripped + " " + data_arg + " " + cache_arg).strip()
        print(f"  [{vdf.parent.parent.name}] would write:")
        print(f"    {new_opts!r}")
else:
    print()
    print("Tip: pass a profile name to also check path resolution:")
    print('  python debug_resonite.py "DrSci - Resonite"')
