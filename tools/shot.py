"""Grab the real app at a forced per-app scale + window size, for cross-DPI
verification. OS display settings are never touched.

Scale is controlled by QT_SCALE_FACTOR, which is a MULTIPLIER off the machine's
native device-pixel-ratio. On a 300%/DPR-3 machine, target DPR = 3 * factor:
  1x -> QT_SCALE_FACTOR=0.3333   2x -> 0.6667   3x -> 1.0 (native)
Usage: QT_SCALE_FACTOR=0.6667 python tools/shot.py market 1280 680 out.png
"""
import os, sys
os.environ.pop("QT_QPA_PLATFORM", None)          # native platform, real fonts
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

page, w, h, out = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
from PySide6.QtGui import QFontDatabase
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv[:1])
from ui import qss
app.setStyleSheet(qss.build(set(QFontDatabase.families())))
from ui.app import MainWindow
win = MainWindow(); win.show_configured()
win.setWindowState(Qt.WindowNoState)             # un-maximize so resize applies
win.resize(w, h); win.navigate(page)
for _ in range(30):
    app.processEvents()
img = win.grab(); img.save(out)
print(f"saved {out}  dpr={win.devicePixelRatioF():.2f} grab={img.width()}x{img.height()} page={page}")
