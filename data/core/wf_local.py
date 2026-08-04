"""
core/wf_local.py - READ-ONLY access to Warframe's local game data.

Warframe (the game) writes a session log to %LOCALAPPDATA%\\Warframe\\EE.log
and refreshes it as you play. Companion apps like AlecaFrame read that file -
never write it - to learn who is logged in and when the data last changed,
which keeps them within the game's terms of service. This module follows the
same rule, enforced in code, not by convention:

  * Every file handle is opened through _open_readonly(), which uses
    os.O_RDONLY at the OS level - the descriptor is physically incapable of
    writing, truncating, or appending, no matter what later code does with it.
  * Nothing in this module ever opens a game file any other way. There is no
    write/append/utime/rename/delete call against game paths anywhere here.
  * Reads are capped (MAX_SCAN_BYTES) so a huge log can't stall the UI.

The game updates EE.log during play, so consumers must expect staleness. By
design nothing here re-reads automatically: callers capture log_mtime() when
they read and decide for themselves when to look again (core.ee_events does
exactly that with its byte offset).
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import BinaryIO
from core import atomic

ROOT = Path(__file__).resolve().parent.parent

# Where the game keeps its local data (fixed location, all launchers).
LOG_DIR = Path(os.environ.get("LOCALAPPDATA", "")) / "Warframe"
EE_LOG = LOG_DIR / "EE.log"

# Never pull more than this much of a log into memory (EE.log can grow to
# hundreds of MB in long sessions; the account lines appear in the first few
# hundred KB, right after login).
MAX_SCAN_BYTES = 16 * 1024 * 1024

# Host-side prefs (the install dir override). This file lives in OUR
# folder - game files are never written, ever.
PREFS_PATH = ROOT / ".wf_local.json"


# ---- the read-only guarantee ------------------------------------------------

def _open_readonly(path: Path) -> BinaryIO:
    """Open a game file so it CANNOT be modified through this handle.

    os.O_RDONLY yields a descriptor with no write capability at the OS level;
    O_BINARY (Windows) avoids any newline translation. The game can keep
    writing to the file while we hold this handle - we never lock it."""
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    return os.fdopen(os.open(str(path), flags), "rb")


def read_file_readonly(path: Path, limit: int = MAX_SCAN_BYTES) -> bytes:
    """The only road to a game file's bytes. Read-only handle, size-capped."""
    with _open_readonly(path) as fh:
        return fh.read(limit)


def read_from_readonly(path: Path, offset: int, limit: int = MAX_SCAN_BYTES) \
        -> bytes:
    """Read up to `limit` bytes starting at `offset`, read-only. Seeking a
    read-only descriptor cannot write; this is how the event tail reads only the
    bytes the game has appended since the last pass, without re-scanning a log
    that grows to hundreds of MB in a long session."""
    with _open_readonly(path) as fh:
        fh.seek(offset)
        return fh.read(limit)


# ---- EE.log ------------------------------------------------------------------

# Verified against a live EE.log (2026-07-26):
#   0.123  Sys [Diag]: Current directory: D:\...\Warframe\Tools
_RX_CURDIR = re.compile(r"Current directory:\s*(.+?)\s*$", re.MULTILINE)


def log_mtime(path: Path = EE_LOG) -> float | None:
    """The game data file's current last-modified time (None if absent).
    stat() only - the file is not opened, let alone written."""
    try:
        return path.stat().st_mtime
    except OSError:
        return None


# ---- install location ---------------------------------------------------------

def detect_install() -> Path | None:
    """Best-effort auto-detect of the Warframe install directory.
    Registry first (authoritative for the launcher actually in use), then the
    log's own 'Current directory' line, then common locations."""
    # 1) the launcher's own registry key (HKCU, no elevation needed)
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Digital Extremes\Warframe\Launcher") as k:
            exe, _ = winreg.QueryValueEx(k, "LauncherExe")
        p = Path(exe).parent            # ...\Warframe\Tools
        if p.name.lower() == "tools":
            p = p.parent
        if p.is_dir():
            return p
    except OSError:
        pass
    # 2) EE.log records the game's working directory (...\Warframe\Tools)
    if EE_LOG.exists():
        try:
            head = read_file_readonly(EE_LOG, 64 * 1024).decode(
                "utf-8", errors="replace")
            m = _RX_CURDIR.search(head)
            if m:
                p = Path(m.group(1).strip())
                if p.name.lower() == "tools":
                    p = p.parent
                if p.is_dir():
                    return p
        except OSError:
            pass
    # 3) the usual suspects
    for cand in (
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
        / "Steam" / "steamapps" / "common" / "Warframe",
        LOG_DIR / "Downloaded" / "Public",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        / "Epic Games" / "Warframe",
    ):
        if cand.is_dir():
            return cand
    return None


# ---- prefs -------------------------------------------------------------------

def load_prefs() -> dict:
    """{install_dir: str|None}"""
    try:
        data = json.loads(PREFS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}                   # []/null would crash the setdefault below
    data.setdefault("install_dir", None)
    return data


def save_prefs(prefs: dict) -> None:
    atomic.write_json(PREFS_PATH, prefs)
