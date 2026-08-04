"""Material Symbols, shipped with the app.

Replaces Segoe Fluent Icons, and the reasons are licensing and portability
before they are visual. The Segoe icon fonts are Windows-only and cannot be
redistributed; Material Symbols is Apache 2.0 (see `assets/licenses/`), so the
app can ship its own icons and look identical on Linux - which is the whole
point of [[linux-portability-goal]].

It also removes a failure mode this codebase kept hitting. A Private Use Area
codepoint is a number nobody can read, so a wrong one is invisible until it
renders, and TWO shipped broken that way: U+E82D fell through to a CJK glyph
in the Wiki button, and Segoe has no ribbon bookmark at all, which is why one
had to be hand-painted. Material Symbols is addressed by LIGATURE - the text
"storefront" renders the shop - so a mistake shows up as a misspelt word
rather than as a plausible-looking wrong picture.

The FILL axis is why the ribbon no longer needs painting: saved and unsaved
are the same glyph at two axis values, so they cannot drift apart.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QIcon, QPainter,
                           QPixmap)
from PySide6.QtWidgets import QApplication

from core import theme as t

FONT_PATH = (Path(__file__).resolve().parent.parent / "assets" / "fonts"
             / "MaterialSymbolsSharp.ttf")
FAMILY = "Material Symbols Sharp"

_loaded: bool | None = None


def ensure_loaded() -> bool:
    """Register the shipped font. Idempotent, and safe to call from anywhere
    that is about to draw - the cost after the first call is one comparison.

    Returns False if the file is missing, in which case `core.theme.FONTS`
    falls back to the Segoe families and the app still runs; every icon just
    reverts to the old Windows glyphs rather than vanishing.
    """
    global _loaded
    if _loaded is not None:
        return _loaded
    if QApplication.instance() is None:      # addApplicationFont needs one
        return False
    if not FONT_PATH.exists():
        _loaded = False
        return False
    _loaded = QFontDatabase.addApplicationFont(str(FONT_PATH)) != -1
    return _loaded


def font(size: int = 0, filled: bool = False, weight: int = 400) -> QFont:
    """A QFont for the icon face at one point on the variable axes."""
    ensure_loaded()
    f = QFont(FAMILY)
    f.setPointSize(size or t.size_of("icon"))
    # variable axes: FILL 0..1 is outline..solid, and the rest of the app
    # never touches GRAD or opsz, so they stay at their defaults
    f.setVariableAxis(QFont.Tag("FILL"), 1.0 if filled else 0.0)
    f.setVariableAxis(QFont.Tag("wght"), float(weight))
    return f


_CACHE: dict[tuple[str, bool, int, str, int], QIcon] = {}


def icon(name: str, filled: bool = False, size: int = 0, color: str = "",
         weight: int = 400) -> QIcon:
    """A Material Symbol as a button icon.

    `name` is either an ICONS key from core.theme ("wiki", "delete") or a
    Material ligature directly ("open_in_new"). Resolving through the table
    first means screens can name what they MEAN and the mapping stays in one
    place.

    Rendered to a pixmap rather than set as the button's font, because a
    button that carries a glyph AND a word cannot use one face for both.
    """
    ligature = t.glyph(name)
    size = size or t.size_of("icon")
    color = color or t.MUTED
    key = (ligature, filled, size, color, weight)
    hit = _CACHE.get(key)
    if hit is not None:
        return hit

    screen = QApplication.primaryScreen()
    dpr = screen.devicePixelRatio() if screen else 1.0
    box = round(size * 1.5)
    pm = QPixmap(round(box * dpr), round(box * dpr))
    pm.setDevicePixelRatio(dpr)              # stays sharp at 300%
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.TextAntialiasing, True)
    p.setFont(font(size, filled, weight))
    p.setPen(QColor(color))
    # A LOGICAL rect, not pm.rect(). QPixmap::rect() is in PHYSICAL pixels
    # while the painter works in logical ones, so at this machine's 300%
    # scaling `AlignCenter` inside pm.rect() centres the glyph at (27, 27) of
    # an 18x18 viewport - entirely off-canvas. The icon comes out blank, and
    # a blank QIcon is not a null one, so every "is the icon set?" check
    # still passes. That is exactly how this shipped invisible.
    p.drawText(QRectF(0, 0, box, box), Qt.AlignCenter, ligature)
    p.end()

    hit = QIcon(pm)
    _CACHE[key] = hit
    return hit
