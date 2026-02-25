"""
Resonite Module — DataPath/CachePath approach
=============================================
Instead of copying the live LiteDB database (which is fragile and error-prone),
each VRProfile profile gets its own permanent Resonite data+cache directory pair.
On profile switch, we update Steam's launch options for Resonite (app 2519830) to
point at that profile's directories via -DataPath and -CachePath.

Why this approach:
  - No file locking / WAL mismatch issues
  - Resonite's database uses absolute paths internally (data↔cache are intertwined),
    so keeping each profile's pair together is correct per the official wiki
  - Switching is instant — just a Steam config edit + a restart of Resonite

Directory layout (inside the VRProfileSwitcher data dir):
  data/resonite_data/<profile_name>/Data/    ← Resonite DataPath
  data/resonite_data/<profile_name>/Cache/   ← Resonite CachePath

Steam config edited:
  %STEAM%/userdata/<userid>/config/localconfig.vdf
  Key: Software > Valve > Steam > Apps > 2519830 > LaunchOptions

Constraints:
  - Steam MUST be closed when we write localconfig.vdf, or Steam overwrites our changes
  - The -DataPath / -CachePath args are injected/replaced while preserving any
    other launch args the user has set (e.g. -SkipIntroTutorial, mod loader flags)
  - If the module is disabled in the active profile, the args are removed and
    Resonite falls back to its default data location

Resonite app ID: 2519830
Args: -DataPath "path" -CachePath "path"
"""

from __future__ import annotations
import os
import re
import logging
import subprocess
from pathlib import Path
from core.module_base import VRModule, ModuleStatus

logger = logging.getLogger(__name__)

RESONITE_APP_ID = "2519830"


# ---------------------------------------------------------------------------
# Steam helpers
# ---------------------------------------------------------------------------

def _steam_root() -> Path | None:
    """Find Steam installation root from registry."""
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                             r"SOFTWARE\WOW6432Node\Valve\Steam")
        path, _ = winreg.QueryValueEx(key, "InstallPath")
        return Path(path)
    except Exception:
        pass
    # Fallback common paths
    for candidate in [
        Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)")) / "Steam",
        Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "Steam",
    ]:
        if candidate.exists():
            return candidate
    return None


def _find_active_userid(steam_root: Path) -> str | None:
    """
    Return the 32-bit account ID of the most-recently-active Steam user,
    by reading loginusers.vdf which Steam maintains with a MostRecent flag.
    Returns None if unreadable or no MostRecent entry found.
    """
    loginusers = steam_root / "config" / "loginusers.vdf"
    if not loginusers.exists():
        return None
    try:
        text = loginusers.read_text(encoding="utf-8", errors="replace")
        # VDF format: "76561198xxxxxxxxx" { ... "MostRecent" "1" ... }
        # Match each top-level user block (steam64 id + braced block)
        block_pat = re.compile(r'"(\d+)"\s*\{([^}]*)\}', re.DOTALL)
        most_recent_pat = re.compile(r'"MostRecent"\s+"1"', re.IGNORECASE)
        for m in block_pat.finditer(text):
            steam64, block = m.group(1), m.group(2)
            if most_recent_pat.search(block):
                # Convert Steam64 to 32-bit account ID (lower 32 bits)
                return str(int(steam64) & 0xFFFFFFFF)
    except Exception as e:
        logger.warning(f"[resonite] Could not read loginusers.vdf: {e}")
    return None


def _find_localconfig_vdfs() -> list[Path]:
    """
    Return localconfig.vdf for the most-recently-active Steam user only.
    Writing to all user VDFs on a shared PC would clobber other accounts launch
    options, so we restrict to the account Steam most recently logged in as.
    Falls back to all VDFs if the active user cannot be determined.
    """
    root = _steam_root()
    if not root:
        return []
    userdata = root / "userdata"
    if not userdata.exists():
        return []

    active_id = _find_active_userid(root)
    if active_id:
        candidate = userdata / active_id / "config" / "localconfig.vdf"
        if candidate.exists():
            logger.debug(f"[resonite] Using localconfig.vdf for active user {active_id}")
            return [candidate]
        logger.warning(
            f"[resonite] Active userid {active_id} has no localconfig.vdf — "            f"falling back to all users"
        )

    # Fallback: all VDFs (single-user machines or loginusers.vdf unreadable)
    return list(userdata.glob("*/config/localconfig.vdf"))


def _steam_is_running() -> bool:
    try:
        out = subprocess.check_output(
            ["tasklist", "/FI", "IMAGENAME eq steam.exe", "/NH"],
            stderr=subprocess.DEVNULL,
            creationflags=0x08000000,
        ).decode(errors="ignore")
        return "steam.exe" in out.lower()
    except Exception:
        return False


def _resonite_is_running() -> bool:
    try:
        out = subprocess.check_output(
            ["tasklist", "/FI", "IMAGENAME eq Resonite.exe", "/NH"],
            stderr=subprocess.DEVNULL,
            creationflags=0x08000000,
        ).decode(errors="ignore")
        return "Resonite.exe" in out
    except Exception:
        return False


# ---------------------------------------------------------------------------
# localconfig.vdf read/write
# We use plain text manipulation rather than a full VDF parser to avoid
# adding a dependency. The LaunchOptions line is a simple quoted string.
# ---------------------------------------------------------------------------

def _read_vdf_text(path: Path) -> str:
    # Try UTF-8 first, fall back to latin-1 (Steam sometimes writes latin-1)
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return path.read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Cannot decode {path}")


def _find_app_block(text: str, app_id: str):
    """
    Locate the app_id block using balanced brace counting.
    [^}]* fails on VDF because app blocks contain nested sub-blocks
    (e.g. "cloud" { ... }) whose } terminates the naive regex early.
    Returns (block_content, open_brace_pos, close_brace_pos) or (None,-1,-1).
    """
    marker = f'"{app_id}"'
    idx = text.find(marker)
    if idx == -1:
        return None, -1, -1
    brace_start = text.find('{', idx + len(marker))
    if brace_start == -1:
        return None, -1, -1
    depth = 0
    for i in range(brace_start, len(text)):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                return text[brace_start + 1:i], brace_start, i
    return None, -1, -1


def _get_launch_options(vdf_path: Path) -> str | None:
    """
    Extract the LaunchOptions value for Resonite from localconfig.vdf.
    Uses balanced-brace block extraction to survive nested sub-blocks.
    The reader allows \" escape sequences inside the VDF value (used to
    quote paths with spaces without breaking VDF outer quoting).
    """
    text = _read_vdf_text(vdf_path)
    block, _, _ = _find_app_block(text, RESONITE_APP_ID)
    if block is None:
        return None
    # Allow \" inside the value: [^"\] matches normal chars, \. matches \+anything
    lo_pat = re.compile(r'"LaunchOptions"\s+"((?:[^"\\]|\\.)*)"', re.IGNORECASE)
    m = lo_pat.search(block)
    return m.group(1) if m else ""


def _strip_resonite_path_args(launch_opts: str) -> str:
    """
    Remove -DataPath and -CachePath (and their values) from a launch options string.
    Handles: \"quoted paths with spaces\", unquoted tokens, bare flags with no value.
    """
    result = re.sub(
        r'-(?:DataPath|CachePath)(?:\s+(?:\\"[^"]*\\"|(?!-)\S+))?',
        "",
        launch_opts,
        flags=re.IGNORECASE,
    )
    return " ".join(result.split())


def _build_path_arg(flag: str, path: Path) -> str:
    """
    Build a -Flag value for the VDF LaunchOptions string.
    Paths with spaces are wrapped in \\"-escaped quotes so the VDF outer
    quoting is not broken. Steam and Windows CreateProcess both handle \\"
    correctly — the backslash escapes the quote in the command-line string.
    """
    s = str(path).replace("\\", "/")
    if " " in s:
        return f'{flag} \\"{s}\\"'
    return f"{flag} {s}"


def _set_launch_options(vdf_path: Path, new_opts: str) -> None:
    """
    Write new_opts as the LaunchOptions for app 2519830 in localconfig.vdf.
    - Uses balanced-brace extraction so nested sub-blocks don't break the edit.
    - Strips corrupt path-fragment VDF keys left by previous bad writes.
    - Creates the app block / LaunchOptions key if absent.
    - Backs up the original file to .vdf.bak before any write.
    """
    text = _read_vdf_text(vdf_path)

    bak = vdf_path.with_suffix('.vdf.bak')
    bak.write_bytes(vdf_path.read_bytes())

    lo_pat = re.compile(r'"LaunchOptions"\s+"(.+?)"(?=\s*[\r\n]|\s*$)', re.IGNORECASE | re.MULTILINE)
    # Lambda replacement avoids re.sub interpreting \U \D etc. in the path
    lo_replacement = f'"LaunchOptions"\t\t"{new_opts}"'

    block, bstart, bend = _find_app_block(text, RESONITE_APP_ID)

    if block is not None:
        # Remove any corrupt path-fragment keys from previous bad writes
        if lo_pat.search(block):
            new_block = lo_pat.sub(lambda _: lo_replacement, block)
        else:
            new_block = block.rstrip() + f'\n\t\t\t\t\t"LaunchOptions"\t\t"{new_opts}"\n\t\t\t\t'
        new_text = text[:bstart + 1] + new_block + text[bend:]
    else:
        # App block absent — insert a minimal one into the Apps block
        apps_block, abstart, abend = _find_app_block(text, 'Apps')
        insert = (
            f'\n\t\t\t\t"{RESONITE_APP_ID}"'
            f'\n\t\t\t\t{{'
            f'\n\t\t\t\t\t"LaunchOptions"\t\t"{new_opts}"'
            f'\n\t\t\t\t}}'
        )
        if apps_block is not None:
            new_text = text[:abstart + 1] + apps_block.rstrip() + insert + '\n\t\t\t' + text[abend:]
        else:
            logger.error('[resonite] Could not find Apps block in localconfig.vdf — skipping write')
            return

    vdf_path.write_text(new_text, encoding='utf-8')
    logger.info(f'[resonite] Wrote LaunchOptions to {vdf_path}: {new_opts!r}')


# ---------------------------------------------------------------------------
# Profile data directory helpers
# ---------------------------------------------------------------------------

def _profile_data_root(profile_dir: Path) -> Path:
    """
    Root directory for Resonite data/cache for this profile.
    Lives adjacent to the profile dir in a shared resonite_data/ folder,
    keyed by profile directory name so it survives profile renames gracefully.
    """
    # Go up from profile_dir (profiles/<name>) to data root, then resonite_data/<name>
    return profile_dir.resolve().parent.parent / "resonite_data" / profile_dir.name


def _data_path(profile_dir: Path) -> Path:
    return _profile_data_root(profile_dir) / "Data"


def _cache_path(profile_dir: Path) -> Path:
    return _profile_data_root(profile_dir) / "Cache"


# ---------------------------------------------------------------------------
# Module
# ---------------------------------------------------------------------------

class ResoniteModule(VRModule):
    id = "resonite"
    display_name = "Resonite"
    icon = "🌐"
    description = (
        "Points Resonite at a per-profile -DataPath via Steam launch options. "
        "Each profile keeps its own Resonite account/session/settings. "
        "Set include_cache_path=True to also redirect -CachePath (off by default)."
    )

    def get_config_paths(self) -> list[Path]:
        # Not used for file-copy backup — this module manages Steam launch options
        return []

    def get_process_names(self) -> list[str]:
        return ["resonite.exe", "resonite-headless.exe"]

    def get_status(self) -> ModuleStatus:
        pids = []
        try:
            import psutil
            for proc in psutil.process_iter(["pid", "name"]):
                name = (proc.info.get("name") or "").lower()
                if name in ("resonite.exe", "resonite-headless.exe"):
                    pids.append(proc.info["pid"])
        except Exception:
            pass
        vdfs = _find_localconfig_vdfs()
        return ModuleStatus(
            is_running=bool(pids),
            process_pids=pids,
            config_paths_exist=bool(vdfs),
        )

    # ------------------------------------------------------------------
    # backup() — nothing to copy, just ensure per-profile dirs exist
    # ------------------------------------------------------------------
    def backup(self, dest_dir: Path) -> tuple[bool, str]:
        """
        No file copy needed — each profile has its own persistent Resonite
        data+cache directory pair. We create them if needed and record their
        absolute paths in a manifest so restore() uses the same paths.
        """
        if _resonite_is_running():
            return False, "Resonite is running. Close it before saving a profile."

        data_dir = _data_path(dest_dir)
        cache_dir = _cache_path(dest_dir)
        data_dir.mkdir(parents=True, exist_ok=True)
        cache_dir.mkdir(parents=True, exist_ok=True)

        import json
        manifest = {
            "data_path": str(data_dir),
            "cache_path": str(cache_dir),
        }
        snap = dest_dir / self.id
        snap.mkdir(parents=True, exist_ok=True)
        (snap / "paths.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        logger.info(f"[resonite] backup: data_dir={data_dir}, cache_dir={cache_dir}")
        return True, f"Profile dirs ready: {data_dir}"

    # ------------------------------------------------------------------
    # restore() — update Steam launch options to point at this profile
    # ------------------------------------------------------------------
    def restore(self, src_dir: Path) -> tuple[bool, str]:
        if _resonite_is_running():
            return False, "Resonite is running. Close it before switching profiles."
        if _steam_is_running():
            return False, (
                "Steam is running. Close Steam before switching Resonite profiles — "
                "Steam overwrites localconfig.vdf while it's open."
            )

        data_dir = _data_path(src_dir)
        cache_dir = _cache_path(src_dir)

        # DataPath and CachePath are always paired — Resonite's database stores
        # absolute paths to cache assets, so the two dirs must stay together.
        data_dir.mkdir(parents=True, exist_ok=True)
        cache_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"[resonite] restore: src_dir={src_dir.resolve()}")
        logger.info(f"[resonite] restore: data_dir={data_dir} (exists={data_dir.exists()})")
        logger.info(f"[resonite] restore: cache_dir={cache_dir} (exists={cache_dir.exists()})")

        if not data_dir.is_absolute():
            return False, (
                f"Data path resolved to a relative path: {data_dir}. "
                f"This is a bug — please report it."
            )

        vdfs = _find_localconfig_vdfs()
        if not vdfs:
            return False, "Could not find Steam localconfig.vdf. Is Steam installed?"

        updated = []
        errors = []
        for vdf_path in vdfs:
            try:
                current = _get_launch_options(vdf_path) or ""
                logger.info(f"[resonite] current LaunchOptions in {vdf_path.parent.parent.name}: {current!r}")
                stripped = _strip_resonite_path_args(current)
                new_args = _build_path_arg("-DataPath", data_dir) + " " + _build_path_arg("-CachePath", cache_dir)
                new_opts = (stripped + " " + new_args).strip() if stripped else new_args
                logger.info(f"[resonite] writing LaunchOptions: {new_opts!r}")
                _set_launch_options(vdf_path, new_opts)
                updated.append(vdf_path.parent.parent.name)
            except Exception as e:
                errors.append(f"{vdf_path}: {e}")
                logger.error(f"[resonite] Failed to update {vdf_path}: {e}")

        if not updated:
            return False, f"Failed to update any localconfig.vdf: {'; '.join(errors)}"

        msg = (
            f"Launch options updated for user(s): {', '.join(updated)}. "
            f"DataPath → {data_dir}, CachePath → {cache_dir}. "
            f"Start Steam and launch Resonite normally."
        )
        if errors:
            msg += f" | Errors: {'; '.join(errors)}"
        return True, msg

    # ------------------------------------------------------------------
    # remove() — called when switching TO a profile that has Resonite DISABLED
    # ------------------------------------------------------------------
    def remove_launch_args(self) -> tuple[bool, str]:
        """
        Remove -DataPath/-CachePath from Steam launch options so Resonite
        falls back to its default data location.
        Called by the switcher when the incoming profile has this module disabled.
        """
        if _steam_is_running():
            return False, (
                "Steam is running. Close Steam before switching profiles — "
                "launch option changes require Steam to be closed."
            )

        vdfs = _find_localconfig_vdfs()
        if not vdfs:
            return False, "Could not find Steam's localconfig.vdf."

        updated = []
        errors = []
        for vdf_path in vdfs:
            try:
                current = _get_launch_options(vdf_path) or ""
                stripped = _strip_resonite_path_args(current)
                _set_launch_options(vdf_path, stripped)
                updated.append(vdf_path.parent.parent.name)
            except Exception as e:
                errors.append(str(e))

        if not updated:
            return False, f"Failed to clear launch args: {'; '.join(errors)}"
        return True, f"Removed -DataPath/-CachePath for user(s): {', '.join(updated)}"

    def validate_backup(self, profile_dir: Path) -> tuple[bool, str]:
        data_dir = _data_path(profile_dir)
        if data_dir.exists():
            return True, f"Profile data dir exists: {data_dir}"
        return False, f"Profile data dir not yet initialised: {data_dir}"
