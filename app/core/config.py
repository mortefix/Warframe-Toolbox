"""
core/config.py - app settings + the registry of user-data files.

Settings live in .wfm_settings.json next to the app. This module also knows
every file the app generates about the user (session, prefs, watchlist,
caches) so the Settings > Data > WF Toolbox page can list, open and delete
them - and it owns the Windows integration bits: the startup registry entry
and launching Warframe itself.
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SETTINGS_PATH = ROOT / ".wfm_settings.json"

# Standard windowed sizes (smallest sets the app's minimum size).
WINDOW_SIZES = ["640x480", "800x600", "1024x600", "1024x768", "1280x720",
                "1366x768", "1440x900", "1536x864", "1920x1080", "2560x1440"]

DEFAULTS = {
    "fullscreen": False,           # maximize on launch
    "window_size": "1280x720",     # windowed size
    "monitor": 1,                  # which display to open on (1-based)
    "start_with_windows": False,   # HKCU Run entry for the Toolbox
    "launch_with_warframe": False, # watcher: open the Toolbox when the GAME starts
    "dev_panels": False,           # show the Settings > DevTools section
    "minimize_to_tray": False,     # minimize hides to the notification area
    "close_to_tray": True,         # closing the window hides to the tray instead
                                   # of quitting - a background helper stays ready
                                   # beside the game (Quit from the tray to exit)
    "adblock": True,               # block ads/trackers in the web apps
    "theme": "Orokin Dark",        # colour palette: "Orokin Dark" / "Orokin Light"
    # Digital Extremes account identity for the public profile API
    # (getProfileViewingData). Captured once from warframe.com/api/user-data or
    # pasted in Settings; empty until then, and the app falls back to AlecaFrame
    # for mastery rank while it is empty. NOT the warframe.market id.
    "wf_account_id": "",           # 24-hex DE ObjectId
    "wf_platform": "pc",           # pc/ps4/xb1/swi/mob/and
    "vosfor_balance": 0,           # Vosfor planner: your current balance
    # which acquisition methods the planner weighs (farm/market discount
    # arcanes you can easily get another way)
    "vosfor_methods": {"vosfor": True, "farm": False, "market": False},
    # ✉ clipboard templates (Settings > Market > Messaging). Placeholders:
    # {user} = the other tenno, {item} = item name, {price} = posted price.
    # The '/w {user} ' prefix makes the paste a whisper in-game.
    "msg_buy": ("/w {user} Hello. I would like to purchase {item} for "
                "{price}p. (warframe.market)"),
    "msg_sell": ("/w {user} Hello. I have {item} available for {price}p. "
                 "(warframe.market)"),
}


def load_settings() -> dict:
    try:
        raw = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    # DEEP copy. `dict(DEFAULTS)` is shallow, so every settings object
    # handed out shared the SAME `vosfor_methods` dict as DEFAULTS itself -
    # ticking a method box in the planner edited the defaults in place, and
    # "reset to defaults" would then restore whatever it had been changed to.
    out = copy.deepcopy(DEFAULTS)
    for k in DEFAULTS:
        if k in raw:
            out[k] = raw[k]
    return out


def save_settings(settings: dict) -> None:
    """Written via a temp file and swapped into place. Settings are saved on
    every keystroke-ish change, so a crash or a full disk mid-write would
    otherwise leave a truncated JSON file - which `load_settings` reads as
    "no settings at all" and silently replaces with defaults."""
    tmp = SETTINGS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    os.replace(tmp, SETTINGS_PATH)


# ---- user data registry -------------------------------------------------------

CACHE_DIR = ROOT / ".cache"
THUMB_CACHE = CACHE_DIR / "thumbs"

#: The collected-game-data store (owned by core.store; the path is duplicated
#: here, like THUMB_CACHE, so the Settings > Data page can size and wipe the
#: whole store as one group rather than listing every namespace file). Holds the
#: profile, worldState, Public Export and inventory namespaces.
WF_DATA_DIR = ROOT / ".wf_data"

# (filename, what it holds). Only files the app GENERATES about the user -
# program assets (embedded icons, assets/logo.ico, the code) are not listed
# and are never touched by the data-deletion actions.
USER_FILES: list[tuple[str, str]] = [
    (".wfm_session.json", "warframe.market session token (the account link)"),
    (".wfm_listings.json", "My Listings prefs: floor/cap offsets + overrides"),
    (".wfm_watchlist.json", "Market watchlist (bookmarked items)"),
    (".wf_local.json", "Warframe install path override"),
    (".vosfor_owned.json", "Vosfor planner: manual arcane check-offs"),
    (".vosfor_prices.json", "Vosfor planner: cached warframe.market prices"),
    (".arcane_inv.json", "(legacy) cached arcane inventory — superseded by the "
                         "collected-data store"),
    (".wfm_settings.json", "app settings (this Settings screen)"),
    # These two were missing, so they were invisible on the WF Toolbox page
    # AND survived "Delete ALL user data" - a wipe that leaves data behind is
    # worse than no wipe, because it is believed.
    (".wfm_contract_watchlist.json", "watched riven / lich contracts"),
    (".web_bookmarks.json", "saved pages in the embedded web apps"),
    ("launch-error.log", "startup crash log (only exists after a crash)"),
]


def user_data_files() -> list[tuple[str, Path, str, int]]:
    """(name, path, description, size_bytes) for every user file that
    currently exists on disk."""
    out = []
    for name, desc in USER_FILES:
        p = ROOT / name
        if p.exists():
            out.append((name, p, desc, p.stat().st_size))
    return out


def thumb_cache_size() -> tuple[int, int]:
    """(file count, total bytes) of the downloaded-image cache."""
    n = total = 0
    if THUMB_CACHE.is_dir():
        for f in THUMB_CACHE.iterdir():
            if f.is_file():
                n += 1
                total += f.stat().st_size
    return n, total

def wf_data_size() -> tuple[int, int]:
    """(file count, total bytes) of the collected-game-data store, walked
    recursively (Public Export nests manifests in a subfolder)."""
    n = total = 0
    if WF_DATA_DIR.is_dir():
        for f in WF_DATA_DIR.rglob("*"):
            if f.is_file():
                n += 1
                total += f.stat().st_size
    return n, total


def clear_wf_data() -> int:
    """Delete the whole collected-data store (profile, worldState, export,
    inventory). Never touches program assets or game files. Returns the number
    of files removed; the refreshers simply re-earn each namespace on next run."""
    n = 0
    if WF_DATA_DIR.is_dir():
        for f in sorted(WF_DATA_DIR.rglob("*"), reverse=True):
            try:
                if f.is_file():
                    f.unlink()
                    n += 1
                elif f.is_dir():
                    f.rmdir()
            except OSError:
                pass
    return n


def human_size(n: int) -> str:
    """Bytes as a short human string. Lives in core because it is a pure
    derivation with no widget dependency (was in the settings view)."""
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} GB"



def clear_thumb_cache() -> int:
    """Delete downloaded item images (never program assets - those are
    embedded in core/assets.py and assets/, not in the cache). Returns the
    number of files removed."""
    n = 0
    if THUMB_CACHE.is_dir():
        for f in THUMB_CACHE.iterdir():
            if f.is_file():
                try:
                    f.unlink()
                    n += 1
                except OSError:
                    pass
    return n


#: The Tk front end kept its browser profile in `.webview` and this module
#: owned the size/clear helpers for it. Both are gone: the Qt front end's
#: profile lives in `.webengine` and is managed by `ui/web.py`, which is where
#: the engine that writes it lives.

def open_in_default_app(path: Path) -> str | None:
    """Open a user-data file in its default editor/viewer. Returns None on
    success, or a printable error. (File-system actions are a core concern -
    UI code calls this instead of os.startfile.)"""
    try:
        os.startfile(str(path))                              # noqa: S606
        return None
    except OSError as exc:
        return str(exc)


def delete_user_file(path: Path) -> bool:
    """Delete one generated user file.

    The USER_FILES registry IS the allowlist - not merely "somewhere under
    our folder", which would also match every module in the app and all of
    core/. Anything else is refused."""
    try:
        resolved = path.resolve()
    except OSError:
        return False
    if resolved.name not in {n for n, _desc in USER_FILES}:
        return False
    if resolved.parent != ROOT.resolve():
        return False
    try:
        resolved.unlink(missing_ok=True)
        return True
    except OSError:
        return False


# ---- Windows integration -----------------------------------------------------
# Everything here is deliberately machine-independent: paths derive from this
# file's location, registry entries are per-user (HKCU, no admin), and process
# detection uses the game's own executable name - so the app works unchanged
# on any Windows PC it is copied to.

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "WarframeToolbox"
RUN_WATCHER_NAME = "WarframeToolboxWatcher"
#: The launcher, in the project root. Its FILENAME is baked into the HKCU Run
#: entries, so renaming it breaks autostart for anyone who enabled it.
LAUNCHER_PYW = ROOT.parent / "Warframe Toolbox.pyw"


def set_launcher(path) -> None:
    """Point the autostart entries at the running launcher.

    A hook from when two front ends shipped side by side and each had its own
    .pyw - registering the wrong one meant "launch on startup" silently opened
    the other app. One launcher remains, so this is now a no-op in practice;
    it is kept because a second entry point (a packaged .exe) would need it
    again immediately.
    """
    global LAUNCHER_PYW
    LAUNCHER_PYW = path
WATCHER_PYW = ROOT / "warframe_watcher.pyw"           # watcher lives in app/


def _pythonw() -> str:
    """The console-less interpreter matching the running one."""
    exe = Path(sys.executable)
    cand = exe.with_name("pythonw.exe")
    return str(cand if cand.exists() else exe)


def _run_entry_exists(name: str) -> bool:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, name)
        return True
    except OSError:
        return False


def _set_run_entry(name: str, cmd: str | None) -> bool:
    """Write/remove one HKCU Run value (current user only, no elevation)."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                            winreg.KEY_SET_VALUE) as k:
            if cmd:
                winreg.SetValueEx(k, name, 0, winreg.REG_SZ, cmd)
            else:
                try:
                    winreg.DeleteValue(k, name)
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        return False


def start_with_windows_enabled() -> bool:
    return _run_entry_exists(RUN_NAME)


def set_start_with_windows(enable: bool) -> bool:
    cmd = f'"{_pythonw()}" "{LAUNCHER_PYW}"' if enable else None
    return _set_run_entry(RUN_NAME, cmd)


def watch_warframe_enabled() -> bool:
    return _run_entry_exists(RUN_WATCHER_NAME)


def set_watch_warframe(enable: bool) -> bool:
    """'Launch with Warframe': register/remove the lightweight watcher that
    starts with Windows, notices the game process appearing, and opens the
    Toolbox. The watcher also re-reads settings each poll and exits itself
    when the feature is turned off."""
    cmd = f'"{_pythonw()}" "{WATCHER_PYW}"' if enable else None
    return _set_run_entry(RUN_WATCHER_NAME, cmd)


def _run_entry_broken(name: str) -> bool:
    """Does this Run entry point at something that no longer exists? The
    commands are '"<pythonw>" "<script>"' - both paths must resolve."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            cmd, _ = winreg.QueryValueEx(k, name)
    except OSError:
        return False                    # not registered: nothing to repair
    parts = [p for p in str(cmd).split('"') if p.strip()]
    return not all(Path(p.strip()).exists() for p in parts[:2])


def repair_run_entries() -> None:
    """Heal Run entries that point at things which no longer exist.

    The registry commands bake in absolute paths, so moving the folder or
    switching Python installs leaves entries that silently fail at logon
    while the Settings checkbox still reads as enabled. Only BROKEN entries
    are re-written: a working entry may belong to another copy of the app,
    and merely launching this copy shouldn't hijack it. Called at every app
    start (ui.app.main); a no-op when nothing is registered."""
    if _run_entry_broken(RUN_NAME):
        set_start_with_windows(True)
    if _run_entry_broken(RUN_WATCHER_NAME):
        set_watch_warframe(True)


def spawn_watcher() -> bool:
    """Start the watcher right now (it exits on its own if disabled or if
    another watcher instance is already running)."""
    try:
        subprocess.Popen([_pythonw(), str(WATCHER_PYW)],
                         cwd=str(ROOT), close_fds=True)
        return True
    except OSError:
        return False
