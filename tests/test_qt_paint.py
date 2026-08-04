"""Pixel-level checks on the Qt front end.

These exist because of a real bug: `QWidget {{ background: ... }}` in a style
sheet also matches QLabel, so every label painted the PAGE colour behind its
text and showed as a dark box on any lighter surface. No logic test can see
that - it is only visible in pixels - so the window is rendered offscreen and
sampled.

Also guards QLabel word-wrap clipping, the other thing that looks fine in a
widget tree and wrong on screen.
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

try:
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtWidgets import QApplication, QLabel
except ImportError:
    print("PySide6 not installed - skipping Qt paint checks")
    raise SystemExit(0)

from core import theme as t
from ui import qss
from ui import web as _web_iso                    # noqa: E402
_web_iso.isolate_for_tests()   # NEVER the running app's profile
from ui.app import MainWindow

fails = []


def check(name, got, want=True):
    ok = got == want
    if not ok:
        fails.append(f"{name}: got {got!r}, want {want!r}")
    print(f"  {'ok  ' if ok else 'FAIL'} {name}")


app = QApplication([])
app.setStyleSheet(qss.build(set(QFontDatabase.families())))
win = MainWindow()
# wide enough that the whole horizontal tool strip fits without scrolling, tall
# enough for one card row - the label checks below sample every card, and a card
# scrolled out of the strip would sample off-image (guarded anyway)
win.resize(1700, 1150)
win.show()
# Flat sidebar: every app is a top-level row, so "market" is already visible.
app.processEvents()
app.processEvents()
img = win.grab().toImage()


def px(x: int, y: int) -> str:
    c = img.pixelColor(x, y)
    return f"#{c.red():02x}{c.green():02x}{c.blue():02x}".lower()


print("surfaces")
check("page background is BG", px(320, 60), t.BG.lower())
# Sample bare rail, not a fixed point: the apps now sit in gold-bordered boxes,
# so most of the sidebar column is box. The stretch gap just above the pinned
# Settings row spans the full width with nothing drawn on it.
_srow = win._rows["settings"]
_so = _srow.mapTo(win, _srow.rect().topLeft())
check("sidebar is SIDEBAR_BG", px(_so.x() + 20, _so.y() - 4),
      t.SIDEBAR_BG.lower())

page = win.stack.currentWidget()
# the cards are a horizontal strip inside a bordered container now (page.
# _tools_container); page._cards is the strip, in order
cards = page._cards
card = cards[0]
top_left = card.mapTo(win, card.rect().topLeft())
# card surface is BG by request (same colour as the page); the darker container
# that holds the strip is the settings-card surface, WFM_CARD
check("home card is BG", px(top_left.x() + 8, top_left.y() + 40),
      t.BG.lower())
section = page._tools_container
so = section.mapTo(win, section.rect().topLeft())
check("home card container is the WFM_CARD box",
      px(so.x() + 6, so.y() + 6), t.WFM_CARD.lower())


def in_bounds(x: int, y: int) -> bool:
    return 0 <= x < img.width() and 0 <= y < img.height()


print("\nlabels are transparent - they show the card surface, not an opaque box")
for i, c in enumerate(cards):
    lbl = max(c.findChildren(QLabel), key=lambda l: len(l.text()))
    origin = lbl.mapTo(win, lbl.rect().topLeft())
    pts = [(origin.x() + x, origin.y() + y)
           for x in range(2, min(lbl.width(), 80), 6)
           for y in range(1, min(lbl.height(), 24), 4)]
    pts = [(x, y) for x, y in pts if in_bounds(x, y)]
    if not pts:
        continue                    # card scrolled out of the strip - skip
    # The home card surface is BG by design now, so a transparent label shows
    # BG between its glyphs. The invariant is that the card surface is visible
    # THROUGH the label (it paints no opaque box of its own): if a label filled
    # its box, the surface colour would appear NOWHERE inside it.
    surface = t.BG.lower()
    shows = any(px(x, y) == surface for x, y in pts)
    check(f"card {i} label shows the card surface through it", shows, True)

print("\nsidebar rows are one colour end to end")
# Tk repaints rowf + icon + button together. Putting the highlight on the
# button alone leaves the finial and glyph on the un-highlighted rail, which
# reads as a box drawn around the label - sampling three points catches it.
# The ACTIVE row (home) paints SIDEBAR_ACTIVE; an idle row is SIDEBAR_BG - the
# same colour as its container's fill, so a boxed app is a plain gold outline.
# Offsets start past the finial (width 10), and the pinned rows carry a left
# indent so their icons line up with the boxed apps - sample from each row's edge.
for key, want in (("home", t.SIDEBAR_ACTIVE), ("market", t.SIDEBAR_BG)):
    row = win._rows[key]
    o = row.mapTo(win, row.rect().topLeft())
    lm = row.layout().contentsMargins().left()   # the pinned-row indent, or 0
    y = o.y() + row.height() // 2
    cols = {px(o.x() + lm + 14, y), px(o.x() + lm + 40, y),
            px(o.x() + lm + 150, y)}
    check(f"{key} row is uniform across finial/glyph/label", len(cols), 1)
    check(f"{key} row colour", cols.pop(), want.lower())

print("\nthe rail's edge survives the rows drawn on top of it")
# `border-right` on the sidebar was painted by the sidebar and then covered by
# every nav row, because rows span the full width and paint their own
# background. Sampling INSIDE the active row is what catches that - the edge
# looked fine in the gap below the last row either way.
side = win._rows["home"].parentWidget()
edge_x = side.mapTo(win, side.rect().topRight()).x() + 1
row = win._rows["home"]
o = row.mapTo(win, row.rect().topLeft())
check("the edge column is the BORDER colour beside the ACTIVE row",
      px(edge_x, o.y() + row.height() // 2), t.BORDER.lower())
check("and beside an inactive one",
      px(edge_x, win._rows["market"].mapTo(win, win._rows["market"]
         .rect().center()).y()), t.BORDER.lower())

print("\nfinial geometry")
fin = win._rows["home"].finial
h = fin.height()
check("finial is tall enough to draw", h >= fin.MIN_HEIGHT)

# Measure what was actually painted rather than trusting the arithmetic: find
# the gold pixels, take the stem's vertical span and the spearpoint's tip, and
# require the tip to sit on the stem's centre. A `h // 2` midpoint misses it by
# half a logical pixel whenever the row height is odd - invisible at 100%,
# 1.5 real pixels at 300%.
o = fin.mapTo(win, fin.rect().topLeft())
gold = set()
for dy in range(h):
    for dx in range(fin.width()):
        c = img.pixelColor(o.x() + dx, o.y() + dy)
        # anything clearly warmer and brighter than the rail is finial
        if c.red() > 90 and c.red() > c.blue() + 30:
            gold.add((dx, dy))
check("the finial actually painted something", len(gold) > 20)
if gold:
    tip_x = max(x for x, _ in gold)
    tip_ys = [y for x, y in gold if x == tip_x]
    tip_centre = sum(tip_ys) / len(tip_ys)
    stem_ys = [y for x, y in gold if x == fin.STEM_X]
    stem_centre = ((min(stem_ys) + max(stem_ys)) / 2 if stem_ys
                   else tip_centre)
    print(f"       tip at x={tip_x} centres on y={tip_centre:.1f}; "
          f"stem centres on y={stem_centre:.1f}")
    check("spearpoint is centred on the stem",
          abs(tip_centre - stem_centre) <= 1.0)

# The whole silhouette must be mirror-symmetric about its own centre. This is
# the check that would have caught the seam: when the stem and the spearpoint
# were drawn as two shapes, the triangle's stroked back edge cut a dark bar
# across the stem, and the rows above and below the join stopped matching.
rows = {}
for dy in range(h):
    rows[dy] = frozenset(x for x, y in gold if y == dy)
filled = sorted(dy for dy, xs in rows.items() if xs)
if filled:
    top, bot = filled[0], filled[-1]
    mismatched = [dy for dy in range(top, (top + bot) // 2 + 1)
                  if rows[dy] != rows[bot - (dy - top)]]
    check("finial is mirror-symmetric top to bottom", mismatched, [])
    check("finial spans a sensible height", bot - top >= 20)

print("\nword wrap has room")
for i, c in enumerate(cards):
    lbl = max(c.findChildren(QLabel), key=lambda l: len(l.text()))
    check(f"card {i} blurb is not clipped",
          lbl.height() >= lbl.heightForWidth(lbl.width()))

print()
if fails:
    print(f"{len(fails)} FAILURES:")
    for f in fails:
        print("   ", f)
    sys.exit(1)
print("ALL QT PAINT CHECKS PASSED")
