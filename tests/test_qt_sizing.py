"""Nothing may change SIZE when it changes state.

A control that grows when you tick it shoves its neighbours sideways, and on
a dense screen that reads as the layout glitching rather than as the control
working. It is also invisible to every other kind of test: the value is
right, the paint is right, only the geometry moved.

The specific bug this was written for: `QCheckBox::indicator` set
`width: 14px` plus, when checked, `padding: 2px`. In Qt style sheets width is
the CONTENT box and padding is added on top, so ticking a box took it from
16px to 20px - every checkbox in the app, on every screen.

This walks the REAL screens rather than a sample widget, because the rule has
to hold wherever a control actually lives - a page can always override the
sheet locally and reintroduce the jump.
"""
import os
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS",
                      "--disable-gpu --disable-software-rasterizer "
                      "--no-sandbox --in-process-gpu")

try:
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtWidgets import (QAbstractButton, QApplication, QCheckBox,
                                   QRadioButton)
except ImportError:
    print("PySide6 not installed - skipping sizing checks")
    raise SystemExit(0)

fails = []


def check(name, got, want=True):
    ok = got == want
    if not ok:
        fails.append(f"{name}: got {got!r}, want {want!r}")
    print(f"  {'ok  ' if ok else 'FAIL'} {name}")


app = QApplication([])
from core import config as core_config                            # noqa: E402
from ui import qss, web as ui_web                                 # noqa: E402
ui_web.isolate_for_tests()   # NEVER the running app's profile
ui_web.AUTOLOAD = False
core_config.save_settings = lambda s: None
app.setStyleSheet(qss.build())

from core import nav as core_nav                                  # noqa: E402
from registry import TOOLS                                        # noqa: E402
from ui.app import MIN_HEIGHT, MIN_WIDTH, MainWindow              # noqa: E402


def sizes(w):
    """(unchecked hint, checked hint) for a checkable widget, repolished so
    the style sheet's state selectors are actually re-resolved - Qt does not
    re-evaluate them on setChecked alone."""
    was = w.isChecked()
    out = []
    for state in (False, True):
        w.setChecked(state)
        w.style().unpolish(w)
        w.style().polish(w)
        out.append(w.sizeHint())
    w.setChecked(was)
    w.style().unpolish(w)
    w.style().polish(w)
    return out


print("the bare controls, straight from the style sheet")
for cls in (QCheckBox, QRadioButton):
    probe = cls("label")
    off, on = sizes(probe)
    check(f"{cls.__name__} keeps its size", (off.width(), off.height()),
          (on.width(), on.height()))

print("\nand every checkable control on every real screen")
win = MainWindow()
win.resize(1280, 760)
win.show()
app.processEvents()
keys = [i.key for i in core_nav.nav_items(TOOLS)]
for key in keys:
    win.navigate(key)
    app.processEvents()

checked_any = 0
jumped = []
for key in keys:
    index = win._pages.get(key)
    if index is None:
        continue
    page = win.stack.widget(index)
    for w in page.findChildren(QAbstractButton):
        if not w.isCheckable():
            continue
        checked_any += 1
        off, on = sizes(w)
        if off != on:
            jumped.append(f"{key}:{w.__class__.__name__}"
                          f"({w.text()[:20]!r}) {off} -> {on}")
check("no control on any screen resizes when toggled", jumped, [])
check("and there were controls to check", checked_any > 0)
print(f"       {checked_any} checkable controls across {len(keys)} screens")

print("\nthe checked fill is inset, not edge to edge")
# the whole reason padding exists here: two filled boxes at 100% read as one
# blob. Measure the gold against the indicator's own box.
probe = QCheckBox("x")
probe.setChecked(True)
probe.show()
app.processEvents()
img = probe.grab().toImage()
from core import theme as th                                      # noqa: E402
# ACCENT only - GOLD_DIM is the BORDER, and counting it made the
# measured span the whole box, which is what the check is trying
# to rule out
gold = {th.ACCENT.lower()}
fill = [(x, y) for x in range(img.width()) for y in range(img.height())
        if img.pixelColor(x, y).name().lower() in gold]
check("something gold is painted", len(fill) > 20)
if fill:
    xs = [x for x, _y in fill]
    ys = [_y for _x, _y in fill]
    span_w = max(xs) - min(xs) + 1
    span_h = max(ys) - min(ys) + 1
    print(f"       gold spans {span_w}x{span_h} px inside a 16px box")
    check("the fill stays INSIDE the frame, not over it",
      span_w <= 14 and span_h <= 14)
    # ~86%: 12 of the 14px inner area. Exactly 80% would need 1.4px padding,
    # and Qt only lays out integer padding predictably.
    check("and still fills most of it", span_w >= 11)

print("\nlaunch settings are actually applied")
# The bug: "Launch fullscreen" was written and read back correctly, and
# nothing ever consulted it.
win.settings["fullscreen"] = True
win.show_configured()
app.processEvents()
check("fullscreen maximizes", win.isMaximized())
avail = QApplication.primaryScreen().availableGeometry()
win.settings["fullscreen"] = False
win.settings["window_size"] = "1024x768"
win.show_configured()
app.processEvents()
check("turning it off un-maximizes", win.isMaximized(), False)
# the request, clamped by the screen below it and the floor above it
want = max(min(1024, avail.width() - 40), MIN_WIDTH)
check("the saved size is honoured within those bounds", win.width(), want)

win.settings["window_size"] = "9999x9999"
win.show_configured()
app.processEvents()
check("a size larger than the screen is clamped to it",
      win.width() <= max(avail.width(), MIN_WIDTH))
win.settings["window_size"] = "not-a-size"
win.show_configured()
app.processEvents()
check("and an unparseable one falls back rather than raising",
      win.width() > 0)

print("\nand the window can always fit the screen it opens on")
# A QStackedWidget's minimum is the MAXIMUM of its pages', so visiting every
# screen used to raise the window's floor to 2173px - wider than this
# machine's entire 1365px desktop. That is why "window size" looked dead:
# none of the sizes on offer were reachable.
worst = max((win.stack.widget(i).minimumSizeHint().width()
             for i in win._pages.values()), default=0)
print(f"       widest page wants {worst}px; the window floor is "
      f"{win.minimumWidth()}px")
check("the floor is the DECLARED one, not the widest page",
      win.minimumWidth(), MIN_WIDTH)
check("and it fits a modest display", MIN_WIDTH <= 1024)
check("height too", win.minimumHeight(), MIN_HEIGHT)

print()
if fails:
    print(f"{len(fails)} FAILURES:")
    for f in fails:
        print("   ", f)
    sys.stdout.flush()
    os._exit(1)
print("ALL QT SIZING CHECKS PASSED")
sys.stdout.flush()
os._exit(0)
