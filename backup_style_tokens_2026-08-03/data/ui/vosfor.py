"""Vosfor: the Arcane Dissolution planner, Qt edition.

The screen the whole migration was argued over - 500-odd rows in a scroller,
and the one that tore worst under Tk. Every string, band and flag comes from
core.vosfor_vm; this file places widgets.

Collection cards are built collapsed and their arcane rows are created only
when a card is opened, so the common case is 9 cards rather than 9 cards plus
~500 rows. Tk rebuilt the entire body on every toggle; here only the card that
changed is touched.
"""

from __future__ import annotations

import threading
import time

from PySide6.QtCore import QObject, QTimer, Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QFrame, QHBoxLayout, QLineEdit,
                               QPushButton, QScrollArea, QVBoxLayout, QWidget)

from core import arcane_market as core_arcane_market
from core import theme as t
from core import vosfor as core_vosfor
from core import vosfor_vm as vm
from core import wf_inventory
from ui.bridge import FetchBridge
from ui.widgets import glyph_icon, label, panel, restyle


class InventoryBridge(QObject):
    """The AlecaFrame read runs on a worker thread; a queued signal carries
    the result back without any of Tk's after(0, ...) plumbing."""
    done = Signal(object)

BAR_HEIGHT = 4
COL_DROP = 70
COL_FARM = 100
COL_PRICE = 78


class ProgressBar(QFrame):
    """The treasury fills with gold; a completed collection turns jade."""

    def __init__(self, fraction: float, complete: bool) -> None:
        super().__init__()
        self.setFixedHeight(BAR_HEIGHT)
        self._fraction = max(0.0, min(1.0, fraction))
        self._colour = t.OK if complete else t.ACCENT
        self.setStyleSheet(f"background: {t.WFM_EDGE}; border: none;")
        self._fill = QFrame(self)
        self._fill.setStyleSheet(f"background: {self._colour}; border: none;")

    def resizeEvent(self, event) -> None:
        self._fill.setGeometry(0, 0,
                               int(self.width() * self._fraction),
                               self.height())
        super().resizeEvent(event)


class ArcaneRow(QWidget):
    """One arcane. Clicking it cycles the manual override - except the wiki
    glyph, which is its own target: a look-up must never flip whether you
    own an arcane."""

    toggled = Signal(dict)
    wiki = Signal(str)

    def __init__(self, arc: dict) -> None:
        super().__init__()
        self._arc = arc
        r = vm.arcane_row(arc)
        self.setCursor(Qt.PointingHandCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 1, 0, 1)
        lay.setSpacing(t.SP_MD)

        mark, level = vm.status_mark(r["status"])
        glyph = label(t.glyph(mark), role="icon",
                      level=level if level != "muted" else "")
        if level == "muted":
            # Colour it; do NOT re-role it. Overwriting role="icon" with
            # role="muted" takes the icon FONT away, and the label then draws
            # the ligature as what it literally is - the word
            # "radio_button_unchecked", clipped by the fixed width to "rac".
            # A missing glyph is invisible; a missing FONT is a sentence.
            glyph.setStyleSheet(f"color: {t.MUTED};")
        glyph.setFixedWidth(18)
        lay.addWidget(glyph)

        frac = label(r["fraction"], role="mono",
                     level="ok" if r["maxed"] else "")
        lay.addWidget(frac)

        name = label(r["name"], role="" if r["maxed"] else "muted")
        lay.addWidget(name)

        # t.WIKI_ICON is a table KEY, not something a font can draw.
        # Passing it straight to a label rendered the letters "wiki" in
        # the icon face, which is why this link was oddly wide.
        link = label(t.glyph(t.WIKI_ICON), role="icon")
        link.setCursor(Qt.PointingHandCursor)
        link.setToolTip(f"Open {r['name']} on the wiki")
        link.mouseReleaseEvent = lambda _e: self.wiki.emit(r["name"])
        lay.addWidget(link)
        lay.addStretch(1)

        price = label(r["price_text"], role="price")
        if r["price_cheap"]:
            # teal flags "finishing this on the market beats buying packs"
            price.setStyleSheet(f"color: {t.WFM_TEAL};")
        price.setFixedWidth(COL_PRICE)
        price.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        if r["price_tooltip"]:
            price.setToolTip(r["price_tooltip"])
        lay.addWidget(price)

        farm = label(r["farm_text"], role="small",
                     level=r["farm_level"] if r["farm_level"] != "ok" else "")
        if r["farm_easy"]:
            farm.setProperty("level", "ok")
        farm.setFixedWidth(COL_FARM)
        farm.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        if r["farm_tooltip"]:
            farm.setToolTip(r["farm_tooltip"])
        lay.addWidget(farm)

        drop = label(r["drop_text"], role="small")
        drop.setFixedWidth(COL_DROP)
        drop.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lay.addWidget(drop)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.toggled.emit(self._arc)
        super().mouseReleaseEvent(event)


class CollectionCard(QFrame):
    """One collection: header, progress bar, and arcane rows once opened."""

    clicked = Signal(str)
    arcane_toggled = Signal(dict)
    wiki = Signal(str)

    def __init__(self, name: str, c: dict, is_open: bool) -> None:
        super().__init__()
        self.name = name
        self.setProperty("surface", "card")
        self.setAttribute(Qt.WA_StyledBackground, True)
        row = vm.collection_row(name, c, is_open)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(t.SP_LG, t.SP_MD, t.SP_LG, t.SP_MD)
        lay.setSpacing(t.SP_MD)

        head = QHBoxLayout()
        head.setSpacing(t.SP_SM)
        arrow = label(t.glyph("expand" if is_open else "collapse"),
                      role="icon")
        arrow.setFixedWidth(20)
        head.addWidget(arrow)
        head.addWidget(label(row["title"], role="h2",
                             level="ok" if row["completed"] else ""))
        if row["completed"]:
            done = label(t.glyph("complete"), role="icon", level="ok")
            done.setToolTip("every arcane in this collection is maxed")
            head.addWidget(done)
            head.addWidget(label("COMPLETE", role="small", level="ok"))
        head.addStretch(1)
        stat = label(row["stat"], role="price")
        stat.setStyleSheet(f"color: {t.WFM_MUTED};")
        head.addWidget(stat)
        lay.addLayout(head)

        lay.addWidget(ProgressBar(row["fraction"], row["completed"]))

        self._rows = QVBoxLayout()
        self._rows.setContentsMargins(0, 0, 0, 0)
        self._rows.setSpacing(0)
        lay.addLayout(self._rows)
        if is_open:
            self._build_rows(c)
        self.setCursor(Qt.PointingHandCursor)

    def _build_rows(self, c: dict) -> None:
        last = None
        for arc in c["arcanes"]:
            r = vm.arcane_row(arc)
            if r["rarity"] != last:
                last = r["rarity"]
                cap = label(r["rarity"].upper(), role="small")
                cap.setStyleSheet(
                    f"color: {t.RARITY_COLOR.get(r['rarity'], t.MUTED)};")
                self._rows.addWidget(cap)
            widget = ArcaneRow(arc)
            widget.toggled.connect(self.arcane_toggled)
            widget.wiki.connect(self.wiki)
            self._rows.addWidget(widget)

    def mouseReleaseEvent(self, event) -> None:
        # only the header area toggles; a click on a row is that row's
        if event.button() == Qt.LeftButton and event.position().y() < 40:
            self.clicked.emit(self.name)
        super().mouseReleaseEvent(event)


class VosforView(QWidget):
    BALANCE_SAVE_MS = 600      # debounce: this fires per keystroke

    def __init__(self, settings, on_wiki, save_settings, market_any) -> None:
        super().__init__()
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._settings = settings
        self._on_wiki = on_wiki
        self._save_settings = save_settings
        self._market_any = market_any
        self.override = core_vosfor.load_overrides()
        self.methods = vm.resolve_methods(settings,
                                          dict(core_vosfor.DEFAULT_METHODS))
        self._open: set[str] = set()
        pd = core_arcane_market.load_prices()
        self.prices = pd.get("prices", {})
        self._prices_at = pd.get("fetched_at")
        self._fetcher = None
        self._bridge = None
        self._inv_bridge = None
        self.owned = self.cached_mtime = None
        self.inv_stale = False

        self._bal_timer = QTimer(self)
        self._bal_timer.setSingleShot(True)
        self._bal_timer.timeout.connect(self._save_balance)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(t.SP_SCREEN, t.SP_XL, t.SP_SCREEN, t.SP_XL)
        outer.setSpacing(t.SP_LG)

        head = QHBoxLayout()
        head.addWidget(label("Vosfor Planner", role="h1"))
        head.addStretch(1)
        self.src_lbl = label("", role="small")
        head.addWidget(self.src_lbl)
        self.update_btn = QPushButton(" Update inventory")
        self.update_btn.setIcon(glyph_icon("refresh", color=t.TEXT))
        self.update_btn.setProperty("wide", "true")
        self.update_btn.setProperty("size", "small")
        self.update_btn.setCursor(Qt.PointingHandCursor)
        self.update_btn.clicked.connect(lambda: self.refresh_inventory(True))
        head.addWidget(self.update_btn)
        outer.addLayout(head)

        # Container 1: the planner - balance, alternatives, recommendation.
        planner = panel("card")
        pl = QVBoxLayout(planner)
        pl.setContentsMargins(t.SP_XL, t.SP_XL, t.SP_XL, t.SP_XL)
        pl.setSpacing(t.SP_LG)

        bal = QHBoxLayout()
        bal.setSpacing(t.SP_MD)
        bal.addWidget(label("Your Vosfor:", role="muted"))
        self.balance = QLineEdit(str(settings.get("vosfor_balance") or ""))
        self.balance.setFixedWidth(90)
        self.balance.setAlignment(Qt.AlignRight)
        self.balance.textChanged.connect(self._balance_changed)
        bal.addWidget(self.balance)
        bal.addWidget(label("(enter your balance for a purchase plan; each "
                            "pack is 200 Vosfor + 50k credits)", role="small"))
        bal.addStretch(1)
        pl.addLayout(bal)

        meth = QHBoxLayout()
        meth.setSpacing(t.SP_LG)
        meth.addWidget(label("Consider how else you'd get arcanes:",
                             role="small"))
        self.method_boxes = {}
        for key, text in (("farm", "Farming"), ("market", "Market price")):
            box = QCheckBox(text)
            box.setChecked(bool(self.methods.get(key)))
            box.toggled.connect(
                lambda on, k=key: self._toggle_method(k, on))
            self.method_boxes[key] = box
            meth.addWidget(box)
        self.price_btn = QPushButton(" Refresh prices")
        self.price_btn.setIcon(glyph_icon("refresh", color=t.TEXT))
        self.price_btn.setProperty("wide", "true")   # match "Update inventory"
        self.price_btn.setProperty("size", "small")
        self.price_btn.setCursor(Qt.PointingHandCursor)
        self.price_btn.clicked.connect(self.fetch_prices)
        meth.addWidget(self.price_btn)
        self.price_status = label("", role="small")
        meth.addWidget(self.price_status)
        meth.addStretch(1)
        pl.addLayout(meth)

        self.reco = label("", role="")
        self.reco.setWordWrap(True)
        self.reco.setProperty("surface", "tab")
        self.reco.setAttribute(Qt.WA_StyledBackground, True)
        # SP_LG all round: on-scale, and its left inset now matches the
        # collection cards below so the reco text shares their left edge
        self.reco.setContentsMargins(t.SP_LG, t.SP_LG, t.SP_LG, t.SP_LG)
        pl.addWidget(self.reco)
        outer.addWidget(planner)

        # Container 2: the collections. Its title sits ABOVE the box (a section
        # heading like Home's "Available Tools"), not inside it.
        outer.addWidget(label("Arcane Collection Progress", role="h1"))
        collections = panel("card")
        cl = QVBoxLayout(collections)
        cl.setContentsMargins(t.SP_XL, t.SP_XL, t.SP_XL, t.SP_XL)
        cl.setSpacing(t.SP_LG)

        self.area = QScrollArea()
        self.area.setWidgetResizable(True)
        self.area.setFrameShape(QFrame.NoFrame)
        self.area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        cl.addWidget(self.area, 1)
        outer.addWidget(collections, 1)

        self.reload()

    # -- model ---------------------------------------------------------------

    def reload(self) -> None:
        self.owned, self.cached_mtime, self.inv_stale = \
            core_vosfor.refresh_inventory(False)
        self.model = core_vosfor.evaluate(self.owned, self.override,
                                          self.methods, self.prices)
        self.rebuild()

    def rebuild(self) -> None:
        src = vm.source_line(self.owned, self.cached_mtime, self.inv_stale,
                             wf_inventory.source_name())
        self.src_lbl.setText(src.text)
        self.src_lbl.setProperty("level", src.level)
        self.src_lbl.style().unpolish(self.src_lbl)
        self.src_lbl.style().polish(self.src_lbl)
        self.reco.setText("\n".join(vm.reco_lines(
            self.model, self.methods, vm.parse_balance(self.balance.text()))))
        self._price_hint()

        body = panel()
        col = QVBoxLayout(body)
        col.setContentsMargins(0, 0, 0, t.SP_XL)
        col.setSpacing(t.SP_SM)
        for name in self.model["ranking"]:
            card = CollectionCard(name, self.model["collections"][name],
                                  name in self._open)
            card.clicked.connect(self._toggle)
            card.arcane_toggled.connect(self._toggle_arcane)
            card.wiki.connect(self._on_wiki)
            col.addWidget(card)
        col.addStretch(1)
        # Preserve the scroll position across a rebuild. setWidget resets the
        # scrollbar to 0, so expanding a collection or ticking an arcane far
        # down the list used to yank you back to the top. Restored after the
        # new body has a size (next tick).
        keep = self.area.verticalScrollBar().value()
        self.area.setWidget(body)
        QTimer.singleShot(
            0, lambda: self.area.verticalScrollBar().setValue(keep))

    # -- interaction ---------------------------------------------------------

    def _toggle(self, name: str) -> None:
        self._open.symmetric_difference_update({name})
        self.rebuild()

    def _toggle_arcane(self, arc: dict) -> None:
        if arc.get("path") is None:
            return
        vm.next_override(self.override, arc)
        core_vosfor.save_overrides(self.override)
        self.model = core_vosfor.evaluate(self.owned, self.override,
                                          self.methods, self.prices)
        self.rebuild()

    def _balance_changed(self, text: str) -> None:
        self._settings["vosfor_balance"] = vm.parse_balance(text)
        # Debounce the disk write - this fires per keystroke, and the settings
        # file does not need six rewrites while typing "150000".
        self._bal_timer.start(self.BALANCE_SAVE_MS)
        self.reco.setText("\n".join(vm.reco_lines(
            self.model, self.methods, vm.parse_balance(text))))

    def _save_balance(self) -> None:
        self._save_settings()

    def _toggle_method(self, key: str, on: bool) -> None:
        self.methods[key] = on
        self._settings["vosfor_methods"] = self.methods
        self._save_settings()
        if key == "market" and on and not self.prices:
            self.fetch_prices()          # market weighting needs prices first
        self.model = core_vosfor.evaluate(self.owned, self.override,
                                          self.methods, self.prices)
        self.rebuild()

    # -- background work -----------------------------------------------------

    def refresh_inventory(self, force: bool) -> None:
        """Re-read AlecaFrame off the UI thread: a stale read is a full AES
        decrypt of the whole inventory, ~900 ms, which would freeze the app
        if it ran inline."""
        if self._inv_bridge is not None:
            return                       # a read is already in flight
        self.update_btn.setEnabled(False)   # signal "working"; re-enabled when done
        self.src_lbl.setText("refreshing inventory…")
        bridge = InventoryBridge()
        self._inv_bridge = bridge
        bridge.done.connect(self._inventory_ready)

        def work():
            try:
                bridge.done.emit(core_vosfor.refresh_inventory(force))
            except Exception:            # noqa: BLE001 - never kill the thread
                bridge.done.emit(None)
        threading.Thread(target=work, daemon=True).start()

    def _inventory_ready(self, result) -> None:
        self._inv_bridge = None
        self.update_btn.setEnabled(True)
        if result is None:
            self.src_lbl.setText("inventory read failed")
            return
        self.owned, self.cached_mtime, self.inv_stale = result
        self.model = core_vosfor.evaluate(self.owned, self.override,
                                          self.methods, self.prices)
        self.rebuild()

    def fetch_prices(self) -> None:
        if self._fetcher is not None:
            return
        self.price_btn.setEnabled(False)    # signal "working"; re-enabled when done
        names = vm.all_arcane_names(core_vosfor.load_collections())
        self.price_status.setText(f"fetching prices 0/{len(names)}…")
        bridge = FetchBridge()
        # A BOUND METHOD, not a lambda: the lambda's Qt receiver would be the
        # bridge (which the fetcher keeps alive past teardown), so a late
        # progress emit would setText on a deleted QLabel. A bound method's
        # receiver is this view, so Qt drops the queued call when it is gone -
        # exactly as `finished` below already relies on.
        bridge.progress.connect(self._on_price_progress)
        bridge.finished.connect(self._prices_ready)
        self._bridge = bridge            # keep it alive for the fetch
        self._fetcher = core_arcane_market.PriceFetcher(self._market_any(),
                                                        names)
        # Signals are queued across threads automatically, so unlike Tk there
        # is no after(0, ...) hop and no destroyed-widget guard to remember.
        self._fetcher.start(bridge.on_progress,
                            lambda prices, err: bridge.on_done((prices, err)))

    def _on_price_progress(self, d, n) -> None:
        self.price_status.setText(f"fetching prices {d}/{n}…")

    def _prices_ready(self, payload) -> None:
        prices, err = payload
        self._fetcher = None
        self.price_btn.setEnabled(True)
        if prices is not None:
            self.prices = prices
            self._prices_at = time.time()
        self.price_status.setText(err or f"prices updated ({len(self.prices)})")
        self.price_status.setProperty("level", "warn" if err else "")
        restyle(self.price_status)
        self.model = core_vosfor.evaluate(self.owned, self.override,
                                          self.methods, self.prices)
        self.rebuild()

    def _price_hint(self) -> None:
        """Cached prices never refresh on their own, so surface their age."""
        if self._fetcher is not None or not self.prices:
            return
        hint = vm.price_age(self._prices_at)
        if hint is not None:
            self.price_status.setText(hint.text)
            self.price_status.setProperty("level", hint.level)
            restyle(self.price_status)
