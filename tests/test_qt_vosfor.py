"""Offscreen checks for the Qt Vosfor screen.

Covers the two things that were wrong when it was first written and looked
finished anyway: a whole row of controls was missing, and the Vosfor balance
was updated in memory but never saved to disk.
"""
import os
import sys
# These tests print the glyphs the UI actually uses. A Windows console
# defaults to cp1252, which cannot encode them, so a PASSING test could
# still die in its own print statement.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtWidgets import QApplication
except ImportError:
    print("PySide6 not installed - skipping Qt Vosfor checks")
    raise SystemExit(0)

from ui import qss
from ui.app import MainWindow
from ui.vosfor import ArcaneRow, CollectionCard

fails = []


def check(name, got, want=True):
    ok = got == want
    if not ok:
        fails.append(f"{name}: got {got!r}, want {want!r}")
    print(f"  {'ok  ' if ok else 'FAIL'} {name}")


app = QApplication([])
app.setStyleSheet(qss.build(set(QFontDatabase.families())))
win = MainWindow()
win.resize(1400, 900)
win.show()
win.navigate("vosfor")
app.processEvents()
v = win.stack.currentWidget()

print("controls")
for name in ("update_btn", "price_btn", "balance", "price_status", "src_lbl"):
    check(f"{name} exists", hasattr(v, name))
check("both weighting toggles present", sorted(v.method_boxes), ["farm",
                                                                "market"])
check("source line is populated", bool(v.src_lbl.text()))
check("recommendation is populated", bool(v.reco.text()))

print("\ncards")
cards = v.area.widget().findChildren(CollectionCard)
check("one card per ranked collection", len(cards), len(v.model["ranking"]))
check("cards start collapsed", v.area.widget().findChildren(ArcaneRow), [])

print("\nexpanding")
first = v.model["ranking"][0]
v._toggle(first)
app.processEvents()
rows = v.area.widget().findChildren(ArcaneRow)
check("expanding a card creates its rows", len(rows) > 0)
n_open = len(rows)
v._toggle(first)
app.processEvents()
check("collapsing removes them again",
      len(v.area.widget().findChildren(ArcaneRow)), 0)
print(f"       ({n_open} rows in the top-ranked collection)")

print("\nbalance persistence")
saved = {"n": 0}
v._save_settings = lambda: saved.__setitem__("n", saved["n"] + 1)
v.balance.setText("150000")
check("balance reaches the settings dict",
      v._settings.get("vosfor_balance"), 150000)
# it must be debounced, not written per keystroke
check("write is deferred, not immediate", saved["n"], 0)
v._bal_timer.stop()
v._save_balance()
check("the debounce actually writes", saved["n"], 1)
check("a balance adds a purchase plan to the recommendation",
      len(v.reco.text().splitlines()) > 1)

print("\nthe arcane row is look-up only; the toggle feature is gone")
v._toggle(first)
app.processEvents()
rows = v.area.widget().findChildren(ArcaneRow)
check("ArcaneRow exposes no toggle signal", hasattr(ArcaneRow, "toggled"), False)
check("the view has no _toggle_arcane handler",
      hasattr(v, "_toggle_arcane"), False)
# the wiki look-up sits directly left of the name (after the fixed-width mark
# + count), so every row's icon still shares one aligned column
lay0 = rows[0].layout()
wiki = lay0.itemAt(2).widget()
name = lay0.itemAt(3).widget()
check("the wiki look-up is directly left of the name",
      wiki is not None and wiki.toolTip().startswith("Open"))
check("and the name follows it", name is not None and name.text() != "")

print("\nevery ligature label keeps the icon FONT")
# A Material ligature is only a symbol while the icon font is applied. Strip
# the role and the label draws the WORD: this screen re-roled its status mark
# to "muted" in order to grey it, and the missing-arcane rows started reading
# "rac" - the clipped front of "radio_button_unchecked". A missing glyph is
# invisible; a missing font is a whole sentence, which is at least loud.
from PySide6.QtWidgets import QLabel                              # noqa: E402
from core import theme as th                                      # noqa: E402
LIGATURES = {i.material for i in th.ICONS.values()}
wrong = [(l.text(), l.property("role"))
         for l in v.findChildren(QLabel)
         if l.text() in LIGATURES and l.property("role") != "icon"]
check("no ligature label has been re-roled off the icon font", wrong, [])
shown = [l for l in v.findChildren(QLabel) if l.text() in LIGATURES]
check("and there are ligature labels to check", len(shown) > 3)
# greying is done with COLOUR, which keeps the font
greyed = [l for l in shown if th.MUTED.lower() in l.styleSheet().lower()]
check("the muted ones are coloured, not re-roled", len(greyed) > 0)

print()
if fails:
    print(f"{len(fails)} FAILURES:")
    for f in fails:
        print("   ", f)
    sys.exit(1)
print("ALL QT VOSFOR CHECKS PASSED")
