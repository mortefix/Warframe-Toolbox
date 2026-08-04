#!/usr/bin/env pythonw
"""
Warframe Toolbox launcher - no terminal window.

Double-clicking a .pyw file runs it with pythonw.exe instead of python.exe, so
the app opens as a standalone window with no console behind it. (The tools it
launches still work: their output is captured over a pipe, not a console.)

Because there's no console, a startup crash would otherwise be invisible - so
any exception before the window opens is written to launch-error.log and shown
in a dialog.
"""

import os
import sys
import traceback

# The app itself lives in data/ - the root holds only this launcher and the
# README. Everything the app generates (session, prefs, caches, logs) stays
# inside data/ too.
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
os.chdir(DATA)
if DATA not in sys.path:
    sys.path.insert(0, DATA)

# Which front end. QT IS NOW THE DEFAULT: every screen is ported, and it is
# the only one that renders at this display's native resolution. `--tk` (or
# WFTOOLBOX_UI=tk) still opens the old Tkinter app, kept for one release as a
# way back if something here turns out to be missing.
#
# Keep the FILENAME either way: config.LAUNCHER_PYW bakes it into the HKCU Run
# entries, so renaming this file breaks autostart for anyone who enabled it.
_TK = "--tk" in sys.argv or os.environ.get("WFTOOLBOX_UI", "").lower() == "tk"

try:
    if _TK:
        from wf_market_helper import main
    else:
        # autostart must register THIS file, which is the default launcher
        from core import config as _config
        _config.set_launcher(_config.LAUNCHER_TK)
        from ui.app import main
    sys.exit(main())
except SystemExit:
    raise
except BaseException:                                       # noqa: BLE001
    tb = traceback.format_exc()
    try:
        with open(os.path.join(DATA, "launch-error.log"), "w",
                  encoding="utf-8") as fh:
            fh.write(tb)
    except OSError:
        pass
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Warframe Toolbox - startup error", tb)
    except Exception:                                       # noqa: BLE001
        pass
    raise
