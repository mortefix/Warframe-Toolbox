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

# The app itself lives in app/ - the root holds only this launcher, the
# docs, and the tooling folders.
HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(HERE, "app")
os.chdir(APP)
if APP not in sys.path:
    sys.path.insert(0, APP)

# QtWebEngine renders the web tabs in a separate Chromium process whose GPU
# compositor, on this display, presented NON-ATOMIC frames while a page
# loaded - a horizontal tear band (half the old frame, half the new) that
# corrects itself a frame later. The first fix was --disable-gpu-compositing:
# every frame came out whole, but compositing a 300%-scaled page on the CPU
# made SCROLLING visibly lag and skip - it traded one artifact for another.
# The tear lives in the PRESENTATION path (Windows DirectComposition
# overlays), not in GPU compositing itself, so disable only that layer:
# frames present through the plain DXGI swap chain, whole, while the GPU
# compositor keeps scrolling smooth. Must be set BEFORE QtWebEngine
# initialises, hence here before any Qt import. setdefault so an explicit
# environment override still wins.
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS",
                      "--disable-features=DirectComposition")

# One front end: PySide6 (app/ui/). The Tkinter host was removed once every
# screen was ported; git history has it if anything needs looking up.
#
# Keep the FILENAME: config.LAUNCHER_PYW bakes it into the HKCU Run entries,
# so renaming this file breaks autostart for anyone who enabled it.
try:
    # autostart must register THIS file, which is the launcher
    from core import config as _config
    _config.set_launcher(_config.LAUNCHER_PYW)
    from ui.app import main
    sys.exit(main())
except SystemExit:
    raise
except BaseException:                                       # noqa: BLE001
    tb = traceback.format_exc()
    try:
        with open(os.path.join(APP, "launch-error.log"), "w",
                  encoding="utf-8") as fh:
            fh.write(tb)
    except OSError:
        pass
    # Qt for the crash dialog too, so the app has no Tkinter dependency at
    # all. Tkinter would still work - it is in the standard library - but
    # "the toolkit we ship on" and "the toolkit that reports we failed to
    # start" being the same thing is one less way for this path to surprise.
    # If even Qt cannot come up there is nothing left to show a dialog with;
    # the log file is the fallback.
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
        _app = QApplication.instance() or QApplication([])
        QMessageBox.critical(None, "Warframe Toolbox - startup error", tb)
    except BaseException:                                   # noqa: BLE001
        pass
    raise
