"""Home: a player status panel over a horizontal strip of tool cards.

Every card's identity, copy and button text comes from core.home; this file
only arranges widgets. Two bordered containers stack under the shell header:

  * a status panel (no title) - player name, mastery rank, and three
    connection "lights" (warframe.market / game files / AlecaFrame);
  * the "Available Tools" container - ONE row of fixed-size cards that scrolls
    HORIZONTALLY inside it, so the container's gold border stays put while the
    cards slide under it (the scrolling frame is INSIDE the border, not the
    other way round).

Mastery rank rides in AlecaFrame's inventory blob but costs a ~0.9s decrypt, so
it is read off the GUI thread (ui.work) and filled in when it lands.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton,
                               QScrollArea, QSizePolicy, QVBoxLayout, QWidget)

from core import arcane_inv
from core import home as core_home
from core import mastery
from core import theme as t
from core import wf_profile
from ui import work
from ui.widgets import alive, glyph_icon, label

# the mastery badge's on-screen height, and the status-light dot diameter
# (doubled from the ~7px "small" bullet it replaced)
BADGE_H = 34
DOT_D = 14

# The card size the strip keeps at every window width; horizontal scrolling
# handles overflow rather than shrinking the cards.
CARD_W = 260

# Element 5's aspect ratio, MEASURED from the reference wireframe's media band
# (483x271 px = 1.782, i.e. 16:9 to within half a percent).
MEDIA_RATIO_W, MEDIA_RATIO_H = 16, 9

# the placeholder emblem's point size (rendered to a pixmap by ui.icons, so it
# never touches the QSS font rules), and the strip's horizontal scrollbar height
WATERMARK_PT = 30
SCROLLBAR_H = t.SCROLLBAR_THICK  # matches the QScrollBar:horizontal height in qss.py


class AspectMedia(QFrame):
    """Element 5: a fixed-aspect image placeholder.

    Holds a strict 16:9 box - the Qt equivalent of a CSS `aspect-ratio: 16 / 9`
    container. `heightForWidth` keeps it right during intermediate layout
    passes; HomeView also pins the exact height when it sizes the cards. Empty
    of real art, it carries a faint accent emblem so the band never reads as
    broken.
    """

    def __init__(self, icon_key: str, accent: str) -> None:
        super().__init__()
        self.setProperty("surface", "media")
        self.setAttribute(Qt.WA_StyledBackground, True)
        pol = QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        pol.setHeightForWidth(True)
        self.setSizePolicy(pol)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        box = round(WATERMARK_PT * 1.5)
        mark = QLabel()
        mark.setAlignment(Qt.AlignCenter)
        mark.setPixmap(glyph_icon(icon_key, size=WATERMARK_PT, color=accent)
                       .pixmap(QSize(box, box)))
        mark.setStyleSheet("background: transparent;")
        lay.addWidget(mark)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, w: int) -> int:
        return round(w * MEDIA_RATIO_H / MEDIA_RATIO_W)

    def set_width(self, w: int) -> None:
        """Pin the band to 16:9 at a known width (the card's inner width)."""
        if w > 0:
            self.setFixedHeight(round(w * MEDIA_RATIO_H / MEDIA_RATIO_W))


class StatusDot(QWidget):
    """A connection light: a filled circle, jade when up and muted when not.
    Painted rather than a "●" glyph so it can be sized freely (twice the old
    bullet) without a hand-written type size the style guide forbids in ui/."""

    def __init__(self, ok: bool) -> None:
        super().__init__()
        self.setFixedSize(DOT_D, DOT_D)
        self._colour = t.OK if ok else t.MUTED

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(self._colour))
        p.drawEllipse(1, 1, DOT_D - 2, DOT_D - 2)


class _HScroll(QScrollArea):
    """A scroll area whose vertical mouse wheel scrolls it HORIZONTALLY - wheel
    down goes right, wheel up goes left - so the tool strip pages sideways under
    the pointer. With nothing to scroll it lets the wheel through to the page's
    own vertical scroll."""

    def wheelEvent(self, event) -> None:
        bar = self.horizontalScrollBar()
        delta = event.angleDelta().y()
        if delta and bar.maximum() > 0:
            # up (delta > 0) -> value down -> left; down -> right
            bar.setValue(bar.value() - delta)
            event.accept()
        else:
            super().wheelEvent(event)


class Card(QFrame):
    """One app as a Material media card: accent stripe, icon + title, a 16:9
    media band, the blurb, and a right-aligned action.

    Only the corner BUTTON opens the app - the card body and media band are
    not click targets. A whole-card hit area made the image and blurb read as
    links they were not, so the affordance now lives solely on the button.
    """

    def __init__(self, card: core_home.Card, action: core_home.Action,
                 on_open, on_link) -> None:
        super().__init__()
        self.setProperty("surface", "tile")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedWidth(CARD_W)             # fixed size; the strip scrolls
        self._cmd = None
        if action.enabled:
            self._cmd = (on_link if action.kind == "link"
                         else lambda: on_open(card.key))

        lay = QVBoxLayout(self)
        lay.setContentsMargins(t.SP_XL, t.SP_LG, t.SP_XL, t.SP_LG)
        lay.setSpacing(0)

        # the accent identifies the card; it rides here and on the icon only
        stripe = QFrame()
        stripe.setFixedHeight(3)
        stripe.setStyleSheet(f"background: {card.accent}; border: none;")
        lay.addWidget(stripe)
        lay.addSpacing(t.SP_LG)

        # header: icon (Element 2) beside title (Element 3). Title is h1 - the
        # same size as the page title - with no secondary line beneath it.
        head = QHBoxLayout()
        head.setSpacing(t.SP_MD)
        icon = label(t.glyph(card.icon), role="icon")
        icon.setStyleSheet(f"color: {card.accent}; background: transparent;")
        head.addWidget(icon, 0, Qt.AlignVCenter)
        head.addWidget(label(card.name, role="h1"))
        head.addStretch(1)
        lay.addLayout(head)
        lay.addSpacing(t.SP_LG)

        # media band (Element 5): strict 16:9, full card width
        self.media = AspectMedia(card.icon, card.accent)
        lay.addWidget(self.media)
        lay.addSpacing(t.SP_LG)

        # blurb (Element 6). role="body" gives it TEXT - the card title's own
        # colour - in place of the muted caption colour. Its height is reserved
        # uniformly when HomeView sizes the cards, so all cards match.
        self.blurb = label(card.blurb, role="body")
        self.blurb.setWordWrap(True)
        self.blurb.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        pol = self.blurb.sizePolicy()
        pol.setHeightForWidth(True)
        self.blurb.setSizePolicy(pol)
        lay.addWidget(self.blurb)
        # slack pools here, pinning the action to the card floor so every
        # card's action lands on one baseline
        lay.addStretch(1)
        lay.addSpacing(t.SP_LG)

        # action (Element 7), strictly right-aligned
        row = QHBoxLayout()
        row.addStretch(1)
        btn = QPushButton(action.label)
        btn.setEnabled(action.enabled)
        btn.setProperty("wide", "true")
        btn.setProperty("size", "small")
        if self._cmd:
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(self._cmd)
        row.addWidget(btn)
        lay.addLayout(row)


class HomeView(QWidget):
    """The status panel + the tool strip. Rebuilt (recreated by the shell) when
    the account link changes, because that changes the name, the market light,
    and what several buttons say."""

    def __init__(self, tools, on_open, on_link, is_linked, player_name) -> None:
        super().__init__()
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._is_linked = is_linked
        self._player_name = player_name
        self._sized = False
        self._mr_job = None
        self._badge: QLabel | None = None

        linked = is_linked()
        self._cards = [Card(card, core_home.action_for(card, linked),
                            on_open, on_link)
                       for card in core_home.cards(tools)]
        status = core_home.player_status(player_name(), linked)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        # a vertical scroll so a short window can still reach everything; the
        # containers move as whole units under it, borders intact
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll, 1)

        frame = QWidget()
        frame.setAttribute(Qt.WA_StyledBackground, True)
        fl = QVBoxLayout(frame)
        fl.setContentsMargins(t.SP_SCREEN, t.SP_XL, t.SP_SCREEN, t.SP_XL)
        fl.setSpacing(t.SP_XL)
        # title row: the app name with the self-update outcome trailing to its
        # right - one quiet line, hidden until set_update_note fills it
        title_row = QHBoxLayout()
        title_row.setSpacing(t.SP_LG)
        title_row.addWidget(label("Warframe Toolbox", role="h1"))
        self._update_note = label("", role="muted")
        self._update_note.setVisible(False)
        title_row.addWidget(self._update_note, 0, Qt.AlignVCenter)
        title_row.addStretch(1)
        fl.addLayout(title_row)
        fl.addWidget(self._status_box(status))
        fl.addWidget(label("Available Tools", role="h1"))
        self._tools_container = self._tools_box()
        fl.addWidget(self._tools_container)
        fl.addStretch(1)
        scroll.setWidget(frame)

        self._load_rank(status.inventory)

    def set_update_note(self, text: str) -> None:
        """One quiet line under the status panel - '' hides it."""
        self._update_note.setText(text)
        self._update_note.setVisible(bool(text))

    # -- status panel -------------------------------------------------------

    def _status_box(self, status: core_home.PlayerStatus) -> QWidget:
        """The bordered identity + lights panel - same surface as the tools
        box. Rank badge (left) then name; lights on the right."""
        box = QWidget()
        box.setAttribute(Qt.WA_StyledBackground, True)
        box.setProperty("surface", "card")
        row = QHBoxLayout(box)
        row.setContentsMargins(t.SP_XL, t.SP_XL, t.SP_XL, t.SP_XL)
        row.setSpacing(t.SP_MD)
        # the mastery badge sits LEFT of the name and is filled off-thread; its
        # square slot is reserved so the name does not shift when it lands
        self._badge = QLabel()
        self._badge.setFixedHeight(BADGE_H)
        self._badge.setMinimumWidth(BADGE_H)
        self._badge.setAlignment(Qt.AlignCenter)
        row.addWidget(self._badge, 0, Qt.AlignVCenter)
        row.addWidget(label(status.name or "Not signed in", role="h1"),
                      0, Qt.AlignVCenter)
        row.addStretch(1)
        for i, (text, ok) in enumerate((("Market", status.market),
                                        ("Game Files", status.game_files),
                                        ("Profile", status.profile),
                                        ("Inventory", status.inventory))):
            if i:
                row.addSpacing(t.SP_LG)
            row.addLayout(self._light(text, ok))
        return box

    @staticmethod
    def _light(text: str, ok: bool) -> QHBoxLayout:
        """A connection light: a jade dot when connected, muted when not - a
        state, not an error, so 'off' is grey rather than red. Dot and label are
        vertically centred on each other."""
        h = QHBoxLayout()
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(t.SP_SM)
        h.addWidget(StatusDot(ok), 0, Qt.AlignVCenter)
        h.addWidget(label(text, role="small"), 0, Qt.AlignVCenter)
        return h

    def _load_rank(self, inventory: bool) -> None:
        """Read the mastery rank and fetch its badge on a worker, then draw it.
        The callback is a BOUND METHOD, so Qt drops it if this view is gone - a
        lambda's receiver would be the Job, which outlives the widget."""
        # Rank comes from the DE profile API, or the inventory blob as a fallback:
        # load it when either source is available.
        if self._badge is None or not (inventory or wf_profile.configured()):
            return
        self._mr_job = work.run(self._read_rank, self._set_rank)

    @staticmethod
    def _read_rank():
        """Worker body: the (cached) rank, plus the (cached/fetched) badge path.
        Both may hit disk or the network, which is why this is off-thread. The
        NEXT rank's badge is pre-cached too, so a level-up swaps in instantly."""
        # Prefer Warframe's own profile API (no AlecaFrame, no Overwolf); the
        # refresh is network but we're off the GUI thread and it self-throttles
        # to a few times a day. AlecaFrame is the fallback while unconfigured.
        wf_profile.refresh_if_stale()
        mr = wf_profile.read_mastery_cached()
        if mr is None:
            mr = arcane_inv.read_mastery_cached()
        if mr is None:
            return None
        path = str(mastery.ensure_badge(mr) or "")
        mastery.ensure_badge(mr + 1)          # pre-cache next rank, ignore result
        return (mr, path)

    def _set_rank(self, payload) -> None:
        if payload is None or not alive(self._badge):
            return
        mr, path = payload
        self._badge.setToolTip(mastery.rank_label(mr))
        pm = QPixmap(path) if path else QPixmap()
        if not pm.isNull():
            self._badge.setPixmap(pm.scaledToHeight(BADGE_H,
                                                    Qt.SmoothTransformation))
        else:                       # offline / unknown rank: compact text
            self._badge.setText(f"LR {mr - 30}" if mr > 30 else f"MR {mr}")

    # -- tool strip ---------------------------------------------------------

    def _tools_box(self) -> QWidget:
        """The bordered tools container. The card strip scrolls HORIZONTALLY
        inside it, so the border never moves with the cards."""
        box = QWidget()
        box.setAttribute(Qt.WA_StyledBackground, True)
        box.setProperty("surface", "card")
        v = QVBoxLayout(box)
        v.setContentsMargins(t.SP_XL, t.SP_XL, t.SP_XL, t.SP_XL)
        v.setSpacing(0)

        self._strip = QWidget()
        sl = QHBoxLayout(self._strip)
        # bottom pad puts a gap between the cards and the scrollbar below them
        sl.setContentsMargins(0, 0, 0, t.SP_LG)
        sl.setSpacing(t.SP_XL)
        for c in self._cards:
            sl.addWidget(c)
        sl.addStretch(1)          # left-pack the cards when the row is wider

        self._hscroll = _HScroll()
        self._hscroll.setWidget(self._strip)
        # Resizable keeps the strip's WIDTH in sync with the viewport; a fixed
        # height (set once the cards are sized) stops it stretching vertically,
        # and the cards' fixed WIDTH gives the strip a minimum width the scroll
        # area can't shrink below - which is what turns on the h-scrollbar.
        self._hscroll.setWidgetResizable(True)
        self._hscroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._hscroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._hscroll.setFrameShape(QFrame.NoFrame)
        v.addWidget(self._hscroll)
        return box

    def _size_cards(self) -> None:
        """Give every card one uniform height (the tallest blurb's), pin each
        media band to 16:9 at the fixed card width, and size the scroll strip
        to one card row. Runs once, on first show, when fonts are polished so
        heightForWidth is truthful."""
        if self._sized or not self._cards:
            return
        self._sized = True
        # subtract the card border on both sides too: it insets the content, so
        # measuring the blurb at the full inner width under-counts its wrap height
        # (and clips) once the border is more than a hairline.
        innerw = CARD_W - 2 * t.SP_XL - 2 * t.BORDER_W
        for c in self._cards:
            c.blurb.ensurePolished()
        body_h = max(c.blurb.heightForWidth(innerw) for c in self._cards)
        for c in self._cards:
            c.media.set_width(innerw)
            c.blurb.setMinimumHeight(body_h)
        # minimumSizeHint, NOT sizeHint: a wrapped label's sizeHint is its
        # PREFERRED size and ignores the setMinimumHeight above, so it would
        # size the card shorter than its own blurb needs. minimumSizeHint sums
        # the real floors (blurb's reserved wrap height, media's fixed 16:9).
        card_h = max(c.minimumSizeHint().height() for c in self._cards)
        for c in self._cards:
            c.setFixedHeight(card_h)
        # + SP_LG for the card->scrollbar gap baked into the strip's bottom pad
        self._strip.setFixedHeight(card_h + t.SP_LG)
        self._hscroll.setFixedHeight(card_h + t.SP_LG + SCROLLBAR_H)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._size_cards()
