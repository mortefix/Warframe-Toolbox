"""
warframe_watcher.pyw - opens the Toolbox when Warframe starts.

Registered under HKCU Run by Settings > Display > "Launch the Toolbox when
Warframe starts", so it begins with Windows and idles in the background
(one tasklist poll every ~15s, no window, no network). When the game process
(Warframe.x64.exe) appears and no Toolbox window is open, it launches the
Toolbox, then waits for the game to exit before watching again - closing the
Toolbox mid-session won't cause it to pop back up.

Nothing here is machine-specific: paths come from this file's location, the
game is detected by its own executable name, and the Toolbox by its window
title - the folder can be copied to any Windows PC and this still works.

It exits on its own when the setting is turned off (settings are re-read
every poll) and refuses to run twice (named mutex).
"""

import ctypes
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent          # the app/ folder
SETTINGS = ROOT / ".wfm_settings.json"
TOOLBOX = ROOT.parent / "Warframe Toolbox.pyw"  # launcher lives in the root
APP_TITLE = "Warframe Toolbox"
POLL_SEC = 15


def enabled() -> bool:
    try:
        return bool(json.loads(SETTINGS.read_text(encoding="utf-8"))
                    .get("launch_with_warframe"))
    except (OSError, ValueError):
        return False


def warframe_running() -> bool:
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq Warframe.x64.exe", "/NH"],
            capture_output=True, text=True, timeout=10,
            creationflags=0x08000000).stdout          # CREATE_NO_WINDOW
        return "Warframe.x64.exe" in out
    except (OSError, subprocess.SubprocessError):
        return False


def toolbox_open() -> bool:
    return bool(ctypes.windll.user32.FindWindowW(None, APP_TITLE))


def launch_toolbox() -> None:
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    try:
        subprocess.Popen([str(pyw if pyw.exists() else exe), str(TOOLBOX)],
                         cwd=str(ROOT), close_fds=True)
    except OSError:
        # a stale interpreter path or a moved launcher must not kill the
        # watcher - it keeps polling so a later launch still works
        pass


def main() -> None:
    # single instance: a named mutex, cleaned up by the OS on exit
    ctypes.windll.kernel32.CreateMutexW(None, False,
                                        "Local\\WarframeToolboxWatcher")
    if ctypes.windll.kernel32.GetLastError() == 183:   # ERROR_ALREADY_EXISTS
        return
    while True:
        if not enabled():
            return
        if warframe_running():
            if not toolbox_open():
                launch_toolbox()
            # ride out the rest of this game session
            while warframe_running():
                time.sleep(20)
                if not enabled():
                    return
        time.sleep(POLL_SEC)


if __name__ == "__main__":
    main()
