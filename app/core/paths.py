"""
core/paths.py - WHERE user data lives. The one module that knows.

The app folder (app/) is pure code and shipped assets: it can sit on a flash
drive, be git-pulled, or be zipped into a release without ever carrying
personal data. Everything the app writes about the user goes to USERDATA,
resolved here once at import - and ONLY resolved: importing this module never
creates a directory or touches a file (ensure_dirs()/migrate_legacy() are
explicit launcher calls).

Resolution precedence:
  1. WFTOOLBOX_DATA env var - explicit override; the test runner uses this to
     point every spawned test at a throwaway temp root.
  2. <project root>/userdata/ EXISTS - the portable/dev override. A dev clone
     creates the (gitignored) folder once and its writes stay inside the
     clone, fully isolated from the live install on the same machine.
  3. The per-machine default: %LOCALAPPDATA%\\WarframeToolbox on Windows,
     $XDG_DATA_HOME/WarframeToolbox (else ~/.local/share/WarframeToolbox)
     elsewhere. Linux support is exactly this one branch - no other module
     knows platform paths.

COMPANION_DIR is deliberately NOT USERDATA: the Overwolf companion writes
inventory.json to the platform dir unconditionally (its manifest bakes the
path), so readers must look there even when the app itself runs portable.
When the app uses the platform default, both are the same directory and the
companion's file simply coexists with ours.

Stdlib-only leaf: core modules derive their file constants from USERDATA at
import time (module-level constants, so tests keep monkeypatching them).
This module must never import settings - the settings file lives INSIDE the
data root it resolves.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent     # app/ - code + assets
ROOT = APP_DIR.parent                                # project root (launcher)


def _platform_default() -> Path:
    """The per-machine data home for this OS - the Linux branch lives here."""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "WarframeToolbox"
        return Path.home() / "AppData" / "Local" / "WarframeToolbox"
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / "WarframeToolbox"


#: The Overwolf companion's fixed output directory (see module docstring).
COMPANION_DIR = _platform_default()

_PORTABLE = ROOT / "userdata"


def _resolve() -> Path:
    env = os.environ.get("WFTOOLBOX_DATA")
    if env:
        return Path(env)
    if _PORTABLE.is_dir():
        return _PORTABLE
    return _platform_default()


USERDATA = _resolve()


def is_portable() -> bool:
    """True when the gitignored <root>/userdata/ override is active."""
    return USERDATA == _PORTABLE


def ensure_dirs() -> None:
    """Create the data root. Called by the launcher, never at import."""
    USERDATA.mkdir(parents=True, exist_ok=True)


# Legacy (pre-restructure) locations inside the app folder -> new names in
# USERDATA. The dot prefixes existed to hide user files among code; in a
# dedicated data dir they are noise (and hide files on Linux), so migration
# renames. `.webengine` moves WHOLE - it holds the web tabs' logins.
_LEGACY: list[tuple[str, str]] = [
    (".wfm_session.json", "wfm_session.json"),
    (".wfm_settings.json", "wfm_settings.json"),
    (".wfm_listings.json", "wfm_listings.json"),
    (".wfm_watchlist.json", "wfm_watchlist.json"),
    (".wfm_contract_watchlist.json", "wfm_contract_watchlist.json"),
    (".wf_local.json", "wf_local.json"),
    (".web_bookmarks.json", "web_bookmarks.json"),
    (".vosfor_owned.json", "vosfor_owned.json"),
    (".vosfor_prices.json", "vosfor_prices.json"),
    (".arcane_inv.json", "arcane_inv.json"),
    (".mastery.json", "mastery.json"),
    (".cache", "cache"),
    (".mastery_badges", "mastery_badges"),
    (".wf_data", "wf_data"),
    (".webengine", "webengine"),
    ("launch-error.log", "launch-error.log"),
]


def migrate_legacy() -> None:
    """Move pre-restructure user files from app/ into USERDATA. Idempotent:
    already-moved (or never-existed) items are skipped, an existing target is
    never overwritten, and a locked item (OSError) is simply left for the
    next launch to retry. Runs in the launcher BEFORE Qt starts, so nothing
    can be holding the webengine profile."""
    for old_name, new_name in _LEGACY:
        src = APP_DIR / old_name
        dst = USERDATA / new_name
        if not src.exists() or dst.exists():
            continue
        try:
            shutil.move(str(src), str(dst))
        except OSError:
            pass
