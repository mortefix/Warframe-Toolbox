"""Offscreen checks for the PySide6 shell (data/ui/).

Runs headless via QT_QPA_PLATFORM=offscreen, so it is safe in the normal
suite. Skips cleanly when PySide6 is not installed - the Tk app is still the
default and must not need Qt to be testable.
"""
import os
import sys
# These tests print the glyphs the UI actually uses. A Windows console
# defaults to cp1252, which cannot encode them, so a PASSING test could
# still die in its own print statement.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "data"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# This test navigates to EVERY nav key, and three of them are QtWebEngine
# tabs. Chromium has no GPU surface offscreen, and a web view that fetched its
# home page would put this test on the network and make it depend on three
# third-party sites being up.
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS",
                      "--disable-gpu --disable-software-rasterizer "
                      "--no-sandbox --in-process-gpu")

try:
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtWidgets import QApplication
except ImportError:
    print("PySide6 not installed - skipping Qt shell checks")
    raise SystemExit(0)

from core import nav, theme
from registry import TOOLS
from ui import qss
from ui.app import APP_TITLE, MainWindow

fails = []


def check(name, got, want=True):
    ok = got == want
    if not ok:
        fails.append(f"{name}: got {got!r}, want {want!r}")
    print(f"  {'ok  ' if ok else 'FAIL'} {name}")


app = QApplication([])
from ui import web as ui_web                                      # noqa: E402
ui_web.isolate_for_tests()   # NEVER the running app's profile
ui_web.AUTOLOAD = False        # see the QTWEBENGINE note above
sheet = qss.build(set(QFontDatabase.families()))
app.setStyleSheet(sheet)

print("style sheet")
import re
hexes = set(re.findall(r"#[0-9a-fA-F]{6}", sheet))
tokens = {v for v in vars(theme).values()
          if isinstance(v, str) and v.startswith("#")}
# every colour in the generated sheet must trace back to core.theme, or the
# two front ends have silently forked
check("no hand-written colours in the sheet", hexes - tokens, set())
check("the sheet is not trivially empty", len(sheet) > 2000)

print("\nshell")
w = MainWindow()
check("title is the watcher's exact match string", w.windowTitle(), APP_TITLE)

keys = [i.key for i in nav.nav_items(TOOLS)]
check("one sidebar row per nav item", len(w._rows), len(keys))
check("home is current at construction", w.current, "home")
# the launch rule: nothing but Home is built until it is visited
check("only home is built at construction", len(w._pages), 1)
# flat sidebar: no folders/groups exist at all
check("no folder groups on the shell", hasattr(w, "_groups"), False)

print("\nnavigation")
for k in keys:
    w.navigate(k)
    check(f"navigate({k})", w.current, k)
check("every visited key is cached", len(w._pages), len(keys))

# the three web tabs are real QWebEngineViews, built but deliberately idle
from core import webapps                                          # noqa: E402
for k in sorted(webapps.WEB_KEYS):
    page = w.stack.widget(w._pages[k])
    check(f"{k} is a web view", hasattr(page, "is_navigated"))
    check(f"{k} fetched nothing", page.is_navigated(), False)

before = dict(w._pages)
for k in keys:
    w.navigate(k)
check("second lap rebuilds nothing", w._pages, before)

print("\nsidebar width is derived from the labels")
from PySide6.QtGui import QFont, QFontMetrics                      # noqa: E402
from ui.app import (SIDEBAR_CHROME, SIDEBAR_MIN_WIDTH,             # noqa: E402
                    NAV_SECTION_CHROME)
items = nav.nav_items(TOOLS)
# the nav labels draw in the "nav_title" face (its own category since fonts
# became themeable), so the rail is measured in THAT face, not h2.
fm = QFontMetrics(QFont(theme.resolve_family("nav_title",
                                             set(QFontDatabase.families())),
                        theme.size_of("nav_title")))
# + NAV_SECTION_CHROME: the widest label sits inside a gold-bordered container,
# so the rail budgets for the rail inset + that box's border and padding.
chrome = SIDEBAR_CHROME + NAV_SECTION_CHROME
want = max(SIDEBAR_MIN_WIDTH,
           max(fm.horizontalAdvance(i.label) for i in items) + chrome)
check("rail width matches the nav_title measurement",
      w._rows["home"].parentWidget().width(), want)

# The floor was hiding a real defect: the width was measured off a button
# whose style sheet font had not been applied yet (it still reported
# "Segoe UI 9"), and the resulting undersize happened to land below
# SIDEBAR_MIN_WIDTH. Only a label long enough to clear the floor can tell the
# two apart - with the wrong face the answer comes out visibly narrower.
LONG = "A Very Long Tool Name Indeed"
long_items = list(items) + [nav.NavItem("x", LONG, "", False)]
grown = w._sidebar_width(long_items)
check("a long label pushes the rail past the floor", grown > SIDEBAR_MIN_WIDTH)
check("and it is measured in the nav_title face",
      grown, fm.horizontalAdvance(LONG) + chrome)

# That last check alone is NOT enough, and finding out why is the point: the
# offscreen platform hands an unpolished button the same Segoe UI Semibold 13
# the h2 rule asks for, so both the right and the wrong implementation agree
# here and the check passes either way. It only discriminates on Windows,
# where an unpolished button reports Segoe UI 9. So pin the invariant itself -
# the measurement comes from the theme and must ignore any widget's font.
w._rows["home"].button.setFont(QFont("Courier New", 30))
check("the rail is measured from the THEME, not off a widget",
      w._sidebar_width(long_items), grown)

print("\nthe warframe.market status control")
# Presence is a websocket, so set_state would really dial out. Stand in for it
# - what is under test is the CONTROL, not core.presence.
picked = []
w.presence.set_state = lambda s: picked.append(s) or setattr(
    w.presence, "_want", s)
sc = w.status
check("it is in the header", sc.parentWidget() is not None)
check("all three visibility states are offered",
      [s for s, _t, _c in sc.STATES], ["ingame", "online", "offline"])
check("in-game comes first - it is the one buyers filter for",
      sc.STATES[0][0], "ingame")

sc.buttons["ingame"].click()
check("clicking a state asks presence for it", picked[-1:], ["ingame"])

# The dot reports the SOCKET, which is a different fact from the state you
# asked for: "In-game" with a dead socket looks identical to "In-game" and
# means the opposite.
sc.paint("ingame", True, None)
connected_dot = sc.dot.styleSheet()
sc.paint("ingame", False, "warframe.market is down (HTTP 521).")
check("a dead socket colours the dot differently",
      sc.dot.styleSheet() != connected_dot)
check("and the reason is on screen, not swallowed",
      "521" in sc.detail.text())
check("the tooltip says so too", "not connected" in sc.dot.toolTip())

# ...but being offline on purpose is not a fault
sc.paint("offline", False, None)
check("offline shows no error", "not connected" in sc.dot.toolTip(), False)
check("it reads as a choice", sc.dot.toolTip(), "offline by choice")
check("and carries no detail line", sc.detail.text(), "")

print("\nsidebar state")
w.navigate("vosfor")
check("active row is the current one",
      [k for k, r in w._rows.items() if r.finial._active], ["vosfor"])
check("exactly one finial lit",
      sum(r.finial._active for r in w._rows.values()), 1)
# one gold tone only: the selected row is marked active="true"
check("selected row marked active", w._rows["vosfor"].property("active"), "true")
check("header title follows nav", w.title.text(),
      "Warframe Toolbox - Vosfor")     # static app-name prefix + screen name

w.navigate("home")
check("finial moves with nav",
      [k for k, r in w._rows.items() if r.finial._active], ["home"])
check("home row marked active", w._rows["home"].property("active"), "true")
check("the previous row is cleared",
      w._rows["vosfor"].property("active"), "false")

print()
if fails:
    print(f"{len(fails)} FAILURES:")
    for f in fails:
        print("   ", f)
    sys.exit(1)
print("ALL QT SHELL CHECKS PASSED")
