"""Resolve real Windows Documents (including redirected/OneDrive folders)."""
from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def documents_dir() -> Path:
    if os.name == "nt":
        # CSIDL_PERSONAL resolves redirected Documents; do not assume USERPROFILE.
        buf = ctypes.create_unicode_buffer(32768)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0:
            return Path(buf.value)
    return Path.home() / "Documents"


def telemetry_dir() -> Path:
    return documents_dir() / "iRacing" / "telemetry"


def setup_files(car: str = "ferrari296gt3") -> list[Path]:
    # Only list filenames: .sto is not a documented editable telemetry format.
    if car != Path(car).name or car in {".", ".."}:
        return []
    root = documents_dir() / "iRacing" / "setups" / car
    return sorted(root.rglob("*.sto")) if root.exists() else []


def data_dir() -> Path:
    override = os.environ.get("ENDURANCE_DATA_DIR")
    if override:
        return Path(override).resolve()
    if getattr(sys, "frozen", False):
        local = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return local / "IRSetupHelper" / "data"
    return ROOT / "data"
