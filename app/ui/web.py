"""The embedded web apps, on QtWebEngine.

This replaces a 668-line Win32/pywebview/WebView2 host with a widget. What
went away was never about the web - it was about hosting a foreign HWND
inside Tk: the one-batch window creation constraint, the `SetParent`
re-parenting dance, `WS_CHILD` style stripping, the `_armed`/`_wanted`/
`_navigating` state machine that existed because navigation had to wait for
an ad blocker attached over a .NET Invoke, the GC pin on the event hooks, the
`'MainThread'` naming hack, and `os._exit(0)`. A `QWebEngineView` is an
ordinary widget in a `QStackedWidget`; hiding it is just hiding it.

What survives is `core.adblock` - the blocklist, the cosmetic selectors, the
injected sweeper and the per-site tweaks - because none of that was ever
about the engine.

THREE THINGS HERE ARE LOAD-BEARING, and each one fails quietly:

  1. The profile must be NAMED. `QWebEngineProfile()` with no arguments is
     off-the-record: it works perfectly and discards every cookie on exit, so
     the failure looks like "the sites keep logging me out" a day later.
  2. The user agent must present as plain Chrome. Claiming to be Edge -
     which the migration plan called for - is what makes overframe.gg serve a
     Cloudflare challenge; see `chrome_user_agent` for the measurements.
     A `cf_clearance` cookie is bound to the fingerprint it was issued under,
     so one earned under a DIFFERENT user agent is rejected forever after -
     changing the UA means clearing that cookie once.
  3. The interceptor must be installed on the profile BEFORE any page loads,
     or the first wave of ad requests goes out unfiltered.

Portability note: QtWebEngine ships for Linux as well, which is the whole
reason this replaced WebView2 - see [[linux-portability-goal]].
"""

from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWebEngineCore import (QWebEngineProfile, QWebEngineScript,
                                     QWebEngineSettings,
                                     QWebEngineUrlRequestInterceptor)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QMessageBox,
                               QPushButton, QScrollArea, QVBoxLayout,
                               QWidget)

from core import adblock
from core import config as core_config
from core import bookmarks as core_bookmarks
from core import theme as t
from core import webapps
from ui.overlay import SlideOver
from ui.widgets import bookmark_icon, glyph_icon, hairline, label, panel

#: The browser profile. A Chromium profile directory is LOCKED to one process:
#: a second process using it gets "Unable to move the cache: Access is denied",
#: a read-only cookie DB and a dead GPU cache - which presents as Cloudflare
#: re-challenging every launch, black screens, and uncached (slow) loads.
#: Measured live when a backgrounded test suite held this directory during a
#: real launch. Hence `isolate_for_tests()` below and the QLockFile guard in
#: ui/app.py: nothing but the one running app may ever open this path.
from core import paths as core_paths
PROFILE_DIR = core_paths.USERDATA / "webengine"


def isolate_for_tests() -> Path:
    """Point this module at a throwaway profile. EVERY test or probe that so
    much as constructs a WebAppView must call this first - building a page
    builds the profile, and the real one belongs to the running app."""
    global PROFILE_DIR
    import tempfile
    PROFILE_DIR = Path(tempfile.mkdtemp(prefix="wftb_test_profile_"))
    return PROFILE_DIR
PROFILE_NAME = "wftoolbox"
#: Fluent "Bookmarks" - a list, deliberately NOT the ribbon. The ribbon
#: means "this page"; this button means "all the saved ones", and giving
#: them the same mark would make the pair ambiguous.
BOOKMARKS_GLYPH = "bookmarks"


def chrome_user_agent() -> str:
    """The engine's own user agent, minus the QtWebEngine token.

    This CORRECTS the migration plan, which called for a hardcoded Edge UA on
    the theory that the default's "QtWebEngine/6.11.1" token was what made
    overframe.gg serve a Cloudflare interstitial. Measured 2026-07-31, one
    throwaway profile per variant so no cf_clearance cookie could carry over:

        default (QtWebEngine token present)   -> loads the site
        plain Chrome (token removed)          -> loads the site
        Edge (Edg/140.0.0.0 appended)         -> "Just a moment..." forever

    Claiming to be Edge is what TRIGGERS the challenge: Edge sends `Sec-CH-UA`
    client hints identifying itself, QtWebEngine does not, and a UA that says
    Edge without Edge's hints reads as a bot. The default passes on its own;
    the token is dropped anyway because it is a needless fingerprint.

    Derived at runtime rather than pinned, so the Chrome version stays correct
    across Qt upgrades - a hardcoded string goes stale silently and a stale
    version is exactly what bot checks look for.
    """
    ua = QWebEngineProfile.defaultProfile().httpUserAgent()
    return re.sub(r"QtWebEngine/[\d.]+ ", "", ua)


#: Tests turn this off. A QWebEngineView that fetches its home page the
#: moment it is shown would put the whole suite on the network and make it
#: depend on three third-party sites being up - so the switch is here rather
#: than a network stub in every test.
AUTOLOAD = True


class Interceptor(QWebEngineUrlRequestInterceptor):
    """Network-level blocking, the same rule the WebView2 handler applied.

    `interceptRequest` runs on the IO thread for EVERY subresource on every
    page, so it does exactly one cheap suffix match and nothing else - no
    logging, no signals, no allocation beyond the host string.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.blocklist = adblock.load_blocklist()
        self.blocked = 0
        self.allowed = 0
        # honours the "Block ads and trackers" setting. Read once at build and
        # flipped live by set_adblock() - without this the checkbox was a
        # setting nothing consulted, so unticking it changed nothing.
        self.enabled = bool(core_config.load_settings().get("adblock", True))

    def interceptRequest(self, info) -> None:
        # ONE suffix match and nothing else. A previous version also wrote
        # Sec-CH-UA client hints here, on the theory that their absence was
        # what made overframe.gg re-challenge. That was wrong - a throwaway
        # profile with a plain Chrome UA and NO hints loads the site fine -
        # and writing three headers onto every subresource made pages
        # measurably slower for no benefit. Removed.
        if not self.enabled:
            return
        host = info.requestUrl().host().lower()
        if adblock.host_blocked(host, self.blocklist):
            info.block(True)
            self.blocked += 1
        else:
            self.allowed += 1


_PROFILE: QWebEngineProfile | None = None
_INTERCEPTOR: Interceptor | None = None


def profile() -> QWebEngineProfile:
    """The one shared profile. Built once; every tab uses it, so a login on
    one site is a login for that site everywhere in the app."""
    global _PROFILE, _INTERCEPTOR
    if _PROFILE is not None:
        return _PROFILE
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    # NAMED - see the module docstring. The no-argument constructor is
    # off-the-record and would silently drop every cookie on exit.
    p = QWebEngineProfile(PROFILE_NAME)
    p.setPersistentStoragePath(str(PROFILE_DIR))
    p.setCachePath(str(PROFILE_DIR / "cache"))
    p.setPersistentCookiesPolicy(
        QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies)
    p.setHttpUserAgent(chrome_user_agent())

    _INTERCEPTOR = Interceptor(p)
    p.setUrlRequestInterceptor(_INTERCEPTOR)

    # The cosmetic sweeper, at document creation on every page in the
    # profile. It has to run in the MAIN world: it reads and removes the
    # page's own elements, which an isolated world cannot touch.
    script = QWebEngineScript()
    script.setName("adblock")
    script.setSourceCode(adblock.ADBLOCK_JS)
    script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
    script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
    script.setRunsOnSubFrames(True)
    p.scripts().insert(script)

    _PROFILE = p
    return p


def interceptor() -> Interceptor | None:
    """For tests and the Settings readout - how much has been blocked."""
    return _INTERCEPTOR


def set_adblock(enabled: bool) -> None:
    """Turn the interceptor on or off live, so the Settings checkbox takes
    effect on the next request rather than at the next launch."""
    if _INTERCEPTOR is not None:
        _INTERCEPTOR.enabled = bool(enabled)


def shutdown() -> None:
    """Destroy the profile so its cookie store FLUSHES to disk.

    Chromium writes cookies on a periodic timer and again when the profile is
    destroyed. This profile is a module global with no parent, so nothing ever
    destroyed it: `app.exec()` returns, the interpreter exits, and whatever
    the timer had not yet written is simply gone.

    That is why overframe.gg re-ran its Cloudflare check on every launch. The
    clearance is earned LATE - the moment that tab is opened - and never lived
    long enough to be flushed, while the wiki's cookies, written minutes
    earlier, survived and made the store look like it worked. Measured: after
    two launches that each PASSED the challenge, `cf_clearance` was absent from
    the file while `theme` from twenty minutes before was still there.

    CALL ORDER MATTERS. Every page built on this profile must be destroyed
    first - a QWebEnginePage outliving its profile crashes.
    """
    global _PROFILE, _INTERCEPTOR
    _INTERCEPTOR = None
    # dropping the last Python reference runs the C++ destructor, and the
    # destructor is what performs the flush
    _PROFILE = None


def clear_cookies() -> None:
    profile().cookieStore().deleteAllCookies()


def clear_cache() -> None:
    profile().clearHttpCache()


def clear_all_data() -> None:
    """Cookies, cache, visited links AND every site's local storage.

    The three Qt calls do not touch on-disk Local/Session Storage, IndexedDB
    or Service Workers, so the confirmation's promise that "every cookie,
    cached file and site setting will be deleted" was only partly true. Those
    live in named subdirectories of the profile; removing them is the only way
    to actually clear them, and they are recreated on the next visit.
    """
    import shutil
    p = profile()
    p.cookieStore().deleteAllCookies()
    p.clearHttpCache()
    p.clearAllVisitedLinks()
    for name in ("Local Storage", "Session Storage", "IndexedDB",
                 "Service Worker", "WebStorage", "databases",
                 "shared_proto_db"):
        shutil.rmtree(PROFILE_DIR / name, ignore_errors=True)


class BookmarkDrawer(SlideOver):
    """The saved pages for ONE web app, sliding in from the right.

    Scoped to its app rather than showing everything: a wiki article and an
    overframe build are not interchangeable, and a shared list would have to
    answer "which tab does this link belong to?" on every click.
    """

    def __init__(self, parent: QWidget, app: webapps.WebApp, on_open) -> None:
        super().__init__(parent)
        self.app = app
        self.on_open = on_open

        head = QHBoxLayout()
        head.setContentsMargins(t.SP_LG, t.SP_MD, t.SP_SM, t.SP_MD)
        title = label(f"Bookmarks — {app.label}", role="h2")
        head.addWidget(title)
        head.addStretch(1)
        shut = QPushButton(glyph_icon("close", color=t.MUTED), "")
        shut.setProperty("kind", "flat")
        shut.setFixedWidth(t.ICON_BTN)
        shut.setCursor(Qt.PointingHandCursor)
        shut.setToolTip("close")
        shut.clicked.connect(self.close_panel)
        head.addWidget(shut)
        self.body.addLayout(head)
        self.body.addWidget(hairline())

        self.area = QScrollArea()
        self.area.setWidgetResizable(True)
        self.area.setFrameShape(QFrame.NoFrame)
        self.area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.body.addWidget(self.area, 1)

        # Clear-all lives at the BOTTOM, away from the per-row ✕ buttons. A
        # destructive action that scopes wider than its neighbours should not
        # sit among them where a mis-aimed click can find it.
        self.body.addWidget(hairline())
        foot = QHBoxLayout()
        foot.setContentsMargins(t.SP_LG, t.SP_SM, t.SP_LG, t.SP_MD)
        self.clear_btn = QPushButton(" Delete all")
        self.clear_btn.setIcon(glyph_icon("delete", color=t.WFM_RED))
        self.clear_btn.setProperty("size", "small")
        self.clear_btn.setCursor(Qt.PointingHandCursor)
        self.clear_btn.setToolTip(
            f"remove every saved {app.label} page - other apps are untouched")
        self.clear_btn.setStyleSheet(
            f"QPushButton {{ color: {t.WFM_RED}; background: transparent;"
            f" border: {t.CTRL_BORDER_W}px solid {t.BORDER}; padding: 3px 10px; }}"
            f"QPushButton:hover {{ border-color: {t.WFM_RED}; }}"
            f"QPushButton:disabled {{ color: {t.WFM_EDGE}; }}")
        self.clear_btn.clicked.connect(self._clear_all)
        foot.addWidget(self.clear_btn)
        foot.addStretch(1)
        self.count = label("", role="small")
        foot.addWidget(self.count)
        self.body.addLayout(foot)
        self.reload()

    def reload(self) -> None:
        entries = core_bookmarks.for_app(core_bookmarks.load(), self.app.key)
        inner = panel()
        col = QVBoxLayout(inner)
        col.setContentsMargins(t.SP_SM, t.SP_SM, t.SP_SM, t.SP_SM)
        col.setSpacing(t.SP_XXS)
        if not entries:
            hint = label(f"Nothing saved yet. Use the ribbon in the bar to "
                         f"bookmark a {self.app.label} page.", role="small")
            hint.setWordWrap(True)
            col.addWidget(hint)
        for entry in entries:
            col.addWidget(self._row(entry))
        col.addStretch(1)
        self.area.setWidget(inner)
        n = len(entries)
        self.count.setText(f"{n} saved" if n else "")
        self.clear_btn.setEnabled(bool(n))

    def _clear_all(self) -> None:
        """Scoped to THIS app, and the confirmation says so and says how many
        - a dialog that only asks "are you sure?" is one people learn to click
        through without reading."""
        data = core_bookmarks.load()
        n = core_bookmarks.count(data, self.app.key)
        if not n:
            return
        if QMessageBox.question(
                self, f"Delete all {self.app.label} bookmarks?",
                f"This removes {n} saved {self.app.label} "
                f"{'page' if n == 1 else 'pages'}.\n"
                f"Bookmarks for the other web apps are not affected.",
                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        core_bookmarks.save(core_bookmarks.clear_app(data, self.app.key))
        self.reload()
        parent = self.parentWidget()
        if hasattr(parent, "_paint_star"):
            parent._paint_star()      # the ribbon on this page just emptied

    def _row(self, entry: dict) -> QWidget:
        row = panel()
        h = QHBoxLayout(row)
        h.setContentsMargins(t.SP_SM, 2, 2, 2)
        h.setSpacing(t.SP_SM)
        link = QPushButton(core_bookmarks.label(entry))
        link.setProperty("kind", "flat")
        link.setCursor(Qt.PointingHandCursor)
        link.setToolTip(entry["url"])
        link.setStyleSheet(f"text-align: left; color: {t.WFM_TEAL};"
                           f"padding: 5px 4px;")
        link.clicked.connect(lambda _c=False, u=entry["url"]: self.on_open(u))
        h.addWidget(link, 1)
        rm = QPushButton(glyph_icon("close", color=t.WFM_RED), "")
        rm.setProperty("kind", "flat")
        rm.setFixedWidth(t.ICON_BTN)
        rm.setCursor(Qt.PointingHandCursor)
        rm.setToolTip("remove this bookmark")
        rm.clicked.connect(lambda _c=False, u=entry["url"]: self._remove(u))
        h.addWidget(rm)
        return row

    def _remove(self, url: str) -> None:
        core_bookmarks.save(core_bookmarks.remove(
            core_bookmarks.load(), self.app.key, url))
        self.reload()
        parent = self.parentWidget()
        if hasattr(parent, "_paint_star"):
            parent._paint_star()          # the ribbon may have just emptied


class WebAppView(QWidget):
    """One site, with a minimal chrome bar.

    Loads LAZILY - nothing is fetched until the tab is first shown, so
    launching the app costs no network at all. After that the page stays
    alive in the stack, keeping its scroll position and session exactly as
    the WebView2 version did, but without any of the machinery that took.
    """

    title_changed = Signal(str)

    def __init__(self, app: webapps.WebApp) -> None:
        super().__init__()
        self.app = app
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._loaded = False
        self._first_paint_done = False
        self._want_url: str | None = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        bar = panel("header")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(t.SP_MD, t.SP_SM, t.SP_MD, t.SP_SM)
        bl.setSpacing(t.SP_SM)
        self.back = self._chrome("back", "back", lambda: self.view.back())
        self.forward = self._chrome("forward", "forward",
                                    lambda: self.view.forward())
        self.reload = self._chrome("refresh", "reload",
                                   lambda: self.view.reload())
        for b in (self.back, self.forward, self.reload):
            bl.addWidget(b)
        # the save toggle sits between reload and home, where the user asked
        # for it - it acts on THIS page, so it belongs with the page controls
        self.star = QPushButton()
        self.star.setProperty("kind", "flat")
        self.star.setFixedWidth(t.ICON_BTN)
        self.star.setCursor(Qt.PointingHandCursor)
        self.star.clicked.connect(self._toggle_bookmark)
        bl.addWidget(self.star)
        home = self._chrome("home_page", f"back to {app.label}",
                            self.go_home)
        bl.addWidget(home)
        self.status = label("", role="small")
        bl.addWidget(self.status, 1)
        self.blocked = label("", role="small")
        self.blocked.setToolTip("ad and tracker requests blocked on this page")
        bl.addWidget(self.blocked)
        # Framed and wider than its neighbours on purpose. The other chrome
        # buttons act on the current page; this one opens a panel, so it is a
        # different KIND of control and should not read as one more arrow.
        self.list_btn = QPushButton(" Bookmarks")
        self.list_btn.setIcon(glyph_icon(BOOKMARKS_GLYPH, color=t.TEXT))
        self.list_btn.setProperty("size", "small")
        self.list_btn.setCursor(Qt.PointingHandCursor)
        self.list_btn.setToolTip(f"saved {app.label} pages")
        self.list_btn.setStyleSheet(
            f"color: {t.TEXT}; background: {t.PANEL};"
            f"border: {t.CTRL_BORDER_W}px solid {t.BORDER}; padding: 3px 12px;")
        self.list_btn.clicked.connect(self._toggle_drawer)
        bl.addWidget(self.list_btn)
        lay.addWidget(bar)
        lay.addWidget(hairline())

        self.view = QWebEngineView()
        self.view.setPage(self._make_page())
        lay.addWidget(self.view, 1)

        # BOUND METHODS, not lambdas. Qt drops a queued signal when its
        # RECEIVER has been deleted, and for a bound method the receiver is
        # this widget - so teardown is safe for free. A lambda has no
        # receiver, so Qt keeps delivering it, and `urlChanged` fires once
        # more while the window is closing: the lambda then touches
        # self.back, whose C++ half is already gone, and shiboken raises
        # "Internal C++ object already deleted". Measured, not theorised.
        self.view.loadStarted.connect(self._load_started)
        self.view.loadProgress.connect(self._load_progress)
        self.view.loadFinished.connect(self._load_finished)
        self.view.urlChanged.connect(self._paint_nav)
        self.view.titleChanged.connect(self.title_changed)

        # the drawer is created LAST so it is the newest sibling, and it is
        # raised again on every open - see ui/overlay.py
        self.drawer = BookmarkDrawer(self, app, self._open_bookmark)
        self._paint_nav()

    def _make_page(self):
        from PySide6.QtWebEngineCore import QWebEnginePage
        page = QWebEnginePage(profile(), self)
        # Paint unrendered regions in the app's own void-black, not the default
        # white. During any surface handover (first paint, tab return) the gap
        # is then a clean dark frame that matches the chrome, instead of a white
        # flash or a torn leftover.
        page.setBackgroundColor(QColor(t.BG))
        s = page.settings()
        # a site that pops a window would otherwise open a bare, chromeless
        # QWebEngineView with no way back
        s.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows,
                       False)
        s.setAttribute(QWebEngineSettings.WebAttribute.ScrollAnimatorEnabled,
                       True)
        css = adblock.SITE_TWEAKS.get(self.app.key)
        if css:
            # per-SITE, so it goes on the page rather than the shared profile
            script = QWebEngineScript()
            script.setName(f"tweak:{self.app.key}")
            script.setSourceCode(adblock.tweak_js(css))
            script.setInjectionPoint(
                QWebEngineScript.InjectionPoint.DocumentCreation)
            script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
            page.scripts().insert(script)
        return page

    def _chrome(self, name: str, tip: str, on_click) -> QPushButton:
        """A bar button carrying an ICON rather than a text arrow, so the
        whole bar reads as one set with the rest of the app."""
        b = QPushButton(glyph_icon(name, color=t.TEXT), "")
        b.setProperty("kind", "flat")
        b.setFixedWidth(t.ICON_BTN)
        b.setCursor(Qt.PointingHandCursor)
        b.setToolTip(tip)
        b.clicked.connect(on_click)
        return b

    # -- navigation ----------------------------------------------------------

    def open_url(self, url: str | None = None) -> None:
        """Show `url`, or this app's home page. Safe to call before the tab
        has ever been shown - the request is remembered and honoured on the
        first showEvent, so a wiki deep link from another screen is never
        dropped."""
        target = url or self.app.url
        if not self.isVisible():
            self._want_url = target
            return
        self._want_url = None
        self._loaded = True
        self.view.setUrl(QUrl(target))

    def go_home(self) -> None:
        self.open_url(self.app.url)

    def preload(self) -> None:
        """Begin loading the home page at launch, in the background, even though
        this tab is not visible yet.

        Lazy loading kept startup free of network, but it also meant the FIRST
        switch to a web tab paid for a cold Chromium page build - a progressive,
        occasionally torn load. Preloading warms the engine's render and GPU
        processes and, more importantly, means a fully-built page is waiting: the
        first show composites it in one clean pass instead of painting it live.
        No-op once any load has started, so it never fights a real navigation."""
        if self._loaded or self._want_url is not None:
            # a real navigation is already queued (e.g. a wiki deep-link parked
            # before this tab was shown) - honour that, not the home page
            return
        self._loaded = True
        self.view.setUrl(QUrl(self.app.url))

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._want_url is not None:
            url, self._want_url = self._want_url, None
            self._loaded = True
            self.view.setUrl(QUrl(url))
        elif not self._loaded and AUTOLOAD:
            # first visit: this is the ONLY place the home page is fetched,
            # so launching the app never touches the network
            self._loaded = True
            self.view.setUrl(QUrl(self.app.url))
        else:
            # returning to a tab that already loaded: its surface may still
            # hold whatever was on screen when it was hidden
            QTimer.singleShot(0, self._repaint)
            # ... and once the swap has had time to land, the lifecycle nudge
            # (see _nudge) quietly heals the case where the new surface never
            # received a frame - the stuck-black screen a user could only fix
            # by clicking away and back
            QTimer.singleShot(450, self._nudge)

    def is_navigated(self) -> bool:
        return self._loaded

    # -- feedback ------------------------------------------------------------

    def _load_started(self) -> None:
        inter = interceptor()
        self._blocked_at_start = inter.blocked if inter else 0
        self.status.setText(f"loading {self.app.label}…")
        self.status.setStyleSheet(f"color: {t.MUTED};")

    def _load_progress(self, pct: int) -> None:
        self.status.setText(f"loading… {pct}%")

    def _repaint(self) -> None:
        """Make the view rebuild its backing surface.

        `update()` alone is not enough: a QWebEngineView hidden inside a
        QStackedWidget can lose its composited surface entirely and come back
        BLACK - the page is alive, there is simply nothing to show. Hiding and
        re-showing the render widget forces Chromium to hand over a new one,
        which is cheap and, unlike a reload, does not lose scroll position or
        session state.
        """
        if not self.isVisible():
            return
        self.view.hide()
        self.view.show()
        self.view.update()

    def _nudge(self) -> None:
        """The stuck-black-screen self-heal.

        A reclaimed surface occasionally never receives a frame: the page is
        alive behind solid black until another tab switch forces another
        swap. Detecting that by pixel-probing was tried and REJECTED - the
        test suite showed a healthy rendered page still grabs as black under
        this engine, so any probe-then-teardown design tears down working
        pages. Instead, an unconditional nudge that is harmless either way:
        hide the PAGE (Chromium's lifecycle visibility, not the Qt widget)
        for one beat and show it again. The renderer re-submits a frame into
        the EXISTING surface - a stuck screen recovers, a healthy one keeps
        its last frame throughout and shows nothing at all."""
        if not (self.isVisible() and self._loaded):
            return
        self.view.page().setVisible(False)
        QTimer.singleShot(30, self._nudge_back)

    def _nudge_back(self) -> None:
        """Restore only while the tab is still on screen. If it was hidden
        during the beat, leave the page hidden - the view's own show handling
        makes it visible again on the next switch, and forcing it visible now
        would have a hidden tab rendering in the background."""
        if self.isVisible():
            self.view.page().setVisible(True)

    def _load_finished(self, ok: bool) -> None:
        self.status.setText("" if ok else "could not load this page")
        self.status.setStyleSheet(f"color: {t.ERR if not ok else t.MUTED};")
        inter = interceptor()
        if inter is not None:
            n = inter.blocked - getattr(self, "_blocked_at_start", 0)
            self.blocked.setText(f"{n} blocked" if n else "")
            self.blocked.setStyleSheet(f"color: {t.MUTED};")
        self._paint_nav()
        # Reclaim the composited surface ONCE, on the first successful paint -
        # that is the "first open shows only the background" case. Doing it on
        # EVERY loadFinished forced a surface swap at the end of every
        # navigation, and a surface torn down and rebuilt mid-frame is exactly
        # what smeared a torn band across the page as it settled. Tab-return
        # still gets its repaint via showEvent, which is the OTHER case that
        # genuinely loses the surface.
        if ok and not self._first_paint_done:
            self._first_paint_done = True
            self._repaint()
            # first paint can strand a black surface the same way tab-return
            # can - give it the same one-shot self-heal
            QTimer.singleShot(450, self._nudge)
        if ok:
            # Load-time stuck-black heal, discovered empirically by the user:
            # SCROLLING un-sticks a page that loaded behind solid black. So
            # every finished load gets an invisible scroll - one pixel down,
            # back up on the next animation frame. The page processes two
            # real scroll events ~16ms apart; the viewport never visibly
            # moves. Runs for hidden (preloading) tabs too - healing before
            # the first look is the point.
            QTimer.singleShot(80, self._scroll_nudge)

    def _scroll_nudge(self) -> None:
        """The imperceptible 1px down/up scroll (see _load_finished)."""
        if not self._loaded:
            return
        self.view.page().runJavaScript(
            "window.scrollBy(0, 1);"
            "requestAnimationFrame(() => window.scrollBy(0, -1));")

    def _paint_nav(self, *_args) -> None:
        """`*_args` so this can be connected straight to `urlChanged`, which
        passes a QUrl. Taking the argument is what lets the connection be a
        bound method instead of a lambda - see the note at the connect."""
        history = self.view.history()
        self.back.setEnabled(history.canGoBack())
        self.forward.setEnabled(history.canGoForward())
        self._paint_star()

    # -- bookmarks -----------------------------------------------------------

    def _paint_star(self) -> None:
        """Filled ribbon when this page is saved, outline when it is not."""
        url = self.view.url().toString()
        saved = bool(url) and core_bookmarks.is_bookmarked(
            core_bookmarks.load(), self.app.key, url)
        self.star.setIcon(bookmark_icon(
            saved, color=t.ACCENT if saved else t.MUTED))
        self.star.setToolTip("remove this page from bookmarks" if saved
                             else "bookmark this page")

    def _toggle_bookmark(self) -> None:
        url = self.view.url().toString()
        if not url:
            return
        data = core_bookmarks.toggle(core_bookmarks.load(), self.app.key,
                                     url, self.view.title())
        core_bookmarks.save(data)
        self._paint_star()
        self.drawer.reload()

    def _toggle_drawer(self) -> None:
        if not self.drawer.is_open():
            self.drawer.reload()
        self.drawer.toggle()

    def _open_bookmark(self, url: str) -> None:
        """Clicking a saved link navigates AND closes - a drawer that stayed
        open would be covering the page you just asked to see."""
        self.drawer.close_panel()
        self.open_url(url)
