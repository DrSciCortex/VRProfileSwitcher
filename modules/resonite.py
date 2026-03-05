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
    """Find Steam installation root, trying registry then common fallback paths."""
    # Primary: Windows registry (most reliable)
    try:
        import winreg
        for reg_path in [
            r"SOFTWARE\WOW6432Node\Valve\Steam",   # 64-bit OS
            r"SOFTWARE\Valve\Steam",                # 32-bit OS
        ]:
            try:
                key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, reg_path)
                path, _ = winreg.QueryValueEx(key, "InstallPath")
                result = Path(path)
                logger.debug(f"[resonite] Steam root from registry ({reg_path}): {result}")
                return result
            except OSError:
                continue
    except ImportError:
        logger.debug("[resonite] winreg not available (not on Windows?)")
    except Exception as e:
        logger.warning(f"[resonite] Registry lookup failed: {e}")

    # Fallback: common install locations
    candidates = [
        Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)")) / "Steam",
        Path(os.environ.get("PROGRAMFILES",       "C:/Program Files"))       / "Steam",
        Path(os.environ.get("LOCALAPPDATA", ""))  / "Steam",
        Path("C:/Steam"),
        Path("D:/Steam"),
        Path("E:/Steam"),
    ]
    for candidate in candidates:
        if candidate.exists() and (candidate / "userdata").exists():
            logger.info(f"[resonite] Steam root found via fallback path: {candidate}")
            return candidate

    logger.warning("[resonite] Could not locate Steam installation.")
    return None


def _find_active_userid(steam_root: Path) -> str | None:
    """
    Return the userdata folder name (32-bit account ID) for the most-recently-
    active Steam account, by reading loginusers.vdf (MostRecent flag).
    Returns None if unreadable or no MostRecent entry found.
    """
    loginusers = steam_root / "config" / "loginusers.vdf"
    if not loginusers.exists():
        logger.warning(f"[resonite] loginusers.vdf not found at {loginusers}")
        return None

    try:
        text = loginusers.read_text(encoding="utf-8", errors="replace")
        # VDF: "76561198xxxxxxxxx" { ... "MostRecent" "1" ... }
        block_pat = re.compile(r'"(\d+)"\s*\{([^}]*)\}', re.DOTALL)
        most_recent_pat = re.compile(r'"MostRecent"\s+"1"', re.IGNORECASE)
        for m in block_pat.finditer(text):
            steam64, block = m.group(1), m.group(2)
            if most_recent_pat.search(block):
                account_id = str(int(steam64) & 0xFFFFFFFF)
                logger.info(f"[resonite] Most-recent Steam user: steam64={steam64} → userid={account_id}")
                return account_id
        logger.warning("[resonite] No MostRecent entry found in loginusers.vdf")
    except Exception as e:
        logger.warning(f"[resonite] Could not read loginusers.vdf: {e}")
    return None


def _find_localconfig_vdfs() -> list[Path]:
    """
    Return localconfig.vdf path(s) to update.
    Targets the most-recently-active Steam user only (to avoid clobbering other
    accounts on shared PCs). Falls back to all user VDFs if the active user
    cannot be determined.
    Logs clearly at each decision point so failures are easy to diagnose.
    """
    root = _steam_root()
    if not root:
        logger.error(
            "[resonite] Steam root not found. "
            "Is Steam installed? Try installing Steam or check that "
            "HKLM\\SOFTWARE\\WOW6432Node\\Valve\\Steam\\InstallPath exists in the registry."
        )
        return []

    userdata = root / "userdata"
    if not userdata.exists():
        logger.error(
            f"[resonite] Steam userdata directory not found: {userdata}. "
            "Has Steam ever been logged into on this PC?"
        )
        return []

    all_vdfs = list(userdata.glob("*/config/localconfig.vdf"))
    logger.debug(f"[resonite] All localconfig.vdf files found: {[str(v) for v in all_vdfs]}")

    if not all_vdfs:
        logger.error(
            f"[resonite] No localconfig.vdf files found under {userdata}. "
            "Log into Steam at least once, then launch Resonite to create the config entry."
        )
        return []

    # Try to target the active user only
    active_id = _find_active_userid(root)
    if active_id:
        candidate = userdata / active_id / "config" / "localconfig.vdf"
        if candidate.exists():
            logger.info(f"[resonite] Using localconfig.vdf for active user {active_id}: {candidate}")
            return [candidate]
        else:
            logger.warning(
                f"[resonite] Active user {active_id} has no localconfig.vdf at {candidate}. "
                "Falling back to all user VDFs."
            )
    else:
        logger.info(
            "[resonite] Could not determine active Steam user — "
            f"falling back to all {len(all_vdfs)} user VDF(s)."
        )

    return all_vdfs


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
# ---------------------------------------------------------------------------

def _read_vdf_text(path: Path) -> str:
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return path.read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Cannot decode {path}")


def _find_app_block(text: str, app_id: str):
    """
    Locate an app_id block using balanced brace counting.
    Naive [^}]* regex fails when the block contains nested sub-blocks.
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


def _find_resonite_block(text: str):
    """
    Find the Resonite (2519830) block scoped within Software > Valve > Steam.
    Some VDFs have a second shallow "2519830" entry at the top level (sibling
    of "Software") used for cloud/achievement metadata — that one has an empty
    LaunchOptions and must be ignored. We drill through the Software > Valve >
    Steam chain, accumulating absolute offsets at each level so that the
    returned bstart/bend positions are correct for splicing back into the full text.
    Falls back to a global search if the Steam block chain isn't found.
    Returns (block_content, abs_bstart, abs_bend) with absolute offsets into text.
    """
    scope = text
    abs_offset = 0
    for parent in ("Software", "Valve", "Steam"):
        block, bstart, bend = _find_app_block(scope, parent)
        if block is None:
            logger.warning(
                f"[resonite] Expected '{parent}' block not found in localconfig.vdf — "
                f"falling back to global search. This may target the wrong '2519830' entry "
                f"if multiple exist. Please report this with a sanitised copy of your VDF."
            )
            return _find_app_block(text, RESONITE_APP_ID)
        abs_offset += bstart + 1  # +1 skips the opening {
        scope = block

    inner_block, rel_bstart, rel_bend = _find_app_block(scope, RESONITE_APP_ID)
    if inner_block is None:
        logger.warning(
            f"[resonite] Resonite ({RESONITE_APP_ID}) block not found inside "
            f"Software > Valve > Steam — falling back to global search. "
            f"Has Resonite been launched from Steam at least once?"
        )
        return _find_app_block(text, RESONITE_APP_ID)

    logger.debug("[resonite] Found Resonite block via Software > Valve > Steam scope")
    return inner_block, rel_bstart + abs_offset, rel_bend + abs_offset


def _get_launch_options(vdf_path: Path) -> str | None:
    """
    Extract the LaunchOptions value for Resonite from localconfig.vdf.
    Returns the raw string, '' if the key is absent, None if the app block is absent.
    """
    text = _read_vdf_text(vdf_path)
    block, _, _ = _find_resonite_block(text)
    if block is None:
        logger.warning(
            f"[resonite] App block {RESONITE_APP_ID} not found in {vdf_path}. "
            "Has Resonite been launched from Steam at least once on this account?"
        )
        return None
    lo_pat = re.compile(r'"LaunchOptions"\s+"((?:[^"\\]|\\.)*)"', re.IGNORECASE)
    m = lo_pat.search(block)
    value = m.group(1) if m else ""
    logger.debug(f"[resonite] Read LaunchOptions from {vdf_path.parent.parent.name}: {value!r}")
    return value


def _strip_resonite_path_args(launch_opts: str) -> str:
    """
    Remove -DataPath and -CachePath (and their values) from a launch options string.
    Handles: \"quoted paths\", unquoted tokens, bare flags with no value.
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
    Paths with spaces are wrapped in backslash-escaped quotes.
    Forward slashes replace backslashes to avoid Windows escape sequences
    (e.g. \\U in \\Users, \\D in \\Desktop) breaking Steam's arg parser.
    """
    s = str(path).replace("\\", "/")
    if " " in s:
        return f'{flag} \\"{s}\\"'
    return f"{flag} {s}"


def _set_launch_options(vdf_path: Path, new_opts: str) -> None:
    """
    Write new_opts as the LaunchOptions for Resonite in localconfig.vdf.
    Uses balanced-brace extraction so nested sub-blocks don't break the edit.
    Creates the app block / LaunchOptions key if absent.
    Backs up to .vdf.bak before writing.
    """
    text = _read_vdf_text(vdf_path)
    bak = vdf_path.with_suffix(".vdf.bak")
    bak.write_bytes(vdf_path.read_bytes())

    lo_pat = re.compile(r'"LaunchOptions"\s+"(?:[^"\\]|\\.)*"', re.IGNORECASE)
    lo_replacement = f'"LaunchOptions"\t\t"{new_opts}"'

    block, bstart, bend = _find_resonite_block(text)

    if block is not None:
        if lo_pat.search(block):
            new_block = lo_pat.sub(lambda _: lo_replacement, block)
        else:
            new_block = block.rstrip() + f'\n\t\t\t\t\t"LaunchOptions"\t\t"{new_opts}"\n\t\t\t\t'
            logger.info(f"[resonite] LaunchOptions key was absent — inserting it")
        new_text = text[:bstart + 1] + new_block + text[bend:]
    else:
        # App block absent — insert a minimal one into the Apps block
        logger.info(f"[resonite] App block {RESONITE_APP_ID} absent — creating it")
        apps_block, abstart, abend = _find_app_block(text, "Apps")
        insert = (
            f'\n\t\t\t\t"{RESONITE_APP_ID}"'
            f'\n\t\t\t\t{{'
            f'\n\t\t\t\t\t"LaunchOptions"\t\t"{new_opts}"'
            f'\n\t\t\t\t}}'
        )
        if apps_block is not None:
            new_text = text[:abstart + 1] + apps_block.rstrip() + insert + "\n\t\t\t" + text[abend:]
        else:
            logger.error(
                f"[resonite] Cannot find Apps block in {vdf_path}. "
                "The localconfig.vdf may be malformed or from an unexpected Steam version."
            )
            return

    vdf_path.write_text(new_text, encoding="utf-8")
    logger.info(f"[resonite] Wrote LaunchOptions to {vdf_path.parent.parent.name}: {new_opts!r}")


# ---------------------------------------------------------------------------
# Profile data directory helpers
# ---------------------------------------------------------------------------

def _profile_data_root(profile_dir: Path) -> Path:
    """Absolute path to resonite_data/<profile_name>/ for this profile."""
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
        "Points Resonite at a per-profile -DataPath and -CachePath via Steam "
        "launch options. Each profile keeps its own Resonite account/world/settings."
    )

    def get_config_paths(self) -> list[Path]:
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
    # backup() — ensure per-profile dirs exist, write paths.json manifest
    # ------------------------------------------------------------------
    def backup(self, dest_dir: Path) -> tuple[bool, str]:
        if _resonite_is_running():
            return False, "Resonite is running. Close it before saving a profile."

        data_dir  = _data_path(dest_dir)
        cache_dir = _cache_path(dest_dir)
        data_dir.mkdir(parents=True, exist_ok=True)
        cache_dir.mkdir(parents=True, exist_ok=True)

        import json
        manifest = {"data_path": str(data_dir), "cache_path": str(cache_dir)}
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

        data_dir  = _data_path(src_dir)
        cache_dir = _cache_path(src_dir)
        data_dir.mkdir(parents=True, exist_ok=True)
        cache_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"[resonite] restore: src_dir={src_dir.resolve()}")
        logger.info(f"[resonite] restore: data_dir={data_dir}")
        logger.info(f"[resonite] restore: cache_dir={cache_dir}")

        if not data_dir.is_absolute():
            return False, f"Data path is relative: {data_dir} — this is a bug, please report it."

        vdfs = _find_localconfig_vdfs()
        if not vdfs:
            return False, (
                "Could not find Steam's localconfig.vdf. "
                "Check the log for details on why Steam was not found."
            )

        new_args = (
            _build_path_arg("-DataPath",  data_dir) + " " +
            _build_path_arg("-CachePath", cache_dir)
        )

        updated, errors = [], []
        for vdf_path in vdfs:
            try:
                current = _get_launch_options(vdf_path)
                if current is None:
                    # App block missing — _set_launch_options will create it
                    logger.info(
                        f"[resonite] No existing Resonite block in "
                        f"{vdf_path.parent.parent.name} — will create it. "
                        "Note: launch Resonite from Steam at least once if this fails."
                    )
                    current = ""
                stripped = _strip_resonite_path_args(current)
                new_opts = (stripped + " " + new_args).strip() if stripped else new_args
                logger.info(f"[resonite] Writing to {vdf_path.parent.parent.name}: {new_opts!r}")
                _set_launch_options(vdf_path, new_opts)
                updated.append(vdf_path.parent.parent.name)
            except Exception as e:
                errors.append(f"{vdf_path.parent.parent.name}: {e}")
                logger.error(f"[resonite] Failed to update {vdf_path}: {e}", exc_info=True)

        if not updated:
            return False, (
                f"Failed to update any localconfig.vdf. Errors: {'; '.join(errors)}"
            )

        msg = (
            f"Launch options updated (user: {', '.join(updated)}). "
            f"Start Steam and launch Resonite normally."
        )
        if errors:
            msg += f" | Partial errors: {'; '.join(errors)}"
        return True, msg

    # ------------------------------------------------------------------
    # remove_launch_args() — called when Resonite module unloaded from stack
    # ------------------------------------------------------------------
    def remove_launch_args(self) -> tuple[bool, str]:
        """Remove -DataPath/-CachePath so Resonite falls back to its default location."""
        if _steam_is_running():
            return False, (
                "Steam is running. Close Steam before unloading a Resonite profile — "
                "launch option changes require Steam to be closed."
            )

        vdfs = _find_localconfig_vdfs()
        if not vdfs:
            return False, (
                "Could not find Steam's localconfig.vdf. "
                "Check the log for details on why Steam was not found."
            )

        updated, errors = [], []
        for vdf_path in vdfs:
            try:
                current = _get_launch_options(vdf_path) or ""
                stripped = _strip_resonite_path_args(current)
                logger.info(f"[resonite] Clearing path args for {vdf_path.parent.parent.name}: {stripped!r}")
                _set_launch_options(vdf_path, stripped)
                updated.append(vdf_path.parent.parent.name)
            except Exception as e:
                errors.append(f"{vdf_path.parent.parent.name}: {e}")
                logger.error(f"[resonite] Failed to clear {vdf_path}: {e}", exc_info=True)

        if not updated:
            return False, f"Failed to clear launch args. Errors: {'; '.join(errors)}"
        msg = f"Removed -DataPath/-CachePath (user: {', '.join(updated)})."
        if errors:
            msg += f" | Partial errors: {'; '.join(errors)}"
        return True, msg

    def validate_backup(self, profile_dir: Path) -> tuple[bool, str]:
        data_dir = _data_path(profile_dir)
        if data_dir.exists():
            return True, f"Profile data dir exists: {data_dir}"
        return False, f"Profile data dir not yet initialised: {data_dir}"
