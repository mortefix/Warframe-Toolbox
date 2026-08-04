"""My Listings: your warframe.market sell (WTS) and buy (WTB) orders.

The densest screen in the app, and the one the Tk version fought hardest.
Two decisions define this port.

**Cards are built once and re-ordered, never rebuilt.** The Tk tab destroyed
and recreated every card on each sort, filter or search change, which is what
made its threading fragile: a worker that had captured a widget could land
after that widget was destroyed, so fourteen code paths each needed their own
`winfo_exists()` guard and three of them were missing it. Measured here, at
100 listings:

    re-order the existing cards      4.8 ms
    destroy them and rebuild         395.8 ms

So the rebuild was never buying anything. A card now lives for as long as its
order does, which deletes the entire class of "configured after destruction"
bug - a late result addresses a card by `order_id`, and the only question left
is the honest one: *is this order still listed?*

**Every side difference comes from `core.listings_vm.SIDES`.** Sell and buy
differ in nine strings and one comparison direction, and this file is rendered
twice rather than branching on `side`. That matters more than it looks: an
account with no buy orders - which is the common case, and this developer's -
can never exercise the WTB path by clicking. It is covered by tests instead.

Severity crosses from core as a ROLE word; ROLE_COLOR is the only place this
file turns one into a colour.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QFontDatabase, QFontMetrics
from PySide6.QtWidgets import (QCheckBox, QDialog, QFrame, QGridLayout,
                               QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QScrollArea, QSizePolicy,
                               QStackedWidget, QVBoxLayout, QWidget)

from core import floors as core_floors
from core import listings_vm as vm
from core import market as core_market
from core import market_vm          # contract_row formatting for MyContractsTab
from core import repricer as core_repricer
from core import theme as t
from ui import work
from ui.suggest import SuggestBox
from ui.widgets import (Dropdown, glyph_icon, hairline, label, panel,
                        plat_icon, plat_label, polarity_icon, restyle)

ROLE_COLOR = {"ok": t.OK, "warn": t.WARN, "err": t.ERR, "muted": t.WFM_MUTED,
              "accent": t.ACCENT, "teal": t.WFM_TEAL, "pink": t.WFM_PINK}

CARD_COLUMNS = 2
ICON_PX = 96
LIMIT_FIELD_W = 52
OFFSET_FIELD_W = 46
#: side -> (badge background, badge foreground). The one thing SideSpec
#: deliberately does NOT carry, because which hue means "sell" is a theme
#: decision, not a rule about orders.
BADGE = {"sell": (t.WFM_BADGE_BG, t.WFM_BADGE_FG),
         "buy": (t.WFM_BUY_BG, t.WFM_BUY_FG)}
TAB_ACCENTS = {"WTS": t.WFM_BADGE_FG, "WTB": t.WFM_BUY_FG,
               "Contracts": t.ACCENT}


def _flat_style(colour: str) -> str:
    """The WFM outlined button, as a style sheet.

    The `:disabled` rule is not decoration. A bare `color: ...` declaration
    applies in every state, so Qt's disabled palette never gets a look in and
    a button you cannot press looks exactly like one you can - which is how
    the "-1 on a single unit" button shipped looking live.
    """
    return (f"QPushButton {{ color: {colour}; background: transparent;"
            f" border: 1px solid {colour}; padding: 2px 8px; }}"
            f"QPushButton:disabled {{ color: {t.WFM_EDGE};"
            f" border-color: {t.WFM_EDGE}; }}")


def _flat(text: str, colour: str, tip: str = "",
          icon: str = "") -> QPushButton:
    """One widget with a border. Tk built this by nesting a Button inside a
    1px Frame and stapling the inner button on as `.btn`, so every caller had
    to remember the extra hop.

    `icon` is a core.theme.ICONS key. It is tinted to match the border, so a
    button never shows a grey mark against a coloured edge.
    """
    b = QPushButton(text)
    if icon:
        b.setIcon(glyph_icon(icon, color=colour))
    b.setProperty("size", "small")
    b.setCursor(Qt.PointingHandCursor)
    b.setStyleSheet(_flat_style(colour))
    if tip:
        b.setToolTip(tip)
    return b


def _placeholder_icon(mark: str = "◍") -> QLabel:
    """The item-image stand-in the cards share: a big glyph in a bordered black
    well. The ONE hand-written type-size literal the style guide sanctions lives
    here, so the order cards and the contract cards can both enlarge their
    placeholder without a second literal drifting out of sync with this one."""
    icon = QLabel(mark)
    icon.setFixedSize(ICON_PX, ICON_PX)
    icon.setAlignment(Qt.AlignCenter)
    icon.setStyleSheet(
        f"background: {t.ICON_BG}; color: {t.WFM_EDGE};"
        f"border: 1px solid {t.WFM_EDGE}; font-size: 30pt;")
    return icon


class ListingCard(QFrame):
    """One order. Created once per `order_id` and kept until that order goes.

    Holds a live reference to the `Listing` dataclass rather than a copy of
    its fields, so a worker that mutates the listing and a repaint that reads
    it cannot disagree - `paint()` is always a pure function of the model.
    """

    sold = Signal(str)
    edit = Signal(str)
    adjust = Signal(str, int)
    visibility = Signal(str)
    remove = Signal(str)
    reprice = Signal(str)
    wiki = Signal(str)
    limit_typed = Signal(str)

    def __init__(self, listing: core_market.Listing, spec: vm.SideSpec) -> None:
        super().__init__()
        self.listing = listing
        self.spec = spec
        self.oid = listing.order_id
        # `market_low is None` is ambiguous on its own - it means both "not
        # fetched yet" and "nobody else is listing this". The sweep sets this
        # when it lands, which is what tells the two apart.
        self.market_known = False
        self.market_failed = False       # last sweep for this card errored
        self.setProperty("surface", "listing")
        self.setAttribute(Qt.WA_StyledBackground, True)

        grid = QGridLayout(self)
        grid.setContentsMargins(t.SP_LG, t.SP_LG, t.SP_LG, t.SP_LG)
        grid.setHorizontalSpacing(t.SP_LG)
        grid.setVerticalSpacing(t.SP_MD)
        grid.setColumnStretch(1, 1)

        self.icon = _placeholder_icon()
        grid.addWidget(self.icon, 0, 0, 3, 1, Qt.AlignTop)

        # -- title row
        title = QHBoxLayout()
        title.setSpacing(t.SP_SM)
        badge_bg, badge_fg = BADGE[spec.side]
        # bold + a touch larger (role="badge"), centred in a box sized to the
        # +/-1 buttons in showEvent; bg/fg are the side colours, set inline
        self.badge = label(spec.badge_text.upper(), role="badge")
        self.badge.setAlignment(Qt.AlignCenter)
        self.badge.setStyleSheet(f"background: {badge_bg}; color: {badge_fg};")
        title.addWidget(self.badge, 0, Qt.AlignVCenter)
        self.name = label(listing.name, role="h2")
        self.name.setStyleSheet(f"color: {t.WFM_TEAL};")
        title.addWidget(self.name)
        # Two orders for the same item at different ranks already get their
        # own cards (a card is keyed by order_id), but without this they would
        # be indistinguishable on screen.
        # h2 (the item-title face) so the rank reads at the title's size, in pink
        self.rank = label(vm.rank_text(listing), role="h2")
        self.rank.setStyleSheet(f"color: {t.WFM_PINK};")
        self.rank.setToolTip("mod / arcane rank")
        self.rank.setVisible(bool(vm.rank_text(listing)))
        title.addWidget(self.rank)
        title.addStretch(1)
        # the wiki shortcut floats at the card's top-right, past the stretch,
        # wearing the same 1px edge every other card control carries. The
        # glyph has to be an ICON: a Private Use Area codepoint left in a
        # button's label renders in that button's face, and Segoe UI resolves
        # U+E82D to a CJK fallback (see ui.widgets.glyph_icon)
        self.wiki_btn = QPushButton(glyph_icon(t.WIKI_ICON, color=t.WFM_MUTED),
                                    "")
        self.wiki_btn.setStyleSheet(_flat_style(t.WFM_MUTED))
        self.wiki_btn.setCursor(Qt.PointingHandCursor)
        self.wiki_btn.setToolTip(f"open {listing.name} on the wiki")
        self.wiki_btn.clicked.connect(lambda: self.wiki.emit(listing.name))
        # sized to match the +/-1 buttons in showEvent (below), not here
        title.addWidget(self.wiki_btn, 0, Qt.AlignTop)
        grid.addLayout(title, 0, 1)

        # -- price / quantity / market line
        # Left-aligned (stretch at the END) so the price reads directly under
        # the item name as one unit, instead of being orphaned to the card's far
        # right with a dead gap between the name and its own price.
        info = QHBoxLayout()
        info.setSpacing(t.SP_SM)
        # a negative top margin halves the gap between this line and the badge/
        # name row above it (the grid's row spacing is SP_MD; pull up by half)
        info.setContentsMargins(0, -(t.SP_MD // 2), 0, 0)
        # everything on this line is vertically centred, so the mixed heights
        # (the loud quantity/price faces, the plat gem) share one centre line
        # instead of each sitting on its own baseline
        mid = Qt.AlignVCenter
        self.qty = label("", role="qty")
        info.addWidget(self.qty, 0, mid)
        info.addWidget(self._dot(), 0, mid)
        self.price = label("", role="price")
        info.addWidget(self.price, 0, mid)
        info.addWidget(plat_label(), 0, mid)
        info.addWidget(label("each", role="small"), 0, mid)
        info.addWidget(self._dot(), 0, mid)
        self.market = label(f"{spec.best_word.capitalize()} …", role="small")
        self.market.setToolTip("best live price from another trader")
        info.addWidget(self.market, 0, mid)
        # the online count is a SEPARATE plain label (never rich text, which
        # sits lower than plain text and broke this line's centring) so it
        # shares the centre line and stays muted even when the price warns
        self.online = label("", role="small")
        self.online.setStyleSheet(f"color: {t.WFM_MUTED};")
        info.addWidget(self.online, 0, mid)
        info.addStretch(1)
        grid.addLayout(info, 1, 1)

        # -- actions
        acts = QHBoxLayout()
        acts.setSpacing(t.SP_SM)
        acts.addStretch(1)
        done = _flat(f" {spec.done_verb}", t.ACCENT,
                     f"mark one unit {spec.done_verb.lower()}",
                     icon="sold")
        done.clicked.connect(lambda: self.sold.emit(self.oid))
        acts.addWidget(done)
        edit = _flat(" Edit", t.WFM_TEAL, "edit price, quantity and limit",
                     icon="edit")
        edit.clicked.connect(lambda: self.edit.emit(self.oid))
        acts.addWidget(edit)
        self.up = _flat("1", t.WFM_TEAL, "one more in stock",
                        icon="add_one")
        self.up.clicked.connect(lambda: self.adjust.emit(self.oid, 1))
        acts.addWidget(self.up)
        self.down = _flat("1", t.WFM_TEAL, "one fewer in stock",
                          icon="less_one")
        self.down.clicked.connect(lambda: self.adjust.emit(self.oid, -1))
        acts.addWidget(self.down)
        # icon-only: the eye IS the state (open = visible, struck = hidden);
        # the tooltip carries the words the face no longer does
        self.vis = _flat("", t.TEXT, "shown on warframe.market - click to "
                         "hide", icon="visible")
        # sized to match the +/-1 buttons in showEvent (below)
        self.vis.clicked.connect(lambda: self.visibility.emit(self.oid))
        acts.addWidget(self.vis)
        grid.addLayout(acts, 2, 1)

        # -- limit row
        bot = QHBoxLayout()
        bot.setSpacing(t.SP_SM)
        bot.addWidget(label(spec.limit_short, role="small"))
        self.limit = QLineEdit()
        self.limit.setFixedWidth(LIMIT_FIELD_W)
        self.limit.setAlignment(Qt.AlignCenter)
        self.limit.setToolTip(
            f"the repricer never goes past this - blank follows the tab "
            f"{spec.limit_word} automatically")
        self.limit.editingFinished.connect(
            lambda: self.limit_typed.emit(self.oid))
        bot.addWidget(self.limit)
        gem = QLabel()
        gem.setPixmap(plat_icon())
        gem.setStyleSheet("background: transparent;")
        bot.addWidget(gem)
        self.limit_mode = label("auto", role="small")
        self.limit_mode.setToolTip("auto follows the tab offset; set is yours")
        bot.addWidget(self.limit_mode)
        self.result = label("", role="small")
        bot.addWidget(self.result, 1)
        rp = QPushButton(" Reprice")
        rp.setIcon(glyph_icon("reprice", color=t.INK))
        rp.setProperty("kind", "money")
        rp.setProperty("size", "small")
        rp.setProperty("compact", "true")   # tighter padding -> compact height
        rp.setCursor(Qt.PointingHandCursor)
        rp.setToolTip("match the best live price, clamped to the limit")
        rp.clicked.connect(lambda: self.reprice.emit(self.oid))
        bot.addWidget(rp)
        rm = QPushButton(glyph_icon("delete", color=t.WFM_RED), "")
        # the same 1px edge its neighbours carry: a bare glyph reads as
        # decoration rather than as the destructive button it is
        rm.setStyleSheet(_flat_style(t.WFM_RED))
        rm.setCursor(Qt.PointingHandCursor)
        rm.setToolTip("delete this order")
        rm.clicked.connect(lambda: self.remove.emit(self.oid))
        bot.addWidget(rm)
        # Height is TAKEN FROM the neighbour rather than guessed. The two sit
        # side by side, so a hardcoded size is a number that has to be kept in
        # sync with a style sheet by hand - and was already out of step.
        self._match_heights = (rp, rm)
        grid.addLayout(bot, 3, 0, 1, 2)

        self.set_hit(False)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # sizeHint is only meaningful once the style sheet has been applied,
        # which has not happened during __init__
        # ONE height for every control on the card - the +/-1 (visibility) button
        # height - and ONE width for the three icon-only buttons (eye, wiki,
        # trash). Everything is derived from a neighbour, never a literal.
        rp, rm = self._match_heights
        H = self.up.sizeHint().height()          # the visibility-button height
        wide = self.up.sizeHint().width()        # the +/-1 width
        icon_w = H + 6                           # eye = wiki = trash width
        for b in (self.vis, self.wiki_btn, rm):
            b.setFixedSize(icon_w, H)
        # Reprice spans the +1 AND -1 buttons above it (trash sits under the
        # eye), so its left edge lines up with +1's - the row reads as a grid.
        rp.setFixedSize(2 * wide + t.SP_SM, H)
        # the badge matches the +/-1 buttons; the repricer field matches their
        # width and the shared button height
        self.badge.setFixedSize(wide, H)
        self.limit.setFixedSize(wide, H)

    def _dot(self) -> QLabel:
        w = label("·", role="small")
        w.setStyleSheet(f"color: {t.WFM_EDGE};")
        return w

    # -- painting ------------------------------------------------------------

    def paint(self, limits: core_floors.Limits) -> None:
        """Repaint everything derived from the model. Idempotent by design:
        any worker can call it at any time without tracking what changed."""
        l = self.listing
        self.name.setText(l.name)
        self.rank.setText(vm.rank_text(l))
        self.rank.setVisible(bool(vm.rank_text(l)))
        self.qty.setText(f"{l.quantity} ❒")
        self.price.setText(str(l.platinum))
        colour = t.TEXT if l.visible else t.WARN
        self.vis.setIcon(glyph_icon("visible" if l.visible else "hidden",
                                    color=colour))
        self.vis.setStyleSheet(_flat_style(colour))
        self.vis.setToolTip("shown on warframe.market - click to hide"
                            if l.visible else
                            "hidden on warframe.market - click to show")
        # -1 stays live and identically styled even on a single unit. Greying
        # it out made the pair look mismatched, and the refusal it gives when
        # pressed ("use Delete to remove the last one") explains itself far
        # better than a disabled control that cannot say why.
        self.down.setToolTip("one fewer in stock" if l.quantity > 1
                             else "use Delete to remove the last one")
        self.paint_limit(limits)
        self.paint_market()

    def paint_limit(self, limits: core_floors.Limits) -> None:
        """The limit field and its auto/set tag. Never touched while the user
        is typing in it - a background repaint that overwrote a half-typed
        number would be maddening and is easy to cause."""
        if not self.limit.hasFocus():
            self.limit.setText(str(limits.limit(
                vm.limit_key(self.listing), self.oid,
                self.listing.platinum)))
        overridden = limits.is_overridden(vm.limit_key(self.listing))
        self.limit_mode.setText("set" if overridden else "auto")
        self.limit_mode.setStyleSheet(
            f"color: {t.WFM_PINK if overridden else t.WFM_MUTED};")

    def paint_market(self) -> None:
        """The live-market readout. `better_than` is the same rule that
        decides whether a reprice clamp bit - sellers are beaten by a lower
        price, buyers by a higher one."""
        l = self.listing
        if getattr(self, "market_failed", False):
            # the fetch errored - distinct from both "loading" and "nobody
            # else listing", because acting on it would be acting on nothing
            self.market.setText("market unknown")
            self.market.setStyleSheet(f"color: {t.WARN};")
            self.online.setText("")
            return
        if l.market_low is None:
            # "…" is still loading; "only listing" is a finished sweep that
            # found no competition - a good outcome, not a stalled one
            self.market.setText("only listing" if self.market_known
                                else f"{self.spec.best_word.capitalize()} …")
            self.market.setStyleSheet(f"color: {t.WFM_MUTED};")
            self.online.setText("")
            return
        beaten = core_repricer.better_than(self.spec.side, l.market_low,
                                           l.platinum)
        mark = "⚠ " if beaten else ""
        self.market.setText(
            f"{mark}{self.spec.best_word.capitalize()} = {l.market_low}p")
        self.market.setStyleSheet(f"color: {t.WARN if beaten else t.WFM_MUTED};")
        # a separate, always-muted label - not part of the warning
        self.online.setText(f"· {l.online_count} online")

    def set_result(self, text: str, role: str = "muted") -> None:
        self.result.setText(text)
        self.result.setStyleSheet(f"color: {ROLE_COLOR[role]};")

    def set_thumb(self, pixmap) -> None:
        self.icon.setStyleSheet(f"background: {t.ICON_BG};"
                                f"border: 1px solid {t.WFM_EDGE};")
        self.icon.setPixmap(pixmap)

    def set_hit(self, hit: bool) -> None:
        """Search highlight: the card's own edge, so the match is visible
        without moving anything or adding a widget that changes the layout."""
        edge = t.ACCENT if hit else t.WFM_EDGE
        self.setStyleSheet(f"QFrame[surface=\"listing\"] {{"
                           f" background: {t.WFM_CARD};"
                           f" border: 1px solid {edge}; }}")


class EditListingDialog(QDialog):
    """Price, quantity, limit and visibility for one order.

    The limit field is blank-means-auto, matching the card: an explicit value
    equal to the derived default is stored as a CLEAR, not a value, or the
    limit would freeze against later baseline movement (see core.floors).
    """

    def __init__(self, tab, card: ListingCard) -> None:
        super().__init__(tab.window())
        self.tab, self.card = tab, card
        l = card.listing
        self.setWindowTitle(f"Edit — {l.name}")
        self.setModal(True)
        self.setMinimumWidth(430)         # §9: dialogs carry a stable min width
        lay = QVBoxLayout(self)
        lay.setContentsMargins(t.SP_XL, t.SP_XL, t.SP_XL, t.SP_XL)
        lay.setSpacing(t.SP_MD)

        head = QHBoxLayout()
        badge_bg, badge_fg = BADGE[tab.spec.side]
        b = label(tab.spec.badge_text, role="small")
        b.setStyleSheet(f"background: {badge_bg}; color: {badge_fg};"
                        f"padding: 1px 4px;")
        # centre the pill instead of letting it stretch to the h2 name's height
        # (an HBox fills its children vertically by default -> a tall rectangle)
        head.addWidget(b, 0, Qt.AlignVCenter)
        nm = label(l.name, role="h2")
        nm.setStyleSheet(f"color: {t.WFM_TEAL};")
        head.addWidget(nm)
        head.addStretch(1)
        lay.addLayout(head)
        lay.addWidget(hairline())

        self.price = self._field(lay, "Price (platinum)", str(l.platinum))
        self.qty = self._field(lay, "Quantity", str(l.quantity))

        # Rank, for goods that have one. Whether an item ranks is read off the
        # ORDER (`rank is not None`), never from a table of rankable items
        # kept in this repo - that table would be stale the week after a new
        # arcane ships. How FAR it ranks needs /v2/item/<slug>, which the bulk
        # catalogue does not carry, so it is fetched here and cached by the
        # client. The picker opens holding the current rank and widens when
        # that lands, so the dialog is usable immediately either way.
        self.rank = None
        if vm.is_rankable(l):
            lay.addWidget(label("Rank", role="small"))
            self.rank = Dropdown([f"R-{l.rank}"])
            self.rank.setCurrentText(f"R-{l.rank}")
            lay.addWidget(self.rank)
            self._rank_job = work.run(
                lambda: tab.client.max_rank(l.slug), self._ranks_ready,
                lambda _m: None)

        self.limit = self._field(
            lay, f"{tab.spec.limit_title} (blank = auto)",
            str(tab.limits.overrides.get(vm.limit_key(l), "")))
        self.visible = QCheckBox("Visible on warframe.market")
        self.visible.setChecked(l.visible)
        lay.addWidget(self.visible)

        self.status = label("", role="small")
        lay.addWidget(self.status)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        self.save = QPushButton("Save")
        self.save.setProperty("kind", "money")
        self.save.setDefault(True)
        self.save.clicked.connect(self._save)
        row.addWidget(self.save)
        lay.addLayout(row)
        self._job = None

    def _field(self, lay, caption: str, value: str) -> QLineEdit:
        lay.addWidget(label(caption, role="small"))
        e = QLineEdit(value)
        lay.addWidget(e)
        return e

    def _ranks_ready(self, max_rank) -> None:
        """Widen the picker to the item's full range once the API says what
        that is. Keeps the current selection - the fetch must never silently
        move the rank out from under someone mid-edit."""
        if self.rank is None or not max_rank:
            return
        self.card.listing.max_rank = max_rank
        keep = self.rank.currentText()
        self.rank.blockSignals(True)
        self.rank.clear()
        self.rank.addItems([f"R-{i}" for i in range(max_rank + 1)])
        idx = self.rank.findText(keep)
        self.rank.setCurrentIndex(max(0, idx))
        self.rank.blockSignals(False)

    def _chosen_rank(self) -> int | None:
        if self.rank is None:
            return None
        try:
            return int(self.rank.currentText().split("-", 1)[1])
        except (IndexError, ValueError):
            return None

    def _save(self) -> None:
        try:
            price = max(1, int(self.price.text().strip()))
            qty = max(1, int(self.qty.text().strip()))
        except ValueError:
            self.status.setText("price and quantity must be whole numbers")
            self.status.setStyleSheet(f"color: {t.ERR};")
            return
        text = self.limit.text().strip()
        limit = core_floors.parse_limit(text) if text else None
        if text and limit is None:
            self.status.setText("that limit is not a number")
            self.status.setStyleSheet(f"color: {t.ERR};")
            return
        visible = self.visible.isChecked()
        self.save.setEnabled(False)
        self.status.setText("saving…")
        self.status.setStyleSheet(f"color: {t.WFM_MUTED};")
        oid = self.card.oid
        rank = self._chosen_rank()
        self._job = work.run(
            lambda: self.tab.client.update_order(oid, price, qty, visible,
                                                 rank),
            lambda _r: self._done(price, qty, visible, limit, rank),
            self._failed)

    def _failed(self, msg: str) -> None:
        self.save.setEnabled(True)
        self.status.setText(msg)
        self.status.setStyleSheet(f"color: {t.ERR};")

    def _done(self, price: int, qty: int, visible: bool,
              limit: int | None, rank: int | None) -> None:
        l = self.card.listing
        # Read the OLD limit key before the rank moves: the key contains the
        # rank, so changing R-0 to R-3 makes this a different good with a
        # different floor, and the entry the old rank owned has to be cleared
        # rather than left behind to be inherited by a future R-0 order.
        was_key = vm.limit_key(l)
        l.platinum, l.quantity, l.visible = price, qty, visible
        if rank is not None:
            l.rank = rank
        # a hand-set price becomes the new reference the auto limit hangs off,
        # otherwise every later default would still derive from the old one
        self.tab.limits.rebase(self.card.oid, price)
        if was_key != vm.limit_key(l):
            self.tab.limits.set_override(was_key, None)
        # A value equal to the derived default is stored as a CLEAR, not a
        # value - the same rule the inline field uses via Limits.commit, and
        # the one this dialog's docstring promises. Storing it as an override
        # would freeze the limit against later baseline movement.
        if limit is not None and limit == self.tab.limits.auto(
                self.card.oid, price):
            limit = None
        self.tab.limits.set_override(vm.limit_key(l), limit)
        try:
            core_market.save_prefs(self.tab.prefs)
        except OSError:
            # the server write already succeeded; a failed prefs write must
            # not wedge the dialog. Say so and close rather than trapping the
            # user in a dialog they cannot dismiss.
            self.card.set_result("order saved; preferences not written", "warn")
        else:
            self.card.set_result("saved", "ok")
        self.card.paint(self.tab.limits)
        self.tab.apply_view()
        self.accept()


class ListingsTab(QWidget):
    """One side's orders. Rendered twice; every difference is in `spec`."""

    def __init__(self, view, side: str) -> None:
        super().__init__()
        self.view = view
        self.side = side
        self.spec = vm.spec(side)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.prefs = view.prefs
        self.limits = core_floors.Limits(view.baseline, view.prefs,
                                         self.spec.offset_key,
                                         self.spec.override_key)
        self.listings: list[core_market.Listing] = []
        self.cards: dict[str, ListingCard] = {}
        self._order: list[str] = []      # display order, for search tie-breaks
        self._thumbs: dict[str, object] = {}
        self._jobs: list[work.Job] = []
        self._sweep: work.Job | None = None
        self._desc = False
        self._busy = False
        self._dirty = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, t.SP_LG, 0, 0)
        lay.setSpacing(t.SP_MD)

        # -- row 1: the tab-wide repricer offset
        row = QHBoxLayout()
        row.setSpacing(t.SP_SM)
        row.addWidget(label(f"{self.spec.limit_title}: set price",
                            role="muted"))
        self.offset = QLineEdit(f"{self.limits.offset:+d}")
        self.offset.setFixedWidth(OFFSET_FIELD_W)
        self.offset.setAlignment(Qt.AlignCenter)
        self.offset.editingFinished.connect(self._commit_offset)
        row.addWidget(self.offset)
        blurb = self.spec.reprice_blurb
        blurb_lbl = label(blurb, role="muted")
        # WRAPPED. Unwrapped, this one sentence reported a 1440px minimum and
        # set the floor for the whole window - see the note in ui/app.py's
        # show_configured.
        blurb_lbl.setWordWrap(True)
        row.addWidget(blurb_lbl, 1)
        row.addStretch(0)
        self.reprice_all_btn = QPushButton(" Reprice all")
        self.reprice_all_btn.setIcon(glyph_icon("reprice", color=t.INK))
        self.reprice_all_btn.setProperty("kind", "money")
        self.reprice_all_btn.setCursor(Qt.PointingHandCursor)
        self.reprice_all_btn.clicked.connect(self._reprice_all)
        row.addWidget(self.reprice_all_btn)
        lay.addLayout(row)

        # -- row 2: search, sort, filter, bulk visibility
        ctl = QHBoxLayout()
        ctl.setSpacing(t.SP_SM)
        ctl.addWidget(label("Search", role="muted"))
        self.search = QLineEdit()
        self.search.setMinimumWidth(200)
        self.search.textChanged.connect(self._search_typed)
        ctl.addWidget(self.search, 1)
        self.suggest = SuggestBox(self.search, self._supply, self._picked)
        ctl.addSpacing(t.SP_LG)
        ctl.addWidget(label("Sort", role="muted"))
        self.sort = Dropdown(list(vm.SORTS))
        self.sort.currentTextChanged.connect(self._sort_changed)
        ctl.addWidget(self.sort)
        self.order_btn = QPushButton()
        self.order_btn.setProperty("size", "small")
        self.order_btn.setMinimumWidth(96)
        self.order_btn.setToolTip("click to reverse the order")
        self.order_btn.clicked.connect(self._flip_order)
        self._paint_direction()
        ctl.addWidget(self.order_btn)
        ctl.addSpacing(t.SP_LG)          # separate the Sort / Show / Visibility
        ctl.addWidget(label("Show", role="muted"))
        self.show_mode = Dropdown(["All", "Visible", "Hidden"])
        self.show_mode.currentTextChanged.connect(lambda _v: self.apply_view())
        ctl.addWidget(self.show_mode)
        ctl.addSpacing(t.SP_LG)          # groups, not one undifferentiated run
        ctl.addWidget(label("Visibility", role="muted"))
        show_all = _flat(" Show all", t.TEXT, "make every order visible",
                         icon="visible")
        show_all.clicked.connect(lambda: self._bulk_visibility(True))
        ctl.addWidget(show_all)
        hide_all = _flat(" Hide all", t.WARN, "hide every order",
                         icon="hidden")
        hide_all.clicked.connect(lambda: self._bulk_visibility(False))
        ctl.addWidget(hide_all)
        lay.addLayout(ctl)

        self.status = label("", role="small")
        lay.addWidget(self.status)

        self.area = QScrollArea()
        self.area.setWidgetResizable(True)
        self.area.setFrameShape(QFrame.NoFrame)
        self.area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.body = panel()
        self.grid = QGridLayout(self.body)
        # right pad so the cards don't butt against the vertical scrollbar
        self.grid.setContentsMargins(0, 0, t.SP_LG, 0)
        self.grid.setSpacing(t.SP_MD)
        for c in range(CARD_COLUMNS):
            self.grid.setColumnStretch(c, 1)
        # which grid row currently carries the vertical slack (see apply_view);
        # kept so it can be reset when the card count changes
        self._stretch_row = None
        self.area.setWidget(self.body)
        lay.addWidget(self.area, 1)

        # empty state: a centred notice card (the Contracts placeholder look),
        # shown in place of the card scroll when this side has no orders
        self.notice = CenteredNotice(*EMPTY_NOTICE[side])
        self.notice.hide()
        lay.addWidget(self.notice, 1)

    # -- model ---------------------------------------------------------------

    @property
    def client(self):
        return self.view.client

    def set_listings(self, rows: list[core_market.Listing]) -> None:
        """Take a fresh fetch. Cards are reconciled against it, not rebuilt:
        an order that is still listed keeps the widget it already had, so a
        result still in flight for it lands somewhere real."""
        self.listings = rows
        alive = {l.order_id for l in rows}
        for oid in [o for o in self.cards if o not in alive]:
            card = self.cards.pop(oid)
            card.setParent(None)
            card.deleteLater()
        for l in rows:
            # pin the session baseline the auto limit derives from, exactly
            # once per order - this is the "first sight" the docs mean
            self.limits.reference(l.order_id, l.platinum)
            card = self.cards.get(l.order_id)
            if card is None:
                self.cards[l.order_id] = self._new_card(l)
            else:
                card.listing = l
                card.paint(self.limits)
        self.apply_view()
        self._load_thumbs()

    def _new_card(self, l: core_market.Listing) -> ListingCard:
        card = ListingCard(l, self.spec)
        card.sold.connect(self._sold)
        card.edit.connect(self._edit)
        card.adjust.connect(self._adjust_qty)
        card.visibility.connect(self._toggle_visible)
        card.remove.connect(self._delete)
        card.reprice.connect(self._reprice_one)
        card.wiki.connect(self.view.open_wiki)
        card.limit_typed.connect(self._commit_limit)
        card.paint(self.limits)
        thumb = self._thumbs.get(l.slug)
        if thumb is not None:
            card.set_thumb(thumb)
        return card

    def apply_view(self) -> None:
        """Filter, sort, and place the cards. Deferred while the tab is off
        screen - not for correctness (Qt has no mapped-guard problem) but
        because a relayout nobody can see is wasted work."""
        if not self.isVisible():
            self._dirty = True
            return
        self._dirty = False
        rows = vm.arrange(self.listings, self.show_mode.currentText(),
                          self.sort.currentText(), self._desc)
        self._order = [l.order_id for l in rows]
        shown = set(self._order)
        # one relayout, not one per widget: without this a filter change on
        # 100 cards costs ~240 ms in show/hide churn alone
        self.body.setUpdatesEnabled(False)
        try:
            for i, oid in enumerate(self._order):
                card = self.cards[oid]
                self.grid.addWidget(card, i // CARD_COLUMNS,
                                    i % CARD_COLUMNS)
                card.setVisible(True)
            for oid, card in self.cards.items():
                if oid not in shown:
                    card.setVisible(False)
            # Pool leftover height BELOW the cards, not inside them. The scroll
            # body is taller than a few cards need; with no stretch row the grid
            # shares that slack across the card rows and each card balloons into
            # a hollow box. Give the row after the last card all the stretch
            # (resetting the previous one - the count changes per view).
            used = (len(self._order) + CARD_COLUMNS - 1) // CARD_COLUMNS
            if self._stretch_row is not None and self._stretch_row != used:
                self.grid.setRowStretch(self._stretch_row, 0)
            self.grid.setRowStretch(used, 1)
            self._stretch_row = used
        finally:
            self.body.setUpdatesEnabled(True)
        # empty (AFTER the Show filter) -> a centred notice instead of the
        # scroll, worded for WHY: no orders at all, or none matching the
        # Hidden / Visible filter
        empty = not self._order
        if empty:
            mode = self.show_mode.currentText()
            if self.listings and mode in FILTER_NOTICE:
                self.notice.set_text(*FILTER_NOTICE[mode])
            else:
                self.notice.set_text(*EMPTY_NOTICE[self.side])
        self.area.setVisible(not empty)
        self.notice.setVisible(empty)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._dirty:
            self.apply_view()

    # -- header controls -----------------------------------------------------

    def _commit_offset(self) -> None:
        value = core_floors.parse_offset(self.offset.text(),
                                         self.limits.offset)
        if value is None:                       # not a number: repaint, keep
            self.offset.setText(f"{self.limits.offset:+d}")
            return
        if self.limits.set_offset(value):
            core_market.save_prefs(self.prefs)
        self.offset.setText(f"{self.limits.offset:+d}")
        for card in self.cards.values():
            card.paint_limit(self.limits)

    def _commit_limit(self, oid: str) -> None:
        card = self.cards.get(oid)
        if card is None:
            return
        l = card.listing
        outcome = self.limits.commit(card.limit.text(),
                                     vm.limit_key(l), oid, l.platinum)
        if outcome.changed:
            core_market.save_prefs(self.prefs)
        card.paint_limit(self.limits)

    def _sort_changed(self, _value: str) -> None:
        self._paint_direction()
        self.apply_view()

    def _paint_direction(self) -> None:
        """Name the resulting order rather than drawing an arrow. Up and down
        arrows are read both ways by different people - "which way is up?" is
        a question a control should not raise - and "low → high" cannot be
        misread."""
        self.order_btn.setText(
            vm.direction_label(self.sort.currentText(), self._desc))

    def _flip_order(self) -> None:
        self._desc = not self._desc
        self._paint_direction()
        self.apply_view()

    def _supply(self, query: str):
        return [(n, n) for n in vm.suggest(
            (l.name for l in self.listings), query)]

    def _picked(self, name: str, _payload) -> None:
        self.search.setText(name)
        self._search_typed()

    def _search_typed(self) -> None:
        """Highlight the first match and scroll it into view. Display order
        decides ties, so the pairs are built from `self._order`."""
        query = self.search.text().strip()
        for card in self.cards.values():
            card.set_hit(False)
        if not query:
            # a search scrolls you somewhere; clearing it should put you back
            # where you started rather than stranding you mid-list
            self.area.verticalScrollBar().setValue(0)
            return
        pairs = [(oid, self.cards[oid].listing.name.lower())
                 for oid in self._order if oid in self.cards]
        hit = vm.find_match(pairs, query)
        if hit is None:
            return
        card = self.cards[hit]
        card.set_hit(True)
        self.area.ensureWidgetVisible(card)

    # -- status --------------------------------------------------------------

    def _set_busy(self, busy: bool, message: str = "") -> None:
        self._busy = busy
        self.reprice_all_btn.setEnabled(not busy)
        if message:
            self.status.setText(message)

    def set_status(self, text: str, role: str = "muted") -> None:
        self.status.setText(text)
        self.status.setStyleSheet(f"color: {ROLE_COLOR[role]};")

    def set_failed(self, msg: str) -> None:
        self.set_status(msg, "err")
        self._set_busy(False)

    def _card_result(self, oid: str, text: str, role: str) -> None:
        """The only guard a late result needs now: is this order still
        listed? Cards outlive every worker, so widget liveness is not the
        question - staleness is."""
        card = self.cards.get(oid)
        if card is not None:
            card.set_result(text, role)

    # -- market sweep --------------------------------------------------------

    def start_sweep(self) -> None:
        """Fetch the best live price for every listing, reporting each as it
        lands. Cancels any sweep already running - the Tk version had no
        generation token, so a second Refresh raced the first one."""
        if self._sweep is not None:
            self._sweep.cancel()
        rows = list(self.listings)
        if not rows:
            self._sweep = None
            return
        best_of = getattr(self.client, self.spec.best_method)
        user = self.view.username

        def body(job):
            for l in rows:
                if job.cancelled:
                    return
                try:
                    # same good only: a ranked listing must not be benchmarked
                    # against every rank in the book
                    best, n = best_of(l.slug, exclude=user, rank=l.rank,
                                      subtype=l.subtype)
                except core_market.MarketError:
                    # a FAILED fetch is not "nobody else is listing"; flag it
                    # so the card reads "market unknown", not "only listing"
                    job.step.emit((l.order_id, None, 0, True))
                    continue
                job.step.emit((l.order_id, best, n, False))
            return None

        self._sweep = work.run_stepped(body, self._market_landed,
                                       lambda _r: None, lambda _m: None)

    def _market_landed(self, payload) -> None:
        oid, best, n, failed = payload
        card = self.cards.get(oid)
        if card is None:
            return
        card.listing.market_low = best
        card.listing.online_count = n
        # market_known stays False on a failed fetch, so paint_market shows
        # the pending/unknown state rather than claiming "only listing"
        card.market_known = not failed
        card.market_failed = failed
        card.paint_market()

    # -- thumbnails ----------------------------------------------------------

    def _load_thumbs(self) -> None:
        wanted = {l.slug: l.thumb for l in self.listings
                  if l.thumb and l.slug not in self._thumbs}
        if not wanted:
            return

        def body(job):
            for slug, path in wanted.items():
                if job.cancelled:
                    return
                raw = self.client.fetch_thumb(path)
                if raw:
                    job.step.emit((slug, raw))
            return None

        self._jobs.append(work.run_stepped(body, self._thumb_landed,
                                           lambda _r: None, lambda _m: None))

    def _thumb_landed(self, payload) -> None:
        from PySide6.QtGui import QPixmap
        slug, raw = payload
        pm = QPixmap()
        if not pm.loadFromData(raw):
            return
        # Qt scales smoothly at any ratio; Tk could only zoom/subsample by
        # whole integers, which is why the old code approximated with a
        # Fraction limited to denominator 8
        pm = pm.scaled(ICON_PX, ICON_PX, Qt.KeepAspectRatio,
                       Qt.SmoothTransformation)
        self._thumbs[slug] = pm
        for card in self.cards.values():
            if card.listing.slug == slug:
                card.set_thumb(pm)

    # -- single-order operations ---------------------------------------------

    def _op(self, oid: str, fn, on_ok) -> None:
        """One order, one worker. `fn` runs off the UI thread and returns a
        message; `on_ok(card)` then runs on the UI thread.

        `on_ok` is handed the card RE-FETCHED at delivery time, not the one
        captured when the op started - a sort/filter/refresh in between can
        destroy the original widget, and touching it then is a use-after-free.
        The same staleness rule the file already applies to _card_result.
        """
        card = self.cards.get(oid)
        if card is None:
            return
        card.set_result("working…", "muted")
        self._set_busy(True)

        def ok(message):
            self._set_busy(False)
            fresh = self.cards.get(oid)
            if fresh is not None:
                on_ok(fresh)
            self._card_result(oid, message, "ok")

        def bad(msg):
            self._set_busy(False)
            self._card_result(oid, msg, "err")

        self._jobs.append(work.run(fn, ok, bad))

    def _sold(self, oid: str) -> None:
        card = self.cards.get(oid)
        if card is None:
            return
        l = card.listing
        verb = self.spec.done_verb.lower()
        if vm.closes_listing(l.quantity):
            if not self._confirm(f"Mark {l.name} {verb}?",
                                 "That was the last one, so the order will "
                                 "be closed."):
                return

            def fn():
                self.client.close_order(oid, 1)
                return f"{self.spec.done_verb} — order closed"
            self._op(oid, fn, lambda _c: self._drop(oid))
            return

        def fn():
            self.client.close_order(oid, 1)
            l.quantity -= 1
            return f"{self.spec.done_verb} — {l.quantity} left"
        self._op(oid, fn, lambda c: c.paint(self.limits))

    def _adjust_qty(self, oid: str, delta: int) -> None:
        card = self.cards.get(oid)
        if card is None:
            return
        l = card.listing
        new_q = vm.adjust_quantity(l.quantity, delta)
        if new_q is None:
            # zero is not a quantity - removing the last one is Delete, a
            # different and destructive action
            card.set_result("use Delete to remove the last one", "warn")
            return

        def fn():
            self.client.update_order(oid, l.platinum, new_q, l.visible)
            l.quantity = new_q
            return f"quantity {new_q}"
        self._op(oid, fn, lambda c: c.paint(self.limits))

    def _toggle_visible(self, oid: str) -> None:
        card = self.cards.get(oid)
        if card is None:
            return
        l = card.listing
        want = not l.visible

        def fn():
            self.client.update_order(oid, l.platinum, l.quantity, want)
            l.visible = want
            return "visible" if want else "hidden"

        def after(c):
            c.paint(self.limits)
            self.apply_view()       # the Show filter may now exclude it
        self._op(oid, fn, after)

    def _delete(self, oid: str) -> None:
        card = self.cards.get(oid)
        if card is None:
            return
        if not self._confirm(f"Delete {card.listing.name}?",
                             "This removes the order from warframe.market."):
            return
        self._op(oid, lambda: (self.client.delete_order(oid), "deleted")[1],
                 lambda _c: self._drop(oid))

    def _edit(self, oid: str) -> None:
        card = self.cards.get(oid)
        if card is not None:
            # deleteLater after exec: the dialog has the window as its C++
            # parent, so PySide hands ownership to C++ and it would otherwise
            # linger as a hidden child until app exit - one per order edited.
            dlg = EditListingDialog(self, card)
            dlg.exec()
            dlg.deleteLater()

    def _drop(self, oid: str) -> None:
        """An order that no longer exists. Removing it from the model and
        re-applying the view is enough - `set_listings` reconciles cards."""
        self.listings = [l for l in self.listings if l.order_id != oid]
        card = self.cards.pop(oid, None)
        if card is not None:
            card.setParent(None)
            card.deleteLater()
        self.apply_view()

    def _confirm(self, title: str, body: str) -> bool:
        return QMessageBox.question(
            self, title, body,
            QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes

    # -- bulk operations -----------------------------------------------------

    def _bulk_visibility(self, visible: bool) -> None:
        targets = vm.needs_visibility(self.listings, visible)
        if not targets:
            # nothing to do is a distinct outcome from a failure, and saying
            # so is better than a silent no-op
            self.set_status(
                f"every order is already {'visible' if visible else 'hidden'}.")
            return
        word = "Show" if visible else "Hide"
        if not self._confirm(f"{word} all {len(targets)} orders?",
                             "This writes one change per order."):
            return
        self._set_busy(True, f"{word}ing {len(targets)} orders…")

        def body(job):
            done = 0
            for l in targets:
                if job.cancelled:
                    return done
                try:
                    self.client.update_order(l.order_id, l.platinum,
                                             l.quantity, visible)
                except core_market.MarketError:
                    continue
                l.visible = visible
                done += 1
                job.step.emit((l.order_id, done))
            return done

        def each(payload):
            oid, done = payload
            card = self.cards.get(oid)
            if card is not None:
                card.paint(self.limits)
            self.status.setText(f"{word}ing… {done}/{len(targets)}")

        def finished(done):
            self._set_busy(False, f"{word} all: {done} updated.")
            self.apply_view()

        self._jobs.append(work.run_stepped(body, each, finished,
                                           self.set_failed))

    def _reprice_one(self, oid: str) -> None:
        card = self.cards.get(oid)
        if card is None:
            return
        self._commit_limit(oid)                 # honour a just-typed limit
        l = card.listing
        limit = self.limits.limit(vm.limit_key(l), oid, l.platinum)

        def fn():
            res = core_repricer.reprice(l, self.client, self.view.username,
                                        self.side, limit)
            if not res.ok:
                raise core_market.MarketError(res.message)
            l.market_low, l.online_count = res.best, res.online
            return res.message

        def after(c):
            c.market_known = True     # a reprice read the book as well
            c.market_failed = False
            c.paint(self.limits)
        self._op(oid, fn, after)

    def _reprice_all(self) -> None:
        rows = list(self.listings)
        if not rows:
            self.set_status("nothing to reprice.")
            return
        if not self._confirm(f"Reprice all {len(rows)} orders?",
                             "Each is matched to the best live price and "
                             "clamped to its limit."):
            return
        for oid in list(self.cards):
            self._commit_limit(oid)
        # The background sweep (start_sweep) also writes l.market_low/online_count
        # and repaints every card. If it keeps running, a stale sweep value can
        # land on top of a fresh reprice result (last write wins, nondeterministic
        # "beaten" flag). Cancel it so reprice-all is the sole writer - the same
        # "one sweep at a time" guarantee start_sweep already makes for itself.
        if self._sweep is not None:
            self._sweep.cancel()
            self._sweep = None
        limits = {l.order_id: self.limits.limit(
            vm.limit_key(l), l.order_id, l.platinum) for l in rows}
        self._set_busy(True, f"Repricing all… 0/{len(rows)}")
        username = self.view.username

        def body(job):
            for i, l in enumerate(rows, 1):
                if job.cancelled:
                    return i
                res = core_repricer.reprice(l, self.client, username,
                                            self.side, limits[l.order_id])
                if res.ok:
                    l.market_low, l.online_count = res.best, res.online
                job.step.emit((l.order_id, res.message, "ok" if res.ok
                               else "err", i))
            return len(rows)

        def each(payload):
            oid, message, role, i = payload
            self._card_result(oid, message, role)
            card = self.cards.get(oid)
            if card is not None:
                card.market_known = role == "ok"
                card.market_failed = role != "ok"
                card.paint(self.limits)
            self.status.setText(f"Repricing all… {i}/{len(rows)}")

        self._jobs.append(work.run_stepped(
            body, each, lambda _n: self._set_busy(False, "Reprice all done."),
            self.set_failed))


class CenteredNotice(QWidget):
    """A centred card with a title and one line of copy - the placeholder look,
    reused for the Contracts tab AND the WTS/WTB empty states (which show this
    instead of a line of text when a side has no orders)."""

    def __init__(self, title: str, message: str) -> None:
        super().__init__()
        self.setAttribute(Qt.WA_StyledBackground, True)
        lay = QVBoxLayout(self)
        lay.addStretch(1)
        box = panel("card")
        bl = QVBoxLayout(box)
        bl.setContentsMargins(t.SP_XL, t.SP_XL, t.SP_XL, t.SP_XL)
        self._title = label(title, role="h2")
        self._title.setAlignment(Qt.AlignCenter)
        bl.addWidget(self._title)
        self._blurb = label(message, role="small")
        self._blurb.setAlignment(Qt.AlignCenter)
        bl.addWidget(self._blurb)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(box)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addStretch(2)

    def set_text(self, title: str, message: str) -> None:
        self._title.setText(title)
        self._blurb.setText(message)


# (title, message) for the empty-state notice, by side and by filter reason.
EMPTY_NOTICE = {
    "sell": ("Sell Orders", "Nothing posted for sale yet."),
    "buy": ("Buy Orders", "No buy orders posted yet."),
}
FILTER_NOTICE = {
    "Hidden": ("No Hidden Items", "Nothing is hidden on this side."),
    "Visible": ("No Visible Items", "Nothing is visible on this side."),
}


class ContractCard(QFrame):
    """One of the user's own riven/lich auctions, drawn as a half-page tile
    (the tab lays them CARD_COLUMNS abreast, like WTS): the weapon picture
    top-left with the two-tone title, the price and the polarity/element
    stacked under it, the rolled stats anchored to the top-right - jade for a
    gain, coral for a loss - and the three controls (wiki, visibility, remove)
    along the bottom edge, anchored right.

    The card is a dumb view over `row`: the owning tab runs the actual API
    writes and re-fetches afterwards, so no state ever lives here."""

    wiki = Signal(str)
    edit = Signal(str)
    visibility = Signal(str)
    remove = Signal(str)

    def __init__(self, row: dict) -> None:
        super().__init__()
        self.row = row
        self.aid = row.get("id", "")
        self.slug = row.get("weapon_slug", "")
        self.setProperty("surface", "listing")
        self.setAttribute(Qt.WA_StyledBackground, True)
        kind = row.get("kind", "riven")
        weapon = row.get("weapon", "")
        visible = bool(row.get("visible", True))
        # `surface="listing"` alone paints nothing (qss.py carries no rule for
        # it - the WTS card draws its own edge in set_hit). State the card's
        # fill and border here the same way, or it reads as a naked layout.
        self.setStyleSheet(f"QFrame[surface=\"listing\"] {{"
                           f" background: {t.WFM_CARD};"
                           f" border: 1px solid {t.WFM_EDGE}; }}")
        # Half a page must MEAN half a page. A non-wrapping QLabel reports its
        # whole text as minimum width, so one long stat line would inflate
        # this card's minimum past its grid column - and with the horizontal
        # scrollbar off, the neighbour card gets squeezed under ITS minimum
        # and everything it anchors right (stats, controls) clips off its
        # edge. Ignored hands the width decision to the tab's equal column
        # stretches instead.
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

        grid = QGridLayout(self)
        grid.setContentsMargins(t.SP_LG, t.SP_LG, t.SP_LG, t.SP_LG)
        grid.setHorizontalSpacing(t.SP_LG)
        grid.setVerticalSpacing(t.SP_MD)
        grid.setColumnStretch(1, 1)     # the description owns the right half
        grid.setRowStretch(2, 1)        # spare height sits above the bottom row

        # -- top region: the picture on the left, the description beside it.
        #    Only the 96px picture shares a row with the stats, so the two
        #    never fight for width; the title, price and polarity each get
        #    the card's full width on their own rows below.
        self.icon = _placeholder_icon("◈")
        grid.addWidget(self.icon, 0, 0, Qt.AlignLeft | Qt.AlignTop)

        # title: kind badge · weapon (teal) · riven name (gold) · rank ·
        # hidden tag
        title = QHBoxLayout()
        title.setSpacing(t.SP_SM)
        # same bold, uppercase, larger badge as the WTS/WTB cards (role="badge");
        # kept naturally sized here (padded), since the contract card keeps its
        # own bottom-row button layout rather than the WTS grid
        badge = label(kind.upper(), role="badge")
        badge.setStyleSheet(f"background: {t.WFM_BADGE_BG};"
                            f"color: {t.WFM_BADGE_FG}; padding: 1px 5px;")
        title.addWidget(badge, 0, Qt.AlignVCenter)
        name = label(weapon, role="h2")
        name.setStyleSheet(f"color: {t.WFM_TEAL};")
        title.addWidget(name)
        # the riven's random name ("acri-igniata") rides beside the weapon in
        # gold - the AlecaFrame two-tone title. Liches carry no such name.
        if row.get("name"):
            suffix = label(row["name"], role="h2")
            suffix.setStyleSheet(f"color: {t.ACCENT};")
            title.addWidget(suffix)
        rank_txt = market_vm.rank_text(row)
        if rank_txt:
            # h2 (the title face) so the rank matches the weapon-name size, pink
            rk = label(rank_txt, role="h2")
            rk.setStyleSheet(f"color: {t.WFM_PINK};")
            rk.setToolTip("mod rank")
            title.addWidget(rk, 0, Qt.AlignVCenter)
        if not visible:
            tag = label("hidden", role="small")
            tag.setStyleSheet(f"color: {t.WARN};")
            tag.setToolTip("hidden on warframe.market")
            title.addWidget(tag, 0, Qt.AlignVCenter)
        title.addStretch(1)
        grid.addLayout(title, 1, 0, 1, 2)

        # -- the bottom row, one shared plane: price and polarity/element on
        #    the left, the three controls anchored right. Vertically CENTRED
        #    (matching the WTS card's info line), so the caption, figure, gem
        #    and polarity share one centre line rather than each on its own.
        info = QHBoxLayout()
        info.setSpacing(t.SP_SM)
        mid = Qt.AlignVCenter
        buyout = row.get("buyout")
        price = buyout if buyout is not None else row.get("starting")
        info.addWidget(label("buyout" if buyout is not None else "start",
                             role="small"), 0, mid)
        info.addWidget(label("—" if price is None else str(price),
                             role="price"), 0, mid)
        info.addWidget(plat_label(), 0, mid)
        sub = row.get("polarity") if kind == "riven" else row.get("element")
        self.pol_icon = None
        if sub:
            dot = label("·", role="small")
            dot.setStyleSheet(f"color: {t.WFM_EDGE};")
            info.addWidget(dot, 0, mid)
            sub_lbl = label(str(sub).title(), role="small")
            sub_lbl.setStyleSheet(f"color: {t.WFM_MUTED};")
            info.addWidget(sub_lbl, 0, mid)
            # the polarity's wiki symbol, in the same muted ink as its name;
            # an element (a lich) has no symbol and gets no label at all
            pol = polarity_icon(str(sub), color=t.WFM_MUTED)
            if pol is not None:
                self.pol_icon = QLabel()
                self.pol_icon.setPixmap(pol)
                self.pol_icon.setStyleSheet("background: transparent;")
                info.addWidget(self.pol_icon, 0, mid)
        info.addStretch(1)

        # -- the description, anchored to the card's top-right
        mid = QVBoxLayout()
        mid.setSpacing(t.SP_SM)
        lines = market_vm.contract_stat_lines(kind, row)
        for ln in lines:
            stat = label(ln["text"], role="h2")
            stat.setAlignment(Qt.AlignRight)
            stat.setStyleSheet(f"color: {t.OK if ln['positive'] else t.ERR};")
            mid.addWidget(stat)
        if not lines:
            blank = label("no rolled stats", role="small")
            blank.setAlignment(Qt.AlignRight)
            blank.setStyleSheet(f"color: {t.WFM_MUTED};")
            mid.addWidget(blank)
        mid.addStretch(1)
        grid.addLayout(mid, 0, 1)

        # the three controls share the bottom row, anchored right; each wears
        # the same 1px edge the WTS action buttons carry, so they read as
        # controls against the card's own border
        self.wiki_btn = QPushButton(
            glyph_icon(t.WIKI_ICON, color=t.WFM_MUTED), "")
        self.wiki_btn.setStyleSheet(_flat_style(t.WFM_MUTED))
        self.wiki_btn.setFixedWidth(28)
        self.wiki_btn.setCursor(Qt.PointingHandCursor)
        self.wiki_btn.setToolTip(f"open {weapon} on the wiki")
        self.wiki_btn.clicked.connect(lambda: self.wiki.emit(weapon))
        info.addWidget(self.wiki_btn)
        self.edit_btn = QPushButton(glyph_icon("edit", color=t.WFM_TEAL), "")
        self.edit_btn.setStyleSheet(_flat_style(t.WFM_TEAL))
        self.edit_btn.setFixedWidth(28)
        self.edit_btn.setCursor(Qt.PointingHandCursor)
        self.edit_btn.setToolTip("edit rank, price and visibility")
        self.edit_btn.clicked.connect(lambda: self.edit.emit(self.aid))
        info.addWidget(self.edit_btn)
        vis_colour = t.TEXT if visible else t.WARN
        self.vis_btn = QPushButton(
            glyph_icon("visible" if visible else "hidden", color=vis_colour),
            "")
        self.vis_btn.setStyleSheet(_flat_style(vis_colour))
        self.vis_btn.setFixedWidth(28)
        self.vis_btn.setCursor(Qt.PointingHandCursor)
        self.vis_btn.setToolTip("show or hide this contract")
        self.vis_btn.clicked.connect(lambda: self.visibility.emit(self.aid))
        info.addWidget(self.vis_btn)
        self.rm_btn = QPushButton(glyph_icon("delete", color=t.WFM_RED), "")
        self.rm_btn.setStyleSheet(_flat_style(t.WFM_RED))
        self.rm_btn.setFixedWidth(28)
        self.rm_btn.setCursor(Qt.PointingHandCursor)
        self.rm_btn.setToolTip("remove this contract")
        self.rm_btn.clicked.connect(lambda: self.remove.emit(self.aid))
        info.addWidget(self.rm_btn)
        grid.addLayout(info, 3, 0, 1, 2)

    def set_thumb(self, pixmap) -> None:
        self.icon.setStyleSheet(f"background: {t.ICON_BG};"
                                f"border: 1px solid {t.WFM_EDGE};")
        self.icon.setPixmap(pixmap)


class EditContractDialog(QDialog):
    """Rank, price and visibility for one contract.

    Two very different writes hide behind one Save. Visibility alone is a
    real update (the PUT the site's own eye toggle uses). Price or rank
    cannot be updated at all - the API 403s a PUT that tries, on a session
    every other action accepts - so those go through relist_auction: the
    same close-and-relist the site forces on its own users, wearing a
    dialog. The price field edits whichever figure the card shows: the
    buyout when the auction has one, the opening bid otherwise; lowering a
    buyout under the current opening bid drags the opening bid down with
    it, since a start above the buyout is not a state an auction can be
    in."""

    def __init__(self, tab, card: ContractCard) -> None:
        super().__init__(tab.window())
        self.tab, self.card = tab, card
        row = card.row
        self.setWindowTitle(f"Edit — {row.get('weapon', 'contract')}")
        self.setModal(True)
        self.setMinimumWidth(430)         # §9: dialogs carry a stable min width
        lay = QVBoxLayout(self)
        lay.setContentsMargins(t.SP_XL, t.SP_XL, t.SP_XL, t.SP_XL)
        lay.setSpacing(t.SP_MD)

        head = QHBoxLayout()
        b = label(row.get("kind", "riven"), role="small")
        b.setStyleSheet(f"background: {t.WFM_BADGE_BG};"
                        f"color: {t.WFM_BADGE_FG}; padding: 1px 4px;")
        head.addWidget(b, 0, Qt.AlignVCenter)
        nm = label(row.get("weapon", ""), role="h2")
        nm.setStyleSheet(f"color: {t.WFM_TEAL};")
        head.addWidget(nm)
        if row.get("name"):
            sx = label(row["name"], role="h2")
            sx.setStyleSheet(f"color: {t.ACCENT};")
            head.addWidget(sx)
        head.addStretch(1)
        lay.addLayout(head)
        lay.addWidget(hairline())

        self._has_buyout = row.get("buyout") is not None
        shown = row["buyout"] if self._has_buyout else row.get("starting")
        lay.addWidget(label(
            f"{'Buyout' if self._has_buyout else 'Starting'} price (platinum)",
            role="small"))
        self.price = QLineEdit("" if shown is None else str(shown))
        lay.addWidget(self.price)

        # rank: rivens only - a lich has no mod rank at all
        self.rank = None
        if row.get("kind") == "riven" and row.get("rank") is not None:
            lay.addWidget(label("Rank", role="small"))
            top = max(8, int(row["rank"]))     # riven mods cap at R-8
            self.rank = Dropdown([f"R-{i}" for i in range(top + 1)])
            self.rank.setCurrentText(f"R-{row['rank']}")
            lay.addWidget(self.rank)

        self.visible = QCheckBox("Visible on warframe.market")
        self.visible.setChecked(bool(row.get("visible", True)))
        lay.addWidget(self.visible)

        self.status = label("", role="small")
        lay.addWidget(self.status)
        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        btns.addWidget(cancel)
        self.save = QPushButton("Save")
        self.save.setProperty("kind", "money")
        self.save.setDefault(True)
        self.save.clicked.connect(self._save)
        btns.addWidget(self.save)
        lay.addLayout(btns)
        self._job = None

    def _chosen_rank(self) -> int | None:
        if self.rank is None:
            return None
        try:
            return int(self.rank.currentText().split("-", 1)[1])
        except (IndexError, ValueError):
            return None

    def _save(self) -> None:
        row = self.card.row
        try:
            price = max(1, int(self.price.text().strip()))
        except ValueError:
            self.status.setText("price must be a whole number")
            self.status.setStyleSheet(f"color: {t.ERR};")
            return
        was = row["buyout"] if self._has_buyout else row.get("starting")
        rank = self._chosen_rank()
        visible = self.visible.isChecked()
        price_changed = price != was
        rank_changed = rank is not None and rank != row.get("rank")
        visible_changed = visible != bool(row.get("visible", True))
        if not (price_changed or rank_changed or visible_changed):
            self.accept()          # nothing changed - nothing to send
            return
        self.save.setEnabled(False)
        client = self.tab.view.client
        aid = self.card.aid
        if price_changed or rank_changed:
            # price and rank cannot be edited in place - relist (see the
            # class docstring), carrying the visibility choice along
            self.status.setText("relisting…")
            if self._has_buyout:
                buyout = price
                starting = min(row.get("starting") or price, price)
            else:
                buyout, starting = row.get("buyout"), price
            self._job = work.run(
                lambda: client.relist_auction(
                    row, starting=starting, buyout=buyout,
                    mod_rank=rank if rank_changed else None,
                    visible=visible),
                self._done, self._failed)
        else:
            self.status.setText("saving…")
            self._job = work.run(
                lambda: client.set_auction_visibility(aid, visible),
                self._done, self._failed)
        self.status.setStyleSheet(f"color: {t.WFM_MUTED};")

    def _failed(self, msg: str) -> None:
        self.save.setEnabled(True)
        self.status.setText(msg)
        self.status.setStyleSheet(f"color: {t.ERR};")

    def _done(self, _result) -> None:
        # the server's word beats local bookkeeping: re-fetch, so whatever it
        # actually accepted is what the card shows
        self.tab.refresh()
        self.accept()


class MyContractsTab(QWidget):
    """The user's OWN riven/lich auctions - the My Listings Contracts tab.
    Read from their warframe.market profile (client.my_auctions), drawn as one
    ContractCard each, with the weapon pictures fetched through
    client.weapon_thumbs() (rivens aren't tradeable items, so /v2/items has no
    picture for them). The card's visibility and remove buttons run the v1
    auction writes and then re-fetch - the server's word beats local
    bookkeeping."""

    def __init__(self, view) -> None:
        super().__init__()
        self.view = view
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._jobs: list[work.Job] = []
        self._loaded = False
        self.cards: dict[str, ContractCard] = {}
        self._thumbs: dict[str, object] = {}     # slug -> QPixmap, kept warm

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, t.SP_LG, 0, 0)
        lay.setSpacing(t.SP_MD)
        self.status = label("", role="small")
        lay.addWidget(self.status)
        self.area = QScrollArea()
        self.area.setWidgetResizable(True)
        self.area.setFrameShape(QFrame.NoFrame)
        self.area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        lay.addWidget(self.area, 1)
        self.notice = CenteredNotice(
            "Contracts", "You have no riven or lich contracts.")
        self.notice.hide()
        lay.addWidget(self.notice, 1)
        self._render([])

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._loaded:
            self._loaded = True
            self.refresh()

    def refresh(self) -> None:
        if self.view.client is None:
            self._render([])
            return
        self.status.setText("loading your contracts…")
        self.status.setProperty("level", "")
        restyle(self.status)
        self._jobs.append(work.run(
            self.view.client.my_auctions, self._render, self._failed))

    def _failed(self, msg: str) -> None:
        self.status.setText(f"couldn't load contracts — {msg}")
        self.status.setProperty("level", "err")
        restyle(self.status)

    def _render(self, rows) -> None:
        empty = not rows
        self.area.setVisible(not empty)
        self.notice.setVisible(empty)
        self.status.setText(
            "" if empty else
            f"{len(rows)} contract{'s' if len(rows) != 1 else ''} listed")
        self.status.setProperty("level", "")
        restyle(self.status)
        self.cards = {}
        if empty:
            return
        body = panel()
        grid = QGridLayout(body)
        grid.setContentsMargins(0, 0, t.SP_LG, 0)    # right pad off the scrollbar
        grid.setHorizontalSpacing(t.SP_MD)
        grid.setVerticalSpacing(t.SP_MD)
        for i, r in enumerate(rows):
            card = ContractCard(r)
            card.wiki.connect(self.view.open_wiki)
            card.edit.connect(self._edit)
            card.visibility.connect(self._toggle_visibility)
            card.remove.connect(self._remove)
            thumb = self._thumbs.get(card.slug)
            if thumb is not None:
                card.set_thumb(thumb)
            self.cards[card.aid] = card
            grid.addWidget(card, i // CARD_COLUMNS, i % CARD_COLUMNS)
        # equal columns even when a row is short: a lone contract still gets
        # exactly half the page, not the whole of it
        for c in range(CARD_COLUMNS):
            grid.setColumnStretch(c, 1)
        grid.setRowStretch((len(rows) + CARD_COLUMNS - 1) // CARD_COLUMNS, 1)
        self.area.setWidget(body)
        self._load_thumbs()

    # -- pictures ------------------------------------------------------------

    def _load_thumbs(self) -> None:
        """Same shape as MyListingsTab._load_thumbs, but the slug -> path map
        comes from weapon_thumbs() (fetched lazily, off the UI thread, on the
        first card that needs it) instead of riding in on the order rows."""
        client = self.view.client
        wanted = {c.slug for c in self.cards.values()
                  if c.slug and c.slug not in self._thumbs}
        if client is None or not wanted:
            return

        def body(job):
            paths = client.weapon_thumbs()
            for slug in wanted:
                if job.cancelled:
                    return
                raw = client.fetch_thumb(paths.get(slug, ""))
                if raw:
                    job.step.emit((slug, raw))
            return None

        self._jobs.append(work.run_stepped(body, self._thumb_landed,
                                           lambda _r: None, lambda _m: None))

    def _thumb_landed(self, payload) -> None:
        from PySide6.QtGui import QPixmap
        slug, raw = payload
        pm = QPixmap()
        if not pm.loadFromData(raw):
            return
        pm = pm.scaled(ICON_PX, ICON_PX, Qt.KeepAspectRatio,
                       Qt.SmoothTransformation)
        self._thumbs[slug] = pm
        for card in self.cards.values():
            if card.slug == slug:
                card.set_thumb(pm)

    # -- contract operations -------------------------------------------------

    def _confirm(self, title: str, body: str) -> bool:
        return QMessageBox.question(
            self, title, body,
            QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes

    def _op(self, card: ContractCard, verb: str, fn) -> None:
        """One write, one worker, then a full re-fetch. The card is disabled
        rather than tracked: _render replaces every card anyway, and on error
        _op_failed re-enables the lot."""
        card.setEnabled(False)
        self.status.setText(f"{verb}…")
        self.status.setProperty("level", "")
        restyle(self.status)
        self._jobs.append(work.run(fn, self._op_done, self._op_failed))

    def _edit(self, aid: str) -> None:
        card = self.cards.get(aid)
        if card is None or self.view.client is None:
            return
        # deleteLater after exec: same ownership note as the WTS edit dialog -
        # the C++ parent is the window, so without this every edited contract
        # would leave a hidden dialog behind until app exit
        dlg = EditContractDialog(self, card)
        dlg.exec()
        dlg.deleteLater()

    def _toggle_visibility(self, aid: str) -> None:
        card = self.cards.get(aid)
        client = self.view.client
        if card is None or client is None:
            return
        want = not card.row.get("visible", True)
        self._op(card, "updating",
                 lambda: client.set_auction_visibility(aid, want))

    def _remove(self, aid: str) -> None:
        card = self.cards.get(aid)
        client = self.view.client
        if card is None or client is None:
            return
        if not self._confirm(
                f"Remove {card.row.get('weapon', 'this')} contract?",
                "This closes the auction on warframe.market."):
            return
        self._op(card, "removing", lambda: client.close_auction(aid))

    def _op_done(self, _result) -> None:
        self.refresh()

    def _op_failed(self, msg: str) -> None:
        for card in self.cards.values():
            card.setEnabled(True)
        self._failed(msg)


class ListingsView(QWidget):
    """Header, the three tabs, and the one fetch that feeds both sides."""

    TAB_NAMES = ("WTS", "WTB", "Contracts")

    def __init__(self, client, session, baseline: dict,
                 open_wiki=lambda _n: None) -> None:
        super().__init__()
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.client = client
        self.username = session.username if session else ""
        self.baseline = baseline
        self.open_wiki = open_wiki
        self.prefs = core_market.load_prefs()
        self._busy = False
        self._jobs: list[work.Job] = []
        self._loaded = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        head = QHBoxLayout()
        head.setContentsMargins(t.SP_SCREEN, t.SP_LG, t.SP_SCREEN, t.SP_LG)
        head.addWidget(label("My Warframe.Market Listings", role="h1"), 0,
                       Qt.AlignVCenter)
        head.addStretch(1)
        # Caption, figure and gem are three different type sizes, so
        # centring each one independently leaves them stepped. They go in one
        # row aligned to a common BOTTOM edge instead, which is the closest a
        # Qt box layout gets to a shared baseline.
        ledger_row = QHBoxLayout()
        ledger_row.setContentsMargins(0, 0, 0, 0)
        ledger_row.setSpacing(t.SP_SM)
        ledger_row.setAlignment(Qt.AlignBottom)
        # order count, before the ledger caption and in the same muted style
        self.order_count = label("", role="muted")
        self.order_count.setToolTip("sell orders listed")
        ledger_row.addWidget(self.order_count, 0, Qt.AlignBottom)
        self.ledger_caption = label("Potential Sales TTL:", role="muted")
        self.ledger_caption.setToolTip(
            "every sell order at its asking price, times quantity")
        ledger_row.addWidget(self.ledger_caption, 0, Qt.AlignBottom)
        self.ledger = label("", role="h2")
        self.ledger.setStyleSheet(f"color: {t.PLAT};")
        self.ledger.setToolTip("total platinum listed across your sell orders")
        ledger_row.addWidget(self.ledger, 0, Qt.AlignBottom)
        self.ledger_gem = QLabel()
        self.ledger_gem.setPixmap(plat_icon(14))
        self.ledger_gem.setStyleSheet("background: transparent;")
        self.ledger_gem.hide()
        # Lift it off the box bottom by the figure's DESCENT. Aligning the
        # boxes lines up their bottoms, but a text box's bottom is below its
        # baseline - the room where a 'g' or a 'y' would hang - so the gem
        # ended up floating under the digits. Qt box layouts have no baseline
        # alignment, and the descent is exactly the difference.
        drop = QFontMetrics(QFont(
            t.resolve_family("h2", set(QFontDatabase.families())),
            t.size_of("h2"))).descent()
        self.ledger_gem.setContentsMargins(0, 0, 0, drop)
        ledger_row.addWidget(self.ledger_gem, 0, Qt.AlignBottom)
        # wrap the group so it can be vertically CENTRED in the header, aligned
        # with the Refresh button (the caption/figure/gem keep their shared
        # bottom baseline inside it)
        ledger_box = QWidget()
        ledger_box.setLayout(ledger_row)
        head.addWidget(ledger_box, 0, Qt.AlignVCenter)
        head.addSpacing(t.SP_LG)
        self.refresh_btn = QPushButton(" Refresh Listings")
        self.refresh_btn.setIcon(glyph_icon("refresh", color=t.TEXT))
        self.refresh_btn.setProperty("size", "small")
        self.refresh_btn.setCursor(Qt.PointingHandCursor)
        self.refresh_btn.clicked.connect(self.refresh)
        head.addWidget(self.refresh_btn, 0, Qt.AlignVCenter)
        lay.addLayout(head)

        # The tabs and everything below them live inside the app's bordered
        # container (the surface="card" box Home and Settings use), inset from
        # the screen like every other container.
        box = panel("card")
        boxlay = QVBoxLayout(box)
        # thin frame; a SMALL bottom pad keeps the cards from eclipsing the gold
        # border while still letting them run close to it (revealed from behind
        # it as they scroll)
        boxlay.setContentsMargins(t.SP_LG, t.SP_LG, t.SP_LG, t.SP_SM)
        boxlay.setSpacing(0)

        bar = QHBoxLayout()
        bar.setContentsMargins(0, 0, 0, 0)
        bar.setSpacing(0)
        self.tab_btns = {}
        for name in self.TAB_NAMES:
            b = QPushButton(name)
            b.setProperty("kind", "flat")
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _c=False, n=name: self.select(n))
            self.tab_btns[name] = b
            bar.addWidget(b, 1)
        boxlay.addLayout(bar)
        boxlay.addWidget(hairline())

        self.stack = QStackedWidget()
        self.stack.setProperty("surface", "tab")
        self.tabs = {"WTS": ListingsTab(self, "sell"),
                     "WTB": ListingsTab(self, "buy"),
                     "Contracts": MyContractsTab(self)}
        for name in self.TAB_NAMES:
            self.stack.addWidget(self.tabs[name])
        boxlay.addWidget(self.stack, 1)

        holder = QHBoxLayout()
        holder.setContentsMargins(t.SP_SCREEN, 0, t.SP_SCREEN, t.SP_XL)
        holder.addWidget(box)
        lay.addLayout(holder, 1)

        self.current = ""
        self.select("WTS")

    def select(self, name: str) -> None:
        if name == self.current:
            return
        for tab in self.tabs.values():
            if hasattr(tab, "suggest"):
                tab.suggest.hide()
        self.current = name
        self.stack.setCurrentWidget(self.tabs[name])
        for k, b in self.tab_btns.items():
            active = k == name
            b.setStyleSheet(
                f"color: {t.TEXT if active else t.MUTED};"
                f"border-bottom: 2px solid "
                f"{TAB_ACCENTS[k] if active else t.HAIRLINE};"
                f"background: {t.TAB_BG if active else t.PANEL};"
                "padding: 6px 18px;")

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._loaded:
            self._loaded = True
            self.refresh()

    # -- the one fetch -------------------------------------------------------

    def refresh(self) -> None:
        if self._busy:
            return
        if self.client is None:
            self.tabs["WTS"].set_failed("no account linked")
            return
        self._busy = True
        self.refresh_btn.setEnabled(False)
        for name in ("WTS", "WTB"):
            self.tabs[name].set_status("loading your orders…")
        self._jobs.append(work.run(self.client.my_listings, self._loaded_ok,
                                   self._failed))
        # contracts are a separate fetch (my_auctions, not my_listings) with its
        # own status, so refresh it alongside rather than folding it into _done
        self.tabs["Contracts"].refresh()

    def _loaded_ok(self, orders: dict) -> None:
        self._done()
        for name, side in (("WTS", "sell"), ("WTB", "buy")):
            tab = self.tabs[name]
            tab.set_listings(orders[side])
            tab.set_status("")
            tab.start_sweep()
        self._set_ledger(len(orders["sell"]), vm.ledger_total(orders["sell"]))

    def _failed(self, msg: str) -> None:
        self._done()
        for name in ("WTS", "WTB"):
            self.tabs[name].set_failed(msg)

    def _done(self) -> None:
        self._busy = False
        self.refresh_btn.setEnabled(True)

    def _set_ledger(self, count: int, total: int) -> None:
        word = "Sell Order" if count == 1 else "Sell Orders"
        self.order_count.setText(f"{count} {word}  ·")
        self.ledger.setText(f"{total:,}")
        self.ledger_gem.setVisible(True)
