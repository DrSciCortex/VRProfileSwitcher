"""
VRProfileSwitcher — PyInstaller build script
============================================
Run from the project root:
    python build.py

Requirements:
    pip install pyinstaller pyqt6 psutil

Output:
    dist/VRProfileSwitcher/VRProfileSwitcher.exe   (folder distribution)

The build produces a single-folder distribution rather than a single-file exe.
This is intentional: the app writes data/ next to the exe, and onefile mode
would unpack to a temp directory on every launch, breaking relative path
resolution for profiles, logs, and config.

To build a single exe anyway, pass --onefile on the command line.
"""

import subprocess
import sys
import shutil
from pathlib import Path

# ── Configuration ────────────────────────────────────────────────────────────

APP_NAME    = "VRProfileSwitcher"
ENTRY_POINT = "main.py"
ICON        = "assets/icon.ico"      # multi-resolution ico from logo.png
ONE_FILE    = False

# Non-Python data to bundle (src_relative_to_root, dest_inside_bundle)
DATAS = [
    ("assets/icon.ico",      "assets"),
    ("assets/icon_64.ico",   "assets"),
]

HIDDEN_IMPORTS = [
    "PyQt6.QtCore",
    "PyQt6.QtGui",
    "PyQt6.QtWidgets",
    "psutil",
    "winreg",
    "logging.handlers",
]

EXCLUDES = [
    "tkinter",
    "unittest",
    "email",
    "http",
    "xml",
    "pydoc",
    "doctest",
    "difflib",
    "pickle",
    "multiprocessing",
]

# ── Helpers ──────────────────────────────────────────────────────────────────

def clean(root: Path):
    for d in (root / "build", root / "dist" / APP_NAME):
        if d.exists():
            shutil.rmtree(d)
            print(f"  Removed {d}")
    spec = root / f"{APP_NAME}.spec"
    if spec.exists():
        spec.unlink()
        print(f"  Removed {spec}")


def build(root: Path, one_file: bool):
    args = [
        sys.executable, "-m", "PyInstaller",
        "--name", APP_NAME,
        "--noconfirm",
        "--clean",
        "--windowed",                # no console window
        "--onefile" if one_file else "--onedir",
    ]

    icon_path = root / ICON
    if icon_path.exists():
        args += ["--icon", str(icon_path)]
    else:
        print(f"  Warning: icon not found at {icon_path} — building without icon")

    sep = ";" if sys.platform == "win32" else ":"
    for src, dst in DATAS:
        src_path = root / src
        if src_path.exists():
            args += ["--add-data", f"{src_path}{sep}{dst}"]
        else:
            print(f"  Warning: data path not found: {src_path} — skipping")

    for imp in HIDDEN_IMPORTS:
        args += ["--hidden-import", imp]

    for exc in EXCLUDES:
        args += ["--exclude-module", exc]

    args.append(str(root / ENTRY_POINT))

    print(f"\nRunning PyInstaller...\n")
    result = subprocess.run(args, cwd=str(root))

    if result.returncode != 0:
        print("\nBuild FAILED.")
        sys.exit(1)

    if not one_file:
        dist = root / "dist" / APP_NAME
        # Create empty data/ so the app can write its log on very first launch
        (dist / "data").mkdir(exist_ok=True)
        print(f"\n  Created empty data/ in {dist}")

    print(f"\nBuild SUCCESS → {root / 'dist'}")
    if not one_file:
        print(f"  Folder: dist/{APP_NAME}/")
        print(f"  Exe:    dist/{APP_NAME}/{APP_NAME}.exe")
    else:
        print(f"  Exe:    dist/{APP_NAME}.exe")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Build VRProfileSwitcher with PyInstaller")
    parser.add_argument("--clean-only", action="store_true", help="Remove build artefacts and exit")
    parser.add_argument("--onefile",    action="store_true", help="Build a single exe instead of a folder")
    parsed = parser.parse_args()

    one_file = ONE_FILE or parsed.onefile
    root = Path(__file__).resolve().parent

    print("=== VRProfileSwitcher build ===")
    print(f"  Mode: {'onefile' if one_file else 'onedir'}")

    clean(root)
    if not parsed.clean_only:
        build(root, one_file)
