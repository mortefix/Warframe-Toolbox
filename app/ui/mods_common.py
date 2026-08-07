"""Building blocks for the Mods app (ui/mods_shade).

One card widget, one progress bar, one image-warming helper - born as the
shared kit of the three 2026-08-07 design candidates, kept separate from the
view because a mod's drawing is not a layout concern. Everything here
follows the style guide: theme tokens only, 0 radius, spacing scale,
ownership severity as jade (OK), gold reserved for the treasury-fills
progress bar (the sanctioned Vosfor precedent).

Card geometry is grounded per the guide's Fibonacci rule: the 96px icon
convention anchors the family - shelf cards are 96 wide, gallery cards
96+34=130. Wiki card art is ~φ tall (256x390), so image heights derive as
width x 1.55.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout, QWidget)

from core import mod_images
from core import theme as t
from ui import work
from ui.widgets import glyph_icon, label, panel, plat_icon, polarity_icon

GALLERY_W = 130            # 96 + 34 (Fibonacci step up from the icon anchor)
SHELF_W = 96               # the app's established item-icon width
_IMG_RATIO = 1.55          # wiki mod-card aspect (measured ~256x390)
_CARD_PAD = t.SP_MD        # the item card's interior padding


def card_footprint(width: int) -> int:
    """A ModCard's true on-screen width: image width + padding + border.
    The wall views size their columns from THIS, not from the image width."""
    return width + 2 * (_CARD_PAD + t.BORDER_W)


def _boxed_style(colour: str) -> str:
    """The WFM outlined button (listings._flat_style twin): each action sits
    in its own 1px box, tinted to its accent, dimming honestly on disable."""
    return (f"QPushButton {{ color: {colour}; background: transparent;"
            f" border: {t.CTRL_BORDER_W}px solid {colour};"
            f" padding: 2px 8px; }}"
            f"QPushButton:disabled {{ color: {t.BORDER};"
            f" border-color: {t.BORDER}; }}")

_pix_cache: dict[tuple[str, int, bool], QPixmap] = {}


def card_pixmap(filename: str | None, width: int,
                owned: bool) -> QPixmap | None:
    """The cached card art scaled to `width`; unowned art is dimmed to a
    ghost of itself (the hole in the collection). None when not downloaded."""
    if not filename:
        return None
    key = (filename, width, owned)
    hit = _pix_cache.get(key)
    if hit is not None:
        return hit
    path = mod_images.cached(filename)
    if path is None:
        return None
    pm = QPixmap(str(path))
    if pm.isNull():
        return None
    pm = pm.scaledToWidth(width, Qt.SmoothTransformation)
    if not owned:
        img = pm.toImage().convertToFormat(QImage.Format_Grayscale8)
        pm = QPixmap.fromImage(img)
        veil = QPixmap(pm.size())
        veil.fill(Qt.transparent)
        p = QPainter(veil)
        p.drawPixmap(0, 0, pm)
        p.setOpacity(0.55)
        p.fillRect(veil.rect(), QColor(t.ICON_BG))
        p.end()
        pm = veil
    _pix_cache[key] = pm
    return pm


class Bar(QFrame):
    """The treasury fills with gold; complete turns jade (Vosfor precedent).
    Height defaults to the Vosfor bar's 4px; the Atlas hero uses 8 (Fib)."""

    def __init__(self, fraction: float, complete: bool = False,
                 height: int = 4) -> None:
        super().__init__()
        self.setFixedHeight(height)
        self._fraction = max(0.0, min(1.0, fraction))
        colour = t.OK_SURFACE if complete else t.ACCENT_SURFACE
        self.setStyleSheet(f"background: {t.BAR_TRACK}; border: none;")
        self._fill = QFrame(self)
        self._fill.setStyleSheet(f"background: {colour}; border: none;")

    def resizeEvent(self, event) -> None:
        self._fill.setGeometry(0, 0, int(self.width() * self._fraction),
                               self.height())
        super().resizeEvent(event)


class ModCard(QWidget):
    """One mod as an ITEM CARD, after the My Listings cards: the information
    and image boxed in together (tile surface: bg + the 1px edge), the art at
    full card width minus padding, its facts below. Ownership is carried by
    the art alone - full colour owned, grey ghost missing - no tick.
    `actions=True` adds the wiki and price-check buttons, each in its own
    outlined box like every listing-card control (the owner ruling: one mod
    at a time, never a sweep)."""

    def __init__(self, row: dict, width: int = GALLERY_W,
                 actions: bool = False, on_wiki=None, price_fn=None,
                 on_market=None) -> None:
        super().__init__()
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setProperty("surface", "tile")
        self._row = row
        self._w = width
        self._on_wiki = on_wiki
        self._price_fn = price_fn
        self._on_market = on_market
        self._job = None
        img_h = int(width * _IMG_RATIO)
        self.setFixedWidth(card_footprint(width))

        lay = QVBoxLayout(self)
        lay.setContentsMargins(_CARD_PAD, _CARD_PAD, _CARD_PAD, _CARD_PAD)
        lay.setSpacing(t.SP_SM)

        # transparent well: the card art carries its own silhouette, so the
        # tile's background shows through instead of a darker media box
        media = panel()
        media.setFixedSize(width, img_h)
        ml = QVBoxLayout(media)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(0)
        self._art = QLabel()
        self._art.setAlignment(Qt.AlignCenter)
        ml.addWidget(self._art, 1)
        self._plate = label(row.get("name") or "", role="small")
        self._plate.setAlignment(Qt.AlignCenter)
        self._plate.setWordWrap(True)
        ml.addWidget(self._plate)
        ml.addStretch(0)
        lay.addWidget(media)

        name_row = QHBoxLayout()
        name_row.setSpacing(t.SP_SM)
        name = label(row.get("name") or "", role="small")
        name.setWordWrap(True)
        name.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        # every title gets a two-line block whether it needs one or not, so
        # every card on a row comes out the same height
        name.ensurePolished()           # the QSS font, before measuring it
        name.setFixedHeight(2 * name.fontMetrics().lineSpacing())
        name_row.addWidget(name, 1)
        # the right column: rank locked to the info block's top-right
        # corner, the polarity symbol beneath it - the SAME tinted mark the
        # market contract cards carry (widgets.polarity_icon, theme ink)
        right = QVBoxLayout()
        right.setSpacing(t.SP_XXS)
        rank = self._rank_text()
        if rank:
            right.addWidget(label(rank, role="small"), 0, Qt.AlignRight)
        pol = polarity_icon(str(row.get("polarity") or ""), height=12)
        if pol is not None:
            mark = QLabel()
            mark.setPixmap(pol)
            mark.setAlignment(Qt.AlignRight | Qt.AlignTop)
            mark.setStyleSheet("background: transparent;")
            mark.setToolTip(str(row.get("polarity")).capitalize())
            right.addWidget(mark, 0, Qt.AlignRight)
        right.addStretch(1)
        name_row.addLayout(right)
        lay.addLayout(name_row)
        if row.get("tooltip"):
            self.setToolTip(row["tooltip"])

        if actions:
            acts = QHBoxLayout()
            acts.setSpacing(t.SP_SM)
            wiki_btn = QPushButton()
            wiki_btn.setIcon(glyph_icon("wiki", 14, color=t.WFM_MUTED))
            wiki_btn.setStyleSheet(_boxed_style(t.WFM_MUTED))
            wiki_btn.setCursor(Qt.PointingHandCursor)
            wiki_btn.setToolTip("Open wiki page")
            wiki_btn.clicked.connect(self._wiki)
            if not row.get("wiki_url"):
                wiki_btn.setEnabled(False)
                wiki_btn.setToolTip("No wiki page (per-player item)")
            acts.addWidget(wiki_btn)
            # "?" = not fetched yet; the answer replaces it in place
            self._price_btn = QPushButton("?")
            self._price_btn.setIcon(QIcon(plat_icon(11)))
            self._price_btn.setStyleSheet(_boxed_style(t.PLAT))
            self._price_btn.setCursor(Qt.PointingHandCursor)
            self._price_btn.setToolTip("Check lowest online seller")
            self._price_btn.clicked.connect(self._price)
            if not row.get("tradable"):
                self._price_btn.setEnabled(False)
                self._price_btn.setToolTip("Not tradable")
            acts.addWidget(self._price_btn, 1)
            if on_market is not None:
                market_btn = QPushButton()
                market_btn.setIcon(glyph_icon("market", 14,
                                              color=t.WFM_TEAL))
                market_btn.setStyleSheet(_boxed_style(t.WFM_TEAL))
                market_btn.setCursor(Qt.PointingHandCursor)
                market_btn.setToolTip("Open in the Market app")
                market_btn.clicked.connect(self._market)
                if not row.get("tradable"):
                    market_btn.setEnabled(False)
                    market_btn.setToolTip("Not tradable")
                acts.addWidget(market_btn)
            lay.addLayout(acts)

        self.refresh_art()

    def _rank_text(self) -> str:
        mr = self._row.get("max_rank")
        if mr in (None, 0):
            return ""
        cur = self._row.get("current_rank")
        return f"{cur}/{mr}" if self._row.get("owned") == 1 \
            and cur is not None else f"–/{mr}"

    def refresh_art(self) -> None:
        pm = card_pixmap(self._row.get("image"), self._w,
                         self._row.get("owned") == 1)
        if pm is not None:
            self._art.setPixmap(pm)
            self._plate.hide()
        else:
            self._plate.show()

    def _wiki(self) -> None:
        if self._on_wiki and self._row.get("wiki_url"):
            self._on_wiki(self._row["wiki_url"])

    def _market(self) -> None:
        if self._on_market and self._row.get("name"):
            self._on_market(self._row["name"])

    def _price(self) -> None:
        if self._price_fn is None:
            return
        self._price_btn.setText("…")
        name = self._row.get("name") or ""
        self._job = work.run(lambda: self._price_fn(name), self._priced)

    def _priced(self, result: dict) -> None:
        if result.get("error"):
            self._price_btn.setText("n/a")
            self._price_btn.setToolTip(result["error"])
        else:
            self._price_btn.setText(f"{result['price']}p")


def warm_images(owner: QWidget, rows: list[dict], done) -> None:
    """Download missing card art (and any polarity symbols the rows need)
    in the background, then call `done()` once. The Job is kept on `owner`
    so it survives the caller's frame (work.py rule: a garbage-collected
    Job emits into a dead C++ object)."""
    missing = [r["image"] for r in rows
               if r.get("image") and mod_images.cached(r["image"]) is None]
    if not missing:
        return

    def body():
        for name in missing:
            mod_images.fetch(name)
        return True

    owner._img_job = work.run(body, lambda _ok: done())
