"""The warframe.market browser: order book, contracts, watchlist.

Every string, filter and severity comes from core.market_vm. Severity arrives
as a ROLE ("ingame", "ok", "muted", "accent"); ROLE_COLOR below is the only
place this front end turns one into a colour.

Threading note: each tab does its fetching on a worker thread and hands the
result back over a Qt signal. That replaces Tk's `self.after(0, lambda: ...)`
plus a `winfo_exists()` guard at every call site - Qt queues cross-thread
emits and drops them for deleted receivers. The one guard still needed is the
STALENESS check (did the user search for something else while this was in
flight?), which is about data, not widget lifetime.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QCheckBox, QDialog, QFrame, QHBoxLayout,
                               QLineEdit, QPushButton, QScrollArea,
                               QStackedWidget, QVBoxLayout, QWidget)

from core import wf_inventory
from core import market as core_market
from core import market_vm as vm
from core import theme as t
from ui.suggest import SuggestBox
from ui.work import run
from ui.widgets import (Dropdown, alive, glyph_icon, hairline, label, panel,
                        plat_label, restyle)

ROLE_COLOR = {"ingame": t.WFM_TEAL, "ok": t.OK, "muted": t.MUTED,
              "err": t.ERR, "accent": t.ACCENT, "warn": t.WARN,
              "rep_up": t.REP_UP, "rep_down": t.REP_DOWN}

ROWS = 12          # contracts page size (the order book shows them all)
TABLE_ROWS = 12    # rows of height a table reserves before it has data
ROW_HEIGHT = t.TABLE_ROW_H
COL_QTY, COL_RANK, COL_PLAT = 46, 40, 46
ANY_RANK = "any"
RANK_WIDTH = 90     # fixed, so showing it costs the search box a known
                    # amount rather than a text-dependent one
TAB_ACCENTS = {"market": t.WFM_TEAL, "contracts": t.WFM_PINK,
               "watchlist": t.ACCENT}


def _track(jobs: set, job):
    """Park a Job in `jobs` until its outcome is delivered, then release it.

    The set keeps the Job alive across the gap between the worker emitting and
    the GUI thread delivering (a Job with no reference is GC'd and its queued
    signal dropped). Removing it on done/failed - which fire AFTER delivery, on
    the GUI thread - stops the set from growing without bound: WatchlistTab
    re-fetches every watched slug on every visit, so a plain append leaked a
    Job per row per visit for the life of the view."""
    jobs.add(job)
    job.done.connect(lambda *_: jobs.discard(job))
    job.failed.connect(lambda *_: jobs.discard(job))
    return job


def _row_panel(index: int) -> QWidget:
    """A card row, zebra-striped for readability."""
    w = panel()
    w.setStyleSheet("background: %s;" %
                    (t.WFM_CARD if index % 2 == 0 else t.ROW_ALT))
    return w


class StatusFilters(QWidget):
    """The Online / In-game checkboxes plus a colour key for the status dots.

    The dots in the tables are the only thing distinguishing an in-game
    trader from a merely-online one, and a colour with no legend is folklore -
    so the key sits right beside the controls that act on it. Shared by the
    Market and Contracts tabs so the two cannot drift.
    """

    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setAttribute(Qt.WA_StyledBackground, True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(t.SP_SM)

        self.online = QCheckBox("Online only")
        self.ingame = QCheckBox("In-game only")
        # Both on by default. They compose rather than conflict - in-game
        # NARROWS online - so the default is in-game only and unticking
        # widens the view a step at a time.
        self.online.setChecked(True)
        self.ingame.setChecked(True)
        for box in (self.online, self.ingame):
            box.toggled.connect(self.changed)

        lay.addWidget(self.online)
        lay.addWidget(self.ingame)
        lay.addSpacing(t.SP_MD)
        for role, text in vm.STATUS_KEY:
            dot = label("●", role="small")
            dot.setStyleSheet(f"color: {ROLE_COLOR[role]};")
            dot.setToolTip(f"{text} traders")
            lay.addWidget(dot)
            cap = label(text, role="small")
            cap.setToolTip(f"{text} traders")
            lay.addWidget(cap)
            lay.addSpacing(t.SP_SM)

    def scope(self):
        return vm.scope_filter(self.ingame.isChecked(), self.online.isChecked())


class MarketTab(QWidget):
    """The order book for one item."""

    def __init__(self, view) -> None:
        super().__init__()
        self.view = view
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.slug = self.name = ""
        self._book = None
        self._index = []
        self._jobs = set()
        # ONE owned single-shot timer for the transient flash line. Owned by the
        # tab, so it dies with it (no fire-after-death); and RESTARTING the same
        # timer means a newer message resets the countdown instead of an older
        # timer blanking a fresh message 0.5s after it appears.
        self._flash_timer = QTimer(self)
        self._flash_timer.setSingleShot(True)
        self._flash_timer.timeout.connect(self._clear_flash)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(*t.TOP_GAP_MARGINS)
        lay.setSpacing(t.SP_LG)

        # Row 1: the search box, with the rank picker beside it - rank is a
        # property OF the search, so it belongs next to the query, not down
        # among the view filters. Row 2 carries the filters, key and buttons.
        top = QHBoxLayout()
        top.setSpacing(t.SP_MD)
        top.addWidget(label("Search", role="muted"))
        self.search = QLineEdit()
        self.search.setMinimumWidth(280)
        top.addWidget(self.search, 1)
        # Rank picker: built from the ranks actually VISIBLE, so it never
        # offers a choice that yields an empty table. Hidden entirely for
        # goods that do not rank.
        self.rank_lbl = label("Rank", role="muted")
        self.rank_pick = Dropdown([ANY_RANK])
        self.rank_pick.setToolTip("filter by mod / arcane rank")
        self.rank_pick.setFixedWidth(RANK_WIDTH)
        self.rank_pick.currentTextChanged.connect(self._rerender)
        self._ranked = False
        self.rank_pick.setEnabled(False)
        self.rank_lbl.setEnabled(False)
        top.addWidget(self.rank_lbl)
        top.addWidget(self.rank_pick)
        lay.addLayout(top)
        self.suggest = SuggestBox(self.search, self._supply, self._picked)
        self.search.textChanged.connect(self._paint_query)

        ctl = QHBoxLayout()
        ctl.setSpacing(t.SP_MD)
        self.filters = StatusFilters()
        self.filters.changed.connect(self._rerender)
        self.online, self.ingame = self.filters.online, self.filters.ingame
        ctl.addWidget(self.filters)
        # Transient feedback (errors, "whisper copied"). It lives HERE rather
        # than beside the search box because it grows and shrinks with its
        # text: on row 1 every message shoved the search field narrower. In
        # front of the stretch it eats slack instead of a neighbour.
        self.flash = label("", role="small")
        ctl.addWidget(self.flash)
        ctl.addStretch(1)
        self.refresh_btn = QPushButton(" Refresh")
        self.refresh_btn.setIcon(glyph_icon("refresh", color=t.TEXT))
        self.refresh_btn.setProperty("size", "small")
        self.refresh_btn.clicked.connect(self.refresh)
        ctl.addWidget(self.refresh_btn)
        # the glyph is an ICON, not text - see widgets.glyph_icon for why.
        # TEXT rather than the default MUTED, so the mark and the word beside
        # it read as one label rather than as two different greys
        self.wiki_btn = QPushButton(glyph_icon(t.WIKI_ICON, color=t.TEXT),
                                    " Wiki")
        self.wiki_btn.setProperty("size", "small")
        self.wiki_btn.setEnabled(False)
        self.wiki_btn.setToolTip("open this item on the wiki")
        self.wiki_btn.clicked.connect(self._open_wiki)
        ctl.addWidget(self.wiki_btn)
        self.watch_btn = QPushButton(" Watch")
        self.watch_btn.setProperty("size", "small")
        self.watch_btn.setEnabled(False)
        self.watch_btn.clicked.connect(self._toggle_watch)
        ctl.addWidget(self.watch_btn)
        lay.addLayout(ctl)


        # Each side gets its OWN scroll area, so a long seller list does not
        # drag the buyer column down with it and each can be read at its own
        # pace. The count lives in the column header, next to the list it
        # counts, rather than in a shared line below both.
        cols = QHBoxLayout()
        cols.setSpacing(t.SP_LG)
        self.cols = {}
        self.counts = {}
        self._headings = {}
        self.actions = {}
        self.inv_label = None            # WTS-only "Inventory: #" owned count
        for side, heading, colour in (("sell", "WTS — sellers",
                                       t.WFM_BADGE_FG),
                                      ("buy", "WTB — buyers", t.WFM_BUY_FG)):
            card = panel("card")
            cl = QVBoxLayout(card)
            cl.setContentsMargins(t.SP_LG, t.SP_MD, t.SP_LG, t.SP_MD)
            cl.setSpacing(t.SP_SM)

            # the count rides in the heading, in parentheses
            top = QHBoxLayout()
            head = label(heading, role="h2")
            head.setStyleSheet(f"color: {colour};")
            self.counts[side] = head
            self._headings[side] = heading
            top.addWidget(head)
            top.addStretch(1)
            # WTS only: how many of the searched item you own, left of the +
            # button, so you can see at a glance whether you have any to sell
            if side == "sell":
                self.inv_label = label("", role="small")
                self.inv_label.setToolTip(
                    "how many of this item you own (from AlecaFrame)")
                top.addWidget(self.inv_label, 0, Qt.AlignVCenter)
                top.addSpacing(t.SP_MD)
            # The + button posts YOUR OWN order on this side (WTS -> Sell), so
            # the label is the own action. Colour follows the side's badge:
            # plum for wts, blue for wtb - which already matches (sell=plum).
            act_text = vm.own_action(side)
            act = QPushButton(act_text)
            act.setProperty("size", "small")
            act.setCursor(Qt.PointingHandCursor)
            act.setToolTip("post your own order - lands with My Listings")
            act.setStyleSheet(
                f"color: {colour}; background: {t.ROW_ALT};"
                f"border: {t.CTRL_BORDER_W}px solid {colour}; padding: 2px 10px;")
            act.clicked.connect(lambda _c=False, sd=side: self._post_order(sd))
            top.addWidget(act, 0, Qt.AlignTop)
            self.actions[side] = act
            cl.addLayout(top)

            area = QScrollArea()
            area.setWidgetResizable(True)
            area.setFrameShape(QFrame.NoFrame)
            area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            # Reserve the height of a full table up front so the frame does
            # not grow into place as results land - an empty table that is
            # already the right size reads as "waiting", not "broken".
            area.setMinimumHeight(TABLE_ROWS * ROW_HEIGHT)
            inner = panel()
            rows = QVBoxLayout(inner)
            rows.setContentsMargins(0, 0, 0, 0)
            rows.setSpacing(0)
            area.setWidget(inner)
            cl.addWidget(area, 1)

            self.cols[side] = rows
            cols.addWidget(card, 1)
        lay.addLayout(cols, 1)

        self.load_index()

    # -- data ----------------------------------------------------------------

    def load_index(self) -> None:
        def ok(rows):
            self._index = rows
            if self.search.text().strip():
                self.suggest.refresh()      # they typed while it was loading

        def failed(msg):
            # the catalogue is what search matches against; swallowing this
            # left the box permanently dead with no explanation. Say so, and
            # retry from _supply on the next keystroke.
            self._flash(f"item list unavailable — {msg}", "err")
        _track(self._jobs, run(self.view.client.item_names, ok, failed))

    def _supply(self, q: str):
        if not self._index:
            self.load_index()               # retry a failed/never-loaded fetch
        return vm.suggest_pairs(self._index, q)

    def _picked(self, name: str, slug: str) -> None:
        self.search.setText(name)
        self.open(slug, name)

    def open(self, slug: str, name: str) -> None:
        self.slug, self.name = slug, name
        # Populate the search box (it doubles as the item title) on EVERY path -
        # picking from the suggest, a watchlist click, a contract deep-link.
        # Signals blocked so setting it does not re-open the suggest popup.
        self.search.blockSignals(True)
        self.search.setText(name)
        self.search.blockSignals(False)
        # Blank the table to its empty "waiting" state BEFORE the new fetch.
        # Still no "loading…" line - that reflow is more distracting than the
        # wait it reports, and the empty right-sized table already reads as
        # waiting (see TABLE_ROWS). But leaving the PREVIOUS item's rows and
        # counts on screen under the new item's title reads as real data for
        # the wrong item, so clear them.
        self._clear_book()
        self.watch_btn.setEnabled(True)
        self.wiki_btn.setEnabled(True)
        self._paint_watch()
        self._paint_query()
        self.refresh()
        self._load_inventory(slug)

    def _load_inventory(self, slug: str) -> None:
        """Off-thread: the item's gameRef -> how many the player owns -> the WTS
        'Inventory: #' label. Blank when there is no AlecaFrame data."""
        if self.inv_label is None:
            return
        self.inv_label.setText("Inventory: …")

        def owned():
            try:
                ref = self.view.client.item_detail(slug).get("gameRef")
            except Exception:                            # noqa: BLE001
                ref = None
            return wf_inventory.count_owned(ref)
        _track(self._jobs, run(owned, self._set_inventory))

    def _set_inventory(self, count) -> None:
        if not alive(self.inv_label):
            return
        self.inv_label.setText(f"Inventory: {count}"
                               if count is not None else "")

    def _clear_book(self) -> None:
        """Back to the pre-load state: empty columns, plain headings, no book.
        Reproduces exactly what the very first load shows, so a switch never
        flashes the previous item's data."""
        self._book = None
        for side, rows_layout in self.cols.items():
            while rows_layout.count():
                item = rows_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            self.counts[side].setText(self._headings[side])
        if self.inv_label is not None:
            self.inv_label.setText("")

    def _paint_query(self) -> None:
        """The search box doubles as the item title: teal and bold once its
        contents ARE the loaded item, plain while you are still typing."""
        loaded = bool(self.name) and self.search.text().strip() == self.name
        self.search.setStyleSheet(
            f"color: {t.WFM_TEAL}; font-weight: 600;" if loaded else "")

    def _open_wiki(self) -> None:
        # the Wiki tab and deep-linking exist now; use them
        if self.name:
            self.view.open_wiki(self.name)

    def _clear_flash(self) -> None:
        self.flash.setText("")

    def _flash(self, text: str, level: str) -> None:
        """One place for transient text. Everything here fades - none of it
        is state, and a stale "copied" line reads as a stuck UI."""
        # _error reaches here via a worker callback, which can land after the
        # tab was dropped mid-fetch: guard before touching the deleted QLabel.
        if not alive(self):
            return
        self.flash.setText(text)
        self.flash.setProperty("level", level)
        restyle(self.flash)
        if text:
            self._flash_timer.start(5000)
        else:
            self._flash_timer.stop()

    def refresh(self) -> None:
        if not self.slug:
            return
        slug = self.slug
        # Disable while a fetch is in flight, as My Listings does: it signals
        # "working" and stops impatient repeat-clicks launching a stack of
        # simultaneous order_book fetches. Re-enabled when the outcome lands.
        self.refresh_btn.setEnabled(False)
        _track(self._jobs, run(
            lambda: self.view.client.order_book(slug),
            lambda book: self._render(slug, book),
            lambda msg: self._error(msg)))

    def _error(self, msg: str) -> None:
        if alive(self):
            self.refresh_btn.setEnabled(True)
        self._flash(msg, "err")

    def _render(self, slug: str, book) -> None:
        # This lands from a worker whose Qt receiver is the Job, not this tab,
        # so Qt will NOT drop it if the tab was deleted mid-fetch (unlink /
        # adopt / wipe): check the C++ object is alive before touching layouts.
        if not alive(self):
            return
        self.refresh_btn.setEnabled(True)   # a fetch landed; allow another
        # the user may have searched for something else while this was in
        # flight - a liveness guard cannot catch that, only a staleness one
        if slug != self.slug:
            return
        self._book = book
        self._rerender()

    def _sync_ranks(self, visible: dict) -> None:
        """Rebuild the rank picker from the rows the user can CURRENTLY
        see, not from the whole book.

        Measured on live Arcane Energize: the full book carries ranks 0-5
        across 1,576 sellers, but with the default in-game filter on only
        ranks 0, 1 and 5 remain. Building the picker from the book offered
        R-2, R-3 and R-4, and every one of them emptied the table - the
        sellers holding those ranks were all offline. A choice that cannot
        produce a row is not a choice, so the picker follows the filters.

        The control is always PRESENT and greyed when there is no choice to
        make. Hiding it moved every neighbour on the row each time an item
        loaded, and an absent control reads as a missing feature rather than
        as "this item does not rank".
        """
        ranks = vm.available_ranks(visible)
        usable = len(ranks) > 1
        # Rankability is a fact about the WHOLE book, not the status-filtered
        # view: a rank-0..5 arcane with only rank-0 sellers online is still a
        # rankable item, and telling the user it "does not come in ranks" is
        # flatly false about a core mechanic. Only say that when NO order at
        # any rank exists.
        rankable = bool(vm.available_ranks(self._book or {}))
        self._ranked = usable
        self.rank_lbl.setEnabled(usable)
        self.rank_pick.setEnabled(usable)
        self.rank_pick.setToolTip(
            "filter by mod / arcane rank" if usable
            else "only one rank is on offer with the current filters" if rankable
            else "this item does not come in ranks")
        keep = self.rank_pick.currentText()
        want = [ANY_RANK] + [f"R-{r}" for r in ranks] if usable else [ANY_RANK]
        if want == [self.rank_pick.itemText(i)
                    for i in range(self.rank_pick.count())]:
            return                          # no churn, no lost selection
        self.rank_pick.blockSignals(True)    # or clear() re-enters here
        self.rank_pick.clear()
        self.rank_pick.addItems(want)
        idx = self.rank_pick.findText(keep)
        self.rank_pick.setCurrentIndex(idx if idx >= 0 else 0)
        self.rank_pick.blockSignals(False)

    def _chosen_rank(self) -> int | None:
        # `self._ranked`, not isVisible(): a book can land while this tab
        # is hidden behind another, and isVisible() is False for every
        # widget on a stacked page that is not on top
        text = self.rank_pick.currentText()
        if not self._ranked or text in ("", ANY_RANK):
            return None
        try:
            return int(text.split("-", 1)[1])
        except (IndexError, ValueError):
            return None

    def _rerender(self) -> None:
        if self._book is None:
            return
        allowed, scope = self.filters.scope()
        me = (self.view.username or "").lower()
        # status first, THEN rank - the picker is rebuilt from what survives
        # the status filter, so widening or narrowing the scope changes which
        # ranks are on offer
        visible = {side: vm.filter_orders(self._book[side], allowed)
                   for side in self.cols}
        self._sync_ranks(visible)
        chosen = self._chosen_rank()
        counts = {}
        for side, rows_layout in self.cols.items():
            while rows_layout.count():
                item = rows_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            rows = vm.filter_rank(visible[side], chosen)
            counts[side] = len(rows)
            # every order, not a top-N slice - the column scrolls
            for i, r in enumerate(rows):
                rows_layout.addWidget(self._order_row(i, side, r, me))
            if not rows:
                rows_layout.addWidget(label("nobody here", role="small"))
            rows_layout.addStretch(1)
            self.counts[side].setText(f"{self._headings[side]}  ({len(rows)})")

    def _order_row(self, i: int, side: str, r: dict, me: str) -> QWidget:
        row = _row_panel(i)
        h = QHBoxLayout(row)
        h.setContentsMargins(t.SP_MD, 2, t.SP_MD, 2)
        h.setSpacing(t.SP_SM)
        glyph, role = vm.status_dot(r["status"])
        dot = label(glyph, role="small")
        dot.setStyleSheet(f"color: {ROLE_COLOR[role]};")
        h.addWidget(dot)
        user = label(f" {r['user']}")
        if r["user"].lower() == me:
            user.setStyleSheet(f"color: {t.WFM_TEAL};")
        h.addWidget(user)
        rep = vm.reputation(r)
        if rep:
            # only the ARROW is coloured - a coloured number stops reading as
            # a quantity and starts reading as a status
            arrow = label(f" {rep.arrow}", role="small")
            arrow.setStyleSheet(f"color: {ROLE_COLOR[rep.role]};")
            arrow.setToolTip("trader reputation")
            h.addWidget(arrow)
            count = label(rep.value, role="small")
            count.setToolTip("trader reputation")
            h.addWidget(count)
        h.addStretch(1)
        # fixed, equal columns so quantity / rank / price / ✉ line up down the
        # list instead of drifting with each trader's name length
        qty = label(f"{r['quantity']} ❒", role="small")
        qty.setFixedWidth(COL_QTY)
        qty.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        h.addWidget(qty)
        rank = label(vm.rank_text(r), role="small")
        rank.setFixedWidth(COL_RANK)
        rank.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        rank.setToolTip("mod / arcane rank")
        h.addWidget(rank)
        plat = label(str(r["platinum"]), role="price")
        plat.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        plat.setFixedWidth(COL_PLAT)
        h.addWidget(plat)
        h.addWidget(plat_label())
        msg = QPushButton(t.glyph("mail"))    # Material ligature
        msg.setProperty("role", "glyph")   # needs the icon face, or
        msg.setCursor(Qt.PointingHandCursor)  # the codepoint is blank
        msg.setFixedWidth(t.ICON_BTN)
        msg.setToolTip("copy a whisper for this trader")
        msg.clicked.connect(
            lambda _c=False, s=side, rr=r: self._whisper(s, rr))
        h.addWidget(msg)
        return row

    def _post_order(self, side: str) -> None:
        """Open the post-order dialog for the loaded item on this side."""
        if self.view.client.session is None:
            self._flash("sign in to warframe.market to post orders", "err")
            return
        if not self.slug:
            self._flash("search for an item first", "")
            return
        PostOrderDialog(self, side).exec()

    def _whisper(self, side: str, r: dict) -> None:
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(
            vm.whisper_message(self.view.settings, side, r, self.name))
        # a confirmation, not state - it fades on its own
        self._flash(f"whisper for {r['user']} copied ✔", "ok")

    # -- watchlist -----------------------------------------------------------

    def _paint_watch(self) -> None:
        watched = self.slug in core_market.load_watchlist()
        text, role = vm.watch_label(watched)
        # the star FILLS rather than changing character - one glyph, two axis
        # values, so the pair cannot drift (see ui.icons)
        self.watch_btn.setText(" " + text.split(" ", 1)[-1])
        self.watch_btn.setIcon(glyph_icon("watch", filled=watched,
                                          color=ROLE_COLOR[role]))
        self.watch_btn.setStyleSheet(f"color: {ROLE_COLOR[role]};")

    def _toggle_watch(self) -> None:
        if not self.slug:
            return
        core_market.save_watchlist(
            vm.toggle_watch(core_market.load_watchlist(), self.slug))
        self._paint_watch()
        self.view.watchlist_changed()


class ContractsTab(QWidget):
    """Riven and lich auctions for one weapon."""

    def __init__(self, view) -> None:
        super().__init__()
        self.view = view
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._weapons: dict[str, list] = {}
        self._asc = True
        self._rows = []
        self.slug = self.wname = ""
        self._jobs = set()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(*t.TOP_GAP_MARGINS)
        lay.setSpacing(t.SP_LG)

        # Same two-row shape as the Market tab: the search field owns row 1,
        # filters + key + buttons sit on row 2.
        top = QHBoxLayout()
        top.setSpacing(t.SP_MD)
        top.addWidget(label("Type", role="muted"))
        self.kind = Dropdown(["riven", "lich"])
        self.kind.currentTextChanged.connect(self._kind_changed)
        top.addWidget(self.kind)
        top.addWidget(label("Weapon", role="muted"))
        self.weapon = QLineEdit()
        self.weapon.setMinimumWidth(240)
        top.addWidget(self.weapon, 1)
        lay.addLayout(top)
        self.suggest = SuggestBox(self.weapon, self._supply, self._picked)
        # the weapon field doubles as the loaded item's title, exactly like the
        # order-book search box: teal + bold once it IS the loaded weapon
        self.weapon.textChanged.connect(self._paint_query)

        ctl = QHBoxLayout()
        ctl.setSpacing(t.SP_MD)
        self.filters = StatusFilters()
        self.filters.changed.connect(self._rerender)
        ctl.addWidget(self.filters)
        ctl.addStretch(1)
        self.order_btn = QPushButton(vm.sort_label(self._asc))
        self.order_btn.setProperty("size", "small")
        self.order_btn.setToolTip("click to reverse the order")
        self.order_btn.clicked.connect(self._flip)
        ctl.addWidget(self.order_btn)
        refresh = QPushButton(" Refresh")
        refresh.setIcon(glyph_icon("refresh", color=t.TEXT))
        refresh.setProperty("size", "small")
        refresh.clicked.connect(lambda: self.slug and self.open())
        ctl.addWidget(refresh)
        self.watch_btn = QPushButton(" Watch")
        self.watch_btn.setProperty("size", "small")
        self.watch_btn.setEnabled(False)
        self.watch_btn.clicked.connect(self._toggle_watch)
        ctl.addWidget(self.watch_btn)
        lay.addLayout(ctl)

        self.status = label("Pick a weapon to see its contracts.",
                            role="small")
        lay.addWidget(self.status)

        # same bordered card the order book columns use, so the three tabs
        # read as one family rather than three loose lists
        card = panel("card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(t.SP_LG, t.SP_MD, t.SP_LG, t.SP_MD)
        self.area = QScrollArea()
        self.area.setWidgetResizable(True)
        self.area.setFrameShape(QFrame.NoFrame)
        self.area.setMinimumHeight(TABLE_ROWS * ROW_HEIGHT)
        cl.addWidget(self.area, 1)
        lay.addWidget(card, 1)
        self._set_rows([])
        self.load_weapons()

    def load_weapons(self) -> None:
        kind = self.kind.currentText()
        if kind in self._weapons:
            return                              # memoised per kind
        fetch = (self.view.client.riven_weapons if kind == "riven"
                 else self.view.client.lich_weapons)
        _track(self._jobs, run(
            fetch,
            lambda rows, k=kind: self._weapons.__setitem__(k, rows),
            lambda msg, k=kind: self._error(
                f"couldn't load {k} weapons — {msg}")))

    def _supply(self, q: str):
        return vm.suggest_pairs(self._weapons.get(self.kind.currentText(), []),
                                q)

    def _picked(self, name: str, slug: str) -> None:
        self.weapon.setText(name)
        self.wname, self.slug = name, slug
        self.watch_btn.setEnabled(True)
        self._paint_watch()
        self.open()

    def _kind_changed(self) -> None:
        self.slug = self.wname = ""
        self._rows = []
        self.weapon.clear()
        self.watch_btn.setEnabled(False)
        self.suggest.hide()
        self._set_rows([])
        self.load_weapons()

    def _flip(self) -> None:
        self._asc = not self._asc
        self.order_btn.setText(vm.sort_label(self._asc))
        if self.slug:
            self.open()

    def _paint_query(self) -> None:
        """The weapon field doubles as the item title: teal and bold once its
        contents ARE the loaded weapon, plain while you are still typing. Mirrors
        MarketTab._paint_query so both search boxes read the same on a hit."""
        loaded = bool(self.wname) and self.weapon.text().strip() == self.wname
        self.weapon.setStyleSheet(
            f"color: {t.WFM_TEAL}; font-weight: 600;" if loaded else "")

    def open(self) -> None:
        kind, slug, asc = self.kind.currentText(), self.slug, self._asc
        self._paint_query()
        # A prior fetch may have left the status at level="err" (red). A fresh
        # load must not paint its "loading…" line in that leftover error colour,
        # which reads as a failure before it has even started.
        self.status.setProperty("level", "")
        restyle(self.status)
        self.status.setText(f"loading {self.wname}…")
        _track(self._jobs, run(
            lambda: self.view.client.auctions(kind, slug, ascending=asc),
            lambda rows: self._render(kind, slug, rows),
            self._error))

    def _error(self, msg: str) -> None:
        self.status.setText(msg)
        self.status.setProperty("level", "err")
        restyle(self.status)

    def _render(self, kind: str, slug: str, rows) -> None:
        # guard on BOTH kind AND weapon: switching to another weapon of the
        # same kind (riven A -> riven B) leaves kind unchanged, so a slow fetch
        # for A would otherwise overwrite B's view
        if kind != self.kind.currentText() or slug != self.slug:
            return
        self._rows = rows                       # kept so filters need no refetch
        self.status.setProperty("level", "")
        restyle(self.status)
        self._rerender()

    def _rerender(self) -> None:
        """Re-filter and redraw from the rows already fetched."""
        if not self.slug:
            return                              # no weapon chosen yet
        kind = self.kind.currentText()
        allowed, scope = self.filters.scope()
        rows = vm.filter_orders(self._rows, allowed)
        self.status.setProperty("level", "")
        restyle(self.status)
        # empty is a real, finished outcome - not "still loading". Without this
        # a weapon nobody is auctioning left the status stuck on "loading…"
        # forever and kept the previous weapon's rows on screen.
        self.status.setText(
            f"{vm.contracts_summary(len(rows), kind, self.wname, ROWS)}"
            f"  ·  {vm.scope_note(scope)}")
        self._set_rows([vm.contract_row(kind, self.wname, r)
                        for r in rows[:ROWS]])

    def _paint_watch(self) -> None:
        watched = vm.is_contract_watched(
            core_market.load_contract_watchlist(),
            self.kind.currentText(), self.slug)
        text, role = vm.watch_label(watched)
        self.watch_btn.setText(" " + text.split(" ", 1)[-1])
        self.watch_btn.setIcon(glyph_icon("watch", filled=watched,
                                          color=ROLE_COLOR[role]))
        self.watch_btn.setStyleSheet(f"color: {ROLE_COLOR[role]};")

    def _toggle_watch(self) -> None:
        if not self.slug:
            return
        core_market.save_contract_watchlist(vm.toggle_contract_watch(
            core_market.load_contract_watchlist(), self.kind.currentText(),
            self.slug, self.wname))
        self._paint_watch()
        self.view.watchlist_changed()

    def _set_rows(self, rows: list[dict]) -> None:
        body = panel()
        col = QVBoxLayout(body)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(t.SP_XXS)
        for i, r in enumerate(rows):
            line = _row_panel(i)
            h = QHBoxLayout(line)
            h.setContentsMargins(t.SP_LG, t.SP_MD, t.SP_LG, t.SP_MD)
            h.setSpacing(t.SP_SM)
            glyph, role = vm.status_dot(r["status"])
            dot = label(glyph, role="small")
            dot.setStyleSheet(f"color: {ROLE_COLOR[role]};")
            h.addWidget(dot)
            title = label(r["title"])
            title.setStyleSheet(f"color: {t.WFM_TEAL};")
            h.addWidget(title)
            meta = label(r["meta"], role="small")
            h.addWidget(meta)
            h.addStretch(1)
            h.addWidget(label(f"{r['owner']}   {r['price_label']} ",
                              role="small"))
            h.addWidget(label(str(r["price"]), role="price"))
            h.addWidget(plat_label())
            msg = QPushButton(t.glyph("mail"))
            msg.setProperty("role", "glyph")
            msg.setCursor(Qt.PointingHandCursor)
            msg.setFixedWidth(t.ICON_BTN)
            msg.setToolTip("copy a whisper for this trader")
            msg.clicked.connect(lambda _c=False, rr=r: self._whisper(rr))
            h.addWidget(msg)
            col.addWidget(line)
        col.addStretch(1)
        self.area.setWidget(body)

    def _whisper(self, r: dict) -> None:
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(vm.contract_whisper(
            self.view.settings, self.kind.currentText(), self.wname, r))
        self.status.setText(f"whisper for {r['owner']} copied ✔")
        self.status.setProperty("level", "ok")
        restyle(self.status)


class WatchlistTab(QWidget):
    """Bookmarked items, with live best prices fetched one at a time."""

    def __init__(self, view) -> None:
        super().__init__()
        self.view = view
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.rows: dict[str, object] = {}
        self.contract_rows: dict[tuple, object] = {}
        self._jobs = set()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(*t.TOP_GAP_MARGINS)
        lay.setSpacing(t.SP_LG)
        ctl = QHBoxLayout()
        ctl.addWidget(label("Watched items and contracts, priced live.",
                            role="small"))
        ctl.addStretch(1)
        btn = QPushButton(" Refresh prices")
        btn.setIcon(glyph_icon("refresh", color=t.TEXT))
        btn.setProperty("size", "small")
        btn.clicked.connect(self.refresh_all)
        ctl.addWidget(btn)
        lay.addLayout(ctl)

        # Items and contracts are different KINDS of thing - orders for an
        # item versus auctions for a weapon - and they open different tabs.
        # Two columns say that without a heading having to, and each scrolls
        # at its own pace instead of a long item list pushing the contracts
        # off the bottom.
        cols = QHBoxLayout()
        cols.setSpacing(t.SP_LG)
        self.areas = {}
        for side, heading, colour in (("items", "ITEMS", t.WFM_TEAL),
                                      ("contracts", "CONTRACTS", t.WFM_PINK)):
            card = panel("card")
            cl = QVBoxLayout(card)
            cl.setContentsMargins(t.SP_LG, t.SP_MD, t.SP_LG, t.SP_MD)
            cl.setSpacing(t.SP_SM)
            head = label(heading, role="caps")
            head.setStyleSheet(f"color: {colour};")
            cl.addWidget(head)
            area = QScrollArea()
            area.setWidgetResizable(True)
            area.setFrameShape(QFrame.NoFrame)
            area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            area.setMinimumHeight(TABLE_ROWS * ROW_HEIGHT)
            cl.addWidget(area, 1)
            self.areas[side] = area
            cols.addWidget(card, 1)
        lay.addLayout(cols, 1)
        self.reload()

    def _link(self, text: str, colour: str, tip: str, on_click) -> QPushButton:
        """The row's NAME is the link. A separate Open button was a second
        target for the thing you were already pointing at, and it pushed the
        price out of the row."""
        b = QPushButton(text)
        b.setProperty("kind", "flat")
        b.setCursor(Qt.PointingHandCursor)
        b.setToolTip(tip)
        b.setStyleSheet(f"color: {colour}; text-align: left;"
                        f"padding: 4px 2px; background: transparent;")
        b.clicked.connect(on_click)
        return b

    def _remove_btn(self, tip: str, on_click) -> QPushButton:
        b = QPushButton(glyph_icon("close", color=t.WFM_RED), "")
        b.setFixedSize(*t.REMOVE_BTN)
        b.setCursor(Qt.PointingHandCursor)
        b.setToolTip(tip)
        b.setStyleSheet(
            f"QPushButton {{ background: transparent;"
            f" border: {t.BORDER_W}px solid {t.BORDER}; }}"
            f"QPushButton:hover {{ border-color: {t.WFM_RED}; }}")
        b.clicked.connect(on_click)
        return b

    def reload(self) -> None:
        self.rows.clear()
        self.contract_rows.clear()
        self._fill_items(core_market.load_watchlist())
        self._fill_contracts(core_market.load_contract_watchlist())

    def _column(self, side: str):
        body = panel()
        col = QVBoxLayout(body)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(t.SP_XXS)
        return body, col

    def _fill_items(self, watchlist: list[str]) -> None:
        body, col = self._column("items")
        if not watchlist:
            col.addWidget(label("Nothing watched yet — use ☆ Watch on the "
                                "Market tab.", role="small"))
        for i, slug in enumerate(watchlist):
            line = _row_panel(i)
            h = QHBoxLayout(line)
            h.setContentsMargins(t.SP_MD, 2, t.SP_MD, 2)
            h.setSpacing(t.SP_SM)
            name = vm.pretty_slug(slug)
            h.addWidget(self._link(
                name, t.WFM_TEAL, f"open {name} in the Market tab",
                lambda _c=False, s=slug, n=name:
                    self.view.open_in_market(s, n)))
            price = label("  —", role="small")
            self.rows[slug] = price
            h.addWidget(price)
            h.addStretch(1)
            h.addWidget(self._remove_btn(
                f"stop watching {name}",
                lambda _c=False, s=slug: self._remove(s)))
            col.addWidget(line)
        col.addStretch(1)
        self.areas["items"].setWidget(body)

    def _fill_contracts(self, contracts: list[dict]) -> None:
        body, col = self._column("contracts")
        if not contracts:
            col.addWidget(label("Nothing watched yet — use ☆ Watch on the "
                                "Contracts tab.", role="small"))
        for i, entry in enumerate(contracts):
            line = _row_panel(i)
            h = QHBoxLayout(line)
            h.setContentsMargins(t.SP_MD, 2, t.SP_MD, 2)
            h.setSpacing(t.SP_SM)
            name = entry.get("name") or vm.pretty_slug(entry["slug"])
            h.addWidget(self._link(
                name, t.WFM_PINK,
                f"open {name} {entry['kind']} contracts",
                lambda _c=False, e=entry: self.view.open_contract(e)))
            h.addWidget(label(entry["kind"], role="small"))
            price = label("  —", role="small")
            self.contract_rows[vm.contract_key(entry)] = price
            h.addWidget(price)
            h.addStretch(1)
            h.addWidget(self._remove_btn(
                f"stop watching {name}",
                lambda _c=False, e=entry: self._remove_contract(e)))
            col.addWidget(line)
        col.addStretch(1)
        self.areas["contracts"].setWidget(body)

    def _remove_contract(self, entry: dict) -> None:
        core_market.save_contract_watchlist(vm.toggle_contract_watch(
            core_market.load_contract_watchlist(), entry["kind"],
            entry["slug"], entry.get("name", "")))
        self.reload()

    def on_show(self) -> None:
        """Opening the tab re-reads the list AND re-prices it. Watched items
        exist to be checked on, so a stale price is worse than a short wait;
        the manual button stays for a second look without leaving the tab."""
        self.reload()
        self.refresh_all()

    def _remove(self, slug: str) -> None:
        core_market.save_watchlist(
            vm.toggle_watch(core_market.load_watchlist(), slug))
        self.reload()
        self.view.watchlist_changed(from_watchlist=True)

    def refresh_all(self) -> None:
        """One worker walking every slug, posting each result as it lands so
        rows fill in progressively. Look the label up by slug at delivery
        time - reload() may have rebuilt the rows meanwhile."""
        slugs = list(self.rows)
        for lbl in self.rows.values():
            lbl.setText("  …")

        def emit_one(slug):
            def ok(book):
                # `w is not None` is not enough: after a page drop the dict still
                # holds the QLabel's Python wrapper while its C++ half is deleted.
                if not alive(self):
                    return
                w = self.rows.get(slug)
                if w is not None:
                    w.setText(vm.price_line(*vm.best_live_prices(book)))

            def bad(_msg):
                if not alive(self):
                    return
                w = self.rows.get(slug)
                if w is not None:
                    w.setText("  fetch failed")
            return ok, bad

        for slug in slugs:
            ok, bad = emit_one(slug)
            _track(self._jobs, run(
                lambda s=slug: self.view.client.order_book(s), ok, bad))

        # watched contracts price the same way, from their auction list
        for entry in core_market.load_contract_watchlist():
            key = vm.contract_key(entry)
            lbl = self.contract_rows.get(key)
            if lbl is not None:
                lbl.setText("  …")

            def made(k):
                def good(rows):
                    if not alive(self):
                        return
                    w = self.contract_rows.get(k)
                    if w is not None:
                        w.setText(vm.contract_price_line(
                            vm.best_contract_price(rows), len(rows)))

                def bad(_msg):
                    if not alive(self):
                        return
                    w = self.contract_rows.get(k)
                    if w is not None:
                        w.setText("  fetch failed")
                return good, bad

            good, bad = made(key)
            _track(self._jobs, run(
                lambda e=entry: self.view.client.auctions(
                    e["kind"], e["slug"], ascending=True), good, bad))


class MarketView(QWidget):
    """The three tabs, and the shared client they all read through."""

    def __init__(self, client, settings, username: str,
                 open_wiki=lambda _n: None, on_posted=lambda: None) -> None:
        super().__init__()
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.client = client
        self.settings = settings
        self.username = username
        self.open_wiki = open_wiki
        # called after an order is posted, so My Listings can refresh itself
        self.on_posted = on_posted

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        head = QHBoxLayout()
        head.setContentsMargins(*t.PAGE_HEADER_MARGINS)
        title = label("Warframe.Market Browser", role="h1")
        head.addWidget(title, 0, Qt.AlignVCenter)
        head.addStretch(1)
        # in line with the title: re-read AlecaFrame and refresh the owned counts
        self.inv_refresh = QPushButton(" Refresh inventory")
        self.inv_refresh.setIcon(glyph_icon("refresh", color=t.TEXT))
        self.inv_refresh.setProperty("size", "small")
        self.inv_refresh.setCursor(Qt.PointingHandCursor)
        self.inv_refresh.setToolTip(
            "re-read your AlecaFrame inventory and update the owned counts")
        self.inv_refresh.clicked.connect(self._refresh_inventory)
        head.addWidget(self.inv_refresh, 0, Qt.AlignVCenter)
        lay.addLayout(head)

        # The tabs and everything below them live inside the app's bordered
        # container (the surface="card" box Home and Settings use), inset from
        # the screen like every other container; the box's own inner padding is
        # the tab content's margins.
        box = panel("card")
        boxlay = QVBoxLayout(box)
        # thin frame so the gold border sits close to the tabs (aligned to the
        # WTS/Watchlist edges); bottom pad == L/R pad so the WTS/WTB panels
        # extend down with the same inset all round
        boxlay.setContentsMargins(t.SP_LG, t.SP_LG, t.SP_LG, t.SP_LG)
        boxlay.setSpacing(0)

        # Full width, each tab a third of it - no trailing stretch, and an
        # equal stretch factor on every button so they divide the frame
        # evenly however wide the window gets.
        bar = QHBoxLayout()
        bar.setContentsMargins(0, 0, 0, 0)
        bar.setSpacing(0)
        self.tab_btns = {}
        for key, text in (("market", "Market"), ("contracts", "Contracts"),
                          ("watchlist", "Watchlist")):
            b = QPushButton(text)
            b.setProperty("kind", "flat")
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _c=False, k=key: self.select(k))
            self.tab_btns[key] = b
            bar.addWidget(b, 1)
        boxlay.addLayout(bar)
        boxlay.addWidget(hairline())

        self.stack = QStackedWidget()
        self.stack.setProperty("surface", "tab")
        self.tabs = {"market": MarketTab(self),
                     "contracts": ContractsTab(self),
                     "watchlist": WatchlistTab(self)}
        for tab in self.tabs.values():
            self.stack.addWidget(tab)
        boxlay.addWidget(self.stack, 1)

        holder = QHBoxLayout()
        holder.setContentsMargins(*t.PAGE_HOLDER_MARGINS)
        holder.addWidget(box)
        lay.addLayout(holder, 1)

        self.current = ""
        self.select("market")

    def select(self, key: str) -> None:
        if key == self.current:
            return
        # a popup left open would float over the next tab
        for tab in self.tabs.values():
            if hasattr(tab, "suggest"):
                tab.suggest.hide()
        self.current = key
        tab = self.tabs[key]
        self.stack.setCurrentWidget(tab)
        if hasattr(tab, "on_show"):     # a tab may freshen itself on the way in
            tab.on_show()
        for k, b in self.tab_btns.items():
            active = k == key
            b.setStyleSheet(
                f"color: {t.TEXT if active else t.MUTED};"
                f"border-bottom: {t.BORDER_W}px solid "
                f"{TAB_ACCENTS[k] if active else t.BORDER};"
                f"background: {t.TAB_BG if active else t.PANEL};"
                "padding: 6px 18px;")

    def _refresh_inventory(self) -> None:
        """Drop the cached inventory and re-count the loaded item's owned total
        (the header 'Refresh inventory' button)."""
        wf_inventory.invalidate()
        mt = self.tabs.get("market")
        if mt is not None and mt.slug:
            mt._load_inventory(mt.slug)

    # -- cross-tab hooks -----------------------------------------------------

    def open_in_market(self, slug: str, name: str) -> None:
        self.select("market")
        self.tabs["market"].open(slug, name)

    def open_contract(self, entry: dict) -> None:
        self.select("contracts")
        tab = self.tabs["contracts"]
        tab.kind.setCurrentText(entry["kind"])
        tab.weapon.setText(entry.get("name", ""))
        tab._picked(entry.get("name", ""), entry["slug"])

    def watchlist_changed(self, from_watchlist: bool = False) -> None:
        if not from_watchlist:
            self.tabs["watchlist"].reload()
        self.tabs["market"]._paint_watch()
        if self.tabs["contracts"].slug:
            self.tabs["contracts"]._paint_watch()


class PostOrderDialog(QDialog):
    """Post a NEW sell/buy order for the loaded item, straight to
    warframe.market. The dialog IS the confirmation - the order goes out only
    when the user fills it in and clicks Post - and the post runs off-thread."""

    def __init__(self, tab, side: str) -> None:
        super().__init__(tab.window())
        self.tab, self.side = tab, side
        verb = "sell" if side == "sell" else "buy"
        self.setWindowTitle(f"Post a {verb} order — {tab.name}")
        self.setModal(True)
        self.setMinimumWidth(t.DIALOG_MIN_W)  # §9: dialogs carry a stable min
        lay = QVBoxLayout(self)
        lay.setContentsMargins(t.SP_XL, t.SP_XL, t.SP_XL, t.SP_XL)
        lay.setSpacing(t.SP_MD)

        nm = label(tab.name, role="h2")
        nm.setStyleSheet(f"color: {t.WFM_TEAL};")
        lay.addWidget(nm)
        lay.addWidget(hairline())

        self.price = self._field(lay, "Price (platinum)", "")
        self.qty = self._field(lay, "Quantity", "1")
        self.per_trade = self._field(lay, "Per trade (max units in one trade)",
                                     "1")

        # Rank picker, revealed only once /v2/item confirms the good ranks and
        # how far (never a table kept here - stale the week a new arcane ships).
        self.rank_cap = label("Rank", role="small")
        self.rank_cap.hide()
        lay.addWidget(self.rank_cap)
        self.rank = Dropdown(["R-0"])
        self.rank.hide()
        lay.addWidget(self.rank)
        _track(tab._jobs, run(lambda: tab.view.client.max_rank(tab.slug),
                              self._ranks_ready, lambda _m: None))

        self.visible = QCheckBox("Visible on warframe.market")
        self.visible.setChecked(True)
        lay.addWidget(self.visible)

        self.status = label("", role="small")
        self.status.setWordWrap(True)     # a full API error must be readable
        lay.addWidget(self.status)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        self.post_btn = QPushButton("Post")
        self.post_btn.setProperty("kind", "money")     # a money action: gold
        self.post_btn.setDefault(True)
        self.post_btn.clicked.connect(self._post)
        row.addWidget(self.post_btn)
        lay.addLayout(row)
        self._job = None

    def _field(self, lay, caption: str, value: str) -> QLineEdit:
        lay.addWidget(label(caption, role="small"))
        e = QLineEdit(value)
        lay.addWidget(e)
        return e

    def _ranks_ready(self, max_rank) -> None:
        if not max_rank or not alive(self.rank):
            return
        self.rank.clear()
        self.rank.addItems([f"R-{i}" for i in range(int(max_rank) + 1)])
        self.rank.setCurrentText("R-0")
        self.rank_cap.show()
        self.rank.show()

    def _post(self) -> None:
        try:
            plat = int(self.price.text().strip())
            qty = int(self.qty.text().strip() or "1")
            per = int(self.per_trade.text().strip() or "1")
        except ValueError:
            self._say("price, quantity and per-trade must be whole numbers",
                      "err")
            return
        if plat <= 0 or qty <= 0 or per <= 0:
            self._say("price, quantity and per-trade must be positive", "err")
            return
        if per > qty:
            self._say("per-trade can't exceed the quantity", "err")
            return
        rank = None
        if self.rank.isVisible():
            try:
                rank = int(self.rank.currentText().split("-")[1])
            except (ValueError, IndexError):
                rank = None
        slug, side, client = self.tab.slug, self.side, self.tab.view.client
        visible = self.visible.isChecked()
        self.post_btn.setEnabled(False)
        self._say("posting…", "")

        def do():
            item_id = client.item_detail(slug).get("id")
            return client.create_order(item_id, side, plat, qty,
                                       per_trade=per, visible=visible,
                                       rank=rank)

        self._job = run(do, self._posted, self._failed)

    def _posted(self, _order_id) -> None:
        self.tab._flash(f"{self.side} order posted ✔", "ok")
        self.tab.refresh()               # the new order lands in the book
        self.tab.view.on_posted()        # and freshens My Listings
        self.accept()

    def _failed(self, msg) -> None:
        if not alive(self):
            return
        self._say(f"could not post: {msg}", "err")
        self.post_btn.setEnabled(True)

    def _say(self, text: str, role: str) -> None:
        self.status.setText(text)
        color = {"err": t.ERR, "ok": t.OK}.get(role, t.MUTED)
        self.status.setStyleSheet(f"color: {color};")
