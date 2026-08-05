"""Offscreen checks for the Qt Market screen, mostly the autocomplete.

The suggest box shipped broken once in a way that no logic test could see:
it was built as a `Qt.Popup` window, showing one stole focus from the entry,
that fired FocusOut, and the FocusOut handler hid it again. Suggestions were
computed correctly the whole time - the popup just never stayed on screen, and
typing stopped reaching the entry. So these drive REAL key events and assert
on what survives them.
"""
import os
import re
import sys
# These tests print the glyphs the UI actually uses. A Windows console
# defaults to cp1252, which cannot encode them, so a PASSING test could
# still die in its own print statement.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
except ImportError:
    print("PySide6 not installed - skipping Qt Market checks")
    raise SystemExit(0)

from core import market_vm as vm
from core import theme as t
from ui import qss
from ui.app import MainWindow

fails = []


def check(name, got, want=True):
    ok = got == want
    if not ok:
        fails.append(f"{name}: got {got!r}, want {want!r}")
    print(f"  {'ok  ' if ok else 'FAIL'} {name}")


def ranks_offered():
    return [mt.rank_pick.itemText(i) for i in range(mt.rank_pick.count())]


def count_in(side):
    """The per-side count rides in the column heading, in parentheses:
    "WTS — sellers  (12)". Parse it out rather than matching the whole
    string, so the heading wording can change without breaking these."""
    m = re.search(r"\((\d+)\)", mt.counts[side].text())
    return int(m.group(1)) if m else None


app = QApplication([])
app.setStyleSheet(qss.build(set(QFontDatabase.families())))
win = MainWindow()
win.resize(1300, 700)
win.show()
win.navigate("market")
app.processEvents()
mv = win.stack.currentWidget()
mt = mv.tabs["market"]
# a fixed index, so nothing here touches the network
mt._index = [("Ash Prime Set", "ash_prime_set", "t"),
             ("Ash Prime Blueprint", "ash_prime_bp", "t"),
             ("Banshee Prime Set", "banshee_prime_set", "t")]

print("tabs")
check("three tabs", sorted(mv.tabs), ["contracts", "market", "watchlist"])
widths = [b.width() for b in mv.tab_btns.values()]
check("each tab is a third of the width", max(widths) - min(widths) <= 1)
# the tabs now live inside the bordered container, so they span its inner
# width (the box minus its SP_XL padding), not the whole view
box = next(iter(mv.tab_btns.values())).parentWidget()
check("they span the container's inner width",
      abs(sum(widths) - (box.width() - 2 * t.SP_LG)) <= 4)

print("\ntyping")
mt.search.setFocus()
app.processEvents()
QTest.keyClicks(mt.search, "ash")
app.processEvents()
check("the text arrives", mt.search.text(), "ash")
check("suggestions are computed",
      [l for l, _ in mt.suggest.items],
      ["Ash Prime Set", "Ash Prime Blueprint"])
# the regression: it used to compute these and then hide instantly
check("THE POPUP STAYS VISIBLE", mt.suggest.visible())
check("the entry keeps focus while typing", mt.search.hasFocus())

# isVisible() is TRUE for a fully clipped widget - it only means "shown, with
# shown ancestors". The list was once parented to the 280x25 search box and
# clipped out of existence while every visibility check passed. So assert
# what actually matters: it hangs off the window, and it fits inside it.
lst = mt.suggest.list
check("the popup is parented to the WINDOW, not the entry",
      lst.parentWidget() is mt.search.window())
check("and its geometry lies inside that window",
      win.rect().contains(lst.geometry()))
check("it sits below the search box",
      lst.y() >= mt.search.mapTo(win, mt.search.rect().bottomLeft()).y())

print("\none character is below the threshold")
mt.search.clear()
QTest.keyClicks(mt.search, "a")
app.processEvents()
check("no popup for a single character", mt.suggest.visible(), False)

print("\nDown browses - it must not close the popup or run a search")
mt.search.clear()
QTest.keyClicks(mt.search, "ash")
app.processEvents()
before = mt.search.text()
QTest.keyClick(mt.search, Qt.Key_Down)
app.processEvents()
check("popup is still open after Down", mt.suggest.visible())
check("the list took focus", mt.suggest.list.hasFocus())
check("row 0 is selected", mt.suggest.list.currentRow(), 0)
check("the query was not changed", mt.search.text(), before)

print("\nEnter picks the selected row")
picked = {}
mt.suggest.on_pick = lambda n, s: picked.update(name=n, slug=s)
QTest.keyClick(mt.suggest.list, Qt.Key_Return)
app.processEvents()
check("on_pick fired with the right item", picked,
      {"name": "Ash Prime Set", "slug": "ash_prime_set"})
check("the popup closed", mt.suggest.visible(), False)

print("\nEscape dismisses")
mt.suggest.on_pick = lambda n, s: None
mt.search.setFocus()
mt.search.clear()
QTest.keyClicks(mt.search, "ash")
app.processEvents()
check("popup is open before Escape", mt.suggest.visible())
QTest.keyClick(mt.search, Qt.Key_Escape)
app.processEvents()
check("Escape hides it", mt.suggest.visible(), False)

print("\norder book rendering (no network)")
mt.slug, mt.name = "ash_prime_set", "Ash Prime Set"
mt._book = {
    "sell": [{"user": "A", "platinum": 40, "quantity": 1, "status": "ingame"},
             {"user": "B", "platinum": 12, "quantity": 1, "status": "offline"}],
    "buy": [{"user": "C", "platinum": 25, "quantity": 2, "status": "offline"}]}
# Both filters ship on. They compose rather than conflict - in-game NARROWS
# online - so the default is in-game only and unticking widens a step at a
# time. That is why unticking just one is NOT enough to show everyone.
check("both filters are on by default",
      (mt.online.isChecked(), mt.ingame.isChecked()), (True, True))
mt._rerender()
app.processEvents()
# counts live in each column's own header now, beside the list they count
check("the default hides the offline seller", count_in("sell"), 1)
check("and the offline buyer", count_in("buy"), 0)
check("default scope is in-game", vm.scope_filter(
      mt.ingame.isChecked(), mt.online.isChecked()).word,
      "in-game")

mt.ingame.setChecked(False)
app.processEvents()
check("dropping in-game widens to online", vm.scope_filter(
      mt.ingame.isChecked(), mt.online.isChecked()).word, "online")
check("still hides the offline seller", count_in("sell"), 1)

mt.online.setChecked(False)
app.processEvents()
check("dropping both shows everyone", count_in("sell"), 2)
check("and the offline buyer appears", count_in("buy"), 1)
check("scope widens to everyone", vm.scope_filter(
      mt.ingame.isChecked(), mt.online.isChecked()).word, "total")

print("\nno top-N cap: every order is rendered")
from ui.market import MarketTab                                   # noqa: E402
many = [{"user": f"U{i}", "platinum": i, "quantity": 1, "status": "ingame"}
        for i in range(40)]
mt._book = {"sell": many, "buy": []}
mt.ingame.setChecked(True)
mt._rerender()
app.processEvents()
check("all 40 sellers counted", count_in("sell"), 40)
widgets = sum(1 for i in range(mt.cols["sell"].count())
              if mt.cols["sell"].itemAt(i).widget() is not None)
check("all 40 rendered, not capped at 12", widgets, 40)

print("\nthe item name lives in the search box, not a separate title")
check("no title label", hasattr(mt, "title"), False)
check("no scope notice label", hasattr(mt, "status"), False)
mt.refresh = lambda: None                      # no network
mt._picked("Ash Prime Set", "ash_prime_set")
app.processEvents()
check("picking fills the box", mt.search.text(), "Ash Prime Set")
check("and styles it teal + bold", "font-weight" in mt.search.styleSheet())
check("opening an item flashes nothing", mt.flash.text(), "")
mt.search.setText("ash pri")
app.processEvents()
check("typing again drops the styling", mt.search.styleSheet(), "")
check("wiki button enables once an item is loaded", mt.wiki_btn.isEnabled())

# A Private Use Area codepoint left in a button's LABEL is rendered in that
# button's font. Segoe UI has no U+E82D, so Windows falls back to whatever
# font claims the block - a CJK face here, which is why this button read as a
# Chinese character. The glyph has to be an icon so it can carry its own face.
check("the wiki glyph is not a codepoint in the label",
      t.WIKI_ICON in mt.wiki_btn.text(), False)
check("it is a rendered icon instead", mt.wiki_btn.icon().isNull(), False)

print("\ntransient text must not resize the search box")
w0 = mt.search.width()
mt._flash("a long transient message of the kind that used to squeeze it", "")
app.processEvents()
check("search box keeps its width", mt.search.width(), w0)
mt._flash("", "")
app.processEvents()

print("\nrank picker - built from what is VISIBLE, not from the whole book")
mt.slug, mt.name = "arcane_energize", "Arcane Energize"
mt.ingame.setChecked(True)
mt.online.setChecked(True)
# The regression, in miniature. Rank 3 IS in the book, but only from an
# offline seller, so under the default in-game filter it can never produce a
# row. Live Arcane Energize does exactly this: the full book carries ranks
# 0-5 across 1,576 sellers, and in-game only leaves 0, 1 and 5 - so the
# picker offered R-2/R-3/R-4 and each one emptied the table.
mt._book = {"sell": [{"user": "A", "platinum": 900, "quantity": 1,
                      "status": "ingame", "rank": 5},
                     {"user": "B", "platinum": 40, "quantity": 1,
                      "status": "ingame", "rank": 0},
                     {"user": "C", "platinum": 300, "quantity": 1,
                      "status": "offline", "rank": 3}], "buy": []}
mt._rerender()
app.processEvents()
check("picker appears for a rankable item", mt.rank_pick.isVisible())
check("and is usable", mt.rank_pick.isEnabled())
check("A RANK NOBODY VISIBLE IS SELLING IS NOT OFFERED",
      ranks_offered(), ["any", "R-0", "R-5"])
check("all visible ranks shown by default", count_in("sell"), 2)
mt.rank_pick.setCurrentText("R-5")
app.processEvents()
check("choosing a rank filters the book", count_in("sell"), 1)
mt.rank_pick.setCurrentText("any")
app.processEvents()
check("back to any", count_in("sell"), 2)

# the picker tracks the scope both ways: widening exposes R-3...
mt.ingame.setChecked(False)
mt.online.setChecked(False)
app.processEvents()
check("widening the scope adds the rank it exposes",
      ranks_offered(), ["any", "R-0", "R-3", "R-5"])
mt.rank_pick.setCurrentText("R-3")
app.processEvents()
check("and that rank now yields a row", count_in("sell"), 1)
# ...and narrowing takes it away again, without leaving a dead selection
# pinned to a rank that is no longer on the list
mt.ingame.setChecked(True)
mt.online.setChecked(True)
app.processEvents()
check("narrowing drops it again", ranks_offered(), ["any", "R-0", "R-5"])
check("the dead selection falls back to any",
      mt.rank_pick.currentText(), "any")
check("so the rows come back", count_in("sell"), 2)

# _chosen_rank must not consult isVisible(): a book can land while this tab
# sits behind another, and every widget on a stacked page that is not on top
# reports isVisible() False
mt.rank_pick.setCurrentText("R-5")
mv.select("watchlist")
app.processEvents()
check("the tab is genuinely hidden now", mt.rank_pick.isVisible(), False)
check("but the chosen rank still applies", mt._chosen_rank(), 5)
mv.select("market")
mt.rank_pick.setCurrentText("any")
app.processEvents()

mt._book = {"sell": [{"user": "A", "platinum": 40, "quantity": 1,
                      "status": "ingame", "rank": None}], "buy": []}
mt._rerender()
app.processEvents()
# The control stays PUT. Hiding it moved every neighbour on the row each time
# an item loaded, and an absent control reads as a missing feature rather
# than as "this item does not come in ranks".
check("a good that does not rank keeps the picker on screen",
      mt.rank_pick.isVisible())
check("but greys it out", mt.rank_pick.isEnabled(), False)
check("it still reads 'any'", mt.rank_pick.currentText(), "any")
check("and stops filtering by rank", mt._chosen_rank(), None)

print("\ntab switching hides any open popup")
mt.search.setFocus()
mt.search.clear()
QTest.keyClicks(mt.search, "ash")
app.processEvents()
check("popup open", mt.suggest.visible())
mv.select("watchlist")
app.processEvents()
check("switching tabs hides it", mt.suggest.visible(), False)

print("\ncontracts: the weapon field goes teal on a hit, like the order book")
# The same _paint_query contract as the market tab, on the OTHER search box:
# teal + bold once the field IS the loaded weapon, plain while still typing.
ct = mv.tabs["contracts"]
ct.view.client.auctions = lambda kind, slug, ascending=True: []   # no network
ct._picked("Kuva Bramma", "kuva_bramma")
app.processEvents()
check("picking fills the weapon box", ct.weapon.text(), "Kuva Bramma")
check("and styles it teal + bold, same as market",
      "font-weight" in ct.weapon.styleSheet())
ct.weapon.setText("kuva bra")
app.processEvents()
check("typing again drops the styling", ct.weapon.styleSheet(), "")

print()
if fails:
    print(f"{len(fails)} FAILURES:")
    for f in fails:
        print("   ", f)
    sys.exit(1)
print("ALL QT MARKET CHECKS PASSED")
