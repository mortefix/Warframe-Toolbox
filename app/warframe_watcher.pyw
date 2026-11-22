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

The HKCU Run entry is the single source of truth. The watcher keeps running
only while that entry exists AND names this very file (re-checked every
poll), so it exits on its own when the option is turned off, when the entry
is removed from outside the app, or when another copy of the Toolbox takes
the entry over. It used to read a settings file instead - which meant an
entry written by anything but this copy's Settings page (the installer, a
repair) started a watcher that quit immediately. It refuses to run twice
(named mutex).
"""

import ctypes
import os
import subprocess
import sys
import time
from pathlib import Path

ME = Path(__file__).resolve()
ROOT = ME.parent                                # the app/ folder
TOOLBOX = ROOT.parent / "Warframe Toolbox.pyw"  # launcher lives in the root
APP_TITLE = "Warframe Toolbox"
POLL_SEC = 15
# Duplicated from core.config on purpose: this file stays dependency-free.
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "WarframeToolboxWatcher"


def enabled() -> bool:
    """Is the Run entry registered, and registered as THIS file?"""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            cmd, _ = winreg.QueryValueEx(k, RUN_NAME)
    except OSError:
        return False
    return os.path.normcase(str(ME)) in os.path.normcase(str(cmd))


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
    """A top-level QT window titled like the app. The title alone is not
    enough: an Explorer window showing the "Warframe Toolbox" folder has the
    same caption, and would stop the Toolbox from ever being launched."""
    user32 = ctypes.windll.user32
    user32.FindWindowExW.restype = ctypes.c_void_p
    user32.FindWindowExW.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                     ctypes.c_wchar_p, ctypes.c_wchar_p]
    user32.GetClassNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p,
                                     ctypes.c_int]
    buf = ctypes.create_unicode_buffer(256)
    hwnd = None
    while True:
        hwnd = user32.FindWindowExW(None, hwnd, None, APP_TITLE)
        if not hwnd:
            return False
        user32.GetClassNameW(hwnd, buf, 256)
        if buf.value.startswith("Qt"):          # e.g. Qt6110QWindowIcon
            return True


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
    # use_last_error: ctypes makes other API calls between ours, so a bare
    # GetLastError() afterwards reads whatever THEY left behind - the
    # "already running" check could miss and two watchers would both launch.
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    handle = kernel32.CreateMutexW(None, False,
                                   "Local\\WarframeToolboxWatcher")
    if not handle or ctypes.get_last_error() == 183:   # ERROR_ALREADY_EXISTS
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
