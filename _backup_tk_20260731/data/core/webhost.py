"""Embedded web apps - Microsoft Edge WebView2 hosted inside Tk frames.

pywebview drives the WebView2 runtime (shipped with Windows 11, so this
works on any friend's machine with no extra installs beyond the Python
packages). Each site gets ONE window, created lazily the first time its
app is opened and kept alive for the rest of the session: the Win32
window is re-parented into the current Tk container (WS_CHILD) while the
app is on screen and hidden again when the user navigates away - so the
page keeps its scroll position, logins, and state between visits.
"""

from __future__ import annotations

import ctypes
import threading
from pathlib import Path

# Browser profile (cookies, cache) lives with the rest of the user data so
# web-app logins survive restarts and delete-all-user-data can wipe it.
WEB_PROFILE_DIR = Path(__file__).resolve().parent.parent / ".webview"

try:
    import webview                                  # pywebview
    HAVE_WEBVIEW = True
except Exception:                                   # noqa: BLE001
    HAVE_WEBVIEW = False

# The ad-block policy now lives in core/adblock.py - it is engine-agnostic
# and the Qt front end consumes the same tuples. Re-exported here so this
# module's existing call sites are untouched.
from core.adblock import (ADBLOCK_CSS_SELECTORS, ADBLOCK_EXTRA_FILE,  # noqa: E402,F401
                          ADBLOCK_HOSTS, ADBLOCK_JS, SITE_TWEAKS,
                          host_blocked, load_blocklist)

_load_blocklist = load_blocklist
_tweak_js = __import__("core.adblock", fromlist=["tweak_js"]).tweak_js


GWL_STYLE = -16
WS_CHILD = 0x40000000
WS_POPUP = 0x80000000
WS_VISIBLE = 0x10000000
WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000
SW_HIDE, SW_SHOW = 0, 5


def _delete_profile_dirs(names: set[str]) -> bool:
    """Disk fallback for when no browser is running: remove every profile
    subdirectory with one of these names."""
    import shutil
    hit = False
    if WEB_PROFILE_DIR.is_dir():
        for d in WEB_PROFILE_DIR.rglob("*"):
            if d.is_dir() and d.name in names:
                shutil.rmtree(d, ignore_errors=True)
                hit = True
    return hit


def _delete_profile_files(stem: str) -> bool:
    hit = False
    if WEB_PROFILE_DIR.is_dir():
        for f in WEB_PROFILE_DIR.rglob(f"{stem}*"):
            if f.is_file():
                try:
                    f.unlink()
                    hit = True
                except OSError:
                    pass
    return hit


def _user32():
    u = ctypes.windll.user32
    u.SetParent.restype = ctypes.c_void_p
    u.SetParent.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    u.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
    u.SetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                 ctypes.c_long]
    u.MoveWindow.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                             ctypes.c_int, ctypes.c_int, ctypes.c_bool]
    u.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
    return u


class WebHost:
    """Owns the pywebview thread and every embedded browser window."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._hwnd: dict[str, int] = {}      # key -> native window handle
        self._windows: dict[str, object] = {}
        self._started = False
        self._failed: str | None = None
        self._thread: threading.Thread | None = None
        # ad blocker: live toggle + per-session counter. Handler delegates
        # are kept here because pythonnet unsubscribes a .NET event the
        # moment its Python-side delegate is garbage collected.
        self.adblock = True
        self.blocked_count = 0
        self._blocklist = _load_blocklist()
        self._adblock_hooks: dict[str, object] = {}
        # Windows start on about:blank and stay there. A site loads only
        # when BOTH conditions hold: a view has asked for it (open_site ->
        # _wanted) and that browser's ad blocker is armed (_armed). So
        # nothing is fetched at launch for a tab you never open, and no ad
        # request can slip out ahead of the filter.
        self._urls: dict[str, str] = {}
        self._navigated: set[str] = set()
        self._armed: set[str] = set()        # blocker in place, or gave up
        self._wanted: set[str] = set()       # a view has asked for the site
        self._navigating: set[str] = set()   # a load_url is in flight

    @property
    def started(self) -> bool:
        return self._started

    @property
    def available(self) -> bool:
        return HAVE_WEBVIEW and self._failed is None

    @property
    def error(self) -> str:
        return self._failed or ("the 'pywebview' package is not installed"
                                if not HAVE_WEBVIEW else "")

    # -- window lifecycle (pywebview side) --------------------------------

    def ensure_all(self, pairs: list[tuple[str, str]]) -> None:
        """Create every browser window in one batch, BEFORE any of them is
        embedded. pywebview creates later windows by Invoke()ing through an
        existing one - which fails once that window has been re-parented
        into Tk - so all windows must exist before the first embed."""
        if not HAVE_WEBVIEW or self._failed:
            return
        with self._lock:
            todo = [(k, u) for k, u in pairs if k not in self._windows]
            for k, _u in todo:
                self._windows[k] = None     # reserved - creation in flight
        if not todo:
            return

        def make() -> None:
            # A worker thread on purpose: pywebview treats create_window()
            # from a thread named 'MainThread' as pre-start bookkeeping -
            # and Tk owns the real main thread. Frameless and parked far
            # off-screen: the windows never show up on their own; we grab
            # their handles and re-parent them into Tk.
            try:
                for k, u in todo:
                    # about:blank first - the real site loads only after
                    # the ad blocker is armed (see _arm_adblock). easy_drag
                    # would let a click-drag on the page move the window -
                    # embedded, that drags the whole Toolbox around.
                    self._urls[k] = u
                    win = webview.create_window(k, "about:blank",
                                                frameless=True,
                                                easy_drag=False,
                                                x=-9000, y=-9000,
                                                width=900, height=700)
                    with self._lock:
                        self._windows[k] = win
                with self._lock:
                    start = not self._started
                    self._started = True
                if start:
                    # pywebview gates start() on the thread NAME only; on
                    # Windows its WinForms backend runs its own STA thread,
                    # so hosting it off the real main thread is safe.
                    self._thread = threading.Thread(
                        target=self._run, name="MainThread", daemon=True)
                    self._thread.start()
                # the blocker arms itself on the side; a hiccup there must
                # never take embedding down with it
                threading.Thread(target=self._arm_adblock,
                                 args=([k for k, _u in todo],),
                                 daemon=True).start()
            except Exception as exc:                # noqa: BLE001
                self._failed = f"couldn't create browser windows: {exc}"

        threading.Thread(target=make, daemon=True).start()

    def _run(self) -> None:
        try:
            # pywebview installs a Ctrl+C handler, which Python only allows
            # from the real main thread - make that a no-op here instead of
            # a crash. Everything else about signal handling is unchanged.
            import signal
            original = signal.signal

            def tolerant(sig, handler):
                try:
                    return original(sig, handler)
                except ValueError:
                    return None
            signal.signal = tolerant
            WEB_PROFILE_DIR.mkdir(exist_ok=True)
            webview.start(gui="edgechromium", private_mode=False,
                          storage_path=str(WEB_PROFILE_DIR))
        except Exception as exc:                    # noqa: BLE001
            self._failed = f"WebView2 failed to start: {exc}"

    def _on_shown(self, key: str, win) -> None:
        """Record the native handle; harmless to call before the window is
        ready (it simply stays unresolved and gets polled again)."""
        try:
            handle = win.native.Handle              # System.IntPtr
            self._hwnd[key] = int(handle.ToInt64())
        except Exception:                           # noqa: BLE001
            try:
                self._hwnd[key] = int(win.native.Handle)
            except Exception:                       # noqa: BLE001
                pass

    def hwnd(self, key: str) -> int | None:
        h = self._hwnd.get(key)
        if h:
            if ctypes.windll.user32.IsWindow(ctypes.c_void_p(h)):
                return h
            self._hwnd.pop(key, None)   # window died - don't hand out a
            h = None                    # stale handle as if it were live
        # windows created AFTER webview.start() can be shown before our
        # event handler is attached - read the handle straight off the
        # native window instead of waiting for an event that already fired
        win = self._windows.get(key)
        if win is not None:
            try:
                self._on_shown(key, win)
            except Exception:                       # noqa: BLE001
                pass
        return self._hwnd.get(key)

    # -- embedding (Tk side, main thread) ----------------------------------

    def _all_created(self) -> bool:
        """True once every reserved window exists with a native handle -
        embedding any earlier would break creation of the rest."""
        with self._lock:
            keys = list(self._windows)
        return bool(keys) and all(self.hwnd(k) for k in keys)

    def embed(self, key: str, container_id: int,
              w: int, h: int) -> bool:
        if not self._all_created():
            return False
        hwnd = self.hwnd(key)
        if not hwnd:
            return False
        u = _user32()
        style = u.GetWindowLongW(hwnd, GWL_STYLE)
        style = (style & ~(WS_POPUP | WS_CAPTION | WS_THICKFRAME)) | WS_CHILD
        u.SetWindowLongW(hwnd, GWL_STYLE, ctypes.c_long(style).value)
        u.SetParent(hwnd, container_id)
        u.MoveWindow(hwnd, 0, 0, max(1, w), max(1, h), True)
        u.ShowWindow(hwnd, SW_SHOW)
        return True

    def resize(self, key: str, w: int, h: int) -> None:
        hwnd = self._hwnd.get(key)
        if hwnd:
            _user32().MoveWindow(hwnd, 0, 0, max(1, w), max(1, h), True)

    # -- ad blocker ---------------------------------------------------------

    def _host_blocked(self, host: str) -> bool:
        for entry in self._blocklist:
            if host == entry or host.endswith("." + entry):
                return True
        return False

    def _install_adblock(self, key: str) -> None:
        """Attach a WebResourceRequested handler to one browser (must run
        until CoreWebView2 exists - retried by the warmup worker). Runs on
        the browser's UI thread via Invoke; the handler answers blocked
        hosts with a local 403 so the request never leaves the machine."""
        with self._lock:
            win = self._windows.get(key)
            if win is None or key in self._adblock_hooks:
                return
        from urllib.parse import urlsplit
        from System import Func, Type                   # via pythonnet

        form = win.native
        if form is None:
            return                  # window not materialized yet
        chrome = form.browser
        done = threading.Event()

        def on_request(sender, args):
            if not self.adblock:
                return
            try:
                # .hostname, not .netloc: netloc is the whole authority, so
                # "ads.example.com:443" or "user@ads.example.com" would miss
                # every blocklist entry. hostname strips port and userinfo
                # and is already lowercased (None for about:/data: URLs).
                host = urlsplit(str(args.Request.Uri)).hostname or ""
                if self._host_blocked(host):
                    args.Response = sender.Environment.\
                        CreateWebResourceResponse(None, 403, "Blocked", "")
                    self.blocked_count += 1
            except Exception:                           # noqa: BLE001
                pass                # never break the page over a filter

        def subscribe():
            try:
                core = chrome.webview.CoreWebView2
                if core is None:
                    return          # not initialized yet - retry later
                # pywebview already registered a '*' filter for this event;
                # .NET events take any number of extra handlers.
                core.WebResourceRequested += on_request
                # cosmetic filter: runs at document start on every page
                # this browser ever loads, removing the ad CONTAINERS the
                # network blocker leaves behind as empty boxes
                core.AddScriptToExecuteOnDocumentCreatedAsync(ADBLOCK_JS)
                css = SITE_TWEAKS.get(key)
                if css:
                    core.AddScriptToExecuteOnDocumentCreatedAsync(
                        _tweak_js(css))
                self._adblock_hooks[key] = on_request
            except Exception:                           # noqa: BLE001
                pass
            finally:
                done.set()

        try:
            form.Invoke(Func[Type](subscribe))
            done.wait(timeout=5)
        except Exception:                               # noqa: BLE001
            pass

    def _arm_adblock(self, keys: list[str]) -> None:
        """Warmup worker: keep trying each browser until its handler is in
        (CoreWebView2 appears within ~a second of window creation).

        It no longer navigates anything on its own - it only reports that a
        browser is safe to navigate. open_site() decides what actually
        loads."""
        import time
        deadline = time.monotonic() + 30
        pending = set(keys)
        try:
            while pending and time.monotonic() < deadline:
                for k in list(pending):
                    try:
                        # the first tries race pythonnet's CLR load (started
                        # on the webview thread) - just retry until it's up
                        self._install_adblock(k)
                    except Exception:               # noqa: BLE001
                        pass
                    if k in self._adblock_hooks:
                        pending.discard(k)
                        self._mark_armed(k)
                time.sleep(0.25)
        finally:
            # EVERY key must end up armed, even on failure or timeout - the
            # site still has to be loadable, just unfiltered. A key that is
            # neither armed nor navigated would leave open_site() waiting on
            # a worker that has already exited: a permanent "Loading ...".
            for k in keys:
                self._mark_armed(k)

    def _mark_armed(self, key: str) -> None:
        """This browser may now be sent to a real URL. Runs on the arming
        worker; navigates immediately if a view already asked."""
        with self._lock:
            if key in self._armed:
                return
            self._armed.add(key)
            go = (key in self._wanted and key not in self._navigated
                  and key not in self._navigating)
            if go:
                self._navigating.add(key)   # same reservation as open_site
        if go:
            self._navigate(key)

    def open_site(self, key: str, url: str | None = None) -> None:
        """Ask a browser to show its site. Non-blocking and idempotent.

        Navigation waits for that browser's ad blocker (see _arm_adblock),
        which is exactly why windows are created on about:blank. Passing
        `url` overrides the site's home page - a deep link, e.g. a wiki
        article - and forces a re-navigation even if the browser is already
        showing something."""
        with self._lock:
            if url:
                self._urls[key] = url
                self._navigated.discard(key)
            elif key in self._navigated or key in self._navigating:
                return          # already showing (or on its way) - leave it
            self._wanted.add(key)
            # Reserve BEFORE spawning. _navigated is only set once
            # form.Invoke returns, and the embed poll calls us every 120ms -
            # without this reservation a single first visit could re-issue
            # load_url dozens of times, each one cancelling the last load.
            if key in self._navigating:
                return
            go = key in self._armed
            if go:
                self._navigating.add(key)
        if go:
            # form.Invoke() blocks until the .NET UI thread runs the
            # delegate, and that thread may be mid-navigation - never call
            # it from the Tk thread (same reason as _clear_browsing_data).
            threading.Thread(target=self._navigate, args=(key,),
                             daemon=True).start()

    def is_navigated(self, key: str) -> bool:
        """True once this browser has been sent to its real URL."""
        return key in self._navigated

    def _navigate(self, key: str) -> None:
        """Send a browser from about:blank to its real site (UI thread)."""
        try:
            if key in self._navigated:
                return
            url = self._urls.get(key)
            with self._lock:
                win = self._windows.get(key)
            if not url or win is None or win.native is None:
                return
            from System import Func, Type
            form = win.native
            sent = []

            def go():
                try:
                    form.browser.load_url(url)
                    sent.append(True)
                except Exception:                   # noqa: BLE001
                    pass

            try:
                form.Invoke(Func[Type](go))
            except Exception:                       # noqa: BLE001
                return
            # Only record success. Marking a FAILED load as navigated would
            # make open_site() early-return forever, stranding the pane on
            # about:blank with no way back.
            if sent:
                with self._lock:
                    self._navigated.add(key)
        finally:
            with self._lock:
                self._navigating.discard(key)

    # -- clearing web data ----------------------------------------------------

    def _clear_browsing_data(self, kinds_name: str) -> bool:
        """Ask WebView2 itself to clear profile data (works while the
        browsers are running - the files on disk are locked). kinds_name is
        a CoreWebView2BrowsingDataKinds member: 'DiskCache', 'Cookies',
        'AllProfile', ..."""
        with self._lock:
            win = next((w for w in self._windows.values() if w is not None),
                       None)
        if win is None:
            return False
        from System import Func, Type
        from Microsoft.Web.WebView2.Core import CoreWebView2BrowsingDataKinds
        kinds = getattr(CoreWebView2BrowsingDataKinds, kinds_name)
        form = win.native
        if form is None:
            return False
        chrome = form.browser
        ok = threading.Event()

        def run():
            try:
                core = chrome.webview.CoreWebView2
                if core is not None:
                    core.Profile.ClearBrowsingDataAsync(kinds)
                    ok.set()
            except Exception:                           # noqa: BLE001
                pass

        try:
            form.Invoke(Func[Type](run))
            return ok.wait(timeout=5)
        except Exception:                               # noqa: BLE001
            return False

    def clear_cache(self) -> bool:
        """Cache only; every site stays signed in. False = nothing running
        and nothing to do on disk either."""
        if self.started and self._clear_browsing_data("DiskCache"):
            self._clear_browsing_data("CacheStorage")
            return True
        return _delete_profile_dirs({"Cache", "Code Cache", "GPUCache",
                                     "ShaderCache", "GrShaderCache"})

    def clear_cookies(self) -> bool:
        if self.started and self._clear_browsing_data("Cookies"):
            return True
        return _delete_profile_files("Cookies")

    def clear_all_data(self) -> bool:
        """Everything: cookies, cache, local storage, history."""
        if self.started and self._clear_browsing_data("AllProfile"):
            return True
        import shutil
        shutil.rmtree(WEB_PROFILE_DIR, ignore_errors=True)
        return True

    def shutdown(self) -> None:
        """Destroy every browser window so pywebview's foreground .NET
        thread ends and the process can actually exit."""
        with self._lock:
            wins = list(self._windows.values())
            self._windows.clear()
            self._hwnd.clear()
        for w in wins:
            try:
                w.destroy()
            except Exception:                       # noqa: BLE001
                pass
        # let the .NET side finish its own teardown while the interpreter
        # is still healthy - racing it produces exit-time CLR exceptions
        if self._thread is not None:
            self._thread.join(timeout=3)

    def release(self, key: str, holder_id: int) -> None:
        """Park the browser in the app's hidden holder frame when its view
        goes away. It stays a live WS_CHILD for the whole session - just of
        an unmapped parent - so re-embedding is a plain SetParent + show,
        and the page keeps running (state, timers, logins) in between."""
        hwnd = self._hwnd.get(key)
        if not hwnd:
            return
        u = _user32()
        u.ShowWindow(hwnd, SW_HIDE)
        u.SetParent(hwnd, holder_id)
