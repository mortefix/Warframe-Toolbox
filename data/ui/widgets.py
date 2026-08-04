"""Small Qt widgets the shell needs that a style sheet cannot express.

Everything that CAN be a QSS rule lives in ui/qss.py. This file is for the two
things that cannot: geometry painted by hand (the finial), and the
`WA_StyledBackground` dance that bare QWidgets need before a background rule
applies to them at all.
"""

from __future__ import annotations

import base64

from shiboken6 import isValid as _is_valid

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QFontDatabase, QIcon,
                           QLinearGradient, QPainter, QPainterPath, QPen,
                           QPixmap, QPolygonF)
from PySide6.QtWidgets import (QApplication, QComboBox, QFrame, QLabel,
                               QWidget)

from core import assets
from core import theme as t


def alive(obj) -> bool:
    """True if a Qt object's underlying C++ half still exists.

    A queued cross-thread signal can be delivered AFTER its target widget was
    deleteLater()'d - a page dropped mid-fetch (unlink / adopt / wipe). The
    Python wrapper survives, so a plain `is not None` check passes, but touching
    it raises "Internal C++ object already deleted". A worker callback that is
    wired as a lambda/closure has the Job (not the widget) as its Qt receiver,
    so Qt's own drop-on-delete does not save it - guard the delivery with this.
    """
    return obj is not None and _is_valid(obj)


def panel(surface: str = "", parent: QWidget | None = None) -> QWidget:
    """A plain container that actually honours its background rule.

    A bare QWidget ignores QSS `background` unless WA_StyledBackground is set -
    the single most common Qt-styling surprise, and the Tk app has ~110 bare
    Frames used as coloured panels that all land here.
    """
    w = QWidget(parent)
    w.setAttribute(Qt.WA_StyledBackground, True)
    if surface:
        w.setProperty("surface", surface)
    return w


def label(text: str = "", role: str = "", level: str = "",
          parent: QWidget | None = None) -> QLabel:
    """A QLabel tagged for the style sheet. `role` picks the typography
    (h1/h2/small/price/mono/icon/...), `level` the severity colour
    (ok/warn/err) - view-models return the latter as a word, never a hex."""
    w = QLabel(text, parent)
    if role:
        w.setProperty("role", role)
    if level:
        w.setProperty("level", level)
    return w


class WrapLabel(QLabel):
    """A word-wrapped label capped to a reading width, whose HEIGHT is computed
    for that cap.

    A plain word-wrapped QLabel with setMaximumWidth clips: the layout asks it
    for heightForWidth at the width IT offers (the full cell, often far wider
    than the cap), which wraps to fewer lines than the capped render actually
    uses. The box is then sized for too few lines, and a vertically-centred
    label loses BOTH its top and bottom lines behind the card border. Clamping
    heightForWidth to the cap - and pinning the minimum height to it - makes the
    box exactly tall enough for the wrapped copy."""

    def __init__(self, text: str = "", max_width: int = 610,
                 parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setWordWrap(True)
        self._max_w = max_width
        self.setMaximumWidth(max_width)
        pol = self.sizePolicy()
        pol.setHeightForWidth(True)
        self.setSizePolicy(pol)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        # measure at the CAPPED width, whatever width the layout offers
        return super().heightForWidth(min(width, self._max_w))

    def minimumSizeHint(self) -> QSize:
        return QSize(0, self.heightForWidth(self._max_w))

    def sizeHint(self) -> QSize:
        w = min(self.width() or self._max_w, self._max_w)
        return QSize(w, self.heightForWidth(w))


def hairline(parent: QWidget | None = None) -> QFrame:
    f = QFrame(parent)
    f.setProperty("surface", "hairline")
    f.setFixedHeight(t.BORDER_W)
    return f


def vline(parent: QWidget | None = None) -> QFrame:
    """A column separator, as a SIBLING rather than a border.

    `border-right` on a container is painted by the container and then
    covered by any child that reaches the full width - which every
    sidebar row does. A separator that occupies its own cell in the
    parent layout cannot be eclipsed, because nothing is laid out on
    top of it.
    """
    f = QFrame(parent)
    f.setProperty("surface", "vline")
    f.setFixedWidth(t.BORDER_W)
    return f


def card_grid(grid) -> None:
    """The shared item/contract card grid geometry: a padded tile with a gutter
    between its cells. ONE definition for both card types (My Listings and
    contracts), so the card rhythm can't drift between them."""
    grid.setContentsMargins(t.SP_LG, t.SP_LG, t.SP_LG, t.SP_LG)
    grid.setHorizontalSpacing(t.SP_LG)
    grid.setVerticalSpacing(t.SP_MD)


def restyle(w: QWidget) -> None:
    """Re-evaluate a widget's style after a dynamic property changed.

    Qt does NOT repaint on setProperty - property selectors are resolved when
    the style is polished. Every `setProperty(...)` used for state (active,
    level, kind) must be followed by this or the change is invisible.
    """
    w.style().unpolish(w)
    w.style().polish(w)
    w.update()


_PIXMAPS: dict[tuple[str, int], QPixmap] = {}


def clear_pixmap_cache() -> None:
    """Drop the decoded/tinted pixmap cache (crest, polarity marks - tinted from
    the palette). Called on a live theme switch so re-tinting picks up the new
    ink; the untinted plat gem just re-decodes, which is cheap."""
    _PIXMAPS.clear()


def _scaled(b64: str, key: str, height: int) -> QPixmap:
    """Decode once, scale per height, cache both - the same shape as the Tk
    decode-then-subsample helpers, minus their integer-factor limitation:
    Qt scales smoothly, so no Fraction juggling is needed."""
    cached = _PIXMAPS.get((key, height))
    if cached is None:
        pm = QPixmap()
        pm.loadFromData(base64.b64decode(b64))
        cached = pm.scaledToHeight(height, Qt.SmoothTransformation)
        _PIXMAPS[(key, height)] = cached
    return cached


def plat_icon(height: int = 13) -> QPixmap:
    """The platinum gem that follows a plat figure."""
    return _scaled(assets.PLATINUM_PNG_B64, "plat", height)


def polarity_icon(name: str, height: int = 13,
                  color: str = "") -> QPixmap | None:
    """The polarity symbol that follows a polarity name; None for a name
    without one (an element, an empty string), so callers can skip the label
    outright. The embedded masters are black glyphs on transparency and the
    theme decides their ink: SourceIn keeps the master's alpha and swaps in
    `color` (muted, by default) everywhere the glyph has coverage."""
    b64 = assets.POLARITY_PNG_B64.get(name.strip().lower())
    if b64 is None:
        return None
    ink = color or t.WFM_MUTED
    key = (f"pol:{name.strip().lower()}:{ink}", height)
    cached = _PIXMAPS.get(key)
    if cached is None:
        pm = QPixmap()
        pm.loadFromData(base64.b64decode(b64))
        img = pm.toImage()
        p = QPainter(img)
        p.setCompositionMode(QPainter.CompositionMode_SourceIn)
        p.fillRect(img.rect(), QColor(ink))
        p.end()
        cached = QPixmap.fromImage(img).scaledToHeight(
            height, Qt.SmoothTransformation)
        _PIXMAPS[key] = cached
    return cached


def logo_pixmap(height: int = 26, color: str = "") -> QPixmap:
    """The Warframe crest, TINTED to match the title text so it themes cleanly.

    The master is a light silhouette on transparency; SourceIn keeps its alpha
    coverage and swaps in `color` (defaults to TEXT, the title ink) everywhere
    the crest has coverage - light on the dark theme, dark on the light theme.
    Same recipe as polarity_icon. Cached per (colour, height)."""
    ink = color or t.TEXT
    key = (f"logo:{ink}", height)
    cached = _PIXMAPS.get(key)
    if cached is None:
        pm = QPixmap()
        pm.loadFromData(base64.b64decode(assets.LOGO_PNG_B64))
        img = pm.toImage()
        p = QPainter(img)
        p.setCompositionMode(QPainter.CompositionMode_SourceIn)
        p.fillRect(img.rect(), QColor(ink))
        p.end()
        cached = QPixmap.fromImage(img).scaledToHeight(
            height, Qt.SmoothTransformation)
        _PIXMAPS[key] = cached
    return cached


def plat_label(parent: QWidget | None = None) -> QLabel:
    w = QLabel(parent)
    w.setPixmap(plat_icon())
    w.setStyleSheet("background: transparent;")
    return w


def glyph_icon(name: str, size: int = 0, color: str = "",
               filled: bool = False) -> QIcon:
    """An icon by NAME - a core.theme.ICONS key, or a Material ligature.

    Was: a Segoe Fluent codepoint painted into a pixmap, because a button
    carrying a glyph and a word cannot use one font for both. That is still
    true, so the pixmap remains; only the font changed, and with it the
    ability to say what you mean instead of "\uE82D".
    """
    from ui import icons
    return icons.icon(name, filled=filled, size=size,
                      color=color)


def bookmark_icon(filled: bool, size: int = 16, color: str = "") -> QIcon:
    """The ribbon bookmark, now the FONT's - not painted.

    It was hand-painted because Segoe Fluent Icons has no ribbon bookmark at
    all. Material Symbols does, WITH a FILL axis, so saved and unsaved are one
    glyph at two axis values and cannot drift apart - which is exactly the
    property the painted version was written to guarantee. Shipping the font
    made the polygon redundant, so it went.
    """
    from ui import icons
    return icons.icon("bookmark", filled=filled, size=size, color=color)


class Dropdown(QComboBox):
    """A QComboBox that actually looks like one.

    Once a style sheet touches QComboBox, Qt stops drawing its native
    down-arrow and there is no way to put one back without shipping an image.
    So the ▾ is painted directly - the same glyph the Tk `arrow_dropdown`
    helper used, from the same theme constant.
    """

    ARROW_PAD = 18

    def __init__(self, items=(), parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.addItems(list(items))
        self.setCursor(Qt.PointingHandCursor)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        p = QPainter(self)
        p.setPen(QColor(t.MUTED))
        p.drawText(self.rect().adjusted(0, 0, -6, 0),
                   Qt.AlignRight | Qt.AlignVCenter, t.ARROW_OPEN)


class Finial(QWidget):
    """The Orokin finial: a gold stem swelling into a spearpoint diamond,
    drawn on the ACTIVE sidebar row only; elsewhere it is empty rail.

    Painted rather than styled because QSS has no polygon. Matches the Tk
    canvas geometry exactly - 2px stem inset 3 from the left, a 7px half-height
    diamond reaching 9px in, GOLD_HI fill over a GOLD_DIM outline.
    """

    WIDTH = 10
    MIN_HEIGHT = 24        # below this the row has not been laid out yet

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedWidth(self.WIDTH)
        self._active = False

    def set_active(self, active: bool) -> None:
        """Show the gold finial when `active`, hide it otherwise."""
        if active != self._active:
            self._active = active
            self.update()

    #  geometry, in logical pixels
    STEM_X, STEM_W = 3.0, 2.0     # the gold stem
    STEM_INSET = 7.0              # how far it stops short, top and bottom
    TIP_X = 9.0                   # how far the spearpoint reaches right
    TIP_HALF = 7.0                # half its height
    # Flush with the stem's left edge - a deliberate departure from the Tk
    # original, which set this to 2.0 so the spearpoint overhung the stem by
    # a pixel. Sharp rendering made that overhang read as a misalignment
    # rather than as flare, so the two now share a left edge.
    TIP_BACK_X = STEM_X

    def _path(self, h: float) -> QPainterPath:
        """Stem and spearpoint as ONE silhouette.

        Drawing them separately means stroking the triangle's back edge, which
        runs straight through the stem and leaves a dark bar across it - the
        two pieces then read as misaligned. Uniting them first means the only
        stroked line is the outer contour, which is what a spear actually
        looks like: a shaft continuous with its head.
        """
        cy = h / 2.0          # float: an integer midpoint is half a logical
        stem = QPainterPath()  # pixel out, = 1.5 real ones at 300%
        stem.addRect(QRectF(self.STEM_X, self.STEM_INSET, self.STEM_W,
                            h - 2 * self.STEM_INSET))
        head = QPainterPath()
        head.addPolygon(QPolygonF([
            QPointF(self.TIP_BACK_X, cy - self.TIP_HALF),
            QPointF(self.TIP_X, cy),
            QPointF(self.TIP_BACK_X, cy + self.TIP_HALF)]))
        return stem.united(head).simplified()

    def paintEvent(self, _event) -> None:
        if not self._active or self.height() < self.MIN_HEIGHT:
            return
        h = float(self.height())
        path = self._path(h)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        # the stem is the duller base and the head brighter, so the gradient
        # keeps "the tip catches the light" without a hard seam - the Orokin gold
        # tone marks the current row.
        grad = QLinearGradient(self.STEM_X, 0.0, self.TIP_X, 0.0)
        grad.setColorAt(0.0, QColor(t.ACCENT))
        grad.setColorAt(1.0, QColor(t.GOLD_HI))
        outline = QColor(t.GOLD_DIM)
        p.setBrush(QBrush(grad))
        pen = QPen(outline)
        pen.setWidthF(0.8)
        pen.setJoinStyle(Qt.MiterJoin)
        p.setPen(pen)
        p.drawPath(path)
