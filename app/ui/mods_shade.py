"""Mods Treasury - the merged design: Atlas dashboard as a pull-down shade
over a full-window Gallery card wall.

The shade works like the Android notification pane. Expanded, it covers the
window with the progress dashboard (hero card, then one body card of arsenal
tiles, mod-set medallions and the collections ledger - Vaulted rides with
the collections) - everything clickable. Picking a category
slides the shade up until only the hero card remains - the SAME container,
now retitled to the picked collection with its progress bar, an
in-collection search box and a hide-owned checkbox - and the card wall
beneath shows that category full-window: fixed-size cards filling a grid
like a file browser, scrolling when full, shorter when not. The gold
spearpoint handle - shown only while the shade is closed - pulls it back
down over the wall.
"""

from __future__ import annotations

from PySide6.QtCore import (QEasingCurve, QEvent, QPoint, QPointF,
                            QPropertyAnimation, QRect, QRectF, Qt, QTimer)
from PySide6.QtGui import (QBrush, QColor, QKeySequence, QLinearGradient,
                           QPainter, QPainterPath, QPen, QPolygonF,
                           QShortcut)
from PySide6.QtWidgets import (QCheckBox, QFrame, QGridLayout, QHBoxLayout,
                               QLineEdit, QScrollArea, QVBoxLayout, QWidget)

from core import mods_vm
from core import theme as t
from ui import work
from ui.mods_common import (Bar, GALLERY_W, ModCard, card_footprint,
                            warm_images)
from ui.widgets import Dropdown, label, panel

_TILE_COLS = 5
_SET_COLS = 8
_SLIDE_MS = 250
_HANDLE_H = 20          # the shade's grab-handle strip

# The wall's symmetric gutters: border -> first card must equal last card ->
# scrollbar. The wall card itself pads SP_LG on the left of the grid but the
# scrollbar sits flush against the viewport's right edge, so the grid's LEFT
# margin runs SP_LG short of its right to land both gaps on SP_XL exactly.
_WALL_L = t.SP_XL - t.SP_LG
_WALL_R = t.SP_XL


class _ShadeHandle(QWidget):
    """The drawer's bottom lip: an opaque card-coloured strip carrying the
    sidebar Finial laid on its side - a gold stem swelling into a spearpoint
    pointing down: pull the drawer open. It RIDES the drawer's bottom edge
    during the slide and parks at the top of the body card when closed.
    Painted, not styled: QSS has no polygon."""

    # The Finial's constants, axes swapped. The stem insets SP_XL so it
    # aligns with the card's interior content edges.
    BAND = 10.0                   # the silhouette's vertical footprint
    STEM_Y, STEM_W = 3.0, 2.0     # the gold stem (transposed Finial STEM_X/W)
    STEM_INSET = float(t.SP_XL)   # flush with the interior content edges
    TIP_Y = 9.0                   # how far the spearpoint reaches
    TIP_HALF = 6.5                # half its width
    TIP_BACK_Y = STEM_Y           # head flush with the stem (Finial ruling)

    def __init__(self, on_click) -> None:
        super().__init__()
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(_HANDLE_H)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Pull the treasury shade down")
        self._on_click = on_click

    def mousePressEvent(self, event) -> None:
        self._on_click()
        super().mousePressEvent(event)

    def _path(self, w: float, dy: float) -> QPainterPath:
        """Stem and spearpoint as ONE silhouette (the Finial lesson: stroking
        them separately leaves a seam across the stem)."""
        cx = w / 2.0
        stem = QPainterPath()
        stem.addRect(QRectF(self.STEM_INSET, dy + self.STEM_Y,
                            w - 2 * self.STEM_INSET, self.STEM_W))
        head = QPainterPath()
        head.addPolygon(QPolygonF([
            QPointF(cx - self.TIP_HALF, dy + self.TIP_BACK_Y),
            QPointF(cx, dy + self.TIP_Y),
            QPointF(cx + self.TIP_HALF, dy + self.TIP_BACK_Y)]))
        return stem.united(head).simplified()

    def paintEvent(self, _event) -> None:
        w = float(self.width())
        h = float(self.height())
        dy = (h - self.BAND) / 2.0
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        # opaque: this IS the drawer's edge - the wall scrolls under it
        p.fillRect(self.rect(), QColor(t.WFM_CARD))
        grad = QLinearGradient(0.0, dy + self.STEM_Y, 0.0, dy + self.TIP_Y)
        grad.setColorAt(0.0, QColor(t.ACCENT))
        grad.setColorAt(1.0, QColor(t.GOLD_HI))
        pen = QPen(QColor(t.GOLD_DIM))
        pen.setWidthF(0.8)
        pen.setJoinStyle(Qt.MiterJoin)
        p.setBrush(QBrush(grad))
        p.setPen(pen)
        p.drawPath(self._path(w, dy))


class _Tile(QWidget):
    """One arsenal bucket: name, count, gold fill. Clickable.

    `count_only=True` drops the owned/total framing and the bar - for the
    Rivens tile, which counts toward no completion (owner ruling)."""

    def __init__(self, entry: dict, on_pick,
                 count_only: bool = False) -> None:
        super().__init__()
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setProperty("surface", "tile")
        self._key = entry["key"]
        self._label = entry["label"]
        self._on_pick = on_pick
        self.setCursor(Qt.PointingHandCursor)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(t.SP_LG, t.SP_LG, t.SP_LG, t.SP_LG)
        lay.setSpacing(t.SP_SM)
        top = QHBoxLayout()
        top.setSpacing(t.SP_SM)
        top.addWidget(label(entry["label"], role="card_title"), 1)
        done = entry["total"] and entry["owned"] >= entry["total"]
        self._count = label("…" if count_only else
                            f"{entry['owned']}/{entry['total']}",
                            role="small", level="ok" if done else "")
        top.addWidget(self._count)
        lay.addLayout(top)
        if count_only:
            # cosmetic full bar (owner ruling): rivens have no completion,
            # but the tile should dress like its arsenal neighbours
            lay.addWidget(Bar(1.0))
        else:
            frac = entry["owned"] / entry["total"] if entry["total"] else 0
            lay.addWidget(Bar(frac, complete=bool(done)))

    def set_count(self, n: int) -> None:
        self._count.setText(str(n))

    def mousePressEvent(self, event) -> None:
        self._on_pick(self._key, self._label)
        super().mousePressEvent(event)


class _Medallion(QWidget):
    """One wearable mod set: name over owned/total. Clickable."""

    def __init__(self, entry: dict, on_pick) -> None:
        super().__init__()
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setProperty("surface", "tile")
        self._key = entry["key"]
        self._label = entry["label"]
        self._on_pick = on_pick
        self.setCursor(Qt.PointingHandCursor)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(t.SP_MD, t.SP_MD, t.SP_MD, t.SP_MD)
        lay.setSpacing(t.SP_XXS)
        done = entry["total"] and entry["owned"] >= entry["total"]
        name = label(entry["label"].removesuffix(" Set"), role="small")
        name.setAlignment(Qt.AlignCenter)
        lay.addWidget(name)
        frac = label(f"{entry['owned']}/{entry['total']}", role="h2",
                     level="ok" if done else "")
        frac.setAlignment(Qt.AlignCenter)
        lay.addWidget(frac)

    def mousePressEvent(self, event) -> None:
        self._on_pick(self._key, self._label)
        super().mousePressEvent(event)


class _LedgerRow(QWidget):
    """One named collection: name, gold bar, count - boxed in its own tile
    like the arsenal entries. Clickable."""

    def __init__(self, entry: dict, on_pick) -> None:
        super().__init__()
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setProperty("surface", "tile")
        self._key = entry["key"]
        self._label = entry["label"]
        self._on_pick = on_pick
        self.setCursor(Qt.PointingHandCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(t.SP_LG, t.SP_MD, t.SP_LG, t.SP_MD)
        lay.setSpacing(t.SP_MD)
        name = label(entry["label"], role="body")
        name.setFixedWidth(130)
        lay.addWidget(name)
        frac = entry["owned"] / entry["total"] if entry["total"] else 0
        done = entry["total"] and entry["owned"] >= entry["total"]
        lay.addWidget(Bar(frac, complete=bool(done)), 1)
        count = label(f"{entry['owned']}/{entry['total']}",
                      role="small", level="ok" if done else "")
        # a fixed count column, so every row's bar spans the same run and
        # the ledger's right edge reads as one line
        count.ensurePolished()
        count.setFixedWidth(count.fontMetrics().horizontalAdvance("888/888"))
        count.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lay.addWidget(count)

    def mousePressEvent(self, event) -> None:
        self._on_pick(self._key, self._label)
        super().mousePressEvent(event)


class _Spinner(QWidget):
    """A spinning gold arc - shown while a freshly picked collection
    builds its wall. Pure paint, no assets; ACCENT ink per the guide."""

    SIZE = 48

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(self.SIZE, self.SIZE)
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._spin)
        self.hide()

    def _spin(self) -> None:
        self._angle = (self._angle + 8) % 360
        self.update()

    def start(self) -> None:
        self._timer.start()
        self.show()

    def stop(self) -> None:
        self._timer.stop()
        self.hide()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        pen = QPen(QColor(t.ACCENT))
        pen.setWidthF(3.0)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        inset = 4.0
        arc = QRectF(inset, inset, self.SIZE - 2 * inset,
                     self.SIZE - 2 * inset)
        p.drawArc(arc, -self._angle * 16, 100 * 16)


class ModsTreasuryView(QWidget):
    def __init__(self, open_wiki, market_any=None, open_market=None) -> None:
        super().__init__()
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setProperty("surface", "app")
        self._open_wiki = open_wiki
        self._market_any = market_any
        self._open_market = open_market
        self._serial = 0
        self._open = True            # shade starts expanded: nothing picked
        self._current: tuple[str, str] | None = None    # (key, title)
        self._rows: list[dict] = []
        self._cols = 5

        # -- the persistent hero: ONE widget, never moved by the slide -------
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._hero_wrap = self._build_hero()
        outer.addWidget(self._hero_wrap)

        # -- THE body card: one container for both faces. The wall lives in
        # its layout; the drawer is an overlay CHILD of the same card, so
        # the slide happens INSIDE the borders (owner ruling 2026-08-07)
        self._wall_scroll = QScrollArea()
        self._wall_scroll.setWidgetResizable(True)
        self._wall_scroll.setFrameShape(QFrame.NoFrame)
        self._wall_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # always-on: the bar appearing later would shrink the viewport under
        # an exact-fit grid without firing the view's resizeEvent
        self._wall_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self._wall = panel()
        self._grid = QGridLayout(self._wall)
        self._grid.setContentsMargins(_WALL_L, t.SP_LG, _WALL_R, t.SP_LG)
        self._grid.setHorizontalSpacing(t.SP_LG)
        self._grid.setVerticalSpacing(t.SP_LG)
        self._wall_scroll.setWidget(self._wall)
        self._body_card = panel("card")
        wcl = QVBoxLayout(self._body_card)
        # the wall's viewport BEGINS at the parked lip's bottom edge, so a
        # scrolling card is clipped exactly where the arrow strip ends -
        # never visible above it, eclipsed by it below
        wcl.setContentsMargins(t.SP_LG, _HANDLE_H + t.BORDER_W,
                               t.SP_LG, t.SP_MD)
        wcl.addWidget(self._wall_scroll)
        wall_holder = QVBoxLayout()
        wall_holder.setContentsMargins(t.SP_SCREEN, t.SP_LG,
                                       t.SP_SCREEN, t.SP_XL)
        wall_holder.addWidget(self._body_card)
        outer.addLayout(wall_holder, 1)

        # the drawer: an opaque card-coloured sheet clipped by the body
        # card, holding the dashboard scroll; its geometry is what slides.
        # Its margins run BORDER_W short of the wall's card padding because
        # the sheet already starts just inside the border - without this
        # the two faces' interiors sit 2px apart and shimmer mid-slide.
        self._drawer = QWidget(self._body_card)
        self._drawer.setAttribute(Qt.WA_StyledBackground, True)
        self._drawer.setStyleSheet(f"background: {t.WFM_CARD};")
        dl = QVBoxLayout(self._drawer)
        dl.setContentsMargins(t.SP_LG - t.BORDER_W, t.SP_MD - t.BORDER_W,
                              t.SP_LG - t.BORDER_W, t.SP_MD - t.BORDER_W)
        dl.addWidget(self._build_dashboard())
        # the handle lives INSIDE the container too: the drawer's bottom
        # lip, riding the wipe edge during the slide (see _ride)
        self._handle = _ShadeHandle(self._expand)
        self._handle.setParent(self._body_card)
        self._handle.hide()

        # animate POSITION, not geometry: a move never relayouts the
        # dashboard, so the slide costs a blit per frame however tall the
        # menu is (height animation measurably juddered on big canvases)
        self._anim = QPropertyAnimation(self._drawer, b"pos", self)
        self._anim.setDuration(_SLIDE_MS)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._ride)
        self._anim.finished.connect(self._slide_done)
        self._body_card.installEventFilter(self)

        self._loading = False
        self._spinner = _Spinner(self._body_card)
        # Esc toggles the drawer from ANYWHERE in the view - a shortcut with
        # child scope, because keyPressEvent never fires while a search box
        # holds focus
        esc = QShortcut(QKeySequence(Qt.Key_Escape), self)
        esc.setContext(Qt.WidgetWithChildrenShortcut)
        esc.activated.connect(self._esc_toggle)

        self._totals_job = work.run(mods_vm.totals, self._totals_done)

    # -- shade content --------------------------------------------------------

    def _build_hero(self) -> QWidget:
        """The persistent title container: 'Mods Treasury' + treasury totals
        while the shade is down, the picked collection + its progress once it
        rides up. Same card, retitled - never rebuilt."""
        wrap = panel("app")
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(t.SP_SCREEN, t.SP_LG, t.SP_SCREEN, 0)
        hero = panel("card")
        hl = QVBoxLayout(hero)
        hl.setContentsMargins(t.SP_XL, t.SP_XL, t.SP_XL, t.SP_XL)
        hl.setSpacing(t.SP_MD)
        head = QHBoxLayout()
        head.setSpacing(t.SP_MD)
        self._title = label("Mods Treasury", role="h1")
        head.addWidget(self._title)
        # collapsed state: the collection's descriptive line rides up here,
        # inline with its name, so the middle row is all filters
        self._head_line = label("", role="body")
        self._head_line.setContentsMargins(t.SP_LG, 0, 0, 0)
        self._head_line.hide()
        head.addWidget(self._head_line, 0, Qt.AlignVCenter)
        head.addStretch(1)
        self.search_all = QLineEdit()
        self.search_all.setPlaceholderText("search all mods…")
        self.search_all.setClearButtonEnabled(True)
        self.search_all.setFixedWidth(233)      # 233 = Fib member; hero-scaled
        self.search_all.returnPressed.connect(self._search_everything)
        head.addWidget(self.search_all)
        self.search = QLineEdit()
        self.search.setPlaceholderText("search this collection…")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(233)
        self.search.textChanged.connect(self._refill)
        self.search.hide()
        head.addWidget(self.search)
        hl.addLayout(head)
        # ONE middle row for both states: the totals line + riven count while
        # the drawer is open, the filters while the wall is visible. They
        # share the slot and the row is pinned to the taller of the two, so
        # the hero's height NEVER changes as the shade toggles.
        line_holder = QWidget()
        line_row = QHBoxLayout(line_holder)
        line_row.setContentsMargins(0, 0, 0, 0)
        line_row.setSpacing(t.SP_LG)
        self._hero_line = label("…", role="body")
        line_row.addWidget(self._hero_line, 0, Qt.AlignVCenter)
        line_row.addStretch(1)
        # display only - rivens count toward no completion (owner ruling)
        self._riven_line = label("", role="body")
        line_row.addWidget(self._riven_line, 0, Qt.AlignRight | Qt.AlignVCenter)

        self._filters = QWidget()
        fl = QHBoxLayout(self._filters)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(t.SP_LG)
        # positive filter (owner ruling): ON narrows the wall to owned-but-
        # unranked mods only; OFF (the default) filters nothing
        self.show_unranked = QCheckBox("Show Unranked")
        self.show_unranked.toggled.connect(self._refill)
        fl.addWidget(self.show_unranked)
        self.hide_owned = QCheckBox("Hide Owned")
        self.hide_owned.toggled.connect(self._refill)
        fl.addWidget(self.hide_owned)
        # parazon-only splits (antivirus / requiem / plain), hidden elsewhere
        self.hide_antivirus = QCheckBox("Hide Antivirus Mods")
        self.hide_antivirus.toggled.connect(self._refill)
        self.hide_antivirus.hide()
        fl.addWidget(self.hide_antivirus)
        self.hide_requiem = QCheckBox("Hide Requiem Mods")
        self.hide_requiem.toggled.connect(self._refill)
        self.hide_requiem.hide()
        fl.addWidget(self.hide_requiem)
        self.hide_parazon = QCheckBox("Hide Parazon Mods")
        self.hide_parazon.toggled.connect(self._refill)
        self.hide_parazon.hide()
        fl.addWidget(self.hide_parazon)
        fl.addStretch(1)
        fl.addWidget(label("SORT", role="caps"))
        self.sort_by = Dropdown(("Name", "Rank", "Rarity", "Polarity"))
        self.sort_by.currentIndexChanged.connect(self._refill)
        fl.addWidget(self.sort_by)
        self.sort_order = Dropdown(("Ascending", "Descending"))
        self.sort_order.currentIndexChanged.connect(self._refill)
        fl.addWidget(self.sort_order)
        self._filters.hide()
        # stretch 1: with the descriptive line gone from this row, the
        # filters own its full width (their inner stretch parks SORT right)
        line_row.addWidget(self._filters, 1, Qt.AlignVCenter)
        # pin the shared row NOW, while both occupants are measurable
        line_holder.setFixedHeight(max(self._filters.sizeHint().height(),
                                       self._hero_line.sizeHint().height()))
        hl.addWidget(line_holder)
        self._hero_bar_holder = QVBoxLayout()
        hl.addLayout(self._hero_bar_holder)
        self._hero_bar = None
        wl.addWidget(hero)
        return wrap

    def _build_dashboard(self) -> QWidget:
        # the category menu, as the drawer's content: a scroll frame whose
        # page is transparent (the drawer sheet carries the card colour).
        # Padding mirrors the wall's, so both faces of the body card share
        # interior insets.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        page = panel()                      # transparent: sheet bg shows
        lay = QVBoxLayout(page)
        lay.setContentsMargins(t.SP_MD, t.SP_LG, t.SP_XL, t.SP_LG)
        lay.setSpacing(t.SP_XL)
        scroll.setWidget(page)

        lay.addWidget(label("Arsenal", role="h2"))
        tiles = QGridLayout()
        tiles.setHorizontalSpacing(t.SP_MD)
        tiles.setVerticalSpacing(t.SP_MD)
        entries = mods_vm.arsenal_progress()
        for i, entry in enumerate(entries):
            tiles.addWidget(_Tile(entry, self._pick),
                            i // _TILE_COLS, i % _TILE_COLS)
        # Rivens ride with the arsenal but count toward nothing: a count-only
        # tile whose number arrives with the (async) totals read
        self._riven_tile = _Tile({"key": "rivens", "label": "Rivens",
                                  "owned": 0, "total": 0}, self._pick,
                                 count_only=True)
        n = len(entries)
        tiles.addWidget(self._riven_tile, n // _TILE_COLS, n % _TILE_COLS)
        lay.addLayout(tiles)

        lay.addWidget(label("Mod Sets", role="h2"))
        sets_grid = QGridLayout()
        sets_grid.setHorizontalSpacing(t.SP_MD)
        sets_grid.setVerticalSpacing(t.SP_MD)
        for i, s in enumerate(mods_vm.set_progress()):
            sets_grid.addWidget(_Medallion(s, self._pick),
                                i // _SET_COLS, i % _SET_COLS)
        lay.addLayout(sets_grid)

        lay.addWidget(label("Collections", role="h2"))
        led = QGridLayout()
        led.setHorizontalSpacing(t.SP_XL)
        led.setVerticalSpacing(t.SP_SM)
        entries = [c for c in mods_vm.collections_progress()
                   if not c["key"].startswith("set:syn_")]
        # the retired trophies ride with the named hunts (owner ruling:
        # trophies are simply another category of mods)
        n_troph = len(mods_vm.trophies())
        entries.append({"key": "trophies", "label": "Vaulted",
                        "owned": n_troph, "total": n_troph})
        for i, c in enumerate(entries):
            led.addWidget(_LedgerRow(c, self._pick), i // 2, i % 2)
        lay.addLayout(led)
        return scroll

    # -- slide mechanics ------------------------------------------------------

    def _drawer_rect(self) -> QRect:
        """The drawer's fully-open geometry: the body card's interior, just
        inside its border, in the card's own coordinates."""
        bw = t.BORDER_W
        return self._body_card.rect().adjusted(bw, bw, -bw, -bw)

    def _pick(self, key: str, title: str) -> None:
        if self._current is not None and self._current[0] == key:
            # same collection: the wall is already right - just close over it
            self._collapse()
            return
        self._current = (key, title)
        self._start_loading()
        self._refill()
        self._collapse()

    def _start_loading(self) -> None:
        """Unload the PREVIOUS collection at once (its cards must not haunt
        the reveal) and spin until the new one lands. While loading, the
        drawer is locked shut - no expand mid-build."""
        self._loading = True
        self._clear_wall()
        card = self._body_card
        self._spinner.move((card.width() - _Spinner.SIZE) // 2,
                           (card.height() - _Spinner.SIZE) // 2)
        self._spinner.start()
        self._spinner.raise_()
        self._drawer.raise_()       # keep the sliding sheet above the spinner
        self._handle.raise_()

    def _clear_wall(self) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self._cards = []
        self._rows = []

    def _apply_hero(self) -> None:
        """Retitle the persistent hero card to match the state: the whole
        treasury while the shade is down, the picked collection once it is
        riding up. Same widgets, new words."""
        if self._open:
            self._title.setText("Mods Treasury")
            tot = getattr(self, "_tot", None)
            if tot:
                pct = 100 * tot["owned"] // tot["total"] if tot["total"] else 0
                self._hero_line.setText(
                    f"{tot['owned']}/{tot['total']} Obtainable "
                    f"+{tot['extras']} Vaulted Mods Collected. "
                    f"- {pct}% Complete.")
                self._riven_line.setText(
                    f"{tot.get('rivens', 0)} Rivens Owned")
                self._set_hero_bar(tot["owned"], tot["total"])
            self._head_line.hide()
            self._hero_line.show()
            self._riven_line.show()
            self._filters.hide()
            self.search.hide()
            self.search_all.show()
        else:
            owned, total = getattr(self, "_stats", (0, 0))
            key = self._current[0] if self._current else ""
            self._title.setText(self._current[1] if self._current else "")
            if self._loading:
                line = "Loading…"
            elif key == "trophies":
                # counts dropped on purpose: the sentence alone fits the
                # head row beside the title
                line = ("Vaulted Mods are no longer obtainable in game but "
                        "players who owned them were allowed to keep them.")
            else:
                line = f"{owned} of {total} owned in this collection."
            self._head_line.setText(line)
            self._head_line.show()
            self._hero_line.hide()
            self._set_hero_bar(owned, total)
            self._riven_line.hide()
            self.search_all.hide()
            self.search.show()
            self._filters.show()

    def _set_hero_bar(self, owned: int, total: int) -> None:
        if self._hero_bar is not None:
            self._hero_bar.setParent(None)
        self._hero_bar = Bar(owned / total if total else 0,
                             complete=bool(total and owned >= total),
                             height=8)
        self._hero_bar_holder.addWidget(self._hero_bar)

    def _ride(self, *_args) -> None:
        """Glue the handle lip to the drawer's bottom edge - the wipe's
        edge. Fully open parks it past the card bottom (clipped away);
        fully closed parks it at the top of the interior."""
        r = self._drawer_rect()
        self._handle.setGeometry(r.x(), self._drawer.geometry().bottom() + 1,
                                 r.width(), _HANDLE_H)
        self._handle.raise_()

    def _esc_toggle(self) -> None:
        """Esc rides both ways: closes an open drawer, opens a closed one
        (_expand's loading lock still applies)."""
        if self._open:
            self._collapse()
        else:
            self._expand()

    def _collapse(self) -> None:
        if not self._open or self._current is None:
            return
        self._open = False
        # the animation must be RUNNING before the hero mutates: retitling
        # ripples a transient body-card resize through the event filter,
        # and only a live animation stops _sync_drawer snapping to the end
        # state (measured 2026-08-07: the snap ate the whole slide)
        r = self._drawer_rect()
        self._drawer.resize(r.size())
        self._anim.stop()
        self._anim.setStartValue(self._drawer.pos())
        self._anim.setEndValue(QPoint(r.x(), r.y() - r.height()))
        self._anim.start()
        self._handle.show()          # rides the wipe edge in from the bottom
        self._ride()
        self._apply_hero()

    def _expand(self) -> None:
        if self._open or self._loading:
            return
        self._open = True
        r = self._drawer_rect()
        self._drawer.resize(r.size())
        self._drawer.show()
        self._anim.stop()
        self._anim.setStartValue(self._drawer.pos())
        self._anim.setEndValue(QPoint(r.x(), r.y()))
        self._anim.start()           # the lip rides out at the bottom
        self._apply_hero()

    def _slide_done(self) -> None:
        if not self._open:
            self._drawer.hide()
        else:
            self._handle.hide()      # fully open: the lip has left the card
        # re-snap to the card's SETTLED interior
        r = self._drawer_rect()
        y = r.y() if self._open else r.y() - r.height()
        self._drawer.setGeometry(r.x(), y, r.width(), r.height())
        self._ride()
        # a wall rebuilt DURING the slide would block the GUI thread and
        # eat the animation (big collections build 100+ cards); it waits
        # here instead
        pending = getattr(self, "_pending_fill", None)
        if pending is not None:
            self._pending_fill = None
            self._apply_fill(pending)

    def eventFilter(self, obj, ev):
        # the body card resizes with the window; the drawer must keep
        # matching its interior (except mid-slide - _slide_done re-snaps)
        if (obj is self._body_card and ev.type() == QEvent.Resize
                and self._anim.state() != QPropertyAnimation.Running):
            self._sync_drawer()
        return super().eventFilter(obj, ev)

    def _sync_drawer(self) -> None:
        if self._anim.state() == QPropertyAnimation.Running:
            self._anim.stop()
            self._slide_done()
        r = self._drawer_rect()
        y = r.y() if self._open else r.y() - r.height()
        self._drawer.setGeometry(r.x(), y, r.width(), r.height())
        self._drawer.setVisible(self._open)
        self._drawer.raise_()
        self._handle.setVisible(not self._open)
        self._ride()
        card = self._body_card
        self._spinner.move((card.width() - _Spinner.SIZE) // 2,
                           (card.height() - _Spinner.SIZE) // 2)

    # -- the wall -------------------------------------------------------------

    def _search_everything(self) -> None:
        q = self.search_all.text().strip()
        self.search.clear()
        if q:
            self._pick(f"search:{q}", f"Search: {q}")
        else:
            # Enter on the empty box = the whole obtainable catalogue
            self._pick("search:", "All Mods")

    def _refill(self) -> None:
        if self._current is None:
            return
        self._serial += 1
        serial = self._serial
        key, _title = self._current
        q = self.search.text().strip()
        hide = self.hide_owned.isChecked()
        show_unranked = self.show_unranked.isChecked()
        hide_av = self.hide_antivirus.isChecked()
        hide_req = self.hide_requiem.isChecked()
        hide_par = self.hide_parazon.isChecked()
        sort_by = self.sort_by.currentText()
        descending = self.sort_order.currentText() == "Descending"

        def unranked(r) -> bool:
            return (r.get("owned") == 1 and (r.get("max_rank") or 0) > 0
                    and not r.get("current_rank"))

        def body():
            if key == "trophies":
                rows = mods_vm.trophies()
            elif key == "rivens":
                rows = mods_vm.rivens()
            elif key.startswith("search:"):
                # 2000: "All Mods" (the empty query) must not truncate at
                # the shelf default of 400
                rows = mods_vm.search_all(key[7:], limit=2000)
            else:
                rows = mods_vm.shelf(key)
            if q:
                rows = [r for r in rows
                        if q.lower() in (r["name"] or "").lower()]
            owned = sum(1 for r in rows if r.get("owned") == 1)
            total = len(rows)
            counts = {"owned": owned,
                      "unranked": sum(1 for r in rows if unranked(r))}
            if key == "parazon":
                cls = {r["internal"]: mods_vm.parazon_class(r["internal"])
                       for r in rows}
                drop = ({"antivirus"} if hide_av else set()) \
                    | ({"requiem"} if hide_req else set()) \
                    | ({"parazon"} if hide_par else set())
                rows = [r for r in rows if cls[r["internal"]] not in drop]
            if hide:
                rows = [r for r in rows if r.get("owned") != 1]
            if show_unranked:
                # positive filter: ONLY the owned-but-unranked mods
                rows = [r for r in rows if unranked(r)]
            rows = mods_vm.sort_rows(rows, sort_by, descending)
            return serial, rows, owned, total, counts

        self._fill_job = work.run(body, self._filled)

    def _filled(self, payload) -> None:
        # rebuilding the wall is the expensive part; while a slide is in
        # flight it parks here and _slide_done applies it
        if self._anim.state() == QPropertyAnimation.Running:
            self._pending_fill = payload
            return
        self._apply_fill(payload)

    def _apply_fill(self, payload) -> None:
        serial, rows, owned, total, counts = payload
        if serial != self._serial:
            return
        # count-badged filter labels for the CURRENT list, and the
        # parazon-only splits shown only on the parazon shelf
        self.show_unranked.setText(f"Show Unranked ({counts['unranked']})")
        self.hide_owned.setText(f"Hide Owned ({counts['owned']})")
        # countless on purpose (space): the labels alone carry the meaning
        parazon = self._current is not None and self._current[0] == "parazon"
        self.hide_antivirus.setVisible(parazon)
        self.hide_requiem.setVisible(parazon)
        self.hide_parazon.setVisible(parazon)
        self._clear_wall()
        self._loading = False
        self._spinner.stop()
        self._rows = rows
        # column count from the LIVE viewport, never a cached guess; then the
        # image width stretches so the columns fill the row edge to edge.
        # avail comes from the FIXED gutter bases, not the live margins -
        # the margins carry the split leftover and would feed back on refill
        avail = max(1, self._wall_scroll.viewport().width()
                    - (_WALL_L + _WALL_R))
        self._cols = max(2, avail // (card_footprint(GALLERY_W) + t.SP_LG))
        self._card_w = max(GALLERY_W // 2,
                           (avail - (self._cols - 1) * t.SP_LG)
                           // self._cols - card_footprint(0))
        # the division's px leftover splits across the two gutters, so the
        # border->card and card->scrollbar gaps stay equal to the pixel
        spare = max(0, avail - self._cols * card_footprint(self._card_w)
                    - (self._cols - 1) * t.SP_LG)
        self._grid.setContentsMargins(_WALL_L + spare // 2, t.SP_LG,
                                      _WALL_R + spare - spare // 2, t.SP_LG)
        for col in range(self._cols + 1):
            self._grid.setColumnStretch(col, 0)
        price_fn = self._price_fn()
        self._cards = []
        for i, r in enumerate(rows):
            card = ModCard(r, self._card_w, actions=True,
                           on_wiki=self._open_wiki, price_fn=price_fn,
                           on_market=self._open_market)
            self._cards.append(card)
            self._grid.addWidget(card, i // self._cols, i % self._cols,
                                 Qt.AlignTop | Qt.AlignLeft)
        self._grid.setColumnStretch(self._cols, 1)
        # file-browser rule: spare space stays BELOW the last row - without
        # this a short wall spreads its rows across the whole viewport
        if getattr(self, "_stretch_row", None) is not None:
            self._grid.setRowStretch(self._stretch_row, 0)
        self._stretch_row = (len(rows) + self._cols - 1) // self._cols
        self._grid.setRowStretch(self._stretch_row, 1)
        self._stats = (owned, total)
        if not self._open:
            self._apply_hero()
        warm_images(self, rows, self._art_arrived)

    def _art_arrived(self) -> None:
        for card in getattr(self, "_cards", []):
            card.refresh_art()

    def _price_fn(self):
        client = self._market_any() if self._market_any else None
        return lambda name: mods_vm.price_check(client, name)

    def _totals_done(self, tot: dict) -> None:
        self._tot = tot
        self._riven_tile.set_count(tot.get("rivens", 0))
        if self._open:
            self._apply_hero()

    def resizeEvent(self, event) -> None:
        self._sync_drawer()
        avail = max(1, self._wall_scroll.viewport().width()
                    - (_WALL_L + _WALL_R))
        cols = max(2, avail // (card_footprint(GALLERY_W) + t.SP_LG))
        card_w = max(GALLERY_W // 2, (avail - (cols - 1) * t.SP_LG)
                     // cols - card_footprint(0))
        # rebuild on a column change, or once the fill drifts visibly wide
        if self._current is not None and (
                cols != self._cols
                or abs(card_w - getattr(self, "_card_w", 0)) > t.SP_XL):
            self._cols = cols
            self._refill()
        super().resizeEvent(event)
