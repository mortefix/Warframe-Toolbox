"""The shipped icon font: Material Symbols, Apache 2.0.

A wrong icon name does not crash and does not render tofu - it renders the
NAME, as letters. "storefornt" sitting in the sidebar looks like content, so
nothing downstream complains and nobody notices until they look. Every check
here exists because of that: they compare against the signature of text drawn
as text.

The licence checks are not ceremony. Apache 2.0 §4(d) requires the NOTICE to
travel with any redistribution, so a build that drops `assets/licenses/` is a
licensing violation rather than a cosmetic regression - and that is exactly
the kind of file a packaging step quietly leaves behind.
"""
import hashlib
import os
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "data"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import Qt, QRectF
    from PySide6.QtGui import (QColor, QFont, QFontDatabase, QImage, QPainter)
    from PySide6.QtWidgets import QApplication
except ImportError:
    print("PySide6 not installed - skipping icon checks")
    raise SystemExit(0)

fails = []


def check(name, got, want=True):
    ok = got == want
    if not ok:
        fails.append(f"{name}: got {got!r}, want {want!r}")
    print(f"  {'ok  ' if ok else 'FAIL'} {name}")


app = QApplication([])
from core import home as core_home                                # noqa: E402
from core import nav as core_nav                                  # noqa: E402
from core import theme as t                                       # noqa: E402
from core import webapps                                          # noqa: E402
from registry import TOOLS                                        # noqa: E402
from ui import icons, qss                                         # noqa: E402

print("the font ships with the app")
check("the .ttf is in the tree", icons.FONT_PATH.exists())
check("it loads", icons.ensure_loaded())
check("loading twice is a no-op, not a second registration",
      icons.ensure_loaded())

print("\nand the style sheet resolves to it, not to a Windows fallback")
sheet = qss.build()
fam = t.resolve_family("icon", set(QFontDatabase.families()))
check("icon role is Material Symbols", fam, icons.FAMILY)
check("the sheet names it", f'"{icons.FAMILY}"' in sheet)
# The regression this guards: build() used to trust a families list the caller
# computed BEFORE the font was registered, which resolved icons to Segoe. That
# looks perfect on Windows and renders nothing at all on Linux.
check("even when handed a stale families list",
      icons.FAMILY in qss.build(set()))


def ink(text, pt=26, fill=0.0):
    f = icons.font(pt, filled=bool(fill))
    img = QImage(80, 80, QImage.Format_ARGB32)
    img.fill(0)
    p = QPainter(img)
    p.setFont(f)
    p.setPen(QColor("white"))
    p.drawText(QRectF(0, 0, 80, 80), Qt.AlignCenter, text)
    p.end()
    b = bytes(img.constBits())
    return (hashlib.md5(b).hexdigest()[:10],
            sum(1 for i in range(3, len(b), 4) if b[i] > 100))


# Two names that certainly are not icons. Whatever they render is what "drawn
# as letters" looks like, and no real icon may match it.
LETTERS = {ink("notanicon")[0], ink("zzqqxxvv")[0]}

print("\nEVERY name in the table renders a SYMBOL, not its own letters")
for key, icon in sorted(t.ICONS.items()):
    h, px = ink(icon.material)
    check(f"{key} -> {icon.material}", h not in LETTERS and px > 40)

print("\nthe QIcon a button gets actually has PIXELS in it")
# The regression this exists for: the glyph was drawn into `pm.rect()`, which
# is in PHYSICAL pixels while the painter works in logical ones. At 300%
# scaling that centres it at (27, 27) of an 18x18 viewport - off-canvas. Every
# icon came out blank, and a blank QIcon is not a NULL one, so `isNull()`
# reported False and the buttons looked fine to every check that existed.


def icon_ink(name, filled=False):
    """Measured at the size the icon was RENDERED at, not a size of my
    choosing. Asking for 32x32 upscales an 18x18 icon (which is what the
    offscreen platform produces, since its devicePixelRatio is 1), and the
    resampling drops thin strokes below any sensible alpha threshold - so the
    check ends up measuring its own interpolation. `list` is horizontal hair
    lines and failed exactly that way while rendering perfectly."""
    ic = icons.icon(name, filled=filled, color="#ffffff")
    size = ic.availableSizes()[0]
    img = ic.pixmap(size).toImage()
    return sum(1 for x in range(img.width()) for y in range(img.height())
               if img.pixelColor(x, y).alpha() > 10)


# "not empty", not "big enough". `remove` is a single horizontal bar and
# `chevron_right` is two short strokes - a generous pixel floor would fail
# those for being correctly thin, which is how a test starts dictating the
# artwork. Blank is the bug; sparse is a design.
for key in sorted(t.ICONS):
    check(f"{key} draws something", icon_ink(key) > 0)
check("a filled icon draws MORE than its outline",
      icon_ink("bookmark", True) > icon_ink("bookmark", False))

print("\nand every icon the app actually asks for is IN the table")
used = {("nav", i.key, i.icon) for i in core_nav.nav_items(TOOLS)}
used |= {("card", c.key, c.icon) for c in core_home.cards(TOOLS)}
used |= {("web", a.key, a.icon) for a in webapps.WEB_APPS}
used |= {("tool", x.id, x.icon) for x in TOOLS}
unknown = sorted((w, k, i) for w, k, i in used if i not in t.ICONS)
check("no screen names an icon the table does not define", unknown, [])
check("and there are icons to check", len(used) > 8)

print("\nthe FILL axis is what makes saved/unsaved one glyph")
h0, i0 = ink("bookmark", fill=0.0)
h1, i1 = ink("bookmark", fill=1.0)
check("filling changes the drawing", h0 != h1)
check("and a solid ribbon is more ink than an outline", i1 > i0 * 1.4)

print("\nboth front ends get a mark for every key")
# One renderable character, not necessarily a Private Use Area one: the
# Vosfor status marks are plain dingbats (✔ ◐ ✗) chosen precisely BECAUSE
# they draw in any font, and "+" is just a plus.
for key in t.ICONS:
    check(f"{key} has a Tk mark too", len(t.glyph(key, fluent=True)), 1)
# an unknown key must degrade to something readable, never raise
check("an unknown key returns itself rather than exploding",
      t.glyph("no_such_icon"), "no_such_icon")

print("\nthe licence travels with the font (Apache 2.0 section 4d)")
lic = icons.FONT_PATH.parent.parent / "licenses"
check("licences directory exists", lic.is_dir())
check("Apache 2.0 full text is present", (lic / "Apache-2.0.txt").exists())
text = (lic / "Apache-2.0.txt").read_text(encoding="utf-8")
check("and it really is the licence, not a stub",
      "Apache License" in text and "Version 2.0" in text)
notice = (lic / "README.md").read_text(encoding="utf-8")
check("the NOTICE names the font", "Material Symbols" in notice)
check("and attributes the copyright holder", "Google" in notice)

print()
if fails:
    print(f"{len(fails)} FAILURES:")
    for f in fails:
        print("   ", f)
    sys.exit(1)
print("ALL ICON CHECKS PASSED")
