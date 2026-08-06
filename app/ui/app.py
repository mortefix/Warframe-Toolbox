"""The PySide6 shell: header, sidebar, content stack.

Runs beside the Tk app, not instead of it - launch with `--qt` or
`WFTOOLBOX_UI=qt`. Screens are ported one at a time (Phase 3); anything not
yet ported shows a placeholder, so the shell is testable from day one.

Three pieces of Tk machinery simply cease to exist here:

  * `_persistent` / `on_show` / `on_hide` - QStackedWidget keeps every page it
    is given, so "build on first visit, then stay alive" is just "add the page
    the first time navigate() asks for it".
  * the `bind_all("<MouseWheel>")` claim/release protocol - Qt delivers wheel
    events to the widget under the pointer, so a hidden page cannot steal them.
  * `SetProcessDpiAwareness(0)` - Qt6 claims per-monitor-v2 at QApplication
    construction and nothing later overrides it (measured; the WebView2 flip
    that forced the old pin is a no-op once Qt has claimed first).
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QFont, QFontDatabase, QFontMetrics, QIcon
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QPushButton,
                               QStackedWidget, QVBoxLayout, QWidget)

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import config as core_config                        # noqa: E402
from core.gateway import Gateway                              # noqa: E402
from core import market as core_market                        # noqa: E402
from core import nav as core_nav                              # noqa: E402
from core import presence as core_presence                    # noqa: E402
from core import session as core_session                      # noqa: E402
from core import theme as t                                   # noqa: E402
from core import webapps as core_webapps                      # noqa: E402
from registry import TOOLS                                    # noqa: E402
from ui import icons                                          # noqa: E402
from ui import qss                                            # noqa: E402
from ui.bridge import PresenceBridge                          # noqa: E402
from ui.widgets import (Finial, clear_pixmap_cache, hairline,  # noqa: E402
                        label, logo_pixmap, panel, restyle, vline)

SIDEBAR_MIN_WIDTH = 150
#  finial rail + glyph + the nav button's left/right padding. Every row shares
#  this exact layout; the gold finial marks the current one.
SIDEBAR_CHROME = 10 + 26 + 16 + 12
#  The apps sit in three gold-bordered containers. These steal horizontal room
#  from each boxed row - the whole rail is inset from its edges, and each box
#  adds a 1px border plus interior padding on both sides - so the width has to
#  budget for it or the longest boxed label (My Listings) clips inside its box.
NAV_RAIL_MARGIN = 8          # inset of the rail's content from the sidebar edges,
                             # and the gap between the stacked groups (outside pad)
NAV_SECTION_PAD = 6          # padding inside each container, around its rows
NAV_SECTION_BORDER = t.BORDER_W  # the gold border, per side (qss uses the same)
NAV_SECTION_CHROME = 2 * (NAV_RAIL_MARGIN + NAV_SECTION_BORDER + NAV_SECTION_PAD)
NAV_TITLE_GAP = 3            # gap between a section's flat title and its box
HEADER_HEIGHT = 44
#: The smallest the window may be made. Below any plausible screen so the app
#: always fits the display it opens on, and low enough that a user can narrow
#: the window until the Home grid reflows down to a single card column. The
#: floor is set by Settings' fixed chrome (main sidebar + settings tree), which
#: still needs room for its content at this width.
MIN_WIDTH, MIN_HEIGHT = 680, 560
APP_TITLE = "Warframe Toolbox"      # the watcher matches this EXACTLY


class NavRow(QWidget):
    """One sidebar entry: [finial | glyph | label], the whole row clickable."""

    def __init__(self, item: core_nav.NavItem, on_click) -> None:
        super().__init__()
        self.key = item.key
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAttribute(Qt.WA_Hover, True)     # so :hover reaches the row
        self.setProperty("nav", "row")
        self.setProperty("active", "false")
        self.setCursor(Qt.PointingHandCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.finial = Finial(self)
        lay.addWidget(self.finial)
        # `item.icon` is a core.theme.ICONS key; the label carries the
        # Material ligature, which the icon font renders as the symbol
        self.icon = label(t.glyph(item.icon), role="icon")
        self.icon.setProperty("nav", "icon")
        lay.addWidget(self.icon)
        self.button = QPushButton(item.label)
        self.button.setProperty("nav", "item")
        self.button.setCursor(Qt.PointingHandCursor)
        self.button.clicked.connect(lambda: on_click(self.key))
        lay.addWidget(self.button, 1)

    def set_active(self, active: bool) -> None:
        self.finial.set_active(active)
        self.setProperty("active", "true" if active else "false")
        # the row's descendant selectors recolour the glyph and label, but Qt
        # only re-resolves them if those children are repolished too
        for w in (self, self.button, self.icon):
            restyle(w)

    def mouseReleaseEvent(self, event) -> None:
        # the whole row is the target, as in Tk - not just the label
        if event.button() == Qt.LeftButton:
            self.button.click()
        super().mouseReleaseEvent(event)


class Placeholder(QWidget):
    """Stands in for a screen not yet ported. Named so it is obvious in a
    screenshot that this is scaffolding, not a broken port."""

    def __init__(self, title: str) -> None:
        super().__init__()
        self.setAttribute(Qt.WA_StyledBackground, True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(t.SP_SCREEN, t.SP_XL, t.SP_SCREEN, t.SP_XL)
        lay.setSpacing(t.SP_LG)
        lay.addWidget(label(title, role="h1"))
        lay.addWidget(label("Not ported to Qt yet - run without --qt for the "
                            "working version of this screen.", role="muted"))
        lay.addStretch(1)


class StatusControl(QWidget):
    """Your visibility on warframe.market, pinned to the header.

    Three states, and the middle one is the point: warframe.market shows
    traders as offline / online / in-game, and in-game is what other players
    filter for. It is presence over a websocket, not a setting on your
    account, so it only holds while this app is running - which is exactly
    why it belongs in the chrome rather than buried in Settings.

    `connected` is shown separately from the state, because "In-game" with a
    dead socket looks identical to "In-game" and means the opposite. The
    detail line is where an outage becomes visible.
    """

    # The third field is the SELECTED chip's background fill. Offline's is a
    # muted SURFACE (not MUTED-the-text-colour) - see theme.MUTED_SURFACE.
    STATES = (("ingame", "In-game", t.WFM_TEAL),
              ("online", "Online", t.OK),
              ("offline", "Offline", t.MUTED_SURFACE))

    def __init__(self, on_pick) -> None:
        super().__init__()
        self.setAttribute(Qt.WA_StyledBackground, True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(t.SP_SM)

        self.dot = label("●", role="small")
        self.dot.setToolTip("websocket connection to warframe.market")
        lay.addWidget(self.dot)
        lay.addWidget(label("Status", role="muted"))

        self.buttons: dict[str, QPushButton] = {}
        for state, text, colour in self.STATES:
            b = QPushButton(text)
            b.setProperty("size", "small")
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip({
                "ingame": "appear in-game - what most buyers filter for",
                "online": "appear online, but not in-game",
                "offline": "disconnect; you appear offline to everyone",
            }[state])
            b.clicked.connect(lambda _c=False, s=state: on_pick(s))
            b._accent = colour
            self.buttons[state] = b
            lay.addWidget(b)

        self.detail = label("", role="small")
        lay.addWidget(self.detail)
        self.paint("offline", False, None)

    def paint(self, want: str, connected: bool, detail) -> None:
        for state, b in self.buttons.items():
            active = state == want
            b.setStyleSheet(
                f"color: {t.INK if active else t.TEXT};"
                f"background: {b._accent if active else t.PANEL};"
                f"border: none; padding: 3px 9px;")
        # offline is a CHOICE, not a fault: no socket is the correct state
        # there, so the dot stays neutral rather than reading as an error
        if want == "offline":
            role, tip = t.MUTED, "offline by choice"
        elif connected:
            role, tip = t.OK, "connected to warframe.market"
        else:
            role, tip = t.ERR, "not connected to warframe.market"
        self.dot.setStyleSheet(f"color: {role};")
        self.dot.setToolTip(tip)
        self.detail.setText(str(detail) if detail else "")
        self.detail.setStyleSheet(
            f"color: {t.ERR if detail and not connected else t.MUTED};")


class SignInRequired(QWidget):
    """Shown in place of a screen that cannot work without a linked account.

    Better than an empty screen full of dead controls: the reason is the
    content, and the fix is one click away.
    """

    def __init__(self, on_link) -> None:
        super().__init__()
        self.setAttribute(Qt.WA_StyledBackground, True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(t.SP_SCREEN, t.SP_XL, t.SP_SCREEN, t.SP_XL)
        lay.setSpacing(t.SP_LG)
        lay.addWidget(label("My Listings", role="h1"))
        lay.addWidget(label("Sign in to warframe.market to see and manage "
                            "your orders.", role="muted"))
        btn = QPushButton("Link account")
        btn.setProperty("kind", "money")
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(on_link)
        row = QHBoxLayout()
        row.addWidget(btn)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addStretch(1)


class MainWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_TITLE)     # the watcher looks for this title
        # The WINDOW icon: what alt-tab (and an unpinned taskbar button)
        # shows. The caption's copy is stripped in _hide_caption_icon() -
        # the crest already lives in the app's own header, and a second
        # logo stacked above it in the corner reads as a mistake.
        self.setWindowIcon(QIcon(str(ROOT / "assets" / "logo.ico")))
        self.setAttribute(Qt.WA_StyledBackground, True)
        # Geometry is applied by show_configured(), not here - the saved
        # settings have not been loaded yet at this point in __init__.
        #
        # But the FLOOR is set here, and it has to be. A QStackedWidget's
        # minimum is the MAXIMUM of every page it holds, so the window can
        # only ever shrink to the widest screen the user has visited. One
        # unwrapped sentence on My Listings put that floor at 2173px - wider
        # than this machine's 1365px desktop - and "window size" appeared to
        # do nothing, because none of the offered sizes were reachable.
        #
        # Wrapping the labels fixed that instance; this stops the NEXT one
        # from holding the window hostage. Pages scroll, so a page that wants
        # more room gets a scrollbar rather than a veto.
        self.setMinimumSize(MIN_WIDTH, MIN_HEIGHT)
        # the ONE widget that paints the page colour; everything else is
        # transparent or declares its own surface (see ui/qss.py)
        self.setProperty("surface", "app")

        self._rows: dict[str, NavRow] = {}
        self._pages: dict[str, int] = {}   # nav key -> QStackedWidget index
        self.current = ""
        # The account link is shared with the Tk app through the same cached
        # session file, so signing in there shows up here on next launch.
        self.session = core_session.load()
        self.settings = core_config.load_settings()
        self._pending_wiki: str | None = None
        self._tray = None            # built on the first minimise, if wanted
        self._quitting = False       # set by the tray's Quit, so closeEvent
                                     # tells a real exit from a hide-to-tray
        # order_id -> the price a repricer limit derives from. Owned by
        # the shell, not the screen, because it must survive navigating
        # away and back: it records the price at FIRST SIGHT this
        # session, which is what makes an auto limit stable.
        self.listing_baseline: dict[str, int] = {}
        # the authenticated client once an account is linked; None until then
        self.market = (core_market.MarketClient(self.session)
                       if self.session else None)
        self._public_market = None

        # Presence runs its own websocket thread. Qt queues a cross-thread
        # emit automatically, so unlike Tk there is no after(0, ...) hop and
        # no destroyed-widget guard - the bridge is the whole adapter.
        # The ONLY road from a tool to warframe.market. Tools are launched
        # with its address and a launch token in their environment; one
        # started without them exits immediately, which is exactly what the
        # API check was doing when Settings ran it bare.
        self.gateway = Gateway()
        self.gateway.session = self.session
        self.gateway.start()

        self.presence = core_presence.Presence()
        self.presence.session = self.session
        self._presence_bridge = PresenceBridge()
        self._presence_bridge.changed.connect(self._on_presence)
        self.presence.on_change = self._presence_bridge.callback

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # -- header
        header = panel("header")
        header.setFixedHeight(HEADER_HEIGHT)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(t.SP_LG, 0, t.SP_SCREEN, 0)
        hl.setSpacing(t.SP_MD)
        self._crest = crest = QLabel()
        crest.setPixmap(logo_pixmap(26))     # 20% larger; tinted to the title ink
        crest.setStyleSheet("background: transparent;")
        hl.addWidget(crest)
        self.title = label("", role="app_title")
        hl.addWidget(self.title)
        hl.addStretch(1)
        self.status = StatusControl(self._set_presence)
        self.status.setEnabled(self.session is not None)
        hl.addWidget(self.status)
        hl.addSpacing(t.SP_LG)
        self.account = label(
            self.session.username if self.session else "not signed in",
            role="small")
        hl.addWidget(self.account)
        outer.addWidget(header)
        outer.addWidget(hairline())

        # -- sidebar | content
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self._side = side = panel("sidebar")
        sl = QVBoxLayout(side)
        sl.setContentsMargins(NAV_RAIL_MARGIN, NAV_RAIL_MARGIN,
                              NAV_RAIL_MARGIN, NAV_RAIL_MARGIN)
        sl.setSpacing(NAV_RAIL_MARGIN)

        def add_row(item, into, indent=0):
            row = NavRow(item, self.navigate)
            if indent:
                # nudge the row's content right (not the widget) so its finial
                # and glyph share the column of the boxed apps; the row itself
                # still spans the rail, so its highlight is full-width
                row.layout().setContentsMargins(indent, 0, 0, 0)
            self._rows[item.key] = row
            into.addWidget(row)

        # Home pinned top and Settings pinned bottom sit directly on the rail
        # (no box); the apps between them fill three gold-bordered containers,
        # each under a flat title. Title + box live in a transparent wrapper so
        # the title hugs its box (NAV_TITLE_GAP) while the rail's own spacing
        # (NAV_RAIL_MARGIN) sets the looser gap between whole groups. The pinned
        # rows are indented so every icon lines up: a boxed row is pushed right by
        # the container's PADDING only (Qt's QSS border is painted but doesn't
        # inset the child layout), so the indent matches that padding, not +border.
        pin_indent = NAV_SECTION_PAD
        add_row(core_nav.HOME, sl, indent=pin_indent)   # pinned top
        for section in core_nav.sidebar_sections(TOOLS):
            wrap = QWidget()
            wl = QVBoxLayout(wrap)
            wl.setContentsMargins(0, 0, 0, 0)
            wl.setSpacing(NAV_TITLE_GAP)
            # a plain caption: no glyph, no indent, no hover/active state ever
            wl.addWidget(label(section.title.upper(), role="caps"))
            box = panel("nav_section")
            bl = QVBoxLayout(box)
            bl.setContentsMargins(NAV_SECTION_PAD, NAV_SECTION_PAD,
                                  NAV_SECTION_PAD, NAV_SECTION_PAD)
            bl.setSpacing(0)
            for item in section.items:
                add_row(item, bl)
            wl.addWidget(box)
            sl.addWidget(wrap)
        sl.addStretch(1)                          # push Settings to the bottom
        add_row(core_nav.SETTINGS, sl, indent=pin_indent)   # pinned bottom

        # Width follows the longest label rather than a hardcoded 186px: the
        # nav is built from the registry, so a tool with a long name would
        # otherwise be clipped by a number nobody remembers to update.
        side.setFixedWidth(self._sidebar_width(core_nav.nav_items(TOOLS)))
        body.addWidget(side)
        body.addWidget(vline())

        self.stack = QStackedWidget()
        body.addWidget(self.stack, 1)
        outer.addLayout(body, 1)

        self.navigate("home")

    def _sidebar_width(self, items) -> int:
        """Widest nav label, measured in the h2 face the buttons actually use,
        plus the finial rail, the glyph and the button's own padding.

        The face is BUILT from core.theme rather than read off a button. A
        style sheet's font rule lands when the widget is polished, which has
        not happened during __init__ - a nav button still reports "Segoe UI 9"
        here, so measuring it sized the rail against a font it never draws in.
        That went unnoticed only because the undersized answer fell below
        SIDEBAR_MIN_WIDTH: the floor returned the right number for the wrong
        reason, and the first long tool name would have clipped.
        """
        # the nav labels draw in the "nav_title" face, so the rail must be
        # measured in that face - a theme can make it wide (e.g. Orbitron) and a
        # width computed from h2 would clip. Defaults to the h2 face, so the
        # base themes size identically.
        fm = QFontMetrics(QFont(
            t.resolve_family("nav_title", set(QFontDatabase.families())),
            t.size_of("nav_title")))
        widest = max(fm.horizontalAdvance(i.label) for i in items)
        # + NAV_SECTION_CHROME: the widest label is a BOXED app, so budget for
        # the rail inset and the container's border + padding it sits inside.
        return max(SIDEBAR_MIN_WIDTH,
                   widest + SIDEBAR_CHROME + NAV_SECTION_CHROME)

    # -- navigation ---------------------------------------------------------

    def _build(self, key: str) -> QWidget:
        """Make the page for `key`. Phase 3 fills these in one screen at a
        time; anything not yet ported falls through to a placeholder."""
        if key == "home":
            from ui.home import HomeView
            return HomeView(TOOLS, self.navigate, self.link_account,
                            lambda: self.session is not None,
                            lambda: self.session.username if self.session
                            else "")
        if key == "market":
            from ui.market import MarketView
            return MarketView(self.market_any(), self.settings,
                              self.session.username if self.session else "",
                              open_wiki=self.open_wiki,
                              on_posted=self._refresh_listings)
        if key == "settings":
            from ui.settings import SettingsView
            return SettingsView(self)
        if key in core_webapps.WEB_KEYS:
            from ui.web import WebAppView
            view = WebAppView(core_webapps.BY_KEY[key])
            # a wiki glyph clicked before the tab existed left a pending URL
            if key == "web_wiki" and self._pending_wiki:
                view.open_url(self._pending_wiki)
                self._pending_wiki = None
            return view
        if key == "listings":
            if self.market is None:
                return SignInRequired(self.link_account)
            from ui.listings import ListingsView
            return ListingsView(self.market, self.session,
                                self.listing_baseline, self.open_wiki)
        if key == "vosfor":
            from ui.vosfor import VosforView
            return VosforView(self.settings, self.open_wiki,
                              lambda: core_config.save_settings(self.settings),
                              self.market_any)
        if key == "mods":
            from ui.mods import ModsView
            return ModsView(self.open_wiki, self.open_overframe)
        tool = next((x for x in TOOLS if x.id == key), None)
        if tool is not None:
            from ui.runner import RunnerView
            return RunnerView(self, tool)
        return Placeholder(core_nav.labels(TOOLS).get(key, key))

    def market_any(self):
        """A market client that always works: the authenticated one when an
        account is linked, else a shared public (read-only) client. Public
        endpoints - order books, item index, contracts - need no session."""
        if self.market is not None:
            return self.market
        if self._public_market is None:
            self._public_market = core_market.MarketClient(None)
        return self._public_market

    # -- presence -----------------------------------------------------------

    def _set_presence(self, state: str) -> None:
        """Repaint from the WANTED state immediately, then let the socket
        confirm. Waiting for the round trip makes the buttons feel broken on
        a slow or dead connection - which is exactly when you are clicking
        them."""
        self.presence.set_state(state)
        self.status.paint(self.presence.want, self.presence.connected, None)

    def _on_presence(self, _state: str, connected: bool, detail) -> None:
        self.status.paint(self.presence.want, connected, detail)

    def show_configured(self) -> None:
        """Show the window the way the saved settings ask for.

        This is why "Launch fullscreen" appeared to do nothing: the setting
        was written and read back correctly, and nothing ever consulted it -
        the window was sized from the screen and shown unconditionally. All
        three launch settings are applied here, in one place, so a new one
        cannot be added and silently ignored the same way.
        """
        screens = QApplication.screens()
        try:
            index = int(self.settings.get("monitor", 1)) - 1
        except (TypeError, ValueError):
            index = 0
        screen = (screens[index] if 0 <= index < len(screens)
                  else QApplication.primaryScreen())
        avail = screen.availableGeometry()

        size = str(self.settings.get("window_size", "1280x720"))
        try:
            want_w, want_h = (int(n) for n in size.lower().split("x"))
        except ValueError:
            want_w, want_h = 1280, 720
        # never larger than the screen it opens on: a 1920x1080 setting on a
        # 1365x720 desktop would otherwise hang off the bottom edge
        self.resize(min(want_w, avail.width() - 40),
                    min(want_h, avail.height() - 40))
        self.move(avail.center() - self.rect().center())

        if self.settings.get("fullscreen"):
            self.showMaximized()
            return
        # showNormal FIRST, then resize again: a maximized window ignores
        # resize(), so turning the setting off and re-applying would leave the
        # window maximized and look like the setting did nothing.
        if self.isMaximized():
            self.showNormal()
            self.resize(min(want_w, avail.width() - 40),
                        min(want_h, avail.height() - 40))
        self.show()

    def event(self, ev):  # noqa: N802 (Qt override)
        # The caption-icon blank must survive native-handle RECREATION:
        # embedding the first QtWebEngine view tears down and rebuilds this
        # top level's hwnd (measured 2026-08-05 - a tweak applied at +200ms
        # was on a dead handle by the +400ms web warmup). Qt announces every
        # handle change with WinIdChange; re-apply on the NEW handle, deferred
        # a tick so the recreated window finishes its native setup first.
        if ev.type() == QEvent.WinIdChange:
            QTimer.singleShot(0, self._hide_caption_icon)
        return super().event(ev)

    def _hide_caption_icon(self) -> None:
        """Blank the icon in the native title bar (Windows only).

        The window icon must exist for alt-tab (that reads ICON_BIG), but
        the caption would draw a second copy of the crest right above the
        header's own. Windows 11's DWM caption ignores the classic
        WS_EX_DLGMODALFRAME trick (measured 2026-08-05) and falls back down
        the chain ICON_SMALL -> ICON_BIG -> class icon, drawing SOMETHING no
        matter what gets nulled - so the working move is to hand it a fully
        TRANSPARENT ICON_SMALL: the caption draws nothing, alt-tab keeps the
        crest from ICON_BIG."""
        from PySide6.QtGui import QGuiApplication
        if QGuiApplication.platformName() != "windows":
            return                        # offscreen tests, future Linux
        import ctypes
        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32
        # 64-bit safety: handles are pointers; without explicit types ctypes
        # truncates them to 32-bit ints.
        gdi32.CreateBitmap.restype = ctypes.c_void_p
        user32.CreateIconIndirect.restype = ctypes.c_void_p
        user32.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                                        ctypes.c_void_p, ctypes.c_void_p]

        if getattr(self, "_blank_hicon", None) is None:
            class _ICONINFO(ctypes.Structure):
                _fields_ = [("fIcon", ctypes.c_int),
                            ("xHotspot", ctypes.c_uint),
                            ("yHotspot", ctypes.c_uint),
                            ("hbmMask", ctypes.c_void_p),
                            ("hbmColor", ctypes.c_void_p)]
            # AND mask all ones (leave screen), 32bpp colour all zero
            # (alpha 0) -> an icon that draws nothing at all.
            mask = gdi32.CreateBitmap(16, 16, 1, 1, b"\xff" * 64)
            color = gdi32.CreateBitmap(16, 16, 1, 32, b"\x00" * (16 * 16 * 4))
            info = _ICONINFO(1, 0, 0, mask, color)
            # kept for the process lifetime on purpose - the caption holds it
            self._blank_hicon = user32.CreateIconIndirect(ctypes.byref(info))
        if self._blank_hicon:
            WM_SETICON, ICON_SMALL = 0x0080, 0
            user32.SendMessageW(int(self.winId()), WM_SETICON, ICON_SMALL,
                                self._blank_hicon)

    # -- tray ---------------------------------------------------------------

    def _build_tray(self):
        """A QSystemTrayIcon, replacing 143 lines of ctypes Shell_NotifyIcon.

        Built lazily on the first minimise rather than at launch: someone who
        never turns the setting on should never get a tray icon, and creating
        one costs a window handle.
        """
        if self._tray is not None:
            return self._tray
        from PySide6.QtGui import QIcon
        from PySide6.QtWidgets import QMenu, QSystemTrayIcon
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return None
        icon = QIcon(str(ROOT / "assets" / "logo.ico"))
        tray = QSystemTrayIcon(icon, self)
        tray.setToolTip(APP_TITLE)
        menu = QMenu()
        menu.addAction("Open", self._restore)
        menu.addSeparator()
        menu.addAction("Quit", self._quit)
        tray.setContextMenu(menu)
        # left click OR double click restores - the Tk version's rule, kept
        # because a tray icon that only answers double clicks feels broken
        tray.activated.connect(
            lambda reason: self._restore()
            if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                          QSystemTrayIcon.ActivationReason.DoubleClick)
            else None)
        self._tray = tray
        return tray

    def _restore(self) -> None:
        # come back the way we left: a window minimised FROM maximised should
        # return to maximised, not shrink to a normal frame
        if getattr(self, "_was_maximized", False):
            self.showMaximized()
        else:
            self.showNormal()
        self.raise_()
        self.activateWindow()
        if self._tray is not None:
            self._tray.hide()

    def _quit(self) -> None:
        """A real exit from the tray. Without the flag, closeEvent would just
        hide back to the tray again (close-to-tray); setting it makes the next
        close a genuine shutdown."""
        self._quitting = True
        self.close()

    def changeEvent(self, event) -> None:
        """Hide to the tray when minimised, if that is what was asked for.

        The setting is read HERE rather than cached at startup, so toggling
        it in Settings takes effect immediately instead of at the next launch.
        """
        from PySide6.QtCore import QEvent
        if (event.type() == QEvent.Type.WindowStateChange
                and self.isMinimized()
                and self.settings.get("minimize_to_tray")):
            # remember the state we came from so _restore returns to it - the
            # old code always came back un-maximized. event.oldState() still
            # holds the pre-minimize flags.
            self._was_maximized = bool(
                event.oldState() & Qt.WindowState.WindowMaximized)
            tray = self._build_tray()
            if tray is not None:
                tray.show()
                # deferred: hiding inside the state-change handler leaves Qt
                # mid-transition and the window can come back on its own
                QTimer.singleShot(0, self.hide)
        super().changeEvent(event)

    def closeEvent(self, event) -> None:
        # Close-to-tray: unless we are really quitting (the tray's Quit sets
        # _quitting), hide to the notification area instead of shutting down, so
        # the helper stays ready beside the game. Falls through to a real exit
        # when the setting is off or no system tray is available.
        if not self._quitting and self.settings.get("close_to_tray"):
            self._was_maximized = self.isMaximized()
            tray = self._build_tray()          # None if no tray is available
            if tray is not None:
                tray.show()
                event.ignore()
                self.hide()
                return
        # the websocket thread would outlive the window otherwise
        self.presence.shutdown()
        self.gateway.stop()
        # Web pages FIRST, then the profile. Chromium flushes its cookie
        # store when the profile is destroyed, and nothing ever destroyed
        # ours - so a clearance or a login earned late in the session was
        # lost on exit. A page outliving its profile crashes, hence the order.
        try:
            from ui import web as _web
            for _key in core_webapps.WEB_KEYS:
                _index = self._pages.get(_key)
                if _index is not None:
                    _page = self.stack.widget(_index)
                    if _page is not None:
                        _page.setParent(None)
                        _page.deleteLater()
            QApplication.processEvents()
            _web.shutdown()
        except Exception:                       # noqa: BLE001
            pass                                # never block a close
        if self._tray is not None:
            self._tray.hide()          # or it lingers in the notification area
        super().closeEvent(event)

    def open_wiki(self, name: str) -> None:
        """A wiki glyph deep-links the Wiki TAB, never an external browser.

        The article URL is derived before navigating, so a tab that has never
        been built still lands on the right page: `_build` hands the pending
        URL straight to the new view, and the view holds it until its first
        showEvent. That ordering is why the Tk version's equivalent dropped
        deep links onto the wiki home page.
        """
        from core import wiki as core_wiki
        url = core_wiki.url_for(name)
        self._pending_wiki = url
        self.navigate("web_wiki")
        page = self.stack.widget(self._pages["web_wiki"])
        if hasattr(page, "open_url") and self._pending_wiki:
            page.open_url(url)
            self._pending_wiki = None

    def open_overframe(self, url: str) -> None:
        """Deep-link the embedded Overframe TAB (build guides for a mod) -
        same never-an-external-browser rule as open_wiki."""
        self.navigate("web_builds")
        page = self.stack.widget(self._pages["web_builds"])
        if hasattr(page, "open_url"):
            page.open_url(url)

    # -- account and data ---------------------------------------------------

    def unlink_account(self) -> None:
        """Drop the saved session. Every screen built while linked holds a
        client bound to it, so they are discarded rather than repaired - a
        half-updated Market view is worse than one that rebuilds."""
        from core import session as _session
        self.presence.set_state("offline")
        _session.logout()
        self.session = None
        self.market = None
        self.gateway.session = None      # live tools see the change too
        self.listing_baseline.clear()
        self.account.setText("not signed in")
        self.status.setEnabled(False)
        # home too: HomeView's buttons say different things linked vs not
        self._drop_pages("listings", "market", "settings", "home")
        self.navigate("home")

    def bookmarks_changed(self) -> None:
        """A web tab's drawer may be showing a list that no longer exists."""
        for key in core_webapps.WEB_KEYS:
            index = self._pages.get(key)
            if index is None:
                continue
            page = self.stack.widget(index)
            if hasattr(page, "drawer"):
                page.drawer.reload()
                page._paint_star()

    def wipe_user_data(self) -> None:
        """Delete everything the app has written, then rebuild from defaults.

        Cached screens are dropped rather than refreshed: they hold the very
        data that was just deleted and would happily write it straight back
        out on the next save.
        """
        for name, path, _desc, _size in core_config.user_data_files():
            if name != "wfm_session.json":
                core_config.delete_user_file(path)
        core_config.clear_thumb_cache()
        core_config.clear_wf_data()      # the collected profile/world/item store
        try:
            from ui import web as _web
            _web.clear_all_data()
        except Exception:                       # noqa: BLE001
            pass
        # the retired Tk front end's WebView2 profile (if any remains): a
        # wipe that leaves ~195 MB of old cookies and history behind is a
        # wipe the user cannot trust
        import shutil
        shutil.rmtree(ROOT / ".webview", ignore_errors=True)
        core_config.set_start_with_windows(False)
        core_config.set_watch_warframe(False)
        self.settings.clear()
        self.settings.update(core_config.load_settings())
        self.listing_baseline.clear()
        # settings too: its pages show pre-wipe values otherwise, and the
        # session page is only dropped by unlink_account (session-only)
        self._drop_pages("listings", "market", "vosfor", "home",
                         "settings")
        if self.session is not None:
            self.unlink_account()

    def _drop_pages(self, *keys: str) -> None:
        """Forget cached pages so they are rebuilt on the next visit.

        Widgets are captured by IDENTITY before anything is removed.
        QStackedWidget renumbers on every removal, so an index taken
        beforehand refers to a different page afterwards - reading the map
        back through stale indices would silently reassign screens to each
        other's keys.
        """
        pages = {k: self.stack.widget(i) for k, i in self._pages.items()}
        for key in keys:
            page = pages.pop(key, None)
            if page is not None:
                self.stack.removeWidget(page)
                page.deleteLater()
        self._pages = {k: self.stack.indexOf(w) for k, w in pages.items()}

    def apply_theme(self, name: str) -> None:
        """Switch theme LIVE, without restarting the app. The palette + font
        faces are re-applied to core.theme's globals, the app stylesheet is
        regenerated (Qt re-polishes every styled widget), the few non-QSS shell
        visuals are refreshed, and the cached pages are dropped so each rebuilds
        in the new theme on its next view.

        The page rebuild is DEFERRED to the next event-loop tick: this is called
        from the Settings theme picker, which lives on a page the rebuild
        deletes, and deleting a widget from inside its own signal handler is the
        very crash this codebase guards against elsewhere.
        """
        t.set_theme(name)
        icons.clear_cache()
        clear_pixmap_cache()
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(qss.build(set(QFontDatabase.families())))
        # non-QSS shell bits: the tinted crest, the sidebar width (a theme may
        # change the nav font's advance), the painted gold finials, and the
        # status chips (whose state colour is set in code, not in the sheet).
        self._crest.setPixmap(logo_pixmap(26))
        self._side.setFixedWidth(self._sidebar_width(core_nav.nav_items(TOOLS)))
        for row in self._rows.values():
            row.update()
        self.status.paint(self.presence.want, self.presence.connected, None)
        QTimer.singleShot(0, self._retheme_pages)

    def _retheme_pages(self) -> None:
        """Rebuild the current page in the new theme and forget the rest, so a
        page's inline-styled / hand-painted parts (item-name colours, the Vosfor
        bars) come back correct. The others rebuild lazily on their next visit."""
        current = self.current
        self._drop_pages(*list(self._pages))
        if current:
            self.navigate(current)

    def link_account(self) -> None:
        from ui.dialogs import LoginDialog
        dialog = LoginDialog(self)
        accepted = dialog.exec() == dialog.DialogCode.Accepted
        session = dialog.session if accepted else None
        dialog.deleteLater()        # else it lingers as a hidden child of the window
        if not accepted:
            return
        self.adopt_session(session)

    def adopt_session(self, session) -> None:
        """Take a freshly signed-in session.

        Every screen built while signed OUT holds a client that is either
        None or read-only, so they are discarded rather than patched - the
        mirror image of unlink_account, and for the same reason: a half
        updated Market view is worse than one that rebuilds.
        """
        self.session = session
        self.gateway.session = session       # live tools pick this up too
        self.market = core_market.MarketClient(session)
        self.presence.set_session(session)
        self.listing_baseline.clear()
        self.account.setText(session.username)
        self.status.setEnabled(True)
        self._drop_pages("listings", "market", "settings", "home")
        self.navigate("home")

    def navigate(self, key: str) -> None:
        """Show a screen, building it on first visit and keeping it after.

        No on_show/on_hide, no _persistent set, no park-before-destroy
        ordering: the stack owns every page for the life of the window.
        """
        if key not in self._pages:
            self._pages[key] = self.stack.addWidget(self._build(key))
        self.stack.setCurrentIndex(self._pages[key])
        self.current = key
        # a STATIC app-name prefix in front of the loaded screen's name, so the
        # header always reads "Warframe Toolbox - <screen>"
        name = core_nav.labels(TOOLS).get(key, "")
        self.title.setText(f"{APP_TITLE} - {name}" if name else APP_TITLE)
        self._paint_active(key)

    def _paint_active(self, key: str) -> None:
        """The gold finial + highlight on the selected row; every other row off."""
        for row in self._rows.values():
            row.set_active(False)
        row = self._rows.get(key)
        if row is not None:
            row.set_active(True)

    def _refresh_listings(self) -> None:
        """Freshen My Listings if it's been built, so an order posted from the
        Market browser shows there without a manual Refresh Listings."""
        index = self._pages.get("listings")
        if index is None:
            return
        page = self.stack.widget(index)
        if hasattr(page, "refresh"):
            page.refresh()

    def _preload_web(self) -> None:
        """Warm the web engine and pre-fetch every web tab shortly after launch.

        Lazy loading kept startup free of network, but it made the FIRST switch
        to a web tab pay for a cold Chromium page build - a live, progressive,
        occasionally torn load. Here each web view is built into the stack
        HIDDEN (exactly a first visit, minus making it current) and its home
        page loaded in the background, so switching to it later shows a ready,
        fully-painted page. Staggered per tab so the warm-up never contends with
        the launch or with itself; the user has opted into spending the RAM."""
        delay = 0
        for key in core_webapps.WEB_KEYS:
            QTimer.singleShot(delay, lambda k=key: self._preload_one(k))
            delay += 700                  # ms apart: warm, not a stampede

    def _preload_one(self, key: str) -> None:
        from ui.web import WebAppView
        if key in self._pages:
            return                        # the user already opened it
        view = self._build(key)
        self._pages[key] = self.stack.addWidget(view)
        if isinstance(view, WebAppView):
            view.preload()

    def _refresh_collected_data(self) -> None:
        """Populate/refresh the local data store in the background. Fire-and-
        forget: the callback is a bound method (so Qt drops it if the window is
        gone) and touches no widgets, so a slow refresh can never stall or
        outlive the UI."""
        from core import collect
        from ui import work
        self._collect_job = work.run(collect.run_startup_refresh,
                                     self._collected_done)

    def _collected_done(self, result: dict) -> None:
        """Refresh finished. Just record the outcome - the store is already
        written, and Home recomputes its lights (and re-triggers the profile
        read) on its next rebuild, so there is no widget to poke here."""
        self._last_collect = result

    def _check_updates(self) -> None:
        """Launch-time self-update (core.updater), off-thread. Silent unless
        it actually updated; every rail (toggle, branch, dirty tree) lives in
        the core module."""
        from core import updater as core_updater
        from ui import work

        def job(settings=dict(self.settings)):
            return core_updater.check_and_update(settings)

        self._update_job = work.run(job, self._update_check_done)

    def _update_check_done(self, result) -> None:
        """Update finished. The new code applies next launch; all this does
        is show one quiet line on Home."""
        if not getattr(result, "updated", False) or not result.new_version:
            return
        index = self._pages.get("home")
        if index is None:
            return
        view = self.stack.widget(index)
        if view is not None and hasattr(view, "set_update_note"):
            view.set_update_note(f"Updated to {result.new_version} — "
                                 f"takes effect next launch.")


def main(argv: list[str] | None = None) -> int:
    app = QApplication(argv if argv is not None else sys.argv[:1])
    app.setApplicationName(APP_TITLE)

    # ONE instance. The browser profile is locked to a single process; a
    # second app sharing it gets "Unable to move the cache: Access is denied",
    # an unwritable cookie DB and a dead GPU cache - which presents as
    # Cloudflare re-challenging every launch, black screens, and uncached
    # loads. All three were observed live when another process held the
    # profile. Refusing to start is strictly better than starting broken.
    from PySide6.QtCore import QLockFile
    from core import paths as core_paths
    lock = QLockFile(str(core_paths.USERDATA / "wftoolbox.lock"))
    lock.setStaleLockTime(0)          # a dead process must not wedge us
    if not lock.tryLock(100):
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(
            None, APP_TITLE,
            "Warframe Toolbox is already running.\n\n"
            "Two copies cannot share the embedded browser's profile - "
            "check the taskbar or the notification area for the open one.")
        return 0
    app._wftb_lock = lock             # hold it for the process lifetime
    # Heal HKCU Run entries whose baked-in absolute paths went stale (folder
    # moved, Python reinstalled). After the lock: only the surviving instance
    # may touch the registry.
    core_config.repair_run_entries()
    app.setStyleSheet(qss.build(set(QFontDatabase.families())))
    win = MainWindow()
    win.show_configured()
    # Warm the web engine and pre-fetch the web tabs a beat after the window is
    # up, so the first switch to Wiki/Overframe shows a ready page. Deferred so
    # the home screen paints first and launch still feels instant.
    QTimer.singleShot(400, win._preload_web)
    # Warm the collected-data store (profile, world state, EE.log events, item
    # DB) in the background, after the window is up. Deferred and off-thread so
    # launch stays instant; each refresher self-throttles and swallows errors.
    QTimer.singleShot(1500, win._refresh_collected_data)
    # Self-update last: it may shell out to git/pip, so it waits for the
    # window and the data warmups to be on their way first.
    QTimer.singleShot(3000, win._check_updates)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
