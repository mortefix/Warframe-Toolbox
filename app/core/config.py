"""
core/config.py - app settings + the registry of user-data files.

Settings live in wfm_settings.json in the per-machine data root
(core.paths.USERDATA). This module also knows every file the app generates
about the user (session, prefs, watchlist, caches) so the Settings > Data >
WF Toolbox page can list, open and delete them - and it owns the Windows
integration bits: the startup registry entry and launching Warframe itself.
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

from core import atomic
from core import paths

ROOT = Path(__file__).resolve().parent.parent

SETTINGS_PATH = paths.USERDATA / "wfm_settings.json"

# Standard windowed sizes (smallest sets the app's minimum size).
WINDOW_SIZES = ["640x480", "800x600", "1024x600", "1024x768", "1280x720",
                "1366x768", "1440x900", "1536x864", "1920x1080", "2560x1440"]

# DEFAULTS is the single source of truth for a new user's settings.
# `docs/default-settings.json` is a human-readable MIRROR of this dict, kept in
# sync for easy review — when you add or change a key here, update that file too
# (the per-user blank fields wf_account_id / wf_platform / vosfor_balance stay
# empty in the mirror on purpose).
DEFAULTS = {
    "fullscreen": True,            # maximize on launch
    "window_size": "1280x720",     # windowed size
    "monitor": 1,                  # which display to open on (1-based)
    "start_with_windows": False,   # HKCU Run entry for the Toolbox
    "launch_with_warframe": False, # watcher: open the Toolbox when the GAME starts
    "dev_panels": False,           # show the Settings > DevTools section
    "minimize_to_tray": False,     # minimize hides to the notification area
    "close_to_tray": False,        # closing the window hides to the tray instead
                                   # of quitting - a background helper stays ready
                                   # beside the game (Quit from the tray to exit)
    "check_updates": True,         # launch-time git self-update (core.updater)
    "welcomed": False,             # first-launch setup wizard has been shown
    "adblock": True,               # block ads/trackers in the web apps
    "theme": "Orokin Dark",        # colour palette: "Orokin Dark" / "Orokin Light"
    # Digital Extremes account identity for the public profile API
    # (getProfileViewingData). Captured once from the signed-in warframe.com site or
    # pasted in Settings; empty until then, and the app falls back to AlecaFrame
    # for mastery rank while it is empty. NOT the warframe.market id.
    "wf_account_id": "",           # 24-hex DE ObjectId
    "wf_platform": "",             # pc/ps4/xb1/swi/mob/and (empty until connected)
    "vosfor_balance": 0,           # Vosfor planner: your current balance
    # which acquisition methods the planner weighs (farm/market discount
    # arcanes you can easily get another way)
    "vosfor_methods": {"vosfor": True, "farm": False, "market": False},
    # ✉ clipboard templates (Settings > Market > Messaging). Placeholders:
    # {user} = the other tenno, {item} = item name, {price} = posted price.
    # The '/w {user} ' prefix makes the paste a whisper in-game.
    "msg_buy": ("/w {user} Hello. I would like to purchase {item} for "
                "{price}p. (Warframe Toolbox)"),
    "msg_sell": ("/w {user} Hello. I have {item} available for {price}p. "
                 "(Warframe Toolbox)"),
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
    "no settings at all" and silently replaces with defaults. core.atomic
    gives each writer its own temp name, so two overlapping saves cannot
    interleave into one garbage file either."""
    atomic.write_json(SETTINGS_PATH, settings)


# ---- user data registry -------------------------------------------------------

CACHE_DIR = paths.USERDATA / "cache"
THUMB_CACHE = CACHE_DIR / "thumbs"
MOD_IMG_CACHE = CACHE_DIR / "mod_images"   # wiki mod-card art (core.mod_images)
BADGE_CACHE = paths.USERDATA / "mastery_badges"   # wiki rank art (core.mastery)

#: Every downloaded-image folder: sized and wiped as one group.
IMAGE_CACHES = (THUMB_CACHE, MOD_IMG_CACHE, BADGE_CACHE)

#: The collected-game-data store (owned by core.store; the path is duplicated
#: here, like THUMB_CACHE, so the Settings > Data page can size and wipe the
#: whole store as one group rather than listing every namespace file). Holds the
#: profile, worldState, Public Export and inventory namespaces.
WF_DATA_DIR = paths.USERDATA / "wf_data"

# (filename, what it holds). Only files the app GENERATES about the user -
# program assets (embedded icons, assets/logo.ico, the code) are not listed
# and are never touched by the data-deletion actions.
USER_FILES: list[tuple[str, str]] = [
    ("wfm_session.json", "warframe.market session token (the account link)"),
    ("wfm_listings.json", "My Listings prefs: floor/cap offsets + overrides"),
    ("wfm_watchlist.json", "Market watchlist (bookmarked items)"),
    ("wfm_archive.json", "My Listings: Saved For Later (parked orders + "
                         "target prices)"),
    ("wf_local.json", "Warframe install path override"),
    ("vosfor_owned.json", "Vosfor planner: manual arcane check-offs"),
    ("vosfor_prices.json", "Vosfor planner: cached warframe.market prices"),
    ("arcane_inv.json", "(legacy) cached arcane inventory — superseded by the "
                        "collected-data store"),
    ("wfm_settings.json", "app settings (this Settings screen)"),
    # These two were missing, so they were invisible on the WF Toolbox page
    # AND survived "Delete ALL user data" - a wipe that leaves data behind is
    # worse than no wipe, because it is believed.
    ("wfm_contract_watchlist.json", "watched riven / lich contracts"),
    ("web_bookmarks.json", "saved pages in the embedded web apps"),
    # ...and so were these two: the wipe left the mod collection and the
    # cached mastery rank behind.
    ("mods_player.db", "Mods: your collection (owned / lost flags)"),
    ("mastery.json", "cached mastery rank"),
    ("launch-error.log", "startup crash log (only exists after a crash)"),
]


def user_data_files() -> list[tuple[str, Path, str, int]]:
    """(name, path, description, size_bytes) for every user file that
    currently exists on disk."""
    out = []
    for name, desc in USER_FILES:
        p = paths.USERDATA / name
        if p.exists():
            out.append((name, p, desc, p.stat().st_size))
    return out


def thumb_cache_size() -> tuple[int, int]:
    """(file count, total bytes) of the downloaded-image caches (market
    thumbnails, wiki mod-card art, mastery badges) - sized and wiped as one
    group."""
    n = total = 0
    for d in IMAGE_CACHES:
        if d.is_dir():
            for f in d.iterdir():
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
    for d in IMAGE_CACHES:
        if not d.is_dir():
            continue
        for f in d.iterdir():
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
    if resolved.parent != paths.USERDATA.resolve():
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
LAUNCHER_PYW = paths.ROOT / "Warframe Toolbox.pyw"


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


def _run_entry_paths(name: str) -> list[Path] | None:
    """The paths a Run entry names - '"<pythonw>" "<script>"' - or None when
    the entry is not registered."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            cmd, _ = winreg.QueryValueEx(k, name)
    except OSError:
        return None
    return [Path(part.strip()) for part in str(cmd).split('"')
            if part.strip()]


def _same_file(a, b) -> bool:
    return (os.path.normcase(os.path.abspath(str(a)))
            == os.path.normcase(os.path.abspath(str(b))))


def _run_entry_is_ours(name: str, script) -> bool:
    """Registered AND pointing at this copy's script. The Run key is one per
    Windows user, but several copies of the app can exist on a machine (an
    installed build and a dev clone): an entry that starts another copy is
    not "enabled" as far as this copy's Settings page is concerned."""
    parts = _run_entry_paths(name)
    return bool(parts) and len(parts) >= 2 and _same_file(parts[1], script)


def _set_owned_run_entry(name: str, script, enable: bool) -> bool:
    """Enable: point the entry at this copy. Disable: remove it - but only
    if it is ours. Turning the option off (or wiping user data) in one copy
    must not silently delete another copy's autostart."""
    if enable:
        return _set_run_entry(name, f'"{_pythonw()}" "{script}"')
    if _run_entry_exists(name) and not _run_entry_is_ours(name, script):
        return True
    return _set_run_entry(name, None)


def start_with_windows_enabled() -> bool:
    return _run_entry_is_ours(RUN_NAME, LAUNCHER_PYW)


def set_start_with_windows(enable: bool) -> bool:
    return _set_owned_run_entry(RUN_NAME, LAUNCHER_PYW, enable)


def watch_warframe_enabled() -> bool:
    return _run_entry_is_ours(RUN_WATCHER_NAME, WATCHER_PYW)


def set_watch_warframe(enable: bool) -> bool:
    """'Launch with Warframe': register/remove the lightweight watcher that
    starts with Windows, notices the game process appearing, and opens the
    Toolbox. The Run entry is the single source of truth: the watcher keeps
    running only while the entry names its own file, so removing the entry
    (here, or from outside the app) is what stops it."""
    return _set_owned_run_entry(RUN_WATCHER_NAME, WATCHER_PYW, enable)


def _run_entry_broken(name: str) -> bool:
    """Does this Run entry point at something that no longer exists? The
    commands are '"<pythonw>" "<script>"' - both paths must resolve."""
    parts = _run_entry_paths(name)
    if parts is None:
        return False                    # not registered: nothing to repair
    return not all(part.exists() for part in parts[:2])


def repair_run_entries() -> None:
    """Heal Run entries, and let the installed build own them.

    The registry commands bake in absolute paths, so moving the folder or
    switching Python installs leaves entries that silently fail at logon
    while the Settings checkbox still reads as enabled. A BROKEN entry is
    re-written to this copy.

    A WORKING entry that starts another copy is left alone - merely
    launching a dev clone must not hijack autostart - with one exception:
    the INSTALLED build takes such an entry over. Autostart belongs to the
    installed app; a dev clone that once registered itself (or healed a
    broken entry after a folder move) hands it back the next time the
    installed build runs.

    Called at every app start (ui.app.main); a no-op when nothing is
    registered."""
    claim = paths.is_installed()
    for name, script, setter in (
            (RUN_NAME, LAUNCHER_PYW, set_start_with_windows),
            (RUN_WATCHER_NAME, WATCHER_PYW, set_watch_warframe)):
        if not _run_entry_exists(name):
            continue
        if _run_entry_broken(name) or (
                claim and not _run_entry_is_ours(name, script)):
            setter(True)


#: Inno Setup's per-user uninstall record for the installed build (AppId in
#: tools/installer/installer.iss + "_is1").
_UNINSTALL_KEY = (r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
                  r"\{A1F5C7E2-4B93-4D6A-9C0E-3F2B1A8D7E6C}_is1")


def sync_installed_version(version: str) -> None:
    """Keep the version Windows shows under "Installed apps" in step with
    the running app. The installer writes it once, but the app updates
    itself afterwards, so without this the list shows whatever version the
    installer was built at for ever. Installed build only; never raises."""
    if not paths.is_installed():
        return
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _UNINSTALL_KEY, 0,
                            winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE) as k:
            try:
                current, _ = winreg.QueryValueEx(k, "DisplayVersion")
            except OSError:
                current = None
            if current != version:
                winreg.SetValueEx(k, "DisplayVersion", 0, winreg.REG_SZ,
                                  version)
    except OSError:
        pass


def spawn_watcher() -> bool:
    """Start the watcher right now (it exits on its own if disabled or if
    another watcher instance is already running)."""
    try:
        subprocess.Popen([_pythonw(), str(WATCHER_PYW)],
                         cwd=str(ROOT), close_fds=True)
        return True
    except OSError:
        return False
