#!/usr/bin/env python3
"""
WF Market Helper - a small desktop host for warframe.market trading tools.

The host owns the account link AND all networking. You sign in once here; the
JWT stays inside the host process. Every API call a tool makes is routed
through the host's local gateway (core/gateway.py), which injects the session,
identifies the client, and enforces one shared rate limit across all running
tools. Tools launched outside the host find no gateway and exit immediately -
they cannot function alone, by design.

Tools are defined in registry.py; new entries appear on the landing page
automatically. Standard library only (Tkinter ships with Python).

Run:  python wf_market_helper.py
"""

from __future__ import annotations

import base64
import queue
import subprocess
import sys
import threading
import webbrowser
from fractions import Fraction
from pathlib import Path
import tkinter as tk
from tkinter import filedialog
from tkinter import font as tkfont
from tkinter import messagebox
from tkinter import ttk

import os

from core import session as wfm_session
from core import market as wfm_market
from core import presence as wfm_presence
from core import assets as wfm_assets
from core import wf_local
from core import vosfor as wfm_vosfor
from core import arcane_market as wfm_arcane_market
from core import wiki as wfm_wiki
from core import theme as wfm_theme
from core import floors as wfm_floors
from core import repricer as wfm_repricer
from core import vosfor_vm as wfm_vosfor_vm
from core import listings_vm as wfm_listings_vm
from core import nav as wfm_nav
from core import market_vm as wfm_market_vm
from core.webhost import WebHost
from core import config as wfm_config
from core.gateway import Gateway
from registry import TOOLS, Tool

APP_NAME = "Warframe Toolbox"

# The custom title bar (overrideredirect + a Win32 taskbar fix) is Windows
# only; elsewhere we keep the native OS title bar.
IS_WINDOWS = sys.platform.startswith("win")
if IS_WINDOWS:
    import ctypes


def monitor_count() -> int:
    """How many displays the device has (1 when it can't be detected)."""
    if IS_WINDOWS:
        try:
            return max(1, ctypes.windll.user32.GetSystemMetrics(80))
        except Exception:                                   # noqa: BLE001
            pass
    return 1


def monitor_rects() -> list[tuple[int, int, int, int]]:
    """Each display's rectangle as (left, top, right, bottom), in the order
    Windows enumerates them (monitor 1 first)."""
    rects: list[tuple[int, int, int, int]] = []
    if not IS_WINDOWS:
        return rects

    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                    ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    proc = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p,
                              ctypes.POINTER(RECT), ctypes.c_longlong)

    def cb(_h, _dc, lprc, _lp):
        r = lprc.contents
        rects.append((r.left, r.top, r.right, r.bottom))
        return 1

    try:
        ctypes.windll.user32.EnumDisplayMonitors(0, 0, proc(cb), 0)
    except Exception:                                       # noqa: BLE001
        pass
    return rects


def display_scale(hwnd: int | None = None) -> float:
    """How hard Windows is bitmap-stretching this process's output.
    1.0 = drawn at native resolution; 3.0 = every pixel we draw becomes a
    3x3 block on screen.

    The Toolbox runs DPI-UNAWARE on purpose (see App.__init__), so it renders
    into a 96-DPI surface that Windows then upscales to fill the monitor.
    On a 4K display at 300% that means drawing 1365x720 and having it blown
    up to 4096x2160 - soft text, and any 1-pixel scroll seam smeared across
    3 physical pixels.

    Measured as physical-vs-virtualised desktop width off one DC, because
    that ratio IS the stretch. Do NOT use GetDpiForMonitor here: despite
    what the docs imply about EFFECTIVE_DPI, it answers a flat 96 to a
    DPI-unaware caller, which is precisely the case this function exists to
    detect (verified: it reported 96 on a monitor running at 288). It is
    kept only as a fallback for when the DC query fails."""
    if not IS_WINDOWS:
        return 1.0
    try:
        dc = ctypes.windll.user32.GetDC(None)
        try:
            g = ctypes.windll.gdi32.GetDeviceCaps
            phys, logical = g(dc, 118), g(dc, 8)   # DESKTOPHORZRES, HORZRES
        finally:
            ctypes.windll.user32.ReleaseDC(None, dc)
        if phys and logical:
            return phys / logical
    except Exception:                                       # noqa: BLE001
        pass
    try:
        hmon = ctypes.windll.user32.MonitorFromWindow(
            ctypes.c_void_p(hwnd) if hwnd else None,
            2 if hwnd else 1)             # NEAREST when we have a window,
        x = ctypes.c_uint()               # else PRIMARY
        y = ctypes.c_uint()
        if ctypes.windll.shcore.GetDpiForMonitor(
                hmon, 0, ctypes.byref(x), ctypes.byref(y)) == 0 and x.value:
            return x.value / 96.0
    except Exception:                                       # noqa: BLE001
        pass
    return 1.0


def scroll_unit(scale: float) -> int:
    """The smallest logical-pixel scroll step that lands on a WHOLE device
    pixel at this scale factor - the fix for the smearing described in
    display_scale(). 100% -> 1, 125% -> 4, 150% -> 2, 175% -> 4, 200% -> 1.

    Capped at 8: a step that large would be visible as chunky scrolling,
    and an exotic scale factor is not worth trading smoothness for."""
    if scale <= 0:
        return 1
    unit = Fraction(scale).limit_denominator(16).denominator
    return max(1, min(unit, 8))

# ---- STYLE GUIDE: "OROKIN TREASURY" ----------------------------------------
# The design system - palette, spacing scale, typography roles, and the rules
# governing them - lives in core/theme.py so the Qt front end reads the same
# source. READ THAT MODULE before changing any design element.
#
# Every token is re-exported here unchanged, so this file's ~638 bg=/fg= call
# sites are untouched. Do not redefine any of these locally: a shadowing
# assignment here would silently diverge the two front ends.
from core.theme import (                                       # noqa: F401
    SP_SCREEN, SP_XL, SP_LG, SP_MD, SP_SM,
    BG, TAB_BG, ICON_BG, ROW_ALT, FIELD_BG_IN, FIELD_BG_OUT, FIELD_EDGE,
    PANEL, PANEL_HI, TITLEBAR_BG, TITLEBAR_HOVER, TITLEBAR_CLOSE, HEADER_BG,
    SIDEBAR_BG, SIDEBAR_ACTIVE, TEXT, MUTED, ACCENT, CONSOLE_BG, CONSOLE_FG,
    OK, WARN, ERR,
    GOLD_HI, GOLD_DIM, GOLD_FAINT, PLAT, HAIRLINE, INK,
    WFM_CARD, WFM_EDGE, WFM_TEAL, WFM_TEAL_DIM, WFM_PINK, WFM_MUTED,
    WFM_BADGE_BG, WFM_BADGE_FG, WFM_BUY_BG, WFM_BUY_FG, WFM_RED, WFM_RED_DIM,
    RARITY_BRONZE, RARITY_SILVER, WEB_ACCENT,
    HOME_ICON, LISTINGS_ICON, WIKI_ICON,
)


_TIPS: list[tk.Toplevel] = []


def _tooltip_hide_all() -> None:
    """Destroy every open tooltip.

    A tip is an -overrideredirect -topmost Toplevel, positioned once from
    winfo_rootx/rooty and never moved again. Its only teardown paths are
    <Leave> and <Destroy>, and neither fires when a view is pack_forget()'d
    or when the canvas under the pointer scrolls - so a tip that was up
    when you left a screen survives as an unmanaged always-on-top window
    floating over the next one. Call this on every view switch and on every
    wheel event."""
    while _TIPS:
        try:
            _TIPS.pop().destroy()
        except tk.TclError:
            pass


def _stop_view(view: tk.Widget) -> None:
    """Run a view's on_hide() before it is destroyed outside navigate().

    A persistent view's <Destroy> never fires while it is cached, so
    on_hide() is its ONLY teardown - and the droppers (link/unlink, wipe)
    destroy views that may still be packed and still own a running scroll
    animation or the app-wide wheel binding. Skipping it leaves after() jobs
    firing against deleted Tcl commands."""
    fn = getattr(view, "on_hide", None)
    if fn:
        try:
            fn()
        except tk.TclError:
            pass


def _wfm_tooltip(widget: tk.Widget, text: str) -> None:
    """Attach a hover tooltip to a widget - a borderless Toplevel shown on
    <Enter>, hidden on <Leave>: a tiny gilt plaque (1px GOLD_DIM border).
    Used for the Vosfor per-arcane farm/market detail without cluttering
    the row."""
    state: dict = {"tip": None}

    def show(_e=None):
        # an off-screen widget must never raise a topmost plaque: <Enter>
        # can still arrive for a row that is being torn down or scrolled
        if state["tip"] or not text or not widget.winfo_ismapped():
            return
        tip = tk.Toplevel(widget)
        tip.wm_overrideredirect(True)
        tip.configure(bg=GOLD_DIM)
        try:
            tip.wm_attributes("-topmost", True)
        except tk.TclError:
            pass
        # use the app's probed font roles (the widget's toplevel is the App);
        # the literal tuple is only a last-resort fallback
        fonts = getattr(widget.winfo_toplevel(), "fonts", None)
        tk.Label(tip, text=text, bg=PANEL_HI, fg=TEXT,
                 font=fonts["small"] if fonts else ("Segoe UI", 9), bd=0,
                 padx=7, pady=4).pack(padx=1, pady=1)
        x = widget.winfo_rootx() + 8
        y = widget.winfo_rooty() + widget.winfo_height() + 4
        tip.wm_geometry(f"+{x}+{y}")
        state["tip"] = tip
        _TIPS.append(tip)

    def hide(_e=None):
        if state["tip"]:
            try:
                _TIPS.remove(state["tip"])
            except ValueError:
                pass                     # already swept by _tooltip_hide_all
            try:
                state["tip"].destroy()
            except tk.TclError:
                pass
            state["tip"] = None

    widget.bind("<Enter>", show, add="+")
    widget.bind("<Leave>", hide, add="+")
    widget.bind("<Destroy>", hide, add="+")


# ---- platinum icon ---------------------------------------------------------
# warframe.market's real platinum icon, embedded as a base64 PNG
# (core/assets.py) and decoded once into a 64x55 master PhotoImage. Smaller
# copies are made by integer subsampling so the gem stays crisp at any size.
# The PNG is transparent, so it composites over whatever background hosts it -
# the `bg` argument is kept only for call-site compatibility and is ignored.
_PLAT_MASTER: tk.PhotoImage | None = None
_PLAT_SCALED: dict[int, tk.PhotoImage] = {}


def plat_master() -> tk.PhotoImage:
    """The full-size (64x55) platinum image; also used as the window icon."""
    global _PLAT_MASTER
    if _PLAT_MASTER is None:
        _PLAT_MASTER = tk.PhotoImage(data=wfm_assets.PLATINUM_PNG_B64)
    return _PLAT_MASTER


def plat_icon(bg: str | None = None, height: int = 14) -> tk.PhotoImage:
    """A platinum gem sized to ~`height` px, cached per height."""
    if height in _PLAT_SCALED:
        return _PLAT_SCALED[height]
    img = plat_master()
    factor = max(1, round(img.height() / height))
    if factor > 1:
        img = img.subsample(factor)
    _PLAT_SCALED[height] = img
    return img


# ---- app logo (Warframe crest) --------------------------------------------
# The title-bar logo, a light silhouette on transparency (core/assets.py), plus
# assets/logo.ico for the window/taskbar icon. Same decode-once-then-subsample
# approach as the platinum gem.
_LOGO_MASTER: tk.PhotoImage | None = None
_LOGO_SCALED: dict[int, tk.PhotoImage] = {}
LOGO_ICO = Path(__file__).resolve().parent / "assets" / "logo.ico"


def logo_master() -> tk.PhotoImage:
    global _LOGO_MASTER
    if _LOGO_MASTER is None:
        _LOGO_MASTER = tk.PhotoImage(data=wfm_assets.LOGO_PNG_B64)
    return _LOGO_MASTER


def logo_icon(height: int = 20) -> tk.PhotoImage:
    """The crest sized to ~`height` px tall, cached per height."""
    if height in _LOGO_SCALED:
        return _LOGO_SCALED[height]
    img = logo_master()
    factor = max(1, round(img.height() / height))
    if factor > 1:
        img = img.subsample(factor)
    _LOGO_SCALED[height] = img
    return img


class ToolRunner:
    """Owns a single subprocess and pumps its output into a queue."""

    def __init__(self) -> None:
        self.proc: subprocess.Popen | None = None
        self.q: "queue.Queue[str | None]" = queue.Queue()

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self, cmd: list[str], cwd: str,
              env: dict[str, str] | None = None) -> None:
        # A FRESH queue per run: a previous run's unread sentinel would
        # otherwise make the next run report "exited" on its first drain.
        self.q = queue.Queue()
        self.proc = subprocess.Popen(
            cmd, cwd=cwd, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True, bufsize=1, encoding="utf-8", errors="replace",
        )
        # the pump owns ITS process and queue, so a restart can never have
        # two pumps feeding one consumer
        threading.Thread(target=self._pump, args=(self.proc, self.q),
                         daemon=True).start()

    @staticmethod
    def _pump(proc: subprocess.Popen, q: "queue.Queue[str | None]") -> None:
        try:
            if proc.stdout is not None:
                for line in proc.stdout:
                    q.put(line)
            proc.wait()
        finally:
            q.put(None)  # sentinel: process finished (always sent)

    def stop(self) -> None:
        if self.running and self.proc:
            self.proc.terminate()


# The embedded web apps table lives in core/webapps.py so the Qt front
# end reads the same list. Re-exported unchanged; WEB_APPS entries are
# NamedTuples, so existing positional unpacking still works.
from core.webapps import WEB_APPS, WEB_KEYS               # noqa: F401


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        # Own taskbar identity: without this Windows groups the app under
        # pythonw.exe and shows the Python icon instead of the crest.
        if IS_WINDOWS:
            try:
                # Pin the DPI mode first: the embedded browser's .NET side
                # flips the process to DPI-aware otherwise, which rescales
                # every coordinate mid-session and shrinks the whole UI on
                # scaled displays. First caller wins, so claim it now.
                ctypes.windll.shcore.SetProcessDpiAwareness(0)
            except Exception:                           # noqa: BLE001
                pass
            try:
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                    "Mortefix.WarframeToolbox")
            except Exception:                               # noqa: BLE001
                pass
        self.title(APP_NAME)
        # Window size / placement come from Settings > Display (default is
        # the ~golden-ratio 1240x766).
        self.settings = wfm_config.load_settings()
        if IS_WINDOWS:
            # Heal stale Start-with-Windows entries: the Run commands bake
            # in absolute pythonw/folder paths, so a moved folder or a new
            # Python leaves entries that fail at logon while the Settings
            # checkbox still reads enabled. No-op when nothing is registered.
            try:
                wfm_config.repair_run_entries()
            except Exception:                               # noqa: BLE001
                pass
        size = self.settings.get("window_size") or "1280x720"
        if size not in wfm_config.WINDOW_SIZES:
            size = "1280x720"
        self.geometry(size)
        self.minsize(640, 480)      # the smallest offered window size
        # Tk's default maxsize is the PRIMARY screen minus assumed window
        # decorations - it would clamp maximize on bigger/secondary
        # monitors, so lift it out of the way.
        self.maxsize(8192, 8192)
        self.configure(bg=BG)

        # How hard Windows is bitmap-stretching us, and the scroll step that
        # keeps every frame on whole device pixels (see display_scale()).
        # Sampled again in _apply_launch_display once the window has been
        # moved to its saved monitor, which may be scaled differently.
        self.display_scale = display_scale(self.winfo_id())
        self.scroll_unit = scroll_unit(self.display_scale)

        # Font families are probed, never assumed: named variable-font
        # instances ("Bahnschrift SemiBold") don't resolve on every machine,
        # so each role falls back down a chain that ends at a family every
        # Windows install has. The chains and sizes belong to core.theme, not
        # to this file - add or retune a role there, in theme.FONTS.
        fams = set(tkfont.families(self))

        # Scrollbars: plain tk.Scrollbar is native-drawn on Windows (light
        # gray, unthemable), so every scrollbar in the app is a ttk one in
        # this flat clam-based style - lacquer trough, bone thumb, gilded
        # under the pointer. Use style="Toolbox.Vertical.TScrollbar".
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Toolbox.Vertical.TScrollbar",
                        background=PANEL_HI, troughcolor=TAB_BG,
                        bordercolor=TAB_BG, arrowcolor=MUTED,
                        relief="flat", gripcount=0)
        style.map("Toolbox.Vertical.TScrollbar",
                  background=[("active", GOLD_DIM), ("pressed", ACCENT)],
                  arrowcolor=[("active", GOLD_HI)])
        # One Font per role in theme.FONTS - the roles, their family
        # preference chains and their sizes are all declared there, so the Tk
        # and Qt front ends cannot drift apart.
        self.fonts = {
            role: tkfont.Font(family=wfm_theme.resolve_family(role, fams),
                              size=wfm_theme.size_of(role))
            for role in wfm_theme.FONTS
        }

        # The account link, owned by the host and shared with every tool.
        self.session: wfm_session.Session | None = wfm_session.load()
        self.session_state = "cached" if self.session else "none"

        # Host-side authenticated client (My Listings). Rebuilt on (un)link.
        self.market: wfm_market.MarketClient | None = (
            wfm_market.MarketClient(self.session) if self.session else None)
        # Session-sticky baseline price per order, so a reprice can never
        # ratchet the floor downward across refreshes. order_id -> platinum.
        self.listing_baseline: dict[str, int] = {}

        # The gateway: the only road from any tool to warframe.market.
        self.gateway = Gateway()
        self.gateway.session = self.session
        self.gateway.start()

        # Online-presence over the WFM websocket (starts offline).
        self.presence = wfm_presence.Presence()
        self.presence.session = self.session
        self.presence.on_change = lambda s, c, d: self.after(
            0, lambda: self._on_presence(s, c, d))

        # -- persistent shell -----------------------------------------------
        # Rows top-to-bottom: [custom title bar] · header · (sidebar | content)
        # The title bar replaces the OS chrome (Windows only); without it the
        # header simply becomes the top row.
        self.try_icon()
        self.nav_btns: dict[str, tk.Button] = {}
        self.current_nav: str | None = None
        self._init_window_chrome()
        row = 0
        if self.custom_chrome:
            self._build_titlebar(row)
            row += 1
        self._build_header(row)
        self.grid_rowconfigure(row + 1, weight=1)
        self.grid_columnconfigure(1, weight=1)
        self._build_sidebar(row + 1)
        self.content = tk.Frame(self, bg=BG)
        self.content.grid(row=row + 1, column=1, sticky="nsew")
        if self.custom_chrome:
            self._build_resize_grip()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        # views that survive navigation (built once, re-packed on return)
        self._persistent: dict[str, tk.Frame] = {}
        # Home is rebuilt on every visit (it bakes the account link state
        # into every card), so its scroll offset is remembered here instead.
        self._home_scroll = 0.0
        self._pending_wiki: str | None = None
        self._refresh_account()
        # Home is the ONLY view built at launch. Every other app builds on
        # its first visit and then lives in _persistent for the rest of the
        # session, so tab-hopping never reloads. Nothing is warmed up in the
        # background: My Listings used to preload here, which cost ~14s of
        # serial market lookups 2.5s after launch for a tab you might never
        # open.
        self.navigate("home")

        if self.session:
            self._verify_session_async()

        # Settings > Display: place on the chosen monitor, then maximize if
        # "launch fullscreen" is on. Minimize-to-tray hooks the <Unmap> event.
        self.after(80, self._apply_launch_display)
        # Embedded web apps: all three browser windows are created at launch
        # in ONE batch (pywebview creates later windows by Invoke()ing
        # through an existing one, which breaks once that window has been
        # re-parented into Tk) - but they sit on about:blank and no site
        # loads until a view asks for it via webhost.open_site(). Between
        # visits they park hidden in web_holder (a never-packed frame), so
        # switching back is instant and the pages keep their state.
        self.webhost = WebHost()
        self.webhost.adblock = bool(self.settings.get("adblock", True))
        self.web_holder = tk.Frame(self)
        if IS_WINDOWS and self.webhost.available:
            self.after(1200, lambda: self.webhost.ensure_all(
                [(k, u) for k, _l, _i, u in WEB_APPS]))
        self.tray = None
        self.bind("<Unmap>", self._maybe_tray)

    def _apply_launch_display(self) -> None:
        try:
            mon = int(self.settings.get("monitor", 1))
            rects = monitor_rects()
            if 1 <= mon <= len(rects):
                left, top, right, bottom = rects[mon - 1]
                w, h = self.winfo_width(), self.winfo_height()
                x = left + max(0, (right - left - w) // 2)
                y = top + max(0, (bottom - top - h) // 3)
                self.geometry(f"+{x}+{y}")
        except Exception:                                   # noqa: BLE001
            pass
        # now that we are on the right monitor, re-sample its scale factor:
        # a second display can be scaled differently from the primary, and
        # the scroll step has to match the display we are actually on.
        self.display_scale = display_scale(self.winfo_id())
        self.scroll_unit = scroll_unit(self.display_scale)
        # Home was built before this ran, against the PRIMARY monitor's
        # scale. If the saved monitor is scaled differently its ScrollArea is
        # still on the old step - re-claim so it re-reads the unit.
        area = getattr(getattr(self, "_active_view", None), "scroll", None)
        if area is not None:
            area.claim_wheel()
        if self.settings.get("fullscreen") and not self._maximized:
            self.after(40, self._toggle_maximize)

    # -- minimize to tray --------------------------------------------------

    def _maybe_tray(self, event) -> None:
        """On minimize (not on ordinary unmaps), hide to the notification
        area when Settings > Display says so."""
        if event.widget is not self:
            return
        if not self.settings.get("minimize_to_tray"):
            return
        try:
            if self.state() != "iconic":
                return
        except tk.TclError:
            return
        self.withdraw()
        if self.tray is None:
            from core.tray import TrayIcon
            self.tray = TrayIcon(
                APP_NAME, str(LOGO_ICO),
                lambda: self.after(0, self._restore_from_tray))
        self.tray.show()

    def _restore_from_tray(self) -> None:
        if self.tray is not None:
            self.tray.hide()
        self.deiconify()
        self.lift()
        self.focus_force()

    def try_icon(self) -> None:
        """Use the Warframe crest as the window/taskbar icon - the multi-size
        .ico on Windows (crisp in the taskbar), a PhotoImage elsewhere."""
        try:
            if IS_WINDOWS and LOGO_ICO.exists():
                self.iconbitmap(default=str(LOGO_ICO))
            else:
                self.iconphoto(True, logo_master())
        except tk.TclError:
            try:
                self.iconphoto(True, logo_master())
            except tk.TclError:
                pass
        if IS_WINDOWS:
            # Tk only reliably sets the SMALL window icon; the TASKBAR shows
            # the BIG one and falls back to pythonw's icon without this.
            self.after(200, self._apply_win_icons)

    def _apply_win_icons(self) -> None:
        try:
            if not LOGO_ICO.exists():
                return
            u = ctypes.windll.user32
            u.LoadImageW.restype = ctypes.c_void_p
            u.LoadImageW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p,
                                     ctypes.c_uint, ctypes.c_int,
                                     ctypes.c_int, ctypes.c_uint]
            u.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                                       ctypes.c_void_p, ctypes.c_void_p]
            hwnd = self._hwnd()
            WM_SETICON, LR_LOADFROMFILE = 0x0080, 0x10
            small = u.GetSystemMetrics(49) or 16    # SM_CXSMICON
            big = u.GetSystemMetrics(11) or 32      # SM_CXICON
            for size, which in ((small, 0), (big, 1)):
                h = u.LoadImageW(None, str(LOGO_ICO), 1, size, size,
                                 LR_LOADFROMFILE)
                if h:
                    u.SendMessageW(hwnd, WM_SETICON, which, h)
        except Exception:                               # noqa: BLE001
            pass

    # -- shell: custom title bar (Windows) ------------------------------------

    def _init_window_chrome(self) -> None:
        """Replace the OS title bar with our own on Windows - WITHOUT
        overrideredirect. The window stays a normal, managed app window
        (taskbar button, alt-tab, minimize animation all intact); we only
        strip the native caption + sizing frame from its Win32 style and
        draw our own bar. Falls back to the native title bar elsewhere."""
        self.custom_chrome = False
        self._maximized = False
        if not IS_WINDOWS:
            return
        self.custom_chrome = True
        self.after(20, self._strip_native_frame)
        # Tk re-applies window styles on some state changes (deiconify after
        # a minimize, for example) - re-strip whenever the window maps.
        self.bind("<Map>", lambda e: self.after(10, self._strip_native_frame)
                  if e.widget is self else None)

    def _hwnd(self) -> int:
        return ctypes.windll.user32.GetParent(self.winfo_id())

    def _strip_native_frame(self) -> None:
        try:
            GWL_STYLE = -16
            WS_CAPTION = 0x00C00000
            WS_THICKFRAME = 0x00040000
            u = ctypes.windll.user32
            hwnd = self._hwnd()
            style = u.GetWindowLongW(hwnd, GWL_STYLE)
            if not (style & (WS_CAPTION | WS_THICKFRAME)):
                return                      # already stripped
            u.SetWindowLongW(hwnd, GWL_STYLE,
                             style & ~(WS_CAPTION | WS_THICKFRAME))
            # SWP_NOMOVE|NOSIZE|NOZORDER|FRAMECHANGED: apply the style now
            u.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0004
                           | 0x0020)
        except Exception:                                   # noqa: BLE001
            pass

    def _build_titlebar(self, row: int) -> None:
        bar = tk.Frame(self, bg=TITLEBAR_BG, height=34)
        bar.grid(row=row, column=0, columnspan=2, sticky="ew")
        bar.grid_propagate(False)
        # the cabinet's gold trim: a 1px inlay line along the lid's bottom edge
        tk.Frame(bar, bg=GOLD_DIM, height=1).pack(side="bottom", fill="x")

        left = tk.Frame(bar, bg=TITLEBAR_BG)
        left.pack(side="left", padx=(12, 0))
        self._logo_title = logo_icon(height=22)
        gem = tk.Label(left, image=self._logo_title, bg=TITLEBAR_BG)
        gem.pack(side="left", padx=(0, 9), pady=6)
        # engraved wordmark: letterspaced caps in aged bone
        wordmark = " ".join(APP_NAME.upper())
        name = tk.Label(left, text=wordmark, bg=TITLEBAR_BG, fg=MUTED,
                        font=self.fonts["small"])
        name.pack(side="left")

        ctrls = tk.Frame(bar, bg=TITLEBAR_BG)
        ctrls.pack(side="right")

        def cbtn(text: str, cmd, hover: str) -> tk.Button:
            b = tk.Button(ctrls, text=text, command=cmd, bg=TITLEBAR_BG,
                          fg=MUTED, relief="flat", bd=0, padx=15, pady=7,
                          cursor="hand2", font=self.fonts["body"],
                          activebackground=hover, activeforeground=TEXT)
            b.pack(side="left", fill="y")
            b.bind("<Enter>", lambda _e: b.configure(bg=hover, fg=TEXT))
            b.bind("<Leave>", lambda _e: b.configure(bg=TITLEBAR_BG, fg=MUTED))
            return b

        cbtn("─", self._minimize, TITLEBAR_HOVER)         # ─ minimise
        self.max_btn = cbtn("☐", self._toggle_maximize,   # ☐ maximise
                            TITLEBAR_HOVER)
        cbtn("✕", self._on_close, TITLEBAR_CLOSE)         # ✕ close

        # Drag anywhere on the bar (and its title text/icon); double-click to
        # toggle maximise, like a native title bar.
        for w in (bar, left, gem, name):
            w.bind("<Button-1>", self._start_move)
            w.bind("<B1-Motion>", self._on_move)
            w.bind("<Double-Button-1>", lambda _e: self._toggle_maximize())

    def _minimize(self) -> None:
        # A normal managed window again, so plain iconify works - and the
        # <Unmap> binding handles minimize-to-tray if that setting is on.
        self.iconify()

    def _toggle_maximize(self) -> None:
        if not self.custom_chrome:
            self.state("normal" if self.state() == "zoomed" else "zoomed")
            return
        if self._maximized:
            # Windows itself remembers the pre-maximize rect; requesting a
            # geometry here would re-add Tk's phantom frame metrics and
            # push the window off the screen edge again.
            self.state("normal")
            self._maximized = False
            self.max_btn.configure(text="☐")             # ☐
        else:
            # Native maximize: Windows sizes the (caption-stripped) window
            # to the monitor work area exactly, and Tk's geometry model
            # stays in sync - hand-rolled geometry requests here fight
            # Tk's phantom frame metrics and bleed off the screen edge.
            self.state("zoomed")
            self._maximized = True
            self.max_btn.configure(text="❐")             # ❐ restore

    def _start_move(self, event) -> None:
        self._drag_x, self._drag_y = event.x_root, event.y_root
        self._drag_ox, self._drag_oy = self.winfo_x(), self.winfo_y()

    def _on_move(self, event) -> None:
        if self._maximized:                 # un-maximise and grab under cursor
            self._toggle_maximize()
            self._drag_ox, self._drag_oy = self.winfo_x(), self.winfo_y()
            self._drag_x, self._drag_y = event.x_root, event.y_root
            return
        dx, dy = event.x_root - self._drag_x, event.y_root - self._drag_y
        self.geometry(f"+{self._drag_ox + dx}+{self._drag_oy + dy}")

    def _build_resize_grip(self) -> None:
        grip = tk.Label(self, text="◢", bg=BG, fg=MUTED,   # ◢
                        cursor="size_nw_se", font=self.fonts["small"])
        grip.place(relx=1.0, rely=1.0, anchor="se")
        grip.bind("<Button-1>", self._start_resize)
        grip.bind("<B1-Motion>", self._on_resize)

    def _start_resize(self, event) -> None:
        self._rs_x, self._rs_y = event.x_root, event.y_root
        self._rs_w, self._rs_h = self.winfo_width(), self.winfo_height()

    def _on_resize(self, event) -> None:
        min_w, min_h = self.minsize()
        w = max(min_w, self._rs_w + event.x_root - self._rs_x)
        h = max(min_h, self._rs_h + event.y_root - self._rs_y)
        self.geometry(f"{w}x{h}")

    # -- shell: header ---------------------------------------------------

    def _build_header(self, row: int) -> None:
        header = tk.Frame(self, bg=HEADER_BG)
        header.grid(row=row, column=0, columnspan=2, sticky="ew")
        # hairline between the header and the content below it
        tk.Frame(header, bg=HAIRLINE, height=1).pack(side="bottom", fill="x")
        left = tk.Frame(header, bg=HEADER_BG)
        left.pack(side="left", padx=20, pady=(10, 8))
        # The app name lives in the title bar now; the header shows the current
        # section (set by navigate()) so it reads like a breadcrumb.
        self.page_title = tk.Label(left, text="", bg=HEADER_BG, fg=TEXT,
                                   font=self.fonts["h1"])
        self.page_title.pack(anchor="w")
        # the Orokin finial: a short gold rule ending in a spearpoint diamond
        # - the page's "engraved" underline, drawn once, never animated
        fin = tk.Canvas(left, width=118, height=9, bg=HEADER_BG,
                        highlightthickness=0, bd=0)
        fin.pack(anchor="w", pady=(3, 0))
        fin.create_rectangle(0, 3, 102, 5, fill=ACCENT, width=0)
        fin.create_polygon(102, 0, 116, 4, 102, 8,
                           fill=GOLD_HI, outline=GOLD_DIM)

        # The WF Market account widget, pinned to the header across all apps.
        acct = tk.Frame(header, bg=HEADER_BG)
        acct.pack(side="right", padx=20)

        # online-status toggle (only meaningful with a linked account)
        self.status_ctrl = tk.Frame(acct, bg=HEADER_BG)
        self.status_ctrl.pack(side="left", padx=(0, 16))
        tk.Label(self.status_ctrl, text="Status", bg=HEADER_BG, fg=MUTED,
                 font=self.fonts["small"]).pack(side="left", padx=(0, 6))
        self.status_btns: dict[str, tk.Button] = {}
        for state, label, color in (("online", "Online", OK),
                                    ("ingame", "In-game", WFM_TEAL),
                                    ("offline", "Offline", MUTED)):
            b = tk.Button(self.status_ctrl, text=label,
                          command=lambda s=state: self._set_presence(s),
                          bg=PANEL, fg=TEXT, relief="flat", bd=0, padx=9,
                          pady=3, cursor="hand2", font=self.fonts["small"],
                          activebackground=PANEL_HI)
            b.pack(side="left", padx=(0, 2))
            b._accent = color
            self.status_btns[state] = b
        self.status_detail = tk.Label(self.status_ctrl, text="", bg=HEADER_BG,
                                      fg=MUTED, font=self.fonts["small"])
        self.status_detail.pack(side="left", padx=(6, 0))

        info = tk.Frame(acct, bg=HEADER_BG)
        info.pack(side="left")
        self.acct_label = tk.Label(info, text="", bg=HEADER_BG, fg=MUTED,
                                   font=self.fonts["small"])
        self.acct_label.pack(side="left", padx=(0, 10))
        self.acct_btn = tk.Button(info, relief="flat", bd=0, padx=12, pady=4,
                                  cursor="hand2", font=self.fonts["small"],
                                  activebackground=PANEL_HI)
        self.acct_btn.pack(side="left")

    def _refresh_account(self) -> None:
        """Repaint the pinned account widget + status toggle for the current
        session state."""
        if self.session is None:
            self.acct_label.configure(text="No account linked", fg=WARN)
            self.acct_btn.configure(text="Link account", bg=ACCENT,
                                    fg=INK, command=self.link_account)
            self.acct_btn.pack(side="left")
            self.status_ctrl.pack_forget()
        else:
            state = {"cached": "verifying…", "ok": "session OK",
                     "expired": "session EXPIRED - re-link"}[self.session_state]
            color = {"cached": MUTED, "ok": OK, "expired": ERR}[self.session_state]
            self.acct_label.configure(
                text=f"{self.session.username} ({self.session.platform}) - "
                     f"{state}", fg=color)
            if self.session_state == "expired":
                self.acct_btn.configure(text="Re-link", bg=ACCENT,
                                        fg=INK, command=self.link_account)
                self.acct_btn.pack(side="left")
            else:
                # Unlink lives on Settings > Data > Market now; a healthy
                # linked session needs no button in the header.
                self.acct_btn.pack_forget()
            self.status_ctrl.pack(side="left", padx=(0, 16))
            self._paint_status()
        # keep an open Settings > Data > Market page's session row in sync
        fn = getattr(getattr(self, "_active_view", None),
                     "update_session", None)
        if fn:
            fn()

    # -- shell: sidebar --------------------------------------------------

    def _nav_items(self) -> list[wfm_nav.NavItem]:
        """(key, label, icon, requires_session). The order and contents are
        core.nav's, so the Qt shell cannot drift from this one."""
        return wfm_nav.nav_items(TOOLS)

    def _build_sidebar(self, row: int) -> None:
        """Each nav item is a row: [finial canvas | Fluent icon | label].
        The 10px canvas on the left edge carries the Orokin finial - a gold
        stem swelling into a spearpoint diamond - on the ACTIVE item only;
        everywhere else it is empty rail."""
        side = tk.Frame(self, bg=SIDEBAR_BG, width=186)
        side.grid(row=row, column=0, sticky="ns")
        side.grid_propagate(False)
        self.nav_rows: dict[str, tuple] = {}
        for key, label, icon_key, _needs in self._nav_items():
            # ICONS key -> the Segoe codepoint this toolkit can draw
            icon = wfm_theme.glyph(icon_key, fluent=True)
            rowf = tk.Frame(side, bg=SIDEBAR_BG)
            rowf.pack(fill="x")
            # height=1: a Canvas otherwise requests its ~265px default and
            # balloons the row; fill="y" stretches it to the real row height
            fin = tk.Canvas(rowf, width=10, height=1, bg=SIDEBAR_BG,
                            highlightthickness=0, bd=0)
            fin.pack(side="left", fill="y")
            ic = tk.Label(rowf, text=icon, width=2, bg=SIDEBAR_BG, fg=MUTED,
                          font=self.fonts["icon"], cursor="hand2")
            ic.pack(side="left")
            b = tk.Button(rowf, text=label, anchor="w",
                          command=lambda k=key: self.navigate(k),
                          bg=SIDEBAR_BG, fg=MUTED, relief="flat", bd=0,
                          padx=8, pady=11, cursor="hand2",
                          font=self.fonts["h2"],
                          activebackground=SIDEBAR_ACTIVE,
                          activeforeground=TEXT)
            b.pack(side="left", fill="x", expand=True)
            for w in (rowf, fin, ic):
                w.bind("<Button-1>", lambda _e, k=key: self.navigate(k))
            for w in (rowf, fin, ic, b):
                w.bind("<Enter>", lambda _e, k=key: self._nav_hover(k, True))
                w.bind("<Leave>", lambda _e, k=key: self._nav_hover(k, False))
            # the finial needs a real height before it can be drawn; redraw
            # whenever the row is (re)sized
            fin.bind("<Configure>", lambda _e, k=key: self._paint_finial(k))
            self.nav_btns[key] = b
            self.nav_rows[key] = (rowf, fin, ic)

    def _paint_sidebar(self) -> None:
        for key, b in self.nav_btns.items():
            active = key == self.current_nav
            bg = SIDEBAR_ACTIVE if active else SIDEBAR_BG
            rowf, fin, ic = self.nav_rows[key]
            rowf.configure(bg=bg)
            ic.configure(bg=bg, fg=ACCENT if active else MUTED)
            b.configure(bg=bg, fg=TEXT if active else MUTED)
            self._paint_finial(key)

    def _paint_finial(self, key: str) -> None:
        """Draw (or clear) the gold finial on one nav row's canvas."""
        _rowf, fin, _ic = self.nav_rows[key]
        active = key == self.current_nav
        fin.delete("all")
        fin.configure(bg=SIDEBAR_ACTIVE if active else _rowf.cget("bg"))
        if not active:
            return
        h = fin.winfo_height()
        if h < 24:
            return                    # not laid out yet; <Configure> re-fires
        mid = h // 2
        fin.create_rectangle(3, 7, 5, h - 7, fill=ACCENT, width=0)
        fin.create_polygon(2, mid - 7, 9, mid, 2, mid + 7,
                           fill=GOLD_HI, outline=GOLD_DIM)

    def _nav_hover(self, key: str, on: bool) -> None:
        """Row-wide hover tint for an inactive nav item."""
        if key == self.current_nav:
            return
        bg = TITLEBAR_HOVER if on else SIDEBAR_BG
        rowf, fin, ic = self.nav_rows[key]
        rowf.configure(bg=bg)
        fin.configure(bg=bg)
        ic.configure(bg=bg, fg=TEXT if on else MUTED)
        self.nav_btns[key].configure(bg=bg, fg=TEXT if on else MUTED)

    # -- navigation ------------------------------------------------------

    def navigate(self, key: str) -> None:
        self.current_nav = key
        self._paint_sidebar()
        labels = {k: label for k, label, _i, _n in self._nav_items()}
        # tools hidden from the sidebar (e.g. API Status, opened from
        # Settings) still deserve a header title
        title = labels.get(key) or next(
            (t.name for t in TOOLS if t.id == key), "")
        self.page_title.configure(text=title)
        _tooltip_hide_all()   # no plaque outlives the screen it belongs to
        for child in self.content.winfo_children():
            # Lifecycle hook, the mirror of on_show(): the outgoing view is
            # still packed here, which is the only moment it can legally
            # release bind_all("<MouseWheel>"). Note winfo_children()
            # includes pack_forget()'d widgets, so EVERY built persistent
            # view gets this on every navigation - on_hide() must be
            # idempotent and must not assume it was the visible one.
            hide = getattr(child, "on_hide", None)
            if hide:
                try:
                    hide()
                except tk.TclError:
                    pass        # a half-torn-down view must not block nav
            # ORDER: park before persistence. A web app must hand its
            # browser back BEFORE the pane dies (Win32 destroys child
            # windows with their parent). No web view is persistent - if one
            # ever becomes persistent this chain MUST be reordered, or it
            # would be parked and destroyed while still sitting in
            # _persistent as a dead entry.
            park = getattr(child, "park", None)
            if park:
                park()
                child.destroy()
            elif child in self._persistent.values():
                child.pack_forget()     # keep it (and its data) alive
            else:
                child.destroy()
        # NO update_idletasks() here or after the pack() below. It does not
        # flush "this widget" - it synchronously drains every pending idle
        # task in the interpreter, which cost 770ms of a 1106ms startup and
        # turned a lap of tab switches from 308ms into 3920ms. Let Tk
        # coalesce the layout the way it normally does; nothing downstream
        # may depend on the map having already happened.
        view = self._view_for(key)
        self._active_view = view
        view.pack(fill="both", expand=True)
        # Lifecycle hook: a view (persistent ones especially - they are
        # re-packed, not rebuilt) can define on_show() to refresh its data
        # every time its app is opened. Keep these cheap: a stat() check,
        # not an unconditional re-fetch.
        shown = getattr(view, "on_show", None)
        if shown:
            shown()

    def _view_for(self, key: str) -> tk.Frame:
        items = {k: (label, needs)
                 for k, label, _i, needs in self._nav_items()}
        label, needs = items.get(key, (key, False))
        if needs and self.session is None:
            return self._needs_account(label)
        if key == "home":
            return HomeView(self.content, self)
        if key == "listings":
            # persistent: fetched data survives switching apps, so the tab
            # opens instantly after the first visit builds it
            view = self._persistent.get("listings")
            if view is None or not view.winfo_exists():
                view = ListingsView(self.content, self)
                self._persistent["listings"] = view
            return view
        if key == "market":
            # persistent: the whole warframe.market catalogue (downloaded
            # once by MarketTab), the loaded order book and the riven weapon
            # lists all survive switching apps. ACCOUNT-SCOPED - the client
            # is baked in at build time, so _drop_account_views() rebuilds
            # it on link/unlink.
            view = self._persistent.get("market")
            if view is None or not view.winfo_exists():
                view = MarketView(self.content, self)
                self._persistent["market"] = view
            return view
        if key == "vosfor":
            view = self._persistent.get("vosfor")
            if view is None or not view.winfo_exists():
                view = VosforView(self.content, self)
                self._persistent["vosfor"] = view
            return view
        if key in ("settings", "profile"):     # profile deprecated -> settings
            return SettingsView(self.content, self)
        web = next((w for w in WEB_APPS if w[0] == key), None)
        if web is not None:
            return WebAppView(self.content, self, *web)
        tool = next((t for t in TOOLS if t.id == key), None)
        if tool is not None:
            return RunnerView(self.content, self, tool)
        return HomeView(self.content, self)

    def open_wiki(self, name: str) -> None:
        """Open an item on the Warframe wiki INSIDE the app's Wiki tab.

        Deliberately never webbrowser.open(): the wiki IS one of our tabs
        (apps load into the container), and shelling out would lose the ad
        blocker and the page state the tab has built up. The URL is parked
        here for the WebAppView that navigate() is about to build, so on the
        first wiki click of a session it is the very first URL that browser
        ever loads - no home page, then a jump."""
        url = wfm_wiki.url_for(name or "")
        if not url:
            return
        self._pending_wiki = url
        self.navigate("web_wiki")

    def _needs_account(self, label: str) -> tk.Frame:
        f = tk.Frame(self.content, bg=BG)
        box = tk.Frame(f, bg=PANEL, padx=40, pady=28)
        box.place(relx=0.5, rely=0.4, anchor="center")
        tk.Label(box, text=f"{label} needs a linked account", bg=PANEL,
                 fg=TEXT, font=self.fonts["h2"]).pack()
        tk.Label(box, text="Link your warframe.market account to continue.",
                 bg=PANEL, fg=MUTED, font=self.fonts["small"]).pack(
                     pady=(6, 14))
        tk.Button(box, text="Link account", command=self.link_account,
                  bg=ACCENT, fg=INK, relief="flat", bd=0, padx=16,
                  pady=6, cursor="hand2", font=self.fonts["small"],
                  activebackground=PANEL_HI).pack()
        return f

    # -- session management --------------------------------------------

    def _verify_session_async(self) -> None:
        """Confirm the cached JWT still works, off the UI thread."""
        sess = self.session

        def work() -> None:
            ok = wfm_session.validate(sess) if sess else False
            def apply() -> None:
                if self.session is not sess:
                    return          # user re-linked/unlinked meanwhile
                self.session_state = "ok" if ok else "expired"
                self._refresh_account()
            self.after(0, apply)

        threading.Thread(target=work, daemon=True).start()

    def market_any(self) -> wfm_market.MarketClient:
        """A market client that always works: the authenticated one when an
        account is linked, else a shared public (read-only) client. Public
        endpoints - order books, item index, contracts - need no session."""
        if self.market is not None:
            return self.market
        if getattr(self, "_public_market", None) is None:
            self._public_market = wfm_market.MarketClient(None)
        return self._public_market

    def _drop_account_views(self) -> None:
        """Forget the cached views that bake the account in at build time.

        ListingsView holds one user's orders. MarketView copies
        market_any() into all three of its tabs at construction, so one
        built while unlinked would keep the PUBLIC client for the rest of
        the session and silently fail every authenticated action."""
        for key in ("listings", "market"):
            old = self._persistent.pop(key, None)
            if old is None:
                continue
            # never leave _active_view pointing at a destroyed widget: the
            # presence and account callbacks getattr methods off it from a
            # background thread, and unlink is reached FROM Settings
            if old is getattr(self, "_active_view", None):
                self._active_view = None
            _stop_view(old)
            try:
                old.destroy()
            except tk.TclError:
                pass

    def drop_persistent_views(self) -> None:
        """Forget every cached view so the next visit rebuilds from disk.

        Persistent views hold their data in memory and write it back on
        interaction, so anything that invalidates their source (a data wipe)
        must drop them or the deleted state comes right back."""
        views, self._persistent = self._persistent, {}
        for view in views.values():
            try:
                if view is getattr(self, "_active_view", None):
                    self._active_view = None
                _stop_view(view)
                view.destroy()
            except tk.TclError:
                pass

    def link_account(self) -> None:
        LoginDialog(self)

    def on_login(self, sess: wfm_session.Session) -> None:
        self.session = sess
        self.session_state = "ok"
        self.gateway.session = sess          # live tools pick this up too
        self.market = wfm_market.MarketClient(sess)
        self.presence.set_session(sess)
        self.listing_baseline.clear()
        self._drop_account_views()
        self._refresh_account()
        self.navigate("home")

    def unlink_account(self) -> None:
        self.presence.set_session(None)      # closes the socket -> offline
        wfm_session.logout()
        self.session = None
        self.session_state = "none"
        self.gateway.session = None
        self.market = None
        self.listing_baseline.clear()
        self._drop_account_views()
        self._refresh_account()
        self.navigate("home")

    # -- online presence -------------------------------------------------

    def _set_presence(self, state: str) -> None:
        self.presence.set_state(state)
        self._paint_status()

    def _on_presence(self, state: str, connected: bool,
                     detail: str | None) -> None:
        self._paint_status()
        self.status_detail.configure(text=detail or "")
        # keep an open Settings > Data > Market page's status in sync
        fn = getattr(getattr(self, "_active_view", None),
                     "update_presence", None)
        if fn:
            fn()

    def _paint_status(self) -> None:
        want = self.presence.want
        for state, b in self.status_btns.items():
            active = state == want
            b.configure(bg=b._accent if active else PANEL,
                        fg=INK if active else TEXT)

    def _on_close(self) -> None:
        try:
            # Flush settings: views debounce their writes (the Vosfor
            # balance waits 600ms), and a pending after() dies with the
            # mainloop - so the last thing typed would be lost.
            wfm_config.save_settings(self.settings)
        except OSError:
            pass
        try:
            if self.tray is not None:
                self.tray.hide()
            self.webhost.shutdown()   # .NET UI thread would outlive us
            self.presence.shutdown()
            self.gateway.stop()
        finally:
            self.destroy()


class LoginDialog(tk.Toplevel):
    """Modal sign-in. The password is read from the field, sent to WFM once,
    and discarded - it is never stored or handed to tools."""

    def __init__(self, app: App) -> None:
        super().__init__(app)
        self.app = app
        self.title("Link warframe.market account")
        self.configure(bg=PANEL, padx=22, pady=18)
        self.resizable(False, False)
        self.transient(app)
        self.grab_set()

        prev = wfm_session.load()
        f = app.fonts

        tk.Label(self, text="Link your warframe.market account", bg=PANEL,
                 fg=TEXT, font=f["h2"]).grid(row=0, column=0, columnspan=2,
                                             sticky="w", pady=(0, 2))
        tk.Label(self, text="Credentials are sent only to api.warframe.market.\n"
                            "Your password is never saved - only the session "
                            "token is kept.",
                 bg=PANEL, fg=MUTED, justify="left",
                 font=f["small"]).grid(row=1, column=0, columnspan=2,
                                       sticky="w", pady=(0, 14))

        tk.Label(self, text="Email", bg=PANEL, fg=MUTED,
                 font=f["small"]).grid(row=2, column=0, sticky="w")
        self.email = tk.Entry(self, width=34, font=f["small"],
                              **field_style(False))
        self.email.grid(row=2, column=1, sticky="w", ipady=4, pady=3)
        if prev and prev.email:
            self.email.insert(0, prev.email)

        tk.Label(self, text="Password", bg=PANEL, fg=MUTED,
                 font=f["small"]).grid(row=3, column=0, sticky="w")
        self.password = tk.Entry(self, width=34, show="•", font=f["small"],
                                 **field_style(False))
        self.password.grid(row=3, column=1, sticky="w", ipady=4, pady=3)

        tk.Label(self, text="Platform", bg=PANEL, fg=MUTED,
                 font=f["small"]).grid(row=4, column=0, sticky="w")
        self.platform = tk.StringVar(value=prev.platform if prev else "pc")
        pf = tk.Frame(self, bg=PANEL)
        pf.grid(row=4, column=1, sticky="w", pady=3)
        for p in ("pc", "xbox", "ps4", "switch"):
            tk.Radiobutton(pf, text=p, value=p, variable=self.platform,
                           bg=PANEL, fg=TEXT, selectcolor=CONSOLE_BG,
                           activebackground=PANEL, activeforeground=TEXT,
                           font=f["small"], highlightthickness=0
                           ).pack(side="left", padx=(0, 8))

        self.status = tk.Label(self, text="", bg=PANEL, fg=ERR, justify="left",
                               wraplength=330, font=f["small"])
        self.status.grid(row=5, column=0, columnspan=2, sticky="w", pady=(8, 0))

        btns = tk.Frame(self, bg=PANEL)
        btns.grid(row=6, column=0, columnspan=2, sticky="e", pady=(12, 0))
        self.ok_btn = tk.Button(btns, text="Sign in", command=self._submit,
                                bg=ACCENT, fg=INK, relief="flat", bd=0,
                                padx=16, pady=5, cursor="hand2",
                                font=f["small"], activebackground=GOLD_HI)
        self.ok_btn.pack(side="right", padx=(8, 0))
        tk.Button(btns, text="Cancel", command=self.destroy,
                  **secondary_style(f["small"], wide=True)).pack(side="right")

        self.bind("<Return>", lambda _e: self._submit())
        (self.password if prev and prev.email else self.email).focus_set()

    def _submit(self) -> None:
        email = self.email.get().strip()
        pw = self.password.get()
        if not email or not pw:
            self.status.configure(text="Email and password are required.")
            return
        self.ok_btn.configure(state="disabled", text="Signing in…")
        self.status.configure(text="", fg=MUTED)

        def work() -> None:
            try:
                sess = wfm_session.login(email, pw, self.platform.get())
            except wfm_session.AuthError as exc:
                msg = str(exc)
                self.after(0, lambda: self._fail(msg))
                return
            self.after(0, lambda: self._done(sess))

        threading.Thread(target=work, daemon=True).start()

    def _fail(self, msg: str) -> None:
        if not self.winfo_exists():
            return
        self.ok_btn.configure(state="normal", text="Sign in")
        self.status.configure(text=msg, fg=ERR)

    def _done(self, sess: wfm_session.Session) -> None:
        app = self.app
        self.destroy()
        app.on_login(sess)


class WebAppView(tk.Frame):
    """Hosts one embedded web app (Edge WebView2). The browser window is
    owned by app.webhost and merely borrowed while this view is on screen,
    so the page keeps its state when you switch apps and come back."""

    def __init__(self, parent, app: App, key: str, label: str,
                 icon: str, url: str) -> None:
        super().__init__(parent, bg=BG)
        self.app = app
        self.key = key
        self.url = url
        self._embedded = False
        self._dead = False
        self._embed_job: str | None = None

        # A wiki link parked a deep link on the App - consume it BEFORE the
        # availability check, so it is never stranded, and so the fallback
        # below offers the article rather than the wiki home page. Consuming
        # matters: a stale deep link must not leak into a later plain visit.
        self._want_url: str | None = None
        self._url_sent = False
        if key == "web_wiki" and getattr(app, "_pending_wiki", None):
            self._want_url = app._pending_wiki
            app._pending_wiki = None

        if not IS_WINDOWS or not app.webhost.available:
            self._fallback(label)
            return

        # The web page is a lit pane set into darker cabinetry: a deepest-
        # black gutter with a 1px hairline frame surrounds the browser, so
        # the site's cool palette reads as an intentional inset, not a clash.
        gutter = tk.Frame(self, bg=ICON_BG, highlightthickness=1,
                          highlightbackground=HAIRLINE)
        gutter.pack(fill="both", expand=True, padx=SP_MD, pady=SP_MD)
        # the pane the browser fills; a status line shows until it's ready
        self.pane = tk.Frame(gutter, bg=ICON_BG)
        self.pane.pack(fill="both", expand=True, padx=SP_SM, pady=SP_SM)
        self.status = tk.Label(self.pane, text=f"Loading {label}…",
                               bg=ICON_BG, fg=MUTED, font=app.fonts["h2"])
        self.status.place(relx=0.5, rely=0.4, anchor="center")

        # every site's window is created up front, in one batch - creating
        # one later, while another is already embedded, breaks pywebview
        app.webhost.ensure_all([(k, u) for k, _l, _i, u in WEB_APPS])
        self.bind("<Destroy>", self._on_destroy, add="+")
        self.pane.bind("<Configure>", self._on_resize, add="+")
        self._embed_job = self.after(80, self._try_embed)

    def _fallback(self, label: str) -> None:
        box = tk.Frame(self, bg=PANEL, padx=40, pady=28)
        box.place(relx=0.5, rely=0.4, anchor="center")
        tk.Label(box, text=f"{label} can't be embedded", bg=PANEL, fg=TEXT,
                 font=self.app.fonts["h2"]).pack()
        why = self.app.webhost.error or "embedding needs Windows + WebView2"
        tk.Label(box, text=why, bg=PANEL, fg=MUTED,
                 font=self.app.fonts["small"]).pack(pady=(6, 14))
        # the ONLY route to an external browser, reachable only when
        # embedding is impossible, and only on an explicit click
        tk.Button(box, text="Open in browser",
                  command=lambda: webbrowser.open(self._want_url or self.url),
                  **secondary_style(self.app.fonts["small"],
                                    wide=True)).pack()

    # How long to keep the "Loading ..." plate up. The site is only asked
    # for on the first visit now, so the wait covers the ad blocker arming
    # (typically well under a second) rather than a cold browser boot.
    LOAD_GRACE = 4000

    def _try_embed(self, waited_ms: int = 0, load_ms: int = 0) -> None:
        self._embed_job = None
        if self._dead:
            return
        wh = self.app.webhost
        if not wh.available or waited_ms > 30000:
            # broken/blocked WebView2 (e.g. a second Toolbox instance holds
            # the browser profile) - stop spinning and offer the browser
            for c in self.winfo_children():
                c.destroy()
            self._fallback(self.app.page_title.cget("text") or "This app")
            return
        w = self.pane.winfo_width()
        h = self.pane.winfo_height()
        if w <= 1 or h <= 1:
            # pane not laid out yet - embedding now would leave a 1x1
            # browser with no <Configure> coming to fix it
            self._embed_job = self.after(
                60, lambda: self._try_embed(waited_ms + 60, load_ms))
            return
        # Ask for the site (idempotent; the first visit of the session is
        # what actually triggers the load), then wait briefly for it to
        # start - embedding an about:blank browser flashes a full-pane WHITE
        # rectangle over our dark "Loading ..." plate.
        # Deliver the deep link once, but KEEP it: the 30s timeout branch
        # above builds the fallback from `_want_url or self.url`, and
        # clearing it here would offer the wiki home page instead of the
        # article the user actually clicked.
        wh.open_site(self.key, None if self._url_sent else self._want_url)
        self._url_sent = True
        if not wh.is_navigated(self.key) and load_ms < self.LOAD_GRACE:
            self._embed_job = self.after(
                120, lambda: self._try_embed(waited_ms, load_ms + 120))
            return
        if wh.embed(self.key, self.pane.winfo_id(), w, h):
            self._embedded = True
            self.status.place_forget()
        else:                                    # window not created yet
            self._embed_job = self.after(
                120, lambda: self._try_embed(waited_ms + 120, load_ms))

    def _on_resize(self, event) -> None:
        if self._embedded:
            self.app.webhost.resize(self.key, event.width, event.height)

    def _cancel_embed(self) -> None:
        if self._embed_job is not None:
            try:
                self.after_cancel(self._embed_job)
            except tk.TclError:
                pass
            self._embed_job = None

    def on_hide(self) -> None:
        """Host lifecycle hook. park() runs right after and sets _dead,
        which _try_embed checks - but a cancelled timer beats a guard that
        happens to catch it."""
        self._cancel_embed()

    def park(self) -> None:
        """Hand the browser back to the app's hidden holder. MUST run while
        the pane still exists - once the pane's window dies, any browser
        still inside dies with it (Win32 destroys child windows)."""
        if not self._dead:
            self._dead = True
            self._cancel_embed()
            if self._embedded:
                self.app.webhost.release(self.key,
                                         self.app.web_holder.winfo_id())

    def _on_destroy(self, event) -> None:
        # backstop only - navigate() parks before destroying the view
        if event.widget is self:
            self.park()


class VosforView(tk.Frame):
    """Vosfor planner. Shows every Arcane Collection as a checklist of its
    arcanes (maxed / owned / missing), marks completed collections, and
    ranks all collections by how many still-needed arcanes a 200-Vosfor
    purchase is expected to yield - so you can see at a glance where your
    Vosfor does the most good. Arcane ownership is read from AlecaFrame's
    inventory cache (read-only); without it, tick arcanes off by hand."""

    # Rarity reads as a metal ladder: bronze -> silver -> gold -> platinum.
    # Rare uses ACCENT (the palette's gold) rather than GOLD_HI, which is
    # scoped to finial tips / hover / caret.
    RARITY_COLOR = {"Common": RARITY_BRONZE, "Uncommon": RARITY_SILVER,
                    "Rare": ACCENT, "Legendary": PLAT}
    STATUS_MARK = {wfm_vosfor.MAXED: ("✔", OK),
                   wfm_vosfor.OWNED: ("◐", WARN),
                   wfm_vosfor.MISSING: ("✗", WFM_MUTED)}

    def __init__(self, parent: tk.Widget, app: App) -> None:
        super().__init__(parent, bg=BG)
        self.app = app
        self.override = wfm_vosfor.load_overrides()
        self.owned = None
        self.cached_mtime = None
        self.inv_stale = False      # inventory served from disk cache only
        self._inv_job = False       # a background inventory read is running
        self._open: set[str] = set()      # expanded collection cards
        self._cards: dict[str, dict] = {}
        # which acquisition methods to weigh, and cached market prices
        m = dict(wfm_vosfor.DEFAULT_METHODS)
        m.update(app.settings.get("vosfor_methods") or {})
        self.methods = m
        pd = wfm_arcane_market.load_prices()
        self.prices = pd.get("prices", {})
        self._prices_at = pd.get("fetched_at")   # for the staleness hint
        self._fetcher = None
        self._bal_save = None       # pending debounced balance save

        # -- header --------------------------------------------------------
        bar = tk.Frame(self, bg=BG)
        bar.pack(fill="x", padx=SP_SCREEN, pady=(16, 4))
        tk.Label(bar, text="Vosfor Planner", bg=BG, fg=TEXT,
                 font=app.fonts["h1"]).pack(side="left")
        self.update_btn = tk.Button(
            bar, text="↻ Update inventory", command=self._update,
            **secondary_style(app.fonts["small"], wide=True))
        self.update_btn.pack(side="right")
        self.src_lbl = tk.Label(bar, text="", bg=BG, fg=MUTED,
                                font=app.fonts["small"])
        self.src_lbl.pack(side="right", padx=(0, 12))

        # -- vosfor balance input -----------------------------------------
        bal = tk.Frame(self, bg=BG)
        bal.pack(fill="x", padx=SP_SCREEN, pady=(SP_LG, 0))
        tk.Label(bal, text="Your Vosfor:", bg=BG, fg=MUTED,
                 font=app.fonts["body"]).pack(side="left")
        self.vosfor_var = tk.StringVar(
            value=str(app.settings.get("vosfor_balance") or ""))
        ent = tk.Entry(bal, textvariable=self.vosfor_var, width=8,
                       font=app.fonts["body"], justify="right",
                       **field_style(False))
        ent.pack(side="left", padx=(SP_MD, SP_SM), ipady=CTRL_IPADY)
        ent.bind("<KeyRelease>", lambda _e: self._balance_changed())
        tk.Label(bal, text="(enter your balance for a purchase plan; each "
                           "pack is 200 Vosfor + 50k credits)",
                 bg=BG, fg=WFM_MUTED, font=app.fonts["small"]).pack(
                     side="left", padx=(SP_SM, 0))

        # -- acquisition-method toggles -----------------------------------
        meth = tk.Frame(self, bg=BG)
        meth.pack(fill="x", padx=SP_SCREEN, pady=(SP_LG, 0))
        tk.Label(meth, text="Consider how else you'd get arcanes:", bg=BG,
                 fg=MUTED, font=app.fonts["small"]).pack(side="left",
                                                         padx=(0, SP_MD))
        self.method_vars = {}
        for key, label in (("farm", "Farming"), ("market", "Market price")):
            var = tk.BooleanVar(value=bool(self.methods.get(key)))
            self.method_vars[key] = var
            tk.Checkbutton(meth, text=label, variable=var,
                           command=lambda k=key: self._toggle_method(k),
                           bg=BG, fg=TEXT, selectcolor=CONSOLE_BG,
                           activebackground=BG, activeforeground=TEXT,
                           font=app.fonts["small"], highlightthickness=0
                           ).pack(side="left", padx=(0, SP_LG))
        self.price_btn = tk.Button(
            meth, text="↻ Refresh prices", command=self._fetch_prices,
            **secondary_style(app.fonts["small"]))
        self.price_btn.pack(side="left", padx=(0, SP_MD))
        self.price_status = tk.Label(meth, text="", bg=BG, fg=MUTED,
                                     font=app.fonts["small"])
        self.price_status.pack(side="left")
        self._price_hint()

        # -- recommendation / plan banner ---------------------------------
        self.reco = tk.Label(self, bg=TAB_BG, fg=TEXT, anchor="w",
                             justify="left", font=app.fonts["body"],
                             padx=14, pady=10, wraplength=980)
        self.reco.pack(fill="x", padx=SP_SCREEN, pady=(SP_LG, 0))

        # -- scrolling body ------------------------------------------------
        self.scroll = ScrollArea(self, bg=TAB_BG)
        self.scroll.pack(fill="both", expand=True,
                         padx=SP_SCREEN, pady=(SP_LG, SP_XL))
        self.canvas, self.body = self.scroll.canvas, self.scroll.body
        # A background inventory read or price sweep can land while another
        # app is on screen. Rebuilding then would destroy and recreate every
        # card on a hidden canvas, so those paths set _dirty instead and
        # on_show() flushes it.
        self._dirty = False
        self._keep_px = 0.0

        self._load_inventory()
        self._rebuild()

    # -- inventory --------------------------------------------------------

    def _load_inventory(self, force: bool = False) -> None:
        """Synchronous load - only for the first build, where there is no
        UI to keep responsive yet. Everything after goes through
        _refresh_inventory()."""
        self.owned, self.cached_mtime, self.inv_stale = \
            wfm_vosfor.refresh_inventory(force)

    def _refresh_inventory(self, force: bool, report: bool = False) -> None:
        """Re-read AlecaFrame off the UI thread. A stale read is a full
        AES decrypt + parse of the game's whole inventory - seconds of
        freeze if it ran inline (same pattern as the price sweep)."""
        if self._inv_job:
            return                          # a read is already in flight
        self._inv_job = True
        self.src_lbl.configure(text="refreshing inventory…", fg=MUTED)
        prev = self.cached_mtime

        def work() -> None:
            result = wfm_vosfor.refresh_inventory(force)

            def apply() -> None:
                self._inv_job = False
                if not self.winfo_exists():
                    return
                self.owned, self.cached_mtime, self.inv_stale = result
                if not self.winfo_ismapped():
                    # the decrypt takes seconds, so navigating away mid-read
                    # is easy - and rebuilding now would destroy and recreate
                    # every card on a hidden canvas
                    self._dirty = True
                    return
                self._rebuild()             # repaints src_lbl for the state
                if not report:
                    return
                if self.owned is None:
                    self.src_lbl.configure(text="no AlecaFrame data", fg=WARN)
                elif self.inv_stale:
                    # forced read failed - _rebuild already says "cached …
                    # AlecaFrame unavailable"; don't overwrite with calm
                    pass
                elif prev == self.cached_mtime:
                    self.src_lbl.configure(text="already up to date",
                                           fg=MUTED)
            self.after(0, apply)

        threading.Thread(target=work, daemon=True).start()

    def on_show(self) -> None:
        """Host lifecycle hook - runs every time the Vosfor app is opened.
        A stat() check decides whether AlecaFrame has new data; only then
        does the (decrypt + rebuild) work happen, so switching to this app
        stays instant when nothing changed."""
        # bind_all is app-wide and last-writer-wins; re-claim the wheel for
        # this persistent view each time it is shown (its <Destroy> unbind
        # never fires precisely because it is persistent).
        self.scroll.claim_wheel()
        self._price_hint()          # the cached-price age advances with time
        if self._dirty:             # a background read landed while hidden
            self._dirty = False
            self._rebuild()
        elif self._keep_px:
            self.scroll.restore_px(self._keep_px)
        if wfm_vosfor.inventory_stale(self.cached_mtime):
            self._refresh_inventory(force=False)

    def on_hide(self) -> None:
        """Host lifecycle hook - the Vosfor app just left the screen. Stop
        the scroll animation dead and hand the wheel back; a persistent
        view's <Destroy> never fires, so this is the only teardown it gets."""
        self._keep_px = self.scroll.top_px()
        self.scroll.stop()
        self.scroll.release_wheel()

    def _update(self) -> None:
        """The manual ↻ button: force a re-read of AlecaFrame's cache right
        now (on_show() only re-reads when the file's timestamp moved) and
        rebuild the checklists."""
        self._refresh_inventory(force=True, report=True)

    # -- rendering --------------------------------------------------------

    def _toggle_method(self, key: str) -> None:
        self.methods[key] = self.method_vars[key].get()
        self.app.settings["vosfor_methods"] = self.methods
        wfm_config.save_settings(self.app.settings)
        if key == "market" and self.methods["market"] and not self.prices:
            self._fetch_prices()      # need prices before market weighting
        self._rebuild()

    def _fetch_prices(self) -> None:
        if self._fetcher is not None:
            return
        names = wfm_vosfor_vm.all_arcane_names(wfm_vosfor.load_collections())
        self.price_status.configure(
            text=f"fetching prices 0/{len(names)}…", fg=WFM_TEAL)
        self._fetcher = wfm_arcane_market.PriceFetcher(
            self.app.market_any(), names)

        def prog(done, total):
            # fires on the fetcher's worker thread; the view can be gone
            self.after(0, lambda: self.winfo_exists() and
                       self.price_status.configure(
                           text=f"fetching prices {done}/{total}…",
                           fg=WFM_TEAL))

        def done(prices, err):
            def apply():
                self._fetcher = None
                if not self.winfo_exists():
                    return
                if prices is not None:
                    self.prices = prices
                    import time
                    self._prices_at = time.time()
                self.price_status.configure(
                    text=(err or f"prices updated ({len(self.prices)})"),
                    fg=WARN if err else MUTED)
                if self.winfo_ismapped():
                    self._rebuild()
                else:
                    self._dirty = True   # flushed by on_show()
            self.after(0, apply)

        self._fetcher.start(prog, done)

    def _price_hint(self) -> None:
        """Idle text for the price row: how old the cached market prices
        are. They never refresh on their own - .vosfor_prices.json is used
        as-is until ↻ prices runs a new sweep - so surface the age."""
        if self._fetcher is not None or not self.prices:
            return
        hint = wfm_vosfor_vm.price_age(self._prices_at)
        if hint is not None:
            self.price_status.configure(
                text=hint.text, fg=WARN if hint.level == "warn" else MUTED)

    def _rebuild(self) -> None:
        # Remember the scroll position - rebuilds fire on every card toggle
        # and override click, and snapping to the top loses your place.
        # Pixels, not the yview fraction: expanding a card changes the
        # content height, so replaying a fraction would shift the viewport.
        keep_px = self.scroll.top_px()
        self._keep_px = keep_px
        self.model = wfm_vosfor.evaluate(self.owned, self.override,
                                         self.methods, self.prices)
        for c in self.body.winfo_children():
            c.destroy()
        self._cards.clear()

        # source line + recommendation
        src = wfm_vosfor_vm.source_line(self.owned, self.cached_mtime,
                                        self.inv_stale)
        self.src_lbl.configure(text=src.text,
                               fg=WARN if src.level == "warn" else MUTED)
        self._render_reco()

        for name in self.model["ranking"]:
            self._render_card(name)

        # once geometry has settled; the job is tracked, so navigating away
        # mid-rebuild cancels it instead of clamping a hidden canvas
        self.scroll.restore_px(keep_px)

    def _balance(self) -> int:
        return wfm_vosfor_vm.parse_balance(self.vosfor_var.get())

    def _balance_changed(self) -> None:
        self.app.settings["vosfor_balance"] = self._balance()
        # Debounce the disk write - this fires per keystroke, and the
        # settings file doesn't need six rewrites while typing "150000".
        if self._bal_save is not None:
            self.after_cancel(self._bal_save)
        self._bal_save = self.after(600, self._save_balance)
        self._render_reco()

    def _save_balance(self) -> None:
        self._bal_save = None
        wfm_config.save_settings(self.app.settings)

    def _render_reco(self) -> None:
        """The recommendation block. Every line of it is derived in
        core.vosfor_vm; all that is left here is putting it in a
        label."""
        self.reco.configure(text="\n".join(
            wfm_vosfor_vm.reco_lines(self.model, self.methods,
                                     self._balance())))

    def _render_card(self, name: str) -> None:
        c = self.model["collections"][name]
        card = tk.Frame(self.body, bg=WFM_CARD)
        card.pack(fill="x", padx=SP_LG, pady=SP_SM)

        head = tk.Frame(card, bg=WFM_CARD, cursor="hand2")
        head.pack(fill="x", padx=SP_LG, pady=SP_MD)
        # the disclosure arrow is sized to the TITLE it belongs to (h2), not
        # to body text - same pairing the Settings tree uses for its ▸/▾
        arrow = "▾" if name in self._open else "▸"
        tk.Label(head, text=arrow, bg=WFM_CARD, fg=MUTED,
                 font=self.app.fonts["h2"], width=2).pack(side="left")
        title = f"{name} Arcane Collection"
        tk.Label(head, text=title, bg=WFM_CARD,
                 fg=OK if c["completed"] else TEXT,
                 font=self.app.fonts["h2"]).pack(side="left")
        if c["completed"]:
            tk.Label(head, text="  ✔ COMPLETE", bg=WFM_CARD, fg=OK,
                     font=self.app.fonts["small"]).pack(side="left")
        # right-side stats - Vosfor/pack numerals get the price role
        stat = (f"needs {c['needed']}/{c['total']}   ·   "
                f"{c['per_buy']:.2f}/pack   ·   {c['vosfor']} Vosfor")
        tk.Label(head, text=stat, bg=WFM_CARD, fg=WFM_MUTED,
                 font=self.app.fonts["price"]).pack(side="right")
        for w in (head, ) + tuple(head.winfo_children()):
            w.bind("<Button-1>", lambda _e, n=name: self._toggle(n))

        # progress bar
        pct = c["maxed"] / c["total"] if c["total"] else 0
        barbg = tk.Frame(card, bg=WFM_EDGE, height=4)
        barbg.pack(fill="x", padx=SP_LG, pady=(0, SP_MD))
        barbg.pack_propagate(False)
        # the treasury fills with gold; a completed collection turns jade
        fill = tk.Frame(barbg, bg=OK if c["completed"] else ACCENT)
        fill.place(relwidth=max(pct, 0.001), relheight=1)

        self._cards[name] = {"card": card}
        if name in self._open:
            self._render_arcanes(card, c)

    def _render_arcanes(self, card: tk.Frame, c: dict) -> None:
        """One row per arcane. Every string, band and flag on the row comes
        from core.vosfor_vm.arcane_row(); this method only places widgets."""
        f = self.app.fonts
        wrap = tk.Frame(card, bg=WFM_CARD)
        wrap.pack(fill="x", padx=SP_LG, pady=(0, SP_MD))
        last = None
        for arc in c["arcanes"]:
            r = wfm_vosfor_vm.arcane_row(arc)
            if r["rarity"] != last:
                last = r["rarity"]
                tk.Label(wrap, text=r["rarity"].upper(), bg=WFM_CARD,
                         fg=self.RARITY_COLOR.get(r["rarity"], MUTED),
                         font=f["small"]).pack(anchor="w", pady=(SP_SM, 1))
            row = tk.Frame(wrap, bg=WFM_CARD)
            row.pack(fill="x")
            mark, mcol = self.STATUS_MARK[r["status"]]
            tk.Label(row, text=mark, bg=WFM_CARD, fg=mcol, width=2,
                     font=f["body"], cursor="hand2").pack(side="left")
            # owned-copies / copies-to-max, monospace, 2 digits each side
            tk.Label(row, text=r["fraction"], bg=WFM_CARD,
                     fg=OK if r["maxed"] else WFM_MUTED,
                     font=f["mono"]).pack(side="left", padx=(0, SP_MD))
            nm = tk.Label(row, text=r["name"], bg=WFM_CARD,
                          fg=TEXT if r["maxed"] else MUTED, anchor="w",
                          font=f["body"], cursor="hand2")
            nm.pack(side="left")
            # its own widget, NOT part of the row's click target below -
            # clicking the name cycles the manual override, and a wiki look-up
            # must never flip whether you own an arcane
            wiki_link(row, self.app, r["name"], WFM_CARD).pack(
                side="left", padx=(SP_SM, 0))
            # right-aligned info: drop% - farmability - market price
            tk.Label(row, text=r["drop_text"], bg=WFM_CARD, fg=WFM_MUTED,
                     font=f["small"], width=7, anchor="e").pack(side="right")
            flab = tk.Label(row, text=r["farm_text"], bg=WFM_CARD,
                            fg=WARN if r["farm_level"] == "warn"
                            else OK if r["farm_text"].endswith("easy")
                            else WFM_MUTED,
                            font=f["small"], width=10, anchor="e")
            flab.pack(side="right")
            if r["farm_tooltip"]:
                _wfm_tooltip(flab, r["farm_tooltip"])
            # plat figures use the price role (DIN tabular digits align the
            # column) and PLAT silver; teal only flags "cheaper than Vosfor"
            plab = tk.Label(row, text=r["price_text"], bg=WFM_CARD,
                            fg=WFM_TEAL if r["price_cheap"] else PLAT,
                            font=f["price"], width=7, anchor="e")
            plab.pack(side="right", padx=(0, SP_MD))
            if r["price_tooltip"]:
                _wfm_tooltip(plab, r["price_tooltip"])
            for w in (row, nm):
                w.bind("<Button-1>",
                       lambda _e, a=arc: self._toggle_arcane(a))

    def _toggle(self, name: str) -> None:
        if name in self._open:
            self._open.discard(name)
        else:
            self._open.add(name)
        self._rebuild()

    def _toggle_arcane(self, arc: dict) -> None:
        """Manual override cycles missing → maxed → (clear back to auto)."""
        if arc.get("path") is None:
            return
        wfm_vosfor_vm.next_override(self.override, arc)
        wfm_vosfor.save_overrides(self.override)
        self._rebuild()


class HomeView(tk.Frame):
    """The app gallery, shown in the content container when Home is selected.
    Cards mirror the sidebar and open the same views; the account widget and
    title now live in the persistent header, not here. Every app gets a card
    EXCEPT Settings - it is chrome, not a tool."""

    LISTINGS_ACCENT = ACCENT       # My Listings IS the treasury - it gets gold

    def __init__(self, parent: tk.Widget, app: App) -> None:
        super().__init__(parent, bg=BG)
        self.app = app

        tk.Label(self, text="AVAILABLE TOOLS", bg=BG, fg=MUTED,
                 font=app.fonts["small"]).pack(anchor="w", padx=28,
                                               pady=(22, 8))
        # The caption stays outside the scroll area (it is a heading, like
        # Vosfor's and My Listings'); only the gallery scrolls. The right pad
        # is trimmed to 6 because the scrollbar now occupies that gutter.
        self.scroll = ScrollArea(self, bg=BG)
        self.scroll.pack(fill="both", expand=True, padx=(20, 6))
        grid = self.scroll.body
        for col in range(2):
            grid.columnconfigure(col, weight=1, uniform="cards")

        # Native apps lead, then the embedded web apps, then the registry
        # tools (API Status lives inside Settings > Data > Market, so it is
        # skipped here just as in the sidebar). Settings deliberately has NO
        # card - it is chrome, not a tool; open it from the sidebar.
        cards = [
            ("listings", "My Listings", LISTINGS_ICON, self.LISTINGS_ACCENT,
             True, True,
             "Your buy & sell orders, warframe.market style: Sold, Edit, "
             "quantity, visibility and delete on every card - plus "
             "one-click repricing that matches the best online price, "
             "never past your floor/cap."),
            ("market", "Market", "\uE7BF", WFM_TEAL, False, True,
             "Browse warframe.market live: the order book for any item, "
             "riven & lich contracts, and a watchlist so you can bookmark "
             "items instead of searching them again."),
            ("vosfor", "Vosfor", "\uE8EF",
             RARITY_BRONZE,                        # bronze: dissolved dust
             False, True,
             "The Arcane Dissolution planner: ranks every collection by "
             "expected value per 200-Vosfor pack, reads your arcanes from "
             "AlecaFrame (or tick them off by hand), and splits your "
             "Vosfor into the best purchase plan."),
        ]
        # Web-app cards come straight from the WEB_APPS table, same as tool
        # cards come from the registry - add a site there, get a card here.
        # WEB_ACCENT slate: "the webview is a lit pane" - neither gold (not
        # money actions) nor PLAT (reserved for platinum numerals).
        web_blurbs = {
            "web_weekly": "The live Warframe world state from browse.wf - "
                          "cycles, invasions and weekly resets, embedded "
                          "right in the Toolbox.",
            "web_wiki": "The official Warframe wiki, embedded - look up "
                        "anything without leaving the app.",
            "web_builds": "Overframe's builds and tier lists, embedded - "
                          "with the Toolbox ad blocker on duty.",
        }
        for wkey, wlabel, wicon, _url in WEB_APPS:
            cards.append((wkey, wlabel, wicon, WEB_ACCENT, False, True,
                          web_blurbs.get(wkey, "Embedded web app.")))
        for tool in TOOLS:
            if tool.id == "api_check":
                continue
            cards.append((tool.id, tool.name,
                          wfm_theme.glyph(tool.icon, fluent=True),
                          tool.accent,
                          tool.requires_session, tool.exists, tool.tagline))
        for i, spec in enumerate(cards):
            r, c = divmod(i, 2)
            self._card(grid, *spec).grid(row=r, column=c, sticky="nsew",
                                         padx=8, pady=8)

    def on_show(self) -> None:
        self.scroll.claim_wheel()
        # Home is rebuilt on every visit (it bakes the account link state
        # into every button), so the scroll position lives on the App.
        px = getattr(self.app, "_home_scroll", 0.0)
        if px:
            self.scroll.restore_px(px)

    def on_hide(self) -> None:
        self.app._home_scroll = self.scroll.top_px()
        self.scroll.stop()
        self.scroll.release_wheel()

    def _card(self, parent: tk.Widget, key: str, name: str, icon: str,
              accent: str, needs: bool, exists: bool, blurb: str) -> tk.Frame:
        # grid, not pack: the blurb row takes all the slack (rowconfigure
        # weight below), which pushes the action row onto the card floor.
        # Every card in a row is stretched to the tallest one by the
        # sticky="nsew" + uniform="cards" grid above, so the buttons land on
        # one baseline instead of ragged under each blurb.
        f = tk.Frame(parent, bg=PANEL, padx=16, pady=14)
        f.columnconfigure(0, weight=1)
        f.rowconfigure(2, weight=1)
        stripe = tk.Frame(f, bg=accent, height=3)
        stripe.grid(row=0, column=0, sticky="ew", pady=(0, 10))

        title = tk.Frame(f, bg=PANEL)
        title.grid(row=1, column=0, sticky="ew")
        tk.Label(title, text=icon, bg=PANEL, fg=accent,
                 font=self.app.fonts["icon"]).pack(side="left", padx=(0, 8))
        tk.Label(title, text=name, bg=PANEL, fg=TEXT,
                 font=self.app.fonts["h2"]).pack(side="left")
        if needs:
            tk.Label(title, text="  account", bg=PANEL, fg=MUTED,
                     font=self.app.fonts["small"]).pack(side="left")

        blurb_lbl = tk.Label(f, text=blurb, bg=PANEL, fg=MUTED,
                             justify="left", wraplength=360,
                             font=self.app.fonts["small"], anchor="nw")
        blurb_lbl.grid(row=2, column=0, sticky="new", pady=(4, 12))

        linked = self.app.session is not None
        # A web tab is a site we host, not an app we run - "Visit" says so.
        verb = "Visit" if key in WEB_KEYS else "Open"
        if not exists:
            label, state, cmd = "Script missing", "disabled", None
        elif needs and not linked:
            label, state, cmd = "Link account first", "normal", self.app.link_account
        else:
            label, state, cmd = (f"{verb}  →", "normal",
                                 lambda k=key: self.app.navigate(k))

        # navigation, not a money action: secondary surface. The card's
        # accent stays on the stripe and icon, which is what identifies it -
        # a filled accent here would put six saturated buttons (one of them
        # gold) on the first screen of the app.
        btn = tk.Button(f, text=label, command=cmd, state=state,
                        **secondary_style(self.app.fonts["small"], wide=True))
        btn.grid(row=3, column=0, sticky="e")
        if cmd is not None:
            # the button is in the far corner now, so the text is the
            # natural click target - make the whole card live
            for w in (f, stripe, title, blurb_lbl) + tuple(
                    title.winfo_children()):
                w.bind("<Button-1>", lambda _e, c=cmd: c())
        return f


#: severity role -> this front end's colour. core.market_vm names roles and
#: never hex, so the Qt shell can resolve the same words differently.
ROLE_COLOR = {"ingame": WFM_TEAL, "ok": OK, "muted": MUTED, "err": ERR,
              "accent": ACCENT, "warn": WARN}


def _status_dot(status: str) -> tuple[str, str]:
    """('●', colour) for a warframe.market user status."""
    glyph, role = wfm_market_vm.status_dot(status)
    return glyph, ROLE_COLOR[role]


# Universal control metrics (style guide): every search field, spinbox and
# dropdown shares the body font and this vertical padding.
CTRL_IPADY = 5


def field_style(inside: bool = True) -> dict:
    """Common look for Entry/Spinbox/Listbox inputs: lightened background
    (lighter still inside the dimmed tab containers) and a 1px dim-gold
    inlay border that lights up gold on keyboard focus; the caret is
    bright gold and selected text sits on a gold wash. Style guide: use
    this for every input field."""
    return {
        "bg": FIELD_BG_IN if inside else FIELD_BG_OUT,
        "fg": TEXT, "insertbackground": GOLD_HI, "relief": "flat",
        "highlightthickness": 1, "highlightbackground": FIELD_EDGE,
        "highlightcolor": ACCENT,
        "selectbackground": GOLD_DIM, "selectforeground": INK,
    }


def secondary_style(font, wide: bool = False) -> dict:
    """The style guide's secondary button: PANEL_HI surface, ivory text,
    one hover tone, one padding. Every non-money button uses this - gold
    fills are reserved for money actions and the account link.

    Style guide: use this for every non-money button; pass the small or
    body font role, and wide=True for a roomier primary-of-its-row button."""
    return {
        "bg": PANEL_HI, "fg": TEXT, "relief": "flat", "bd": 0,
        "padx": 14 if wide else 10, "pady": 5,
        "cursor": "hand2", "font": font,
        "activebackground": PANEL, "activeforeground": TEXT,
    }


def wiki_link(parent: tk.Widget, app: "App", name, bg: str) -> tk.Label:
    """A lone Library glyph that opens `name` on the Warframe wiki - in the
    app's OWN Wiki tab, never an external browser.

    `name` may be a string or a zero-argument callable, for rows whose label
    changes under the widget (the Market tab's current item).

    Style guide: a Segoe Fluent codepoint on the icon role (never a colour
    emoji), in WEB_ACCENT slate - the embedded-web token, so it reads as
    neither a money action (gold) nor a platinum numeral (PLAT)."""
    g = tk.Label(parent, text=WIKI_ICON, bg=bg, fg=WEB_ACCENT,
                 font=app.fonts["icon"], cursor="hand2")
    g.bind("<Button-1>",
           lambda _e: app.open_wiki(name() if callable(name) else name))
    g.bind("<Enter>", lambda _e: g.configure(fg=TEXT))
    g.bind("<Leave>", lambda _e: g.configure(fg=WEB_ACCENT))
    _wfm_tooltip(g, "Open on the Warframe wiki")
    return g


class ScrollArea(tk.Frame):
    """The app's one scrolling container: a Canvas, a themed ttk scrollbar,
    and a `body` frame that always matches the canvas width. Put content in
    `.body`; the owning view forwards its on_show()/on_hide() here.

    It also owns the pixel-glide wheel animation and every after() job that
    animation starts, which is the whole point of it existing. Three rules
    each hand-rolled copy of this got wrong:

      * The glide only ticks while the area is MAPPED, and its after() id is
        kept so it can be cancelled outright. winfo_exists() is useless as a
        stop condition for a persistent view - navigate() pack_forget()s
        those, never destroys them, so a discarded after(12) id kept
        scrolling a hidden canvas for ~300ms while the incoming view mapped
        a thousand widgets. That is the tab-switch artifact.
      * The scrollregion is only re-assigned when it actually CHANGED.
        body<Configure> -> set scrollregion and canvas<Configure> -> resize
        body feed each other, and re-writing scrollregion mid-glide makes
        the canvas clamp and snap between animation frames.
      * bind_all("<MouseWheel>") is claimed in claim_wheel() from the view's
        on_show() and dropped in release_wheel() from on_hide() while still
        mapped - never unbound from a hidden widget (last writer wins, so a
        hidden view revoking the binding steals it from the visible one).

    Scrolling moves `body` - a real Win32 window with the whole content tree
    parented under it. Measured inside a real mainloop that costs 1.7ms
    median / 4.0ms p90 per frame, so there is ample headroom and these knobs
    are tuned for SMOOTHNESS, not for saving work. (An earlier pass made them
    coarse on the strength of a 132ms figure that turned out to be a
    benchmark artifact - update_idletasks() in a tight loop never lets a
    repaint coalesce. Do not re-coarsen them without a mainloop measurement.)

    What Tk cannot do here is vsync or double-buffer the move, which is why
    fast scrolling still tears; that is the reason for the Qt migration, not
    a tuning problem."""

    GLIDE_MS = 12        # ~83Hz; a frame costs 1.7ms, so this is affordable
    GLIDE_DIVISOR = 4    # fraction of the remaining distance per frame
    GLIDE_MIN_PX = 1     # smooth tail; snapped up to `unit` when DPI-scaled
    NOTCH = 0.7          # wheel delta -> pixels

    def __init__(self, parent: tk.Widget, bg: str) -> None:
        super().__init__(parent, bg=bg)
        app = self.winfo_toplevel()
        # whole device pixels only - see display_scale()/scroll_unit()
        self.unit = max(1, int(getattr(app, "scroll_unit", 1)))
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0,
                                yscrollincrement=self.unit)
        self.sb = ttk.Scrollbar(self, orient="vertical",
                                command=self.canvas.yview,
                                style="Toolbox.Vertical.TScrollbar")
        self.canvas.configure(yscrollcommand=self.sb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.sb.pack(side="right", fill="y")
        self.body = tk.Frame(self.canvas, bg=bg)
        self._win = self.canvas.create_window((0, 0), window=self.body,
                                              anchor="nw")
        self._region: tuple | None = None
        self._width: int | None = None
        self._glide_px = 0
        self._glide_job: str | None = None
        self._region_job: str | None = None
        self.body.bind("<Configure>", lambda _e: self._sync_region())
        self.canvas.bind("<Configure>", self._on_canvas_configure)

    # -- geometry ---------------------------------------------------------

    def _sync_region(self) -> None:
        box = self.canvas.bbox("all")
        if box and box != self._region:
            self._region = box
            self.canvas.configure(scrollregion=box)

    def _on_canvas_configure(self, event) -> None:
        if event.width != self._width:
            self._width = event.width
            self.canvas.itemconfigure(self._win, width=event.width)
        self._sync_region()

    def top_px(self) -> float:
        """Current scroll offset in pixels (0.0 when unavailable)."""
        try:
            return float(self.canvas.canvasy(0))
        except tk.TclError:
            return 0.0

    def restore_px(self, px: float) -> None:
        """Scroll back to a pixel offset once the new content has been laid
        out. Pixel-based on purpose: a fraction would land somewhere else
        entirely after a rebuild changed the content height."""
        if self._region_job is not None:
            try:
                self.after_cancel(self._region_job)
            except tk.TclError:
                pass
            self._region_job = None

        def apply() -> None:
            self._region_job = None
            if not self.canvas.winfo_exists() or not self.winfo_ismapped():
                return
            self._sync_region()
            box = self._region
            height = (box[3] - box[1]) if box else 0
            if height > 0:
                self.canvas.yview_moveto(max(0.0, px) / height)
        self._region_job = self.after_idle(apply)

    # -- the app-wide wheel -----------------------------------------------

    def claim_wheel(self) -> None:
        """Take the app-wide wheel binding. Called from the view's on_show(),
        after navigate() has flushed the map - bind_all is last-writer-wins,
        and any view may have taken it since we were last shown."""
        # Re-read the scale unit here, not just at construction: Home is
        # built before _apply_launch_display has moved the window, so it can
        # be created against the primary monitor's scale and then end up on
        # a differently-scaled one.
        unit = max(1, int(getattr(self.winfo_toplevel(), "scroll_unit", 1)))
        if unit != self.unit:
            self.unit = unit
            self.canvas.configure(yscrollincrement=unit)
        try:
            self.canvas.bind_all("<MouseWheel>", self._on_wheel)
        except tk.TclError:
            pass

    def release_wheel(self) -> None:
        try:
            self.canvas.unbind_all("<MouseWheel>")
        except tk.TclError:
            pass

    def _on_wheel(self, event) -> None:
        if not self.canvas.winfo_exists() or not self.winfo_ismapped():
            return
        # a tip is pinned to a screen coordinate and never follows its row
        _tooltip_hide_all()
        self._glide_px -= int(event.delta * self.NOTCH)
        if self._glide_job is None:
            self._glide()

    def _glide(self) -> None:
        self._glide_job = None
        if (not self.canvas.winfo_exists() or not self.winfo_ismapped()
                or abs(self._glide_px) < self.unit):
            self._glide_px = 0
            return
        step = max(self.GLIDE_MIN_PX,
                   abs(self._glide_px) // self.GLIDE_DIVISOR)
        step -= step % self.unit                  # whole device pixels only
        step = max(step, self.unit)
        step = min(step, abs(self._glide_px))
        signed = step if self._glide_px > 0 else -step
        self.canvas.yview_scroll(signed // self.unit, "units")
        self._glide_px -= signed
        self._glide_job = self.after(self.GLIDE_MS, self._glide)

    # -- lifecycle --------------------------------------------------------

    def stop(self) -> None:
        """Cancel every pending job. The on_hide() entry point: after this
        the area touches nothing until it is shown again."""
        for name in ("_glide_job", "_region_job"):
            job = getattr(self, name)
            if job is not None:
                try:
                    self.after_cancel(job)
                except tk.TclError:
                    pass
                setattr(self, name, None)
        self._glide_px = 0


def arrow_dropdown(parent: tk.Widget, var: tk.StringVar,
                   values: tuple[str, ...], command, font) -> tk.Menubutton:
    """A themed dropdown that actually looks like one: current value + a ▾
    arrow, opening a menu of choices. (Tk's OptionMenu with indicatoron=False
    gives no visual hint that it drops down.)"""
    mb = tk.Menubutton(parent, text=f"{var.get()}  ▾", bg=FIELD_BG_IN, fg=TEXT,
                       relief="flat", bd=0, padx=12, pady=CTRL_IPADY,
                       cursor="hand2", highlightthickness=1,
                       highlightbackground=FIELD_EDGE,
                       highlightcolor=ACCENT,
                       font=font, activebackground=PANEL_HI,
                       activeforeground=TEXT, anchor="w")
    menu = tk.Menu(mb, tearoff=0, bg=PANEL, fg=TEXT, relief="flat", bd=0,
                   activebackground=PANEL_HI, activeforeground=TEXT,
                   font=font)

    def choose(v: str) -> None:
        var.set(v)
        mb.configure(text=f"{v}  ▾")
        if command:
            command(v)

    for v in values:
        menu.add_command(label=v, command=lambda v=v: choose(v))
    mb.configure(menu=menu)
    return mb


def build_tabbar(parent: tk.Widget, names, accents: dict, select,
                 btns: dict, bars: dict, fonts) -> tk.Frame:
    """A slim tab bar that FILLS the container width: each tab gets an equal
    share (width / len(names)) and carries a colour-coded accent bar under
    its text. Style guide: tabs are h2, slim (SP_SM vertical padding)."""
    tabbar = tk.Frame(parent, bg=BG)
    for i, name in enumerate(names):
        tabbar.columnconfigure(i, weight=1, uniform="tabs")
        cell = tk.Frame(tabbar, bg=PANEL)
        cell.grid(row=0, column=i, sticky="ew",
                  padx=(0, 2) if i < len(names) - 1 else 0)
        b = tk.Button(cell, text=name, command=lambda n=name: select(n),
                      relief="flat", bd=0, pady=SP_SM, cursor="hand2",
                      font=fonts["h2"], bg=PANEL, fg=MUTED,
                      activebackground=PANEL_HI, activeforeground=TEXT)
        b.pack(fill="x")
        bar = tk.Frame(cell, bg=HAIRLINE, height=2)
        bar.pack(fill="x")
        btns[name] = b
        bars[name] = bar
    return tabbar


def paint_tabbar(btns: dict, bars: dict, accents: dict, active: str) -> None:
    for n, b in btns.items():
        on = n == active
        b.configure(bg=TAB_BG if on else PANEL, fg=TEXT if on else MUTED)
        bars[n].configure(bg=accents.get(n, ACCENT) if on else HAIRLINE)


class SuggestBox:
    """Autocomplete dropdown for an Entry, shared by every search bar.

    Behaviour (per user spec): suggestions appear while typing; ArrowDown
    moves into the list and Up/Down browse it WITHOUT closing it or running
    a search - only Enter or a click picks. Escape closes. Picking calls
    on_pick(label, payload) - which should also autocomplete the entry."""

    _NAV_KEYS = {"Up", "Down", "Left", "Right", "Return", "KP_Enter",
                 "Escape", "Tab", "Shift_L", "Shift_R", "Control_L",
                 "Control_R", "Alt_L", "Alt_R", "Home", "End"}

    def __init__(self, owner: tk.Widget, entry: tk.Entry, supplier,
                 on_pick, font) -> None:
        self.entry = entry
        self.supplier = supplier          # (query) -> [(label, payload), ...]
        self.on_pick = on_pick
        self.items: list[tuple[str, object]] = []
        style = field_style(True)
        style.pop("insertbackground")        # Listbox has no cursor
        style.pop("selectbackground")        # picks are gold, not a wash
        style.pop("selectforeground")
        self.lb = tk.Listbox(owner, height=8, font=font,
                             selectbackground=ACCENT,
                             selectforeground=INK,
                             activestyle="none", **style)
        entry.bind("<KeyRelease>", self._typed, add="+")   # keep host binds
        entry.bind("<Down>", lambda _e: self._focus_list())
        entry.bind("<Return>", lambda _e: self.pick(0))
        entry.bind("<Escape>", lambda _e: self.hide())
        self.lb.bind("<Return>", lambda _e: self._pick_current())
        self.lb.bind("<KP_Enter>", lambda _e: self._pick_current())
        self.lb.bind("<ButtonRelease-1>", lambda _e: self._pick_current())
        self.lb.bind("<Escape>", lambda _e: (self.hide(),
                                             entry.focus_set()))

    # -- events --------------------------------------------------------------

    def _typed(self, event) -> None:
        if event.keysym in self._NAV_KEYS:
            return                       # navigation never re-queries/closes
        self.refresh()

    def refresh(self) -> None:
        self.items = list(self.supplier(self.entry.get().strip()))
        self.lb.delete(0, "end")
        if not self.items:
            self.hide()
            return
        for label, _payload in self.items:
            self.lb.insert("end", f"  {label}")
        self.lb.configure(height=min(8, len(self.items)))
        self.lb.place(in_=self.entry, relx=0, rely=1.0, y=3, anchor="nw",
                      width=max(300, self.entry.winfo_width()))
        self.lb.lift()

    def hide(self) -> None:
        self.lb.place_forget()

    def _focus_list(self) -> None:
        if self.lb.winfo_ismapped() and self.lb.size():
            self.lb.focus_set()
            self.lb.selection_clear(0, "end")
            self.lb.selection_set(0)
            self.lb.activate(0)

    def _pick_current(self) -> None:
        sel = self.lb.curselection()
        if sel:
            self.pick(sel[0])

    def pick(self, index: int) -> None:
        if not self.items or index >= len(self.items):
            return
        label, payload = self.items[index]
        self.hide()
        self.entry.focus_set()
        self.on_pick(label, payload)


class MarketView(tk.Frame):
    """The Market app: a read-only browser of warframe.market itself.

    Three tabs: Market (search any item, see its live order book the way the
    site shows it), Contracts (the site's auction house - riven and lich
    contracts), and Watchlist (bookmarked items so favourites don't have to
    be searched again - the ☆ button on the Market tab adds them)."""

    TAB_NAMES = ("Market", "Contracts", "Watchlist")
    # an active-tab underline is a sanctioned gold role, so the Watchlist
    # tab uses ACCENT itself - not a one-off hex a shade away from it
    TAB_ACCENTS = {"Market": WFM_TEAL, "Contracts": WFM_PINK,
                   "Watchlist": ACCENT}

    def __init__(self, parent: tk.Widget, app: App) -> None:
        super().__init__(parent, bg=BG)
        self.app = app
        self.client = app.market_any()

        bar = tk.Frame(self, bg=BG)
        bar.pack(fill="x", padx=SP_SCREEN, pady=(SP_XL, SP_SM))
        tk.Label(bar, text="warframe.market Browser", bg=BG, fg=TEXT,
                 font=app.fonts["h1"]).pack(side="left")
        tk.Label(bar, text="read-only", bg=BG, fg=MUTED,
                 font=app.fonts["small"]).pack(side="left", padx=(SP_LG, 0))

        self.tab_btns, self.tab_bars = {}, {}
        tabbar = build_tabbar(self, self.TAB_NAMES, self.TAB_ACCENTS,
                              self.select_tab, self.tab_btns, self.tab_bars,
                              app.fonts)
        tabbar.pack(fill="x", padx=SP_SCREEN, pady=(SP_LG, 0))

        # dimmed backdrop so the tabs read as a tabbed window
        container = tk.Frame(self, bg=TAB_BG)
        container.pack(fill="both", expand=True, padx=SP_SCREEN, pady=(0, SP_XL))
        # Set BEFORE the tabs are built: WatchlistTab.__init__ calls reload(),
        # which asks tab_live(). This view is persistent, so a fetch started
        # before you tab-hopped can land while it is off screen; tracked
        # explicitly rather than via winfo_ismapped(), which is only accurate
        # after a layout flush - and flushing on navigation was a 3.6s cost.
        self.current: str | None = None
        self._shown = False
        self.tabs: dict[str, tk.Frame] = {
            "Market": MarketTab(container, self),
            "Contracts": ContractsTab(container, self),
            "Watchlist": WatchlistTab(container, self),
        }
        self.select_tab("Market")

    def tab_live(self, tab: tk.Frame) -> bool:
        """True when rendering into `tab` would actually be seen."""
        return self._shown and self.current is not None \
            and self.tabs.get(self.current) is tab

    def select_tab(self, tab_name: str) -> None:
        if self.current == tab_name:
            return
        for frame in self.tabs.values():
            frame.pack_forget()
        paint_tabbar(self.tab_btns, self.tab_bars, self.TAB_ACCENTS, tab_name)
        tab = self.tabs[tab_name]
        tab.pack(fill="both", expand=True)
        self.current = tab_name
        if hasattr(tab, "on_show"):
            tab.on_show()
        self._flush_dirty()

    def _flush_dirty(self) -> None:
        """Re-render any tab that deferred while it was off screen."""
        for tab in self.tabs.values():
            if getattr(tab, "_dirty", False) and self.tab_live(tab):
                tab._dirty = False
                tab._redraw()

    # host lifecycle ---------------------------------------------------------

    def on_show(self) -> None:
        """This view is persistent, so navigate() re-packs it rather than
        rebuilding it - forward to the active tab, whose on_show() is
        otherwise only reached through select_tab()."""
        self._shown = True
        tab = self.tabs.get(self.current) if self.current else None
        fn = getattr(tab, "on_show", None)
        if fn:
            fn()
        self._flush_dirty()

    def on_hide(self) -> None:
        """A SuggestBox is a place()d, lift()ed Listbox with no teardown of
        its own; left open it would float over the next app."""
        self._shown = False
        for tab in self.tabs.values():
            sg = getattr(tab, "suggest", None)
            if sg:
                sg.hide()

    # cross-tab hooks -------------------------------------------------------

    def open_in_market(self, slug: str, name: str) -> None:
        """Watchlist 'Open' -> jump to the Market tab on that item."""
        self.select_tab("Market")
        self.tabs["Market"].open_item(slug, name)

    def watchlist_changed(self) -> None:
        self.tabs["Watchlist"].reload()


class MarketTab(tk.Frame):
    """Search any item, see its live order book like on the site: sellers
    ascending, buyers descending, status dots, reputation - and a ☆ button
    that bookmarks the item onto the Watchlist tab."""

    ROWS = 12          # rows shown per side, like the site's first page

    def __init__(self, parent: tk.Widget, view: MarketView) -> None:
        super().__init__(parent, bg=TAB_BG)
        self.view = view
        self.app = view.app
        self.client = view.client
        self.slug: str | None = None
        self.name: str | None = None
        self._book: dict[str, list[dict]] | None = None
        self._index: list[tuple[str, str, str]] = []
        self._dirty = False     # a fetch landed while this tab was hidden
        f = self.app.fonts

        ctr = tk.Frame(self, bg=TAB_BG)
        ctr.pack(fill="x", padx=SP_SCREEN, pady=(12, 0))
        tk.Label(ctr, text="Search", bg=TAB_BG, fg=MUTED,
                 font=f["small"]).pack(side="left")
        self.search_var = tk.StringVar()
        se = tk.Entry(ctr, textvariable=self.search_var, width=34,
                      font=f["body"], **field_style(True))
        se.pack(side="left", padx=(6, 14), ipady=CTRL_IPADY,
                fill="x", expand=True)
        self._search_entry = se
        self.suggest = SuggestBox(self, se, self._supply, self._picked,
                                  f["body"])

        self.watch_btn = tk.Button(ctr, text="☆ Watch",
                                   command=self._toggle_watch,
                                   state="disabled",
                                   **secondary_style(f["small"]))
        self.watch_btn.configure(fg=MUTED)      # dim until an item is loaded
        self.watch_btn.pack(side="right")
        tk.Button(ctr, text="↻ Refresh", command=self._refresh,
                  **secondary_style(f["small"])).pack(side="right",
                                                      padx=(0, SP_MD))
        self.online_var = tk.BooleanVar(value=True)
        self.ingame_var = tk.BooleanVar(value=False)
        for text, var in (("In-game only", self.ingame_var),
                          ("Online only", self.online_var)):
            tk.Checkbutton(ctr, text=text, variable=var,
                           command=self._rerender, bg=TAB_BG, fg=MUTED,
                           selectcolor=CONSOLE_BG, activebackground=TAB_BG,
                           activeforeground=TEXT, font=f["small"],
                           highlightthickness=0).pack(side="right",
                                                      padx=(0, 12))

        head = tk.Frame(self, bg=TAB_BG)
        head.pack(fill="x", padx=SP_SCREEN, pady=(12, 2))
        self.item_lbl = tk.Label(head, text="Search for an item to see its "
                                 "order book.", bg=TAB_BG, fg=MUTED, anchor="w",
                                 font=f["h2"])
        self.item_lbl.pack(side="left")
        # one glyph for the loaded item, not one per order row - the rows
        # below are users, not items. Hidden until an item is loaded.
        self.wiki_btn = wiki_link(head, self.app, lambda: self.name, TAB_BG)
        self.status = tk.Label(self, text="", bg=TAB_BG, fg=MUTED, anchor="w",
                               font=f["small"])
        self.status.pack(fill="x", padx=SP_SCREEN)

        book = tk.Frame(self, bg=TAB_BG)
        book.pack(fill="both", expand=True, padx=SP_SCREEN, pady=(8, 16))
        book.columnconfigure(0, weight=1, uniform="bk")
        book.columnconfigure(1, weight=1, uniform="bk")
        self.cols: dict[str, tk.Frame] = {}
        for i, (side, label) in enumerate((("sell", "WTS — sellers"),
                                           ("buy", "WTB — buyers"))):
            col = tk.Frame(book, bg=WFM_CARD, padx=14, pady=10)
            col.grid(row=0, column=i, sticky="nsew",
                     padx=(0, 8) if i == 0 else (8, 0))
            hdr = tk.Label(col, text=label, bg=WFM_CARD,
                           fg=WFM_BADGE_FG if side == "sell" else WFM_BUY_FG,
                           anchor="w", font=f["h2"])
            hdr.pack(fill="x", pady=(0, 6))
            rows = tk.Frame(col, bg=WFM_CARD)
            rows.pack(fill="both", expand=True)
            self.cols[side] = rows
            col._hdr = hdr

        self._load_index()

    def on_show(self) -> None:
        pass

    # -- search ------------------------------------------------------------

    def _load_index(self) -> None:
        def work() -> None:
            try:
                idx = self.client.item_names()
            except wfm_market.MarketError:
                return

            def apply() -> None:
                if not self.winfo_exists():
                    return
                self._index = idx
                # if the user was already typing, surface suggestions now
                if self.search_var.get().strip():
                    self.suggest.refresh()
            self.after(0, apply)
        threading.Thread(target=work, daemon=True).start()

    def _supply(self, q: str) -> list[tuple[str, str]]:
        return wfm_market_vm.suggest_pairs(self._index, q)

    def _picked(self, name: str, slug: str) -> None:
        self.search_var.set(name)        # autocomplete the search form
        self.open_item(slug, name)

    # -- the order book ------------------------------------------------------

    def open_item(self, slug: str, name: str) -> None:
        self.slug, self.name = slug, name
        self.item_lbl.configure(text=name, fg=WFM_TEAL)
        self.wiki_btn.pack(side="left", padx=(SP_MD, 0))
        self._paint_watch()
        self.watch_btn.configure(state="normal")
        self._refresh()

    def _refresh(self) -> None:
        if not self.slug:
            return
        slug = self.slug
        self.status.configure(text="loading order book…", fg=MUTED)

        def work() -> None:
            try:
                book = self.client.order_book(slug)
            except wfm_market.MarketError as exc:
                msg = str(exc)
                self.after(0, lambda: self.winfo_exists() and
                           self.status.configure(text=msg, fg=ERR))
                return
            self.after(0, lambda: self._render(slug, book))

        threading.Thread(target=work, daemon=True).start()

    def _rerender(self) -> None:
        """Filter toggles re-render the cached book - no refetch needed."""
        if self.slug and self._book is not None:
            self._render(self.slug, self._book)

    def _copy_message(self, side: str, r: dict) -> None:
        """✉: copy a ready-to-whisper trade message. A WTS row means I'm
        buying from them; a WTB row means I'm selling to them. Templates are
        editable in Settings > Market > Messaging."""
        msg = wfm_market_vm.whisper_message(self.app.settings, side, r,
                                            self.name)
        self.clipboard_clear()
        self.clipboard_append(msg)
        self.status.configure(text=f"whisper for {r['user']} copied ✔",
                              fg=OK)

    def _redraw(self) -> None:
        """Re-render from the cached book (used by the deferred flush)."""
        self._rerender()

    def _render(self, slug: str, book: dict[str, list[dict]]) -> None:
        if not self.winfo_exists() or slug != self.slug:
            return
        self._book = book
        # This view is persistent now, so a fetch can land after you have
        # tab-hopped away. Rebuilding 24 order rows on a hidden tab is pure
        # cost and races the visible view's painting.
        if not self.view.tab_live(self):
            self._dirty = True
            return
        me = (self.app.session.username.lower()
              if self.app.session else "")
        # In-game only narrows Online only; both off = everyone.
        allowed, scope = wfm_market_vm.scope_filter(self.ingame_var.get(),
                                                    self.online_var.get())
        f = self.app.fonts
        counts = {}
        for side, rows_frame in self.cols.items():
            for child in rows_frame.winfo_children():
                child.destroy()
            rows = wfm_market_vm.filter_orders(book[side], allowed)
            counts[side] = len(rows)
            for i, r in enumerate(rows[:self.ROWS]):
                # subtle zebra striping for readability
                rbg = WFM_CARD if i % 2 == 0 else ROW_ALT
                line = tk.Frame(rows_frame, bg=rbg)
                line.pack(fill="x", pady=1)
                dot, color = _status_dot(r["status"])
                tk.Label(line, text=dot, bg=rbg, fg=color,
                         font=f["small"]).pack(side="left")
                own = r["user"].lower() == me
                tk.Label(line, text=f" {r['user']}", bg=rbg,
                         fg=WFM_TEAL if own else TEXT, anchor="w",
                         font=f["body"]).pack(side="left")
                tk.Label(line, text=f" +{r['reputation']}", bg=rbg,
                         fg=WFM_MUTED, font=f["small"]).pack(side="left")
                tk.Button(line, text="\uE715",       # Fluent: Mail
                          command=lambda s=side, row=r:
                          self._copy_message(s, row),
                          bg=rbg, fg=WFM_MUTED, relief="flat", bd=0,
                          padx=12, cursor="hand2", font=f["msgbtn"],
                          activebackground=WFM_EDGE,
                          activeforeground=WFM_TEAL).pack(side="right",
                                                          padx=(10, 0))
                tk.Label(line, image=plat_icon(rbg), bg=rbg).pack(
                    side="right")
                # platinum numerals: cool silver DIN digits, right-aligned so
                # the money column reads as one unbroken rail down the book
                tk.Label(line, text=str(r["platinum"]), bg=rbg,
                         fg=PLAT, font=f["price"], width=4,
                         anchor="e").pack(side="right", padx=(0, 4))
                tk.Label(line, text=f"{r['quantity']} ❒", bg=rbg,
                         fg=WFM_MUTED, font=f["small"]).pack(side="right",
                                                             padx=(0, 12))
            if not rows:
                tk.Label(rows_frame, text="nobody here", bg=WFM_CARD,
                         fg=WFM_MUTED, font=f["small"]).pack(anchor="w")
        self.status.configure(
            text=wfm_market_vm.book_summary(counts["sell"], counts["buy"],
                                            scope, self.ROWS), fg=MUTED)

    # -- watchlist hook -------------------------------------------------------

    def _paint_watch(self) -> None:
        watched = self.slug in wfm_market.load_watchlist()
        # a watched item is gilded, not "warned about"
        text, role = wfm_market_vm.watch_label(watched)
        self.watch_btn.configure(text=text, fg=ROLE_COLOR[role])

    def _toggle_watch(self) -> None:
        if not self.slug:
            return
        wfm_market.save_watchlist(
            wfm_market_vm.toggle_watch(wfm_market.load_watchlist(), self.slug))
        self._paint_watch()
        self.view.watchlist_changed()


class ContractsTab(tk.Frame):
    """The site's Contracts page (its auction house), read-only: riven and
    lich contracts for a chosen weapon, cheapest first or dearest first."""

    ROWS = 15

    def __init__(self, parent: tk.Widget, view: MarketView) -> None:
        super().__init__(parent, bg=TAB_BG)
        self.view = view
        self.app = view.app
        self.client = view.client
        self._weapons: dict[str, list[tuple[str, str]]] = {}
        self._dirty = False              # a fetch landed while hidden
        self._last: tuple[str, list[dict]] | None = None
        self._asc = True
        f = self.app.fonts

        ctr = tk.Frame(self, bg=TAB_BG)
        ctr.pack(fill="x", padx=SP_SCREEN, pady=(12, 0))
        tk.Label(ctr, text="Type", bg=TAB_BG, fg=MUTED,
                 font=f["small"]).pack(side="left")
        self.kind_var = tk.StringVar(value="Riven")
        arrow_dropdown(ctr, self.kind_var, ("Riven", "Lich"),
                       lambda _v: self._kind_changed(),
                       f["body"]).pack(side="left", padx=(6, 14))

        tk.Label(ctr, text="Weapon", bg=TAB_BG, fg=MUTED,
                 font=f["small"]).pack(side="left")
        self.weapon_var = tk.StringVar()
        we = tk.Entry(ctr, textvariable=self.weapon_var, width=26,
                      font=f["body"], **field_style(True))
        we.pack(side="left", padx=(6, 14), ipady=CTRL_IPADY)
        self.suggest = SuggestBox(self, we, self._supply, self._picked,
                                  f["body"])

        self.order_btn = tk.Button(ctr, text="price ▲",
                                   command=self._flip_order, bg=PANEL,
                                   fg=TEXT, relief="flat", bd=0, padx=10,
                                   pady=3, cursor="hand2", font=f["small"],
                                   activebackground=PANEL_HI)
        self.order_btn.pack(side="left")

        self.status = tk.Label(self, text="Pick a weapon to browse its "
                               "contracts.", bg=TAB_BG, fg=MUTED, anchor="w",
                               font=f["small"])
        self.status.pack(fill="x", padx=SP_SCREEN, pady=(10, 2))
        self.body = tk.Frame(self, bg=TAB_BG)
        self.body.pack(fill="both", expand=True, padx=SP_SCREEN, pady=(4, 16))

        self.slug: str | None = None
        self.wname: str | None = None

    def on_show(self) -> None:
        self._load_weapons()

    # -- weapon picker --------------------------------------------------------

    def _kind(self) -> str:
        return self.kind_var.get().lower()

    def _kind_changed(self) -> None:
        self.slug = None
        self.weapon_var.set("")
        self.suggest.hide()
        self._load_weapons()

    def _load_weapons(self) -> None:
        kind = self._kind()
        if kind in self._weapons:
            return

        def work() -> None:
            try:
                lst = (self.client.riven_weapons() if kind == "riven"
                       else self.client.lich_weapons())
            except wfm_market.MarketError as exc:
                # surface it - a silent empty weapon picker looks broken
                msg = str(exc)
                self.after(0, lambda: self.winfo_exists() and
                           self.status.configure(
                               text=f"couldn't load {kind} weapons — {msg}",
                               fg=ERR))
                return
            self.after(0, lambda: self._weapons.__setitem__(kind, lst))
        threading.Thread(target=work, daemon=True).start()

    def _supply(self, q: str) -> list[tuple[str, str]]:
        q = q.lower()
        pool = self._weapons.get(self._kind(), [])
        if len(q) < 2:
            return []
        pre = [t for t in pool if t[0].lower().startswith(q)]
        sub = [t for t in pool
               if q in t[0].lower() and not t[0].lower().startswith(q)]
        return (pre + sub)[:10]

    def _picked(self, name: str, slug: str) -> None:
        self.weapon_var.set(name)        # autocomplete the search form
        self._open((name, slug))

    def _flip_order(self) -> None:
        self._asc = not self._asc
        self.order_btn.configure(text=wfm_market_vm.sort_label(self._asc))
        if self.slug:
            self._open((self.wname, self.slug))

    # -- contracts list --------------------------------------------------------

    def _open(self, weapon: tuple[str, str]) -> None:
        self.wname, self.slug = weapon
        kind, asc = self._kind(), self._asc
        self.status.configure(text=f"loading {kind} contracts for "
                                   f"{self.wname}…", fg=MUTED)

        def work() -> None:
            try:
                rows = self.client.auctions(kind, self.slug, ascending=asc)
            except wfm_market.MarketError as exc:
                msg = str(exc)
                self.after(0, lambda: self.winfo_exists() and
                           self.status.configure(text=msg, fg=ERR))
                return
            self.after(0, lambda: self._render(kind, rows))

        threading.Thread(target=work, daemon=True).start()

    def _redraw(self) -> None:
        """Re-render the last fetched contract list (deferred flush)."""
        if self._last:
            self._render(*self._last)

    def _render(self, kind: str, rows: list[dict]) -> None:
        if not self.winfo_exists():
            return
        self._last = (kind, rows)
        if not self.view.tab_live(self):
            self._dirty = True      # persistent view, fetch landed off screen
            return
        f = self.app.fonts
        for child in self.body.winfo_children():
            child.destroy()
        self.status.configure(
            text=wfm_market_vm.contracts_summary(len(rows), kind, self.wname,
                                                 self.ROWS), fg=MUTED)
        for raw in rows[:self.ROWS]:
            r = wfm_market_vm.contract_row(kind, self.wname, raw)
            line = tk.Frame(self.body, bg=WFM_CARD, padx=12, pady=6)
            line.pack(fill="x", pady=2)
            dot, color = _status_dot(r["status"])
            tk.Label(line, text=dot, bg=WFM_CARD, fg=color,
                     font=f["small"]).pack(side="left")
            tk.Label(line, text=r["title"], bg=WFM_CARD, fg=WFM_TEAL,
                     font=f["body"]).pack(side="left")
            tk.Label(line, text=r["meta"], bg=WFM_CARD, fg=WFM_MUTED,
                     font=f["small"]).pack(side="left")
            tk.Label(line, image=plat_icon(WFM_CARD), bg=WFM_CARD).pack(
                side="right")
            tk.Label(line, text=str(r["price"]), bg=WFM_CARD, fg=PLAT,
                     font=f["price"]).pack(side="right", padx=(0, 3))
            tk.Label(line, text=f"{r['owner']}   {r['price_label']} ",
                     bg=WFM_CARD, fg=WFM_MUTED,
                     font=f["small"]).pack(side="right")


class WatchlistTab(tk.Frame):
    """Bookmarked items (☆ on the Market tab). Each row shows the item and,
    after a refresh, the best online sell/buy - one click back into the full
    order book, no re-searching."""

    def __init__(self, parent: tk.Widget, view: MarketView) -> None:
        super().__init__(parent, bg=TAB_BG)
        self.view = view
        self.app = view.app
        self.client = view.client
        f = self.app.fonts

        ctr = tk.Frame(self, bg=TAB_BG)
        ctr.pack(fill="x", padx=SP_SCREEN, pady=(12, 4))
        tk.Label(ctr, text="Bookmarked items - add more with ☆ Watch on the "
                 "Market tab.", bg=TAB_BG, fg=MUTED,
                 font=f["small"]).pack(side="left")
        tk.Button(ctr, text="↻ Refresh prices", command=self._refresh_all,
                  **secondary_style(f["small"])).pack(side="right")

        self.body = tk.Frame(self, bg=TAB_BG)
        self.body.pack(fill="both", expand=True, padx=SP_SCREEN, pady=(4, 16))
        self.rows: dict[str, tk.Label] = {}      # slug -> price label
        self._dirty = False
        self.reload()

    def on_show(self) -> None:
        self.reload()

    def _redraw(self) -> None:
        self.reload()

    def _name_of(self, slug: str) -> str:
        # Public no-fetch lookup; a prettified slug fills in until the
        # catalogue loads (the Market tab's first search fetches it).
        return self.client.name_of(slug) or slug.replace("_", " ").title()

    def reload(self) -> None:
        # ☆ Watch on the Market tab calls this cross-tab, and __init__ calls
        # it before this view has ever been shown - rebuild only when it
        # would be seen. on_show() reloads unconditionally, so nothing stales.
        if not self.view.tab_live(self):
            self._dirty = True
            return
        for child in self.body.winfo_children():
            child.destroy()
        self.rows.clear()
        f = self.app.fonts
        slugs = wfm_market.load_watchlist()
        if not slugs:
            tk.Label(self.body, text="Nothing watched yet.", bg=TAB_BG, fg=MUTED,
                     font=f["small"]).pack(anchor="w")
            return
        for slug in slugs:
            line = tk.Frame(self.body, bg=WFM_CARD, padx=12, pady=8)
            line.pack(fill="x", pady=2)
            name = self._name_of(slug)
            tk.Label(line, text=name, bg=WFM_CARD, fg=WFM_TEAL, anchor="w",
                     font=f["body"]).pack(side="left")
            wiki_link(line, self.app, name, WFM_CARD).pack(
                side="left", padx=(SP_SM, 0))
            price = tk.Label(line, text="  —", bg=WFM_CARD, fg=WFM_MUTED,
                             font=f["small"])
            price.pack(side="left", padx=(10, 0))
            self.rows[slug] = price
            tk.Button(line, text="✕", command=lambda s=slug: self._remove(s),
                      bg=WFM_CARD, fg=WFM_RED, relief="flat", bd=0, padx=8,
                      pady=1, cursor="hand2", font=f["small"],
                      activebackground=WFM_EDGE).pack(side="right")
            tk.Button(line, text="Open",
                      command=lambda s=slug, n=name:
                      self.view.open_in_market(s, n),
                      bg=WFM_EDGE, fg=TEXT, relief="flat", bd=0, padx=10,
                      pady=1, cursor="hand2", font=f["small"],
                      activebackground=PANEL_HI).pack(side="right",
                                                      padx=(0, 6))

    def _remove(self, slug: str) -> None:
        wl = wfm_market.load_watchlist()
        if slug in wl:
            wl.remove(slug)
            wfm_market.save_watchlist(wl)
        self.reload()
        # keep the Market tab's star in sync if it shows this item
        mt = self.view.tabs.get("Market")
        if mt and mt.slug == slug:
            mt._paint_watch()

    def _refresh_all(self) -> None:
        slugs = list(self.rows)
        if not slugs:
            return
        for lbl in self.rows.values():
            lbl.configure(text="  …", fg=WFM_MUTED)

        def work() -> None:
            for slug in slugs:
                try:
                    book = self.client.order_book(slug)
                except wfm_market.MarketError:
                    self.after(0, lambda s=slug: s in self.rows and
                               self.rows[s].winfo_exists() and
                               self.rows[s].configure(text="  fetch failed",
                                                      fg=ERR))
                    continue
                text = wfm_market_vm.price_line(
                    *wfm_market_vm.best_live_prices(book))
                self.after(0, lambda s=slug, t=text: s in self.rows and
                           self.rows[s].winfo_exists() and
                           self.rows[s].configure(text=t, fg=TEXT))

        threading.Thread(target=work, daemon=True).start()


class SettingsView(tk.Frame):
    """The Settings app: a secondary tree sidebar picks a page. Headers
    are collapsible (children hidden by default) - the ▸ arrow toggles a
    section, clicking a header expands it AND opens its first page.

        Settings
        ▸ Display  ─ Window
        ▸ Data     ─ Warframe / Market / WF Toolbox
        ▸ Market   ─ Messaging
    """

    # (header, [(page-key, label), ...]) - children hidden until expanded
    TREE = [("Display", [("window", "Window")]),
            ("Data", [("warframe", "Warframe"),
                      ("market", "Market"),
                      ("webview", "WebView"),
                      ("toolbox", "WF Toolbox")]),
            ("Market", [("messaging", "Messaging")])]

    def __init__(self, parent: tk.Widget, app: App) -> None:
        super().__init__(parent, bg=BG)
        self.app = app
        f = app.fonts

        # Tree typography per the style guide: title = small caps muted,
        # category headings = h2 (with a ▸/▾ toggle), leaves = body text.
        tree = tk.Frame(self, bg=PANEL, width=200)
        tree.pack(side="left", fill="y")
        tree.pack_propagate(False)
        title = tk.Label(tree, text="SETTINGS", bg=PANEL, fg=MUTED,
                         font=f["small"], cursor="hand2")
        title.pack(anchor="w", padx=SP_XL, pady=(SP_XL, SP_MD))
        title.bind("<Button-1>",
                   lambda _e: self._header_click(self.TREE[0][0]))

        self.tree_btns: dict[str, tk.Button] = {}
        self.sections: dict[str, dict] = {}
        self.parent_of: dict[str, str] = {}
        for header, kids in self.TREE:
            row = tk.Frame(tree, bg=PANEL)
            row.pack(fill="x", pady=(SP_LG, 0))
            arrow = tk.Label(row, text="▸", bg=PANEL, fg=MUTED, width=2,
                             font=f["h2"], cursor="hand2")
            arrow.pack(side="left", padx=(SP_LG, 0))
            arrow.bind("<Button-1>", lambda _e, h=header: self._toggle(h))
            tk.Button(row, text=header, anchor="w",
                      command=lambda h=header: self._header_click(h),
                      bg=PANEL, fg=TEXT, relief="flat", bd=0,
                      pady=SP_SM, cursor="hand2", font=f["h2"],
                      activebackground=PANEL_HI, activeforeground=TEXT
                      ).pack(side="left", fill="x", expand=True)
            kidsf = tk.Frame(tree, bg=PANEL)      # hidden until expanded
            for key, label in kids:
                b = tk.Button(kidsf, text=label, anchor="w",
                              command=lambda k=key: self.select_page(k),
                              bg=PANEL, fg=MUTED, relief="flat", bd=0,
                              padx=SP_XL * 3, pady=SP_MD, cursor="hand2",
                              font=f["body"], activebackground=PANEL_HI,
                              activeforeground=TEXT)
                b.pack(fill="x")
                self.tree_btns[key] = b
                self.parent_of[key] = header
            self.sections[header] = {"row": row, "arrow": arrow,
                                     "kids": kidsf, "open": False,
                                     "first": kids[0][0]}

        self.holder = tk.Frame(self, bg=BG)
        self.holder.pack(side="left", fill="both", expand=True,
                         padx=20, pady=16)
        self.page: tk.Frame | None = None
        self.current: str | None = None
        self._header_click(self.TREE[0][0])   # expand Display, open Window

    def _toggle(self, header: str) -> None:
        sec = self.sections[header]
        if sec["open"]:
            sec["kids"].pack_forget()
            sec["arrow"].configure(text="▸")
        else:
            sec["kids"].pack(fill="x", after=sec["row"])
            sec["arrow"].configure(text="▾")
        sec["open"] = not sec["open"]

    def _header_click(self, header: str) -> None:
        """Header click = reveal the children AND open the first of them."""
        if not self.sections[header]["open"]:
            self._toggle(header)
        self.select_page(self.sections[header]["first"])

    def select_page(self, key: str) -> None:
        factories = {"window": DisplayPage, "warframe": WarframeDataPage,
                     "market": MarketDataPage, "webview": WebViewDataPage,
                     "toolbox": ToolboxDataPage, "messaging": MessagingPage}
        if key not in factories or key == self.current:
            return
        parent = self.parent_of.get(key)
        if parent and not self.sections[parent]["open"]:
            self._toggle(parent)
        for k, b in self.tree_btns.items():
            active = k == key
            b.configure(bg=SIDEBAR_ACTIVE if active else PANEL,
                        fg=TEXT if active else MUTED)
        for child in self.holder.winfo_children():
            child.destroy()
        self.page = factories[key](self.holder, self.app)
        self.page.pack(fill="both", expand=True)
        self.current = key

    # live-update hooks forwarded from App to whichever page is showing
    def update_session(self) -> None:
        fn = getattr(self.page, "update_session", None)
        if fn:
            fn()

    def update_presence(self) -> None:
        fn = getattr(self.page, "update_presence", None)
        if fn:
            fn()


class DisplayPage(tk.Frame):
    """Settings > Display. Style guide: every control (checkbox, spinbox)
    sits LEFT of its descriptive text; cyclic pickers wrap around."""

    def __init__(self, parent: tk.Widget, app: App) -> None:
        super().__init__(parent, bg=BG)
        self.app = app
        f = app.fonts
        s = app.settings

        box = tk.Frame(self, bg=PANEL, padx=SP_XL, pady=SP_XL)
        box.pack(fill="x")
        tk.Label(box, text="Display", bg=PANEL, fg=TEXT,
                 font=f["h2"]).pack(anchor="w", pady=(0, SP_LG))

        def row() -> tk.Frame:
            r = tk.Frame(box, bg=PANEL)
            r.pack(fill="x", pady=SP_MD)
            return r

        def note(parent: tk.Widget, text: str) -> tk.Label:
            lbl = tk.Label(parent, text=text, bg=PANEL, fg=MUTED,
                           font=f["small"])
            lbl.pack(side="left", padx=(SP_LG, 0))
            return lbl

        def check(label: str, key: str, hint: str = "",
                  command=None) -> tk.BooleanVar:
            # a Checkbutton renders its box LEFT of its own text
            var = tk.BooleanVar(value=bool(s.get(key)))

            def flip() -> None:
                s[key] = var.get()
                self._save()
                if command:
                    command(var.get())
            r = row()
            tk.Checkbutton(r, text=label, variable=var, command=flip,
                           bg=PANEL, fg=TEXT, selectcolor=CONSOLE_BG,
                           activebackground=PANEL, activeforeground=TEXT,
                           font=f["body"], highlightthickness=0
                           ).pack(side="left")
            if hint:
                note(r, hint)
            return var

        def spin(values, var: tk.StringVar, command,
                 wrap: bool = True) -> tk.Spinbox:
            return tk.Spinbox(row(), values=values, textvariable=var,
                              wrap=wrap, width=10,
                              buttonbackground=PANEL, justify="center",
                              font=f["body"], command=command,
                              state="readonly",
                              readonlybackground=FIELD_BG_OUT,
                              **field_style(False))

        self.fs_var = check("Launch fullscreen (maximized)", "fullscreen")

        # window size: a wrap-around spinbox (scrolling past the end loops)
        cur_size = s.get("window_size", "1280x720")
        if cur_size not in wfm_config.WINDOW_SIZES:
            cur_size = "1280x720"           # normalize stale saved values
            s["window_size"] = cur_size
            self._save()
        self.size_var = tk.StringVar(value=cur_size)
        sp = spin(tuple(wfm_config.WINDOW_SIZES), self.size_var,
                  self._size_changed)
        sp.pack(side="left")
        # Tk resets a values= spinbox to its first entry on creation;
        # re-assert the saved value.
        self.size_var.set(cur_size)
        note(sp.master, "window size · applies immediately when not maximized")

        # monitor: spinbox clamped to the number of displays detected
        n_mon = monitor_count()
        self.mon_var = tk.StringVar(
            value=str(min(max(1, int(s.get("monitor", 1))), n_mon)))
        mon_cur = self.mon_var.get()
        mp = spin(tuple(str(i) for i in range(1, n_mon + 1)), self.mon_var,
                  self._mon_changed)
        mp.pack(side="left")
        self.mon_var.set(mon_cur)           # same values= reset quirk
        note(mp.master, f"open on monitor · {n_mon} display(s) detected · "
             "applies at launch")

        # Windows integration --------------------------------------------
        r = row()
        self.startup_var = tk.BooleanVar(
            value=wfm_config.start_with_windows_enabled())
        tk.Checkbutton(r, text="Launch on Windows startup",
                       variable=self.startup_var, command=self._startup_flip,
                       bg=PANEL, fg=TEXT, selectcolor=CONSOLE_BG,
                       activebackground=PANEL, activeforeground=TEXT,
                       font=f["body"], highlightthickness=0).pack(side="left")
        self.startup_note = note(r, "current-user registry entry, no admin "
                                    "needed")

        r = row()
        self.watch_var = tk.BooleanVar(
            value=wfm_config.watch_warframe_enabled()
            or bool(s.get("launch_with_warframe")))
        tk.Checkbutton(r, text="Launch the Toolbox when Warframe starts",
                       variable=self.watch_var, command=self._watch_flip,
                       bg=PANEL, fg=TEXT, selectcolor=CONSOLE_BG,
                       activebackground=PANEL, activeforeground=TEXT,
                       font=f["body"], highlightthickness=0).pack(side="left")
        self.watch_note = note(r, "a background watcher notices the game "
                                  "process and opens the Toolbox - works on "
                                  "any PC")

        check("Send to tray when minimized", "minimize_to_tray",
              "minimizing hides the window to the notification area; click "
              "the tray icon to restore")

        # Read-out, not a setting: nothing here is adjustable, so it stays
        # out of config.DEFAULTS. It answers "why does this look soft, and
        # what is the app doing about it" before it becomes a bug report.
        scale = display_scale(app.winfo_id())
        r = row()
        tk.Label(r, text=f"Display scaling: {round(scale * 100)}%",
                 bg=PANEL, fg=TEXT, font=f["body"]).pack(side="left")
        if scale > 1.001:
            sw = app.winfo_screenwidth()
            sh = app.winfo_screenheight()
            note(r, f"the Toolbox draws at {sw}x{sh} and Windows upscales it "
                    f"{scale:g}x to fill the display · text is softer than "
                    "native as a result. The embedded browser forces this "
                    "(it would otherwise change the DPI mode mid-session).")
        else:
            note(r, "unscaled - the Toolbox is rendering at native "
                    "resolution")

    def _save(self) -> None:
        wfm_config.save_settings(self.app.settings)

    def _size_changed(self) -> None:
        value = self.size_var.get()
        if value not in wfm_config.WINDOW_SIZES:
            return
        self.app.settings["window_size"] = value
        self._save()
        if not self.app._maximized:
            self.app.geometry(value)

    def _mon_changed(self) -> None:
        try:
            self.app.settings["monitor"] = int(self.mon_var.get())
        except ValueError:
            return
        self._save()

    def _startup_flip(self) -> None:
        want = self.startup_var.get()
        if wfm_config.set_start_with_windows(want):
            self.app.settings["start_with_windows"] = want
            self._save()
            self.startup_note.configure(
                text="added to startup ✔" if want else "removed from startup",
                fg=OK if want else MUTED)
        else:
            self.startup_var.set(not want)
            self.startup_note.configure(text="couldn't write the registry "
                                        "entry", fg=ERR)

    def _watch_flip(self) -> None:
        """'Launch with Warframe' - the right way round: a tiny watcher
        (warframe_watcher.pyw) starts with Windows, waits for the game
        process to appear, and opens the Toolbox. Detection is by the game's
        own executable name, so it works on any machine this folder is
        copied to."""
        want = self.watch_var.get()
        if wfm_config.set_watch_warframe(want):
            self.app.settings["launch_with_warframe"] = want
            self._save()
            if want:
                wfm_config.spawn_watcher()      # active right away, not just
                self.watch_note.configure(      # after the next reboot
                    text="watcher active ✔ - the Toolbox will open when "
                         "Warframe does", fg=OK)
            else:
                self.watch_note.configure(text="watcher disabled", fg=MUTED)
        else:
            self.watch_var.set(not want)
            self.watch_note.configure(text="couldn't write the registry "
                                      "entry", fg=ERR)


class MessagingPage(tk.Frame):
    """Settings > Market > Messaging: the ✉ clipboard templates used by the
    Market browser. Placeholders: {user} (the other tenno), {item},
    {price}. The '/w {user} ' prefix makes the paste a whisper in-game."""

    FIELDS = (("msg_buy", "Buying — copied from a WTS row (you purchase)"),
              ("msg_sell", "Selling — copied from a WTB row (you supply)"))

    def __init__(self, parent: tk.Widget, app: App) -> None:
        super().__init__(parent, bg=BG)
        self.app = app
        f = app.fonts
        s = app.settings

        box = tk.Frame(self, bg=PANEL, padx=SP_XL, pady=SP_XL)
        box.pack(fill="x")
        tk.Label(box, text="Messaging", bg=PANEL, fg=TEXT,
                 font=f["h2"]).pack(anchor="w", pady=(0, SP_SM))
        tk.Label(box, text="Templates for the mail-copy buttons in the Market "
                           "browser. Placeholders: {user} = the other tenno, "
                           "{item} = the item name, {price} = their posted "
                           "price. Keep the '/w {user} ' prefix so pasting "
                           "in-game whispers them directly.",
                 bg=PANEL, fg=MUTED, wraplength=680, justify="left",
                 font=f["small"]).pack(anchor="w", pady=(0, SP_LG))

        self.vars: dict[str, tk.StringVar] = {}
        for key, label in self.FIELDS:
            tk.Label(box, text=label, bg=PANEL, fg=MUTED,
                     font=f["small"]).pack(anchor="w", pady=(SP_MD, 2))
            var = tk.StringVar(value=s.get(key)
                               or wfm_config.DEFAULTS[key])
            e = tk.Entry(box, textvariable=var, font=f["body"],
                         **field_style(False))
            e.pack(fill="x", ipady=CTRL_IPADY)
            e.bind("<FocusOut>", lambda _e, k=key: self._save(k))
            e.bind("<Return>", lambda _e, k=key: self._save(k))
            self.vars[key] = var

        rail = tk.Frame(box, bg=PANEL)
        rail.pack(fill="x", pady=(SP_LG, 0))
        tk.Button(rail, text="Reset to defaults", command=self._reset,
                  bg=PANEL_HI, fg=TEXT, relief="flat", bd=0, padx=12,
                  pady=4, cursor="hand2", font=f["small"],
                  activebackground=PANEL).pack(side="left")
        self.status = tk.Label(rail, text="", bg=PANEL, fg=MUTED,
                               font=f["small"])
        self.status.pack(side="left", padx=(SP_LG, 0))

    def _save(self, key: str) -> None:
        self.app.settings[key] = self.vars[key].get().strip() \
            or wfm_config.DEFAULTS[key]
        wfm_config.save_settings(self.app.settings)
        self.status.configure(text="saved ✔", fg=OK)

    def _reset(self) -> None:
        for key, _label in self.FIELDS:
            self.vars[key].set(wfm_config.DEFAULTS[key])
            self._save(key)
        self.status.configure(text="reset to defaults ✔", fg=OK)


class GoodbyeDialog(tk.Toplevel):
    """Destructive-action confirmation: the user must type 'goodbye' and hit
    Enter / OK before on_confirm runs."""

    WORD = "goodbye"

    def __init__(self, parent: tk.Widget, app: App, title: str,
                 message: str, on_confirm) -> None:
        super().__init__(parent)
        self.on_confirm = on_confirm
        f = app.fonts
        self.title(title)
        self.configure(bg=PANEL, padx=22, pady=18)
        self.resizable(False, False)
        self.transient(app)
        self.grab_set()

        tk.Label(self, text=title, bg=PANEL, fg=ERR,
                 font=f["h2"]).pack(anchor="w")
        tk.Label(self, text=message, bg=PANEL, fg=TEXT, justify="left",
                 wraplength=420, font=f["small"]).pack(anchor="w",
                                                       pady=(6, 10))
        tk.Label(self, text=f"Type '{self.WORD}' to confirm:", bg=PANEL,
                 fg=MUTED, font=f["small"]).pack(anchor="w")
        self.entry = tk.Entry(self, width=24, font=f["body"],
                              **field_style(False))
        self.entry.pack(anchor="w", ipady=4, pady=(3, 12))
        self.entry.bind("<KeyRelease>", lambda _e: self._check())
        self.entry.bind("<Return>", lambda _e: self._ok())
        self.entry.focus_set()

        btns = tk.Frame(self, bg=PANEL)
        btns.pack(anchor="e")
        self.ok_btn = tk.Button(btns, text="OK", command=self._ok,
                                bg=WFM_RED_DIM, fg=TEXT, relief="flat", bd=0,
                                padx=18, pady=5, cursor="hand2",
                                state="disabled", font=f["small"],
                                activebackground=WFM_RED)
        self.ok_btn.pack(side="right", padx=(8, 0))
        tk.Button(btns, text="Cancel", command=self.destroy,
                  **secondary_style(f["small"], wide=True)).pack(side="right")

        # center on the screen the app is on (dialogs otherwise open at the
        # window manager's default position)
        self.update_idletasks()
        try:
            ax, ay = app.winfo_rootx(), app.winfo_rooty()
            aw, ah = app.winfo_width(), app.winfo_height()
            w, h = self.winfo_reqwidth(), self.winfo_reqheight()
            self.geometry(f"+{max(0, ax + (aw - w) // 2)}"
                          f"+{max(0, ay + (ah - h) // 2)}")
        except tk.TclError:
            pass

    def _match(self) -> bool:
        return self.entry.get().strip().lower() == self.WORD

    def _check(self) -> None:
        self.ok_btn.configure(state="normal" if self._match() else "disabled")

    def _ok(self) -> None:
        if not self._match():
            return
        cb = self.on_confirm
        self.destroy()
        cb()


class WebViewDataPage(tk.Frame):
    """Settings > Data > WebView: the embedded web apps' browser data
    (cookies, cache, site storage in `data/.webview/`) plus the ad
    blocker. Clearing goes through WebView2 itself when the browsers are
    running (the files on disk are locked), so it works live."""

    def __init__(self, parent: tk.Widget, app: App) -> None:
        super().__init__(parent, bg=BG)
        self.app = app
        f = app.fonts
        s = app.settings

        box = tk.Frame(self, bg=PANEL, padx=18, pady=14)
        box.pack(fill="both", expand=True)
        tk.Label(box, text="Web data", bg=PANEL, fg=TEXT,
                 font=f["h2"]).pack(anchor="w")
        tk.Label(box, text="The embedded web apps (WF Live, Wiki, "
                           "Overframe) share one browser profile in "
                           "data/.webview - cookies and logins persist "
                           "across sessions on purpose. Clear parts of it "
                           "here.",
                 bg=PANEL, fg=MUTED, wraplength=640, justify="left",
                 font=f["small"]).pack(anchor="w", pady=(2, SP_LG))

        # -- sizes ---------------------------------------------------------
        self.size_rows: dict[str, tk.Label] = {}
        for key, label, desc in (
                ("total", "All web data", "everything in data/.webview"),
                ("cache", "Cache", "page resources; safe to clear anytime"),
                ("cookies", "Cookies", "logins and site preferences")):
            row = tk.Frame(box, bg=WFM_CARD, padx=10, pady=5)
            row.pack(fill="x", pady=2)
            tk.Label(row, text=label, bg=WFM_CARD, fg=TEXT, width=14,
                     anchor="w", font=f["body"]).pack(side="left")
            val = tk.Label(row, text="…", bg=WFM_CARD, fg=WFM_MUTED,
                           font=f["small"])
            val.pack(side="left")
            self.size_rows[key] = val
            tk.Label(row, text=desc, bg=WFM_CARD, fg=WFM_MUTED,
                     font=f["small"]).pack(side="right", padx=(0, 10))

        # -- ad blocker ------------------------------------------------------
        ab = tk.Frame(box, bg=PANEL)
        ab.pack(fill="x", pady=(SP_LG, 0))
        self.adblock_var = tk.BooleanVar(value=bool(s.get("adblock", True)))

        def flip() -> None:
            s["adblock"] = self.adblock_var.get()
            wfm_config.save_settings(s)
            self.app.webhost.adblock = self.adblock_var.get()
            self._update_blocked()
        tk.Checkbutton(ab, text="Block ads and trackers in the web apps",
                       variable=self.adblock_var, command=flip, bg=PANEL,
                       fg=TEXT, selectcolor=CONSOLE_BG,
                       activebackground=PANEL, activeforeground=TEXT,
                       font=f["body"], highlightthickness=0
                       ).pack(side="left")
        self.blocked_lbl = tk.Label(ab, text="", bg=PANEL, fg=MUTED,
                                    font=f["small"])
        self.blocked_lbl.pack(side="left", padx=(SP_LG, 0))
        tk.Label(box, text="Requests to known ad/tracking hosts are "
                           "answered locally and never sent. Add your own "
                           "hosts in data/adblock-hosts.txt (one per line, "
                           "applies at next launch).",
                 bg=PANEL, fg=MUTED, wraplength=640, justify="left",
                 font=f["small"]).pack(anchor="w", pady=(2, 0))

        # -- action rail pinned at the bottom -------------------------------
        rail = tk.Frame(box, bg=PANEL)
        rail.pack(side="bottom", fill="x", pady=(SP_XL, 0))
        tk.Button(rail, text="Clear cache", command=self._clear_cache,
                  bg=PANEL_HI, fg=WARN, relief="flat", bd=0, padx=14,
                  pady=6, cursor="hand2", font=f["small"],
                  activebackground=PANEL).pack(side="left")
        tk.Button(rail, text="Clear cookies", command=self._clear_cookies,
                  bg=PANEL_HI, fg=WARN, relief="flat", bd=0, padx=14,
                  pady=6, cursor="hand2", font=f["small"],
                  activebackground=PANEL).pack(side="left", padx=(SP_LG, 0))
        tk.Button(rail, text="⚠ Clear ALL web data",
                  command=self._clear_all, bg=WFM_RED_DIM, fg=TEXT,
                  relief="flat", bd=0, padx=14, pady=6, cursor="hand2",
                  font=f["small"], activebackground=WFM_RED
                  ).pack(side="right")
        self.status = tk.Label(box, text="", bg=PANEL, fg=MUTED,
                               font=f["small"])
        self.status.pack(side="bottom", anchor="w", pady=(SP_LG, 0))

        self._refresh_sizes()
        self._update_blocked()

    @staticmethod
    def _fmt(n: int) -> str:
        if n >= 1 << 20:
            return f"{n / (1 << 20):.1f} MB"
        if n >= 1 << 10:
            return f"{n / (1 << 10):.0f} KB"
        return f"{n} B"

    def _refresh_sizes(self) -> None:
        if not self.winfo_exists():
            return
        sizes = wfm_config.webview_data_breakdown()
        for key, lbl in self.size_rows.items():
            lbl.configure(text=f"  {self._fmt(sizes[key])}")

    def _update_blocked(self) -> None:
        wh = self.app.webhost
        if wh.adblock:
            self.blocked_lbl.configure(
                text=f"{wh.blocked_count} request(s) blocked this session")
        else:
            self.blocked_lbl.configure(text="off - pages load everything")

    def _done(self, what: str, ok: bool) -> None:
        self.status.configure(
            text=f"{what} cleared." if ok else f"nothing to clear / "
                                               f"{what} clear failed.",
            fg=OK if ok else WARN)
        # WebView2 clears asynchronously - give it a beat, then re-measure
        self.after(1500, self._refresh_sizes)

    def _clear_async(self, what: str, fn) -> None:
        """WebView2 clears are a cross-thread WinForms Invoke plus a wait
        (up to ~5s each, longer if the browser is mid-navigation), and the
        no-browser fallback is a recursive rmtree - all of which would
        freeze the window if run inline."""
        self.status.configure(text=f"clearing {what}…", fg=MUTED)

        def work() -> None:
            ok = False
            try:
                ok = fn()
            except Exception:                               # noqa: BLE001
                ok = False
            self.after(0, lambda: self.winfo_exists()
                       and self._done(what, ok))
        threading.Thread(target=work, daemon=True).start()

    def _clear_cache(self) -> None:
        if messagebox.askyesno("Clear cache", "Clear the web apps' cached "
                               "page resources? (You stay signed in "
                               "everywhere.)", parent=self):
            self._clear_async("cache", self.app.webhost.clear_cache)

    def _clear_cookies(self) -> None:
        if messagebox.askyesno("Clear cookies", "Clear all cookies? This "
                               "signs you out of every site in the web "
                               "apps.", parent=self):
            self._clear_async("cookies", self.app.webhost.clear_cookies)

    def _clear_all(self) -> None:
        GoodbyeDialog(
            self, self.app, "Clear ALL web data",
            "This wipes the embedded browser profile completely - cookies, "
            "logins, cache, site storage and history for WF Live, Wiki and "
            "Overframe. The Toolbox itself is not affected.",
            lambda: self._clear_async("all web data",
                                      self.app.webhost.clear_all_data))


class ToolboxDataPage(tk.Frame):
    """Settings > Data > WF Toolbox: every file the app generates about the
    user - open any of them in the default editor, delete them singly, wipe
    the downloaded-image cache, or delete everything (each wipe requires
    typing 'goodbye'). Program assets (embedded icons, assets/, the code)
    are never listed and never touched."""

    def __init__(self, parent: tk.Widget, app: App) -> None:
        super().__init__(parent, bg=BG)
        self.app = app
        f = app.fonts

        box = tk.Frame(self, bg=PANEL, padx=18, pady=14)
        box.pack(fill="both", expand=True)
        tk.Label(box, text="Your data", bg=PANEL, fg=TEXT,
                 font=f["h2"]).pack(anchor="w")
        tk.Label(box, text="Everything the Toolbox stores about you lives in "
                           "these files, next to the app. Click a name to "
                           "open it in your default editor; ✕ deletes just "
                           "that file.",
                 bg=PANEL, fg=MUTED, wraplength=640, justify="left",
                 font=f["small"]).pack(anchor="w", pady=(2, 10))
        # The session file is a trading credential. Inside the user profile
        # its ACLs keep other local accounts out; on a data drive the
        # default root ACLs usually don't - say so rather than imply safety.
        if wfm_session.exposed_location():
            tk.Label(box, text="⚠  These files sit outside your user profile "
                               f"({wfm_session.ROOT}), where other accounts "
                               "on this PC may be able to read them - "
                               "including your saved warframe.market login. "
                               "Move the Toolbox under your user folder if "
                               "this PC is shared.",
                     bg=PANEL, fg=WARN, wraplength=640, justify="left",
                     font=f["small"]).pack(anchor="w", pady=(0, SP_LG))

        # action rail pinned to the BOTTOM of the page (packed side=bottom
        # first, so the file list above can grow without pushing it around)
        rail = tk.Frame(box, bg=PANEL)
        rail.pack(side="bottom", fill="x", pady=(SP_XL, 0))
        tk.Button(rail, text="Delete cached images",
                  command=self._delete_images,
                  **{**secondary_style(f["small"], wide=True), "fg": WARN}
                  ).pack(side="left")
        tk.Button(rail, text="⚠ Delete ALL user data",
                  command=self._delete_all, bg=WFM_RED_DIM, fg=TEXT,
                  relief="flat", bd=0, padx=14, pady=6, cursor="hand2",
                  font=f["small"], activebackground=WFM_RED
                  ).pack(side="right")
        self.status = tk.Label(box, text="", bg=PANEL, fg=MUTED,
                               font=f["small"])
        self.status.pack(side="bottom", anchor="w", pady=(SP_LG, 0))

        self.files_box = tk.Frame(box, bg=PANEL)
        self.files_box.pack(fill="x")

        self.reload()

    def reload(self) -> None:
        for child in self.files_box.winfo_children():
            child.destroy()
        f = self.app.fonts
        files = wfm_config.user_data_files()
        if not files:
            tk.Label(self.files_box, text="No user data on disk.", bg=PANEL,
                     fg=MUTED, font=f["small"]).pack(anchor="w")
        for name, path, desc, size in files:
            row = tk.Frame(self.files_box, bg=WFM_CARD, padx=10, pady=5)
            row.pack(fill="x", pady=2)
            tk.Button(row, text=name, command=lambda p=path: self._open(p),
                      bg=WFM_CARD, fg=WFM_TEAL, relief="flat", bd=0,
                      cursor="hand2", font=f["body"], anchor="w",
                      activebackground=WFM_EDGE, activeforeground=WFM_TEAL
                      ).pack(side="left")
            tk.Label(row, text=f"  {size:,} B", bg=WFM_CARD, fg=WFM_MUTED,
                     font=f["small"]).pack(side="left")
            tk.Button(row, text="✕", command=lambda p=path, n=name:
                      self._delete_one(p, n),
                      bg=WFM_CARD, fg=WFM_RED, relief="flat", bd=0, padx=8,
                      cursor="hand2", font=f["small"],
                      activebackground=WFM_EDGE).pack(side="right")
            tk.Label(row, text=desc, bg=WFM_CARD, fg=WFM_MUTED, anchor="e",
                     font=f["small"]).pack(side="right", padx=(0, 10))
        # the image cache is a folder, shown as its own row
        n, total = wfm_config.thumb_cache_size()
        row = tk.Frame(self.files_box, bg=WFM_CARD, padx=10, pady=5)
        row.pack(fill="x", pady=2)
        tk.Button(row, text=".cache/thumbs/",
                  command=lambda: self._open(wfm_config.THUMB_CACHE),
                  bg=WFM_CARD, fg=WFM_TEAL, relief="flat", bd=0,
                  cursor="hand2", font=f["body"], anchor="w",
                  activebackground=WFM_EDGE, activeforeground=WFM_TEAL
                  ).pack(side="left")
        tk.Label(row, text=f"  {n} image(s), {total:,} B", bg=WFM_CARD,
                 fg=WFM_MUTED, font=f["small"]).pack(side="left")
        tk.Label(row, text="downloaded item images (not program assets)",
                 bg=WFM_CARD, fg=WFM_MUTED, font=f["small"]).pack(
                     side="right", padx=(0, 10))
        # so is the embedded web apps' browser profile
        n, total = wfm_config.webview_profile_size()
        if n:
            row = tk.Frame(self.files_box, bg=WFM_CARD, padx=10, pady=5)
            row.pack(fill="x", pady=2)
            tk.Button(row, text=".webview/",
                      command=lambda: self._open(
                          wfm_config.WEBVIEW_PROFILE),
                      bg=WFM_CARD, fg=WFM_TEAL, relief="flat", bd=0,
                      cursor="hand2", font=f["body"], anchor="w",
                      activebackground=WFM_EDGE,
                      activeforeground=WFM_TEAL).pack(side="left")
            tk.Label(row, text=f"  {n} file(s), {total:,} B", bg=WFM_CARD,
                     fg=WFM_MUTED, font=f["small"]).pack(side="left")
            tk.Label(row, text="web apps' cookies + cache - manage under "
                               "Data > WebView",
                     bg=WFM_CARD, fg=WFM_MUTED, font=f["small"]).pack(
                         side="right", padx=(0, 10))

    def _open(self, path: Path) -> None:
        err = wfm_config.open_in_default_app(path)
        if err:
            self.status.configure(text=f"couldn't open: {err}", fg=ERR)

    def _delete_one(self, path: Path, name: str) -> None:
        if not messagebox.askyesno("Delete file",
                                   f"Delete {name}?", parent=self):
            return
        if name == ".wfm_session.json" and self.app.session is not None:
            self.app.unlink_account()      # proper unlink, not just the file
            return
        wfm_config.delete_user_file(path)
        self.status.configure(text=f"{name} deleted.", fg=OK)
        self.reload()

    def _delete_images(self) -> None:
        GoodbyeDialog(
            self, self.app, "Delete cached images",
            "This removes every item image downloaded while browsing the "
            "market or managing listings. Program assets (the platinum "
            "icon, the app logo, and so on) are embedded in the app and "
            "are not affected. Images re-download as needed.",
            self._do_delete_images)

    def _do_delete_images(self) -> None:
        n = wfm_config.clear_thumb_cache()
        self.status.configure(text=f"{n} cached image(s) deleted.", fg=OK)
        self.reload()

    def _delete_all(self) -> None:
        GoodbyeDialog(
            self, self.app, "Delete ALL user data",
            "This unlinks your warframe.market account, clears the cached "
            "Warframe account data and install path, empties the market "
            "watchlist, deletes the image cache and the web apps' browser "
            "data (cookies, cache), and resets every setting "
            "(floors, caps, display, startup) to its default. The app keeps "
            "working - as if freshly installed.",
            self._do_delete_all)

    def _do_delete_all(self) -> None:
        app = self.app
        # files first (session file goes via the proper unlink below)
        for name, path, _d, _s in wfm_config.user_data_files():
            if name != ".wfm_session.json":
                wfm_config.delete_user_file(path)
        wfm_config.clear_thumb_cache()
        wfm_config.clear_webview_profile()
        wfm_config.set_start_with_windows(False)
        wfm_config.set_watch_warframe(False)   # the watcher's Run entry too
        app.settings.clear()
        app.settings.update(wfm_config.load_settings())   # back to defaults
        app.listing_baseline.clear()
        # Persistent views hold the deleted data in memory - and would write
        # it straight back (an arcane click re-saves the whole override map).
        # Drop them so they rebuild from the now-clean disk state.
        app.drop_persistent_views()
        if app.session is not None:
            app.unlink_account()          # presence off, token file deleted
        else:
            app.navigate("home")
        messagebox.showinfo("Data deleted",
                            "All user data has been deleted.", parent=app)


class WarframeDataPage(tk.Frame):
    """Settings > Data > Warframe: the local game account (migrated from the
    old Profile app's top half - read from the game's own EE.log, strictly
    read-only, see core/wf_local.py).

    Nothing re-reads game data automatically: one read when the page opens
    captures the data file's mtime, which is cached (core/wf_local prefs) so
    a future Update button can compare cached vs current timestamps before
    deciding to read again."""

    def __init__(self, parent: tk.Widget, app: App) -> None:
        super().__init__(parent, bg=BG)
        self.app = app
        self.prefs = wf_local.load_prefs()
        f = app.fonts

        wrap = tk.Frame(self, bg=BG)
        wrap.pack(fill="both", expand=True)

        # ---- the local game account ----------------------------------------
        game = tk.Frame(wrap, bg=PANEL, padx=18, pady=14)
        game.pack(fill="x")
        tk.Label(game, text="⬢  Warframe account", bg=PANEL, fg=TEXT,
                 font=f["h2"]).grid(row=0, column=0, columnspan=3, sticky="w")
        tk.Label(game, text="Read from the game's own data "
                            "(%LOCALAPPDATA%\\Warframe\\EE.log) - opened "
                            "strictly read-only, exactly like AlecaFrame.",
                 bg=PANEL, fg=MUTED, font=f["small"]).grid(
                     row=1, column=0, columnspan=3, sticky="w", pady=(0, 10))

        def grow(r: int, label: str) -> tk.Label:
            tk.Label(game, text=label, bg=PANEL, fg=MUTED, width=16,
                     anchor="w", font=f["small"]).grid(row=r, column=0,
                                                       sticky="w", pady=2)
            v = tk.Label(game, text="…", bg=PANEL, fg=TEXT, anchor="w",
                         font=f["body"])
            v.grid(row=r, column=1, columnspan=2, sticky="w", pady=2)
            return v

        self.g_user = grow(2, "Username")
        self.g_access = grow(3, "Data access")
        self.g_updated = grow(4, "Data updated")

        # install location: entry + auto-detect + browse
        tk.Label(game, text="Install location", bg=PANEL, fg=MUTED, width=16,
                 anchor="w", font=f["small"]).grid(row=5, column=0,
                                                   sticky="w", pady=(10, 2))
        self.install_var = tk.StringVar(value=self.prefs.get("install_dir") or "")
        ie = tk.Entry(game, textvariable=self.install_var, width=58,
                      font=f["body"], **field_style(False))
        ie.grid(row=5, column=1, sticky="w", ipady=4, pady=(10, 2))
        ie.bind("<Return>", lambda _e: self._commit_install())
        ie.bind("<FocusOut>", lambda _e: self._commit_install())
        btns = tk.Frame(game, bg=PANEL)
        btns.grid(row=5, column=2, sticky="w", padx=(8, 0), pady=(10, 2))
        tk.Button(btns, text="Auto-detect", command=self._auto_detect,
                  **secondary_style(f["small"])).pack(side="left",
                                                      padx=(0, SP_MD))
        tk.Button(btns, text="Browse…", command=self._browse,
                  bg=PANEL_HI, fg=TEXT, relief="flat", bd=0, padx=12, pady=4,
                  cursor="hand2", font=f["small"],
                  activebackground=PANEL).pack(side="left")
        self.install_note = tk.Label(game, text="", bg=PANEL, fg=MUTED,
                                     font=f["small"])
        self.install_note.grid(row=6, column=1, columnspan=2, sticky="w")

        self._load_game_data()

    # ---- local game data (read-only) --------------------------------------

    def _load_game_data(self) -> None:
        """One read-only read of EE.log, off the UI thread. Its mtime is
        cached for the future Update button's staleness check."""
        def work() -> None:
            try:
                info = wf_local.read_account()
            except wf_local.WFLocalError as exc:
                msg = str(exc)
                self.after(0, lambda: self._game_failed(msg))
                return
            def fin() -> None:
                # prefs I/O on the Tk thread: _commit_install writes the
                # same file from there - this serializes the two writers
                wf_local.cache_log_mtime(self.prefs, info.log_mtime)
                self._game_loaded(info)
            self.after(0, fin)

        threading.Thread(target=work, daemon=True).start()
        if not self.install_var.get().strip():
            self._auto_detect(quiet=True)
        else:
            self._check_install()

    def _game_loaded(self, info: wf_local.AccountInfo) -> None:
        if not self.winfo_exists():
            return
        client = f"  ·  {info.client}" if info.client else ""
        self.g_user.configure(text=f"{info.username}{client}", fg=OK)
        self.g_access.configure(
            text="read-only access OK  ·  EE.log found", fg=OK)
        import datetime as _dt
        stamp = _dt.datetime.fromtimestamp(info.log_mtime)
        self.g_updated.configure(
            text=f"{stamp:%Y-%m-%d %H:%M:%S}  (timestamp cached for manual "
                 "update checks)", fg=TEXT)

    def _game_failed(self, msg: str) -> None:
        if not self.winfo_exists():
            return
        self.g_user.configure(text="—", fg=MUTED)
        self.g_access.configure(text=msg, fg=WARN)
        self.g_updated.configure(text="—", fg=MUTED)

    # ---- install location --------------------------------------------------

    def _auto_detect(self, quiet: bool = False) -> None:
        found = wf_local.detect_install()
        if found is not None:
            self.install_var.set(str(found))
            self._commit_install()
        elif not quiet:
            self.install_note.configure(
                text="Couldn't auto-detect - use Browse…", fg=WARN)

    def _browse(self) -> None:
        chosen = filedialog.askdirectory(
            parent=self, title="Select your Warframe install folder",
            initialdir=self.install_var.get() or "C:\\")
        if chosen:
            self.install_var.set(chosen)
            self._commit_install()

    def _commit_install(self) -> None:
        path = self.install_var.get().strip()
        self.prefs["install_dir"] = path or None
        wf_local.save_prefs(self.prefs)
        self._check_install()

    def _check_install(self) -> None:
        path = self.install_var.get().strip()
        if not path:
            self.install_note.configure(text="Not set.", fg=MUTED)
        elif Path(path).is_dir():
            self.install_note.configure(text="Folder found ✔  (saved)", fg=OK)
        else:
            self.install_note.configure(text="Folder does not exist.", fg=ERR)


class MarketDataPage(tk.Frame):
    """Settings > Data > Market: the warframe.market profile (migrated from
    the old Profile app's bottom half - account, session validity, expanded
    online/connection status, active order counts, Unlink) plus the embedded
    API status check."""

    def __init__(self, parent: tk.Widget, app: App) -> None:
        super().__init__(parent, bg=BG)
        self.app = app
        f = app.fonts

        wrap = tk.Frame(self, bg=BG)
        wrap.pack(fill="both", expand=True)

        # ---- the warframe.market profile ------------------------------------
        wfm = tk.Frame(wrap, bg=PANEL, padx=18, pady=14)
        wfm.pack(fill="x")
        head = tk.Frame(wfm, bg=PANEL)
        head.pack(fill="x")
        tk.Label(head, text="warframe.market profile", bg=PANEL, fg=TEXT,
                 font=f["h2"]).pack(side="left")
        self.wfm_body = tk.Frame(wfm, bg=PANEL)
        self.wfm_body.pack(fill="x", pady=(10, 0))
        self._build_wfm()

        # ---- API status (the old standalone tool, embedded here) -----------
        api = tk.Frame(wrap, bg=PANEL, padx=18, pady=14)
        api.pack(fill="both", expand=True, pady=(14, 0))
        head = tk.Frame(api, bg=PANEL)
        head.pack(fill="x")
        tk.Label(head, text="API status", bg=PANEL, fg=TEXT,
                 font=f["h2"]).pack(side="left")
        self.api_btn = tk.Button(head, text="▶ Run check",
                                 command=self._run_api,
                                 **secondary_style(f["small"]))
        self.api_btn.pack(side="right")
        self.api_state = tk.Label(head, text="idle", bg=PANEL, fg=MUTED,
                                  font=f["small"])
        self.api_state.pack(side="right", padx=(0, 10))
        tk.Label(api, text="Read-only health check of every warframe.market "
                           "endpoint the apps depend on. Run it after a WFM "
                           "update, before trusting any writes.",
                 bg=PANEL, fg=MUTED, font=f["small"]).pack(anchor="w",
                                                           pady=(0, 8))
        self.api_console = tk.Text(api, bg=CONSOLE_BG, fg=CONSOLE_FG,
                                   insertbackground=CONSOLE_FG, relief="flat",
                                   font=f["mono"], wrap="word", height=8,
                                   state="disabled", padx=10, pady=6)
        self.api_console.pack(fill="both", expand=True)
        self.api_console.tag_config("warn", foreground=WARN)
        self.api_console.tag_config("ok", foreground=OK)
        self.api_runner = ToolRunner()
        self.bind("<Destroy>", lambda e: self.api_runner.stop()
                  if e.widget is self else None)

    # ---- embedded API status check ------------------------------------------

    def _api_write(self, text: str, tag: str = "") -> None:
        if not self.api_console.winfo_exists():
            return
        self.api_console.configure(state="normal")
        self.api_console.insert("end", text, tag)
        self.api_console.see("end")
        self.api_console.configure(state="disabled")

    def _run_api(self) -> None:
        if self.api_runner.running:
            return
        tool = next((t for t in TOOLS if t.id == "api_check"), None)
        if tool is None or not tool.exists:
            self._api_write("api_check tool not found.\n", "warn")
            return
        self.api_console.configure(state="normal")
        self.api_console.delete("1.0", "end")
        self.api_console.configure(state="disabled")
        env = self.app.gateway.child_env(os.environ.copy())
        try:
            self.api_runner.start([sys.executable, "-u", str(tool.script)],
                                  cwd=str(tool.workdir), env=env)
        except Exception as exc:                             # noqa: BLE001
            self._api_write(f"failed to launch: {exc}\n", "warn")
            return
        self.api_btn.configure(state="disabled")
        self.api_state.configure(text="running…", fg=OK)
        self.after(80, self._drain_api)

    def _drain_api(self) -> None:
        if not self.winfo_exists():
            return
        try:
            while True:
                line = self.api_runner.q.get_nowait()
                if line is None:
                    code = (self.api_runner.proc.returncode
                            if self.api_runner.proc else "?")
                    ok = code == 0
                    self._api_write(f"— exited ({code}) —\n",
                                    "ok" if ok else "warn")
                    self.api_btn.configure(state="normal")
                    self.api_state.configure(
                        text="all checks passed ✔" if ok else f"FAILED ({code})",
                        fg=OK if ok else ERR)
                    return
                low = line.lower()
                tag = ("warn" if ("fail" in low or "error" in low) else
                       "ok" if low.startswith("ok") else "")
                self._api_write(line, tag)
        except queue.Empty:
            pass
        # sentinel-driven, not liveness-driven (see RunnerView._drain)
        self.after(80, self._drain_api)

    # ---- warframe.market profile -------------------------------------------

    def _build_wfm(self) -> None:
        for child in self.wfm_body.winfo_children():
            child.destroy()
        f = self.app.fonts
        app = self.app

        if app.session is None:
            tk.Label(self.wfm_body,
                     text="No warframe.market account linked - use "
                          "Link account in the header.",
                     bg=PANEL, fg=WARN, font=f["small"]).pack(anchor="w")
            return

        def wrow(r: int, label: str) -> tk.Label:
            tk.Label(self.wfm_body, text=label, bg=PANEL, fg=MUTED, width=16,
                     anchor="w", font=f["small"]).grid(row=r, column=0,
                                                       sticky="w", pady=2)
            v = tk.Label(self.wfm_body, text="…", bg=PANEL, fg=TEXT,
                         anchor="w", font=f["body"])
            v.grid(row=r, column=1, sticky="w", pady=2)
            return v

        self.w_acct = wrow(0, "Account")
        self.w_session = wrow(1, "Session")
        self.w_status = wrow(2, "Status")
        self.w_orders = wrow(3, "Active orders")

        self.w_acct.configure(
            text=f"{app.session.username}  ({app.session.platform})")
        self.update_session()
        self.update_presence()

        rail = tk.Frame(self.wfm_body, bg=PANEL)
        rail.grid(row=4, column=0, columnspan=2, sticky="w", pady=(12, 0))
        tk.Button(rail, text="↻ Refresh counts", command=self._load_orders,
                  bg=PANEL_HI, fg=TEXT, relief="flat", bd=0, padx=12, pady=4,
                  cursor="hand2", font=f["small"],
                  activebackground=PANEL).pack(side="left", padx=(0, 8))
        tk.Button(rail, text="Unlink account", command=app.unlink_account,
                  bg=WFM_RED_DIM, fg=TEXT, relief="flat", bd=0, padx=12,
                  pady=4, cursor="hand2", font=f["small"],
                  activebackground=PANEL).pack(side="left")

        self._load_orders()

    def update_session(self) -> None:
        """Session-validity row (called live when background verify lands)."""
        if not hasattr(self, "w_session") or not self.w_session.winfo_exists():
            return
        text, color = {"cached": ("verifying…", MUTED), "ok": ("valid", OK),
                       "expired": ("EXPIRED - re-link", ERR),
                       "none": ("none", MUTED)}[self.app.session_state]
        self.w_session.configure(text=text, fg=color)

    def update_presence(self) -> None:
        """Expanded online/connection status (called live on changes)."""
        if not hasattr(self, "w_status") or not self.w_status.winfo_exists():
            return
        p = self.app.presence
        names = {"offline": "Offline", "online": "Online",
                 "ingame": "In-game"}
        conn = "connected to warframe.market" if p.connected else \
               "not connected (socket closed)"
        color = {"offline": MUTED, "online": OK,
                 "ingame": WFM_TEAL}[p.want if p.want in names else "offline"]
        self.w_status.configure(text=f"{names.get(p.want, '?')}  ·  {conn}",
                                fg=color)

    def _load_orders(self) -> None:
        market = self.app.market
        if market is None or not hasattr(self, "w_orders"):
            return
        self.w_orders.configure(text="loading…", fg=MUTED)

        def work() -> None:
            try:
                orders = market.my_listings()
            except wfm_market.MarketError as exc:
                msg = str(exc)
                self.after(0, lambda: self.w_orders.winfo_exists() and
                           self.w_orders.configure(text=msg, fg=ERR))
                return
            ns, nb = len(orders["sell"]), len(orders["buy"])
            def fin() -> None:
                if self.w_orders.winfo_exists():
                    # contracts aren't counted yet (Contracts tab is still a
                    # placeholder) - don't fake a number
                    self.w_orders.configure(
                        text=f"{ns} WTS  ·  {nb} WTB", fg=TEXT)
            self.after(0, fin)

        threading.Thread(target=work, daemon=True).start()


class RunnerView(tk.Frame):
    def __init__(self, parent: tk.Widget, app: App, tool: Tool) -> None:
        super().__init__(parent, bg=BG)
        self.app = app
        self.tool = tool
        self.runner = ToolRunner()
        self.flag_vars: dict[str, tk.BooleanVar] = {}
        self.arg_vars: dict[str, tk.StringVar] = {}

        # -- top bar -------------------------------------------------------
        bar = tk.Frame(self, bg=BG)
        bar.pack(fill="x", padx=SP_SCREEN, pady=(18, 4))
        tk.Label(bar, text=wfm_theme.glyph(tool.icon, fluent=True),
                 bg=BG, fg=ACCENT,
                 font=app.fonts["icon"]).pack(side="left", padx=(0, 10))
        tk.Label(bar, text=tool.name, bg=BG, fg=TEXT,
                 font=app.fonts["h1"]).pack(side="left")
        # Stop the subprocess if the user navigates away via the sidebar.
        self.bind("<Destroy>", lambda e: self.runner.stop()
                  if e.widget is self else None)
        if tool.requires_session:
            linked = app.session is not None
            tk.Label(bar,
                     text=(f"as {app.session.username}" if linked
                           else "no account linked"),
                     bg=BG, fg=(OK if linked else ERR),
                     font=app.fonts["small"]).pack(side="right")

        tk.Label(self, text=tool.description, bg=BG, fg=MUTED, justify="left",
                 wraplength=800, font=app.fonts["small"]).pack(
                     anchor="w", padx=SP_SCREEN, pady=(2, 10))

        # -- options -------------------------------------------------------
        opts = tk.Frame(self, bg=PANEL, padx=14, pady=12)
        opts.pack(fill="x", padx=SP_SCREEN)

        if tool.flags:
            row = tk.Frame(opts, bg=PANEL)
            row.pack(fill="x", anchor="w")
            for fl in tool.flags:
                var = tk.BooleanVar(value=fl.default)
                self.flag_vars[fl.flag] = var
                tk.Checkbutton(
                    row, text=fl.label, variable=var, bg=PANEL, fg=TEXT,
                    selectcolor=CONSOLE_BG, activebackground=PANEL,
                    activeforeground=TEXT, font=app.fonts["small"],
                    highlightthickness=0, bd=0).pack(side="left", padx=(0, 18))

        for a in tool.args:
            row = tk.Frame(opts, bg=PANEL)
            row.pack(fill="x", anchor="w", pady=(8, 0))
            tk.Label(row, text=a.label, bg=PANEL, fg=MUTED, width=20,
                     anchor="w", font=app.fonts["small"]).pack(side="left")
            var = tk.StringVar(value=a.default)
            self.arg_vars[a.key] = var
            tk.Entry(row, textvariable=var, width=40,
                     font=app.fonts["small"], **field_style(False)).pack(
                         side="left", ipady=3, padx=(0, 8))
            if a.placeholder:
                tk.Label(row, text=a.placeholder, bg=PANEL, fg=MUTED,
                         font=app.fonts["small"]).pack(side="left")

        # -- controls ------------------------------------------------------
        ctrl = tk.Frame(self, bg=BG)
        ctrl.pack(fill="x", padx=SP_SCREEN, pady=10)
        self.run_btn = tk.Button(ctrl, text="▶ Run", command=self._run,
                                 **secondary_style(app.fonts["small"],
                                                   wide=True))
        self.run_btn.pack(side="left")
        self.stop_btn = tk.Button(ctrl, text="■ Stop", command=self._stop,
                                  bg=PANEL, fg=TEXT, relief="flat", bd=0,
                                  padx=18, pady=6, cursor="hand2",
                                  state="disabled", font=app.fonts["small"],
                                  activebackground=PANEL_HI)
        self.stop_btn.pack(side="left", padx=8)
        tk.Button(ctrl, text="Clear", command=self._clear_console, bg=PANEL,
                  fg=MUTED, relief="flat", bd=0, padx=14, pady=6,
                  cursor="hand2", font=app.fonts["small"],
                  activebackground=PANEL_HI).pack(side="left")
        self.status = tk.Label(ctrl, text="idle", bg=BG, fg=MUTED,
                               font=app.fonts["small"])
        self.status.pack(side="right")

        # -- console -------------------------------------------------------
        # a 1px gold rule caps the console pane - telemetry under glass
        tk.Frame(self, bg=GOLD_DIM, height=1).pack(fill="x", padx=SP_SCREEN)
        cwrap = tk.Frame(self, bg=CONSOLE_BG)
        cwrap.pack(fill="both", expand=True, padx=SP_SCREEN, pady=(0, 18))
        self.console = tk.Text(
            cwrap, bg=CONSOLE_BG, fg=CONSOLE_FG, insertbackground=GOLD_HI,
            selectbackground=GOLD_DIM, selectforeground=INK,
            relief="flat", font=app.fonts["mono"], wrap="word",
            state="disabled", padx=10, pady=8)
        cbar = ttk.Scrollbar(cwrap, orient="vertical",
                             command=self.console.yview,
                             style="Toolbox.Vertical.TScrollbar")
        self.console.configure(yscrollcommand=cbar.set)
        cbar.pack(side="right", fill="y")
        self.console.pack(side="left", fill="both", expand=True)
        self.console.tag_config("meta", foreground=ACCENT)
        self.console.tag_config("warn", foreground=WARN)
        self.console.tag_config("ok", foreground=OK)

        self._write(f"$ {tool.script.name}  (ready)\n", "meta")
        if tool.requires_session and app.session is None:
            self._write("⚠ This tool needs a linked account. Go back and use "
                        "'Link account' first.\n", "warn")

    # -- command assembly --------------------------------------------------

    def _build_cmd(self) -> list[str]:
        cmd = [sys.executable, "-u", str(self.tool.script)]
        for fl, var in self.flag_vars.items():
            if var.get():
                cmd.append(fl)
        for a in self.tool.args:
            val = self.arg_vars[a.key].get().strip()
            if not val:
                continue
            if a.flag:
                cmd += [a.flag, val]
            else:
                cmd.append(val)
        return cmd

    # -- actions -----------------------------------------------------------

    def _run(self) -> None:
        if self.runner.running:
            return
        if self.tool.requires_session and self.app.session is None:
            self._write("✖ Not running: no account linked. Use 'Link account' "
                        "on the home page.\n", "warn")
            return

        live = self.flag_vars.get("--live")
        if live and live.get():
            self._write("⚠ LIVE mode: this will write real price changes.\n",
                        "warn")

        # Every tool talks to WFM only through the host's gateway. The JWT
        # itself never enters the tool's environment.
        env = self.app.gateway.child_env(os.environ.copy())
        cmd = self._build_cmd()
        self._write("$ " + " ".join(self._short(c) for c in cmd) + "\n", "meta")
        who = (f"session: {self.app.session.username}" if self.app.session
               else "no session (public reads only)")
        self._write(f"  (via host gateway {self.app.gateway.url} - {who})\n",
                    "meta")
        try:
            self.runner.start(cmd, cwd=str(self.tool.workdir), env=env)
        except Exception as exc:  # noqa: BLE001
            self._write(f"failed to launch: {exc}\n", "warn")
            return
        self.run_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.status.configure(text="running…", fg=OK)
        self.after(80, self._drain)

    def _stop(self) -> None:
        self.runner.stop()
        self._write("■ stop requested\n", "warn")

    def _drain(self) -> None:
        if not self.winfo_exists():
            return                  # view navigated away; stop the timer
        try:
            while True:
                line = self.runner.q.get_nowait()
                if line is None:
                    self._finished()
                    return
                self._write(line, self._tag_for(line))
        except queue.Empty:
            pass
        # Reschedule on the SENTINEL, never on process liveness: a tick
        # that lands after the child exits but before the pump flushes its
        # tail would otherwise stop draining and strand the page (output
        # lost, Run stuck disabled).
        self.after(80, self._drain)

    def _finished(self) -> None:
        code = self.runner.proc.returncode if self.runner.proc else "?"
        self._write(f"— process exited (code {code}) —\n",
                    "ok" if code == 0 else "warn")
        self.run_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self.status.configure(text=f"exited ({code})",
                              fg=OK if code == 0 else WARN)

    # -- console helpers ---------------------------------------------------

    @staticmethod
    def _short(part: str) -> str:
        return f'"{part}"' if " " in part else part

    @staticmethod
    def _tag_for(line: str) -> str:
        low = line.lower()
        if ("error" in low or "failed" in low or "stranded" in low
                or "warning" in low or "dry run" in low):
            return "warn"
        if low.startswith("ok") or " ok " in low:
            return "ok"
        return ""

    def _write(self, text: str, tag: str = "") -> None:
        self.console.configure(state="normal")
        self.console.insert("end", text, tag)
        self.console.see("end")
        self.console.configure(state="disabled")

    def _clear_console(self) -> None:
        self.console.configure(state="normal")
        self.console.delete("1.0", "end")
        self.console.configure(state="disabled")


class ListingsView(tk.Frame):
    """The tabbed My Listings screen.

    The header (Back / title / Refresh) stays put across tabs. WTS and WTB
    are full ListingsTab instances, each with its own controls (default
    floor/cap, search, sort, show filter, bulk visibility, count, Reprice
    all); Contracts is a placeholder. Refresh reloads every tab's data in one
    sweep without switching away from the current tab."""

    TAB_NAMES = ("WTS", "WTB", "Contracts")
    TAB_ACCENTS = {"WTS": WFM_BADGE_FG, "WTB": WFM_BUY_FG,
                   "Contracts": ACCENT}

    def __init__(self, parent: tk.Widget, app: App) -> None:
        super().__init__(parent, bg=BG)
        self.app = app
        self._busy = False
        self.prefs = wfm_market.load_prefs()   # shared by both listing tabs

        # -- tab-scoped header (Back/title/account live in the app shell) ---
        bar = tk.Frame(self, bg=BG)
        bar.pack(fill="x", padx=SP_SCREEN, pady=(16, 4))
        tk.Label(bar, text="My Warframe.Market Listings",
                 bg=BG, fg=TEXT, font=app.fonts["h1"]).pack(side="left")
        self.refresh_btn = tk.Button(
            bar, text="↻ Refresh", command=self.refresh, bg=PANEL, fg=TEXT,
            relief="flat", bd=0, padx=14, pady=5, cursor="hand2",
            font=app.fonts["small"], activebackground=PANEL_HI)
        self.refresh_btn.pack(side="right")
        # the ledger line: total plat listed across your sell orders, set in
        # platinum silver and underscored with a 1px gold inlay - the
        # treasury's tithe counter
        led = tk.Frame(bar, bg=BG)
        led.pack(side="right", padx=(0, 16))
        lrow = tk.Frame(led, bg=BG)
        lrow.pack()
        self.ledger_lbl = tk.Label(lrow, text="", bg=BG, fg=PLAT,
                                   font=app.fonts["h2"])
        self.ledger_lbl.pack(side="left")
        self._ledger_gem = tk.Label(lrow, image=plat_icon(BG, 14), bg=BG)
        self.ledger_rule = tk.Frame(led, bg=BG, height=1)
        self.ledger_rule.pack(fill="x", pady=(1, 0))
        _wfm_tooltip(led, "Total platinum listed across your sell orders")

        # -- tab bar ----------------------------------------------------------
        self.tab_btns, self.tab_bars = {}, {}
        tabbar = build_tabbar(self, self.TAB_NAMES, self.TAB_ACCENTS,
                              self.select_tab, self.tab_btns, self.tab_bars,
                              app.fonts)
        tabbar.pack(fill="x", padx=SP_SCREEN, pady=(SP_LG, 0))

        # dimmed backdrop so the tabs read as a tabbed window
        container = tk.Frame(self, bg=TAB_BG)
        container.pack(fill="both", expand=True, padx=SP_SCREEN, pady=(0, SP_XL))
        # Set BEFORE the tabs are built - a tab may ask tab_live() from its
        # own constructor. Whether this whole view is the one on screen is
        # tracked explicitly rather than read from winfo_ismapped(), because
        # pack() only queues geometry at idle: answering "am I visible?" from
        # Tk would need a synchronous layout flush on every navigation, and
        # that flush was a 3.6s regression. See _tab_live().
        self.current: str | None = None
        self._shown = False
        self.tabs: dict[str, tk.Frame] = {
            "WTS": ListingsTab(container, app, "sell", self.prefs),
            "WTB": ListingsTab(container, app, "buy", self.prefs),
            "Contracts": self._contracts_tab(container),
        }
        for _t in self.tabs.values():
            _t.owner = self          # so a tab can ask whether it is on screen
        self.select_tab("WTS")
        self.after(50, self.refresh)

    def _tab_live(self, tab: tk.Frame) -> bool:
        """True when rendering into `tab` would actually be seen: it is the
        selected tab AND this view is the one the shell is showing."""
        return self._shown and self.current is not None \
            and self.tabs.get(self.current) is tab

    def _contracts_tab(self, parent: tk.Widget) -> tk.Frame:
        f = tk.Frame(parent, bg=TAB_BG)
        box = tk.Frame(f, bg=PANEL, padx=48, pady=32)
        box.place(relx=0.5, rely=0.38, anchor="center")
        tk.Label(box, text="Contracts", bg=PANEL, fg=TEXT,
                 font=self.app.fonts["h2"]).pack()
        tk.Label(box, text="Feature in development — coming soon.",
                 bg=PANEL, fg=MUTED, font=self.app.fonts["small"]).pack(
                     pady=(8, 0))
        return f

    def select_tab(self, tab_name: str) -> None:
        if self.current == tab_name:
            return
        for frame in self.tabs.values():
            frame.pack_forget()
        paint_tabbar(self.tab_btns, self.tab_bars, self.TAB_ACCENTS, tab_name)
        tab = self.tabs[tab_name]
        tab.pack(fill="both", expand=True)
        self.current = tab_name
        # The wheel should scroll whichever listings tab is showing - but
        # only claim the app-wide binding when this view is actually on
        # screen: __init__ calls select_tab before the shell has shown us,
        # and claiming from a hidden view would steal the wheel from
        # whatever the user is looking at.
        if isinstance(tab, ListingsTab) and self._shown:
            tab.scroll.claim_wheel()
        # a refresh feeds all three tabs, but only the visible one renders
        # (see _apply_view) - so the tab we just revealed may owe a render
        self._flush_dirty()

    def _flush_dirty(self) -> None:
        """Render any tab that deferred while it was off screen."""
        for tab in self.tabs.values():
            if getattr(tab, "_dirty", False) and self._tab_live(tab):
                tab._dirty = False
                tab._apply_view()

    def on_show(self) -> None:
        """Host lifecycle hook: re-claim the app-wide mousewheel binding for
        the active tab - bind_all is last-writer-wins, and another view may
        have taken it since this persistent view was last shown."""
        self._shown = True
        tab = self.tabs.get(self.current) if self.current else None
        if isinstance(tab, ListingsTab) and tab.canvas.winfo_exists():
            tab.scroll.claim_wheel()
        # a refresh feeds every tab, so flush whichever one is now live
        self._flush_dirty()

    def on_hide(self) -> None:
        """Host lifecycle hook: stop every tab, not just the visible one - a
        background fetch feeds all three, and any of them may have a glide
        or a suggestion list still up."""
        self._shown = False
        for tab in self.tabs.values():
            fn = getattr(tab, "on_hide", None)
            if fn:
                fn()

    # -- data ----------------------------------------------------------------

    def refresh(self) -> None:
        """One fetch feeds every tab; the current tab selection is kept."""
        if self._busy:
            return
        wts, wtb = self.tabs["WTS"], self.tabs["WTB"]
        if self.app.market is None:
            for t in (wts, wtb):
                t.status.configure(text="No account linked.", fg=WARN)
            return
        self._busy = True
        self.refresh_btn.configure(state="disabled")
        market = self.app.market
        user = self.app.session.username
        for t in (wts, wtb):
            t._set_busy(True, "Loading your listings…")

        def work() -> None:
            try:
                orders = market.my_listings()
            except wfm_market.MarketError as exc:
                msg = str(exc)
                def fail() -> None:
                    wts.set_failed(msg)
                    wtb.set_failed(msg)
                    self._refresh_done()
                self.after(0, fail)
                return
            self.after(0, lambda: wts.set_listings(orders["sell"]))
            self.after(0, lambda: wtb.set_listings(orders["buy"]))
            # Market bests, one item at a time (spaced by the client).
            for tab, side, best_of in ((wts, "sell", market.lowest_online),
                                       (wtb, "buy", market.highest_online)):
                for l in orders[side]:
                    try:
                        best, n = best_of(l.slug, exclude=user)
                    except wfm_market.MarketError:
                        best, n = None, 0
                    self.after(0, lambda t=tab, l=l, b=best, n=n:
                               t._set_market_low(l.order_id, b, n))
            def done() -> None:
                wts._set_busy(False, f"{len(orders['sell'])} listings · "
                                     "market data updated")
                wtb._set_busy(False, f"{len(orders['buy'])} listings · "
                                     "market data updated")
                self._set_ledger(
                    wfm_listings_vm.ledger_total(orders["sell"]))
                self._refresh_done()
            self.after(0, done)

        threading.Thread(target=work, daemon=True).start()

    def _refresh_done(self) -> None:
        self._busy = False
        if self.refresh_btn.winfo_exists():
            self.refresh_btn.configure(state="normal")

    def _set_ledger(self, total: int) -> None:
        """Paint the header's tithe counter (gem + gold rule appear with the
        first real figure)."""
        if not self.ledger_lbl.winfo_exists():
            return
        self.ledger_lbl.configure(text=f"{total:,}")
        self._ledger_gem.pack(side="left", padx=(4, 0))
        self.ledger_rule.configure(bg=GOLD_DIM)


class ListingsTab(tk.Frame):
    """One side of the order book (WTS = your sell orders, WTB = your buy
    orders) rendered as warframe.market-style cards, with its own controls:
    default floor/cap offset, search, sort, show filter, bulk visibility
    toggles, listing count, and a master Reprice-all.

    Floors (sell) and caps (buy) are absolute platinum. By default they
    derive from an item's reference price (posted price when the session
    started, or the last price set by hand in Edit) plus this tab's global
    +/- offset: floor/cap = reference + offset. A value typed into a card's
    field overrides it per item (persisted); clearing returns to auto.

    Reprice on WTS matches the lowest online seller - never undercuts, never
    below the floor. Reprice on WTB matches the highest online buyer - never
    overbids, never above the cap. Either way it's one write, which also
    refreshes the order to the top of its band. Nothing loops."""

    # Sort keys live in core.listings_vm; the dropdown is built from this
    # dict's key order, so adding a sort there adds it to the UI.
    SORTS = wfm_listings_vm.SORTS

    def __init__(self, parent: tk.Widget, app: App, side: str,
                 prefs: dict) -> None:
        super().__init__(parent, bg=TAB_BG)
        self.app = app
        self.owner: "ListingsView | None" = None   # set by ListingsView
        self.side = side                        # "sell" or "buy"
        self.prefs = prefs                      # shared dict, saved whole
        self.cards: dict[str, dict] = {}        # order_id -> widgets/vars
        self.listings: list[wfm_market.Listing] = []   # full set, unfiltered
        self._display_order: list[str] = []            # order_ids as rendered
        self._thumbs: dict[str, tk.PhotoImage] = {}    # slug -> icon
        self._busy = False
        self._desc = False

        # Everything that differs between WTS and WTB except colour lives in
        # core.listings_vm.SIDES; only the two palette picks stay here.
        selling = side == "sell"
        spec = wfm_listings_vm.spec(side)
        self.OKEY = spec.offset_key
        self.PKEY = spec.override_key
        self.LIMIT = spec.limit_word
        self.BEST = spec.best_word
        self.done_verb = spec.done_verb
        self.LIMIT_TITLE = spec.limit_title
        self.LIMIT_SHORT = spec.limit_short
        self.badge_text = spec.badge_text
        self.badge_bg = WFM_BADGE_BG if selling else WFM_BUY_BG
        self.badge_fg = WFM_BADGE_FG if selling else WFM_BUY_FG

        # Floor/cap rules live in core.floors - one object owning the baseline,
        # the per-item overrides and the tab offset, because they are a single
        # invariant (see that module's docstring).
        self.limits = wfm_floors.Limits(app.listing_baseline, prefs,
                                        self.OKEY, self.PKEY)

        sub = tk.Frame(self, bg=TAB_BG)
        sub.pack(fill="x", padx=SP_SCREEN, pady=(10, 0))
        row = tk.Frame(sub, bg=TAB_BG)
        row.pack(fill="x", anchor="w")
        tk.Label(row, text=f"{self.LIMIT_TITLE}: set price ", bg=TAB_BG,
                 fg=MUTED, font=app.fonts["small"]).pack(side="left")
        self.offset_var = tk.StringVar(value=f"{self.limits.offset:+d}")
        off = tk.Entry(row, textvariable=self.offset_var, width=4,
                       justify="center", font=app.fonts["body"],
                       **field_style(True))
        off.pack(side="left", ipady=CTRL_IPADY - 1)
        off.bind("<Return>", lambda _e: self._commit_offset())
        off.bind("<FocusOut>", lambda _e: self._commit_offset())
        blurb = ("plat.  Reprice matches the lowest online seller - never "
                 "undercuts, never below an item's minimum." if selling else
                 "plat.  Reprice matches the highest online buyer - never "
                 "overbids, never above an item's maximum.")
        tk.Label(row, text=" " + blurb, bg=TAB_BG, fg=MUTED,
                 font=app.fonts["small"]).pack(side="left")
        # money action -> the gold primary button (style guide: gold is
        # spent on money actions and almost nowhere else)
        self.reprice_all_btn = tk.Button(
            row, text="⟳ Reprice all", command=self._reprice_all, bg=ACCENT,
            fg=INK, relief="flat", bd=0, padx=14, pady=4, cursor="hand2",
            font=app.fonts["small"], activebackground=GOLD_HI)
        self.reprice_all_btn.pack(side="right")

        # -- search / sort / visibility controls ---------------------------
        # style guide: dropdowns show a ▾ (arrow_dropdown). A bare
        # OptionMenu with indicatoron=False gives no hint that it opens.
        def dropdown(parent: tk.Widget, var: tk.StringVar,
                     values: tuple[str, ...], on_change) -> tk.Menubutton:
            return arrow_dropdown(parent, var, values, on_change,
                                  app.fonts["body"])

        ctrls = tk.Frame(sub, bg=TAB_BG)
        ctrls.pack(fill="x", anchor="w", pady=(6, 0))
        tk.Label(ctrls, text="Search", bg=TAB_BG, fg=MUTED,
                 font=app.fonts["small"]).pack(side="left")
        self.search_var = tk.StringVar()
        se = tk.Entry(ctrls, textvariable=self.search_var, width=26,
                      font=app.fonts["body"], **field_style(True))
        # the search bar takes all the width the right-side controls leave
        se.pack(side="left", padx=(6, 26), ipady=CTRL_IPADY,
                fill="x", expand=True)
        se.bind("<KeyRelease>", self._search_typed)
        self.suggest = SuggestBox(self, se, self._suggest_supply,
                                  self._suggest_picked, app.fonts["body"])

        # right-aligned controls; bulk visibility hugs the right edge
        tk.Button(ctrls, text="◌ Hide all",
                  command=lambda: self._bulk_visibility(False), bg=PANEL,
                  fg=WARN, relief="flat", bd=0, padx=10, pady=3,
                  cursor="hand2", font=app.fonts["small"],
                  activebackground=PANEL_HI).pack(side="right")
        tk.Button(ctrls, text="◉ Show all",
                  command=lambda: self._bulk_visibility(True), bg=PANEL,
                  fg=TEXT, relief="flat", bd=0, padx=10, pady=3,
                  cursor="hand2", font=app.fonts["small"],
                  activebackground=PANEL_HI).pack(side="right", padx=(0, 4))
        tk.Label(ctrls, text="Visibility", bg=TAB_BG, fg=MUTED,
                 font=app.fonts["small"]).pack(side="right", padx=(0, 6))

        self.vis_var = tk.StringVar(value="All")
        dropdown(ctrls, self.vis_var, ("All", "Visible", "Hidden"),
                 lambda _v: self._apply_view()).pack(side="right",
                                                     padx=(6, 26))
        tk.Label(ctrls, text="Show", bg=TAB_BG, fg=MUTED,
                 font=app.fonts["small"]).pack(side="right")

        self.order_btn = tk.Button(
            ctrls, text="▲", command=self._flip_order, bg=PANEL, fg=TEXT,
            relief="flat", bd=0, padx=8, pady=3, cursor="hand2",
            font=app.fonts["small"], activebackground=PANEL_HI)
        self.order_btn.pack(side="right", padx=(0, 26))
        self.sort_var = tk.StringVar(value="Name")
        dropdown(ctrls, self.sort_var, tuple(self.SORTS),
                 lambda _v: self._apply_view()).pack(side="right",
                                                     padx=(6, 2))
        tk.Label(ctrls, text="Sort", bg=TAB_BG, fg=MUTED,
                 font=app.fonts["small"]).pack(side="right")

        self.status = tk.Label(sub, text="", bg=TAB_BG, fg=MUTED,
                               font=app.fonts["small"])
        self.status.pack(anchor="w", pady=(4, 8))

        # -- scrollable card area -----------------------------------------
        self.scroll = ScrollArea(self, bg=TAB_BG)
        self.scroll.pack(fill="both", expand=True, padx=20, pady=(0, 16))
        self.canvas, self.body = self.scroll.canvas, self.scroll.body
        # A refresh or a bulk edit can finish while another app is on
        # screen; re-rendering then would destroy and rebuild every card on
        # a hidden canvas, so those paths set _dirty and on_show() flushes.
        self._dirty = False

    # -- scrolling ---------------------------------------------------------

    def on_hide(self) -> None:
        """Stop the scroll animation and hand the app-wide wheel back. This
        view is persistent, so its <Destroy> never fires - navigate()'s
        on_hide() is the only teardown it gets."""
        self.scroll.stop()
        self.scroll.release_wheel()
        self.suggest.hide()

    # -- floors --------------------------------------------------------------

    def _commit_offset(self) -> None:
        """Parse this tab's global +/- offset, persist it, refresh every card
        limit that is still following the default."""
        val = wfm_floors.parse_offset(self.offset_var.get(), self.limits.offset)
        if val is None:                       # not a number - repaint, ignore
            self.offset_var.set(f"{self.limits.offset:+d}")
            return
        if self.limits.set_offset(val):
            wfm_market.save_prefs(self.prefs)
        self.offset_var.set(f"{val:+d}")
        for oid in self.cards:
            self._refresh_floor_field(oid)

    def _floor_for(self, l: wfm_market.Listing) -> int:
        return self.limits.limit(l.slug, l.order_id, l.platinum)

    def _commit_floor(self, order_id: str) -> None:
        """A card's floor/cap field lost focus: absolute plat = per-item
        override; empty (or exactly the derived value) = follow the default."""
        card = self.cards.get(order_id)
        if not card:
            return
        l = card["listing"]
        outcome = self.limits.commit(card["floor_var"].get(), l.slug,
                                     l.order_id, l.platinum)
        if outcome.changed:
            wfm_market.save_prefs(self.prefs)
        self._refresh_floor_field(order_id)

    def _refresh_floor_field(self, order_id: str) -> None:
        card = self.cards.get(order_id)
        if not card or not card["floor_mode"].winfo_exists():
            return
        l = card["listing"]
        override = self.limits.is_overridden(l.slug)
        card["floor_var"].set(str(self._floor_for(l)))
        card["floor_mode"].configure(
            text="set" if override else "auto",
            fg=WFM_PINK if override else WFM_MUTED)

    # -- misc helpers --------------------------------------------------------

    def _set_busy(self, busy: bool, msg: str = "") -> None:
        self._busy = busy
        self.reprice_all_btn.configure(state="disabled" if busy else "normal")
        if msg:
            self.status.configure(text=msg, fg=MUTED)

    def _btn(self, parent: tk.Widget, text: str, command,
             fg: str = WFM_TEAL, edge: str = WFM_TEAL_DIM,
             font_key: str = "small") -> tk.Frame:
        """A WFM-style outlined button: thin coloured border, dark body.
        font_key="icon" renders a lone Segoe Fluent Icons glyph."""
        box = tk.Frame(parent, bg=edge, padx=1, pady=1)
        b = tk.Button(box, text=text, command=command, bg=WFM_CARD, fg=fg,
                      activebackground=WFM_EDGE, activeforeground=fg,
                      relief="flat", bd=0, padx=10, pady=3, cursor="hand2",
                      font=self.app.fonts[font_key])
        b.pack(fill="both", expand=True)
        box.btn = b
        return box

    # -- data entry points (driven by the parent ListingsView) --------------

    def set_failed(self, msg: str) -> None:
        if not self.winfo_exists():
            return
        self._set_busy(False)
        self.status.configure(text=msg, fg=ERR)

    def set_listings(self, listings: list[wfm_market.Listing]) -> None:
        """New full data set from a refresh; re-derive the displayed view."""
        self.listings = listings
        self._apply_view()

    def _apply_view(self, *_a) -> None:
        """Filter (visibility) + sort the full set, then render."""
        if not self.winfo_exists():
            return
        owner = getattr(self, "owner", None)
        if owner is not None and not owner._tab_live(self):
            # A refresh feeds all three tabs and a bulk edit finishes on a
            # worker thread, so this lands on hidden tabs routinely.
            # _render() destroys and rebuilds every card - ~25 widgets each -
            # which off screen is pure cost, and races whatever the visible
            # view is painting. Defer; _flush_dirty() picks it up.
            self._dirty = True
            return
        self._render(wfm_listings_vm.arrange(
            self.listings, self.vis_var.get(), self.sort_var.get(),
            self._desc))
        if self.search_var.get().strip():
            self._search()

    def _flip_order(self) -> None:
        self._desc = not self._desc
        self.order_btn.configure(text="▼" if self._desc else "▲")
        self._apply_view()

    def _search_typed(self, event) -> None:
        # navigation keys are the SuggestBox's business, not a new search
        if event.keysym in SuggestBox._NAV_KEYS:
            return
        self._search()

    def _suggest_supply(self, q: str) -> list[tuple[str, str]]:
        # SuggestBox wants (label, payload); here the name is both
        return [(n, n) for n in
                wfm_listings_vm.suggest((l.name for l in self.listings), q)]

    def _suggest_picked(self, name: str, _payload: str) -> None:
        self.search_var.set(name)        # autocomplete, then jump to it
        self._search()

    def _search(self) -> None:
        """Scroll the list to the first card whose title matches the query
        (prefix first, then substring) and outline it. Clearing the box
        resets the scroll to the top."""
        q = self.search_var.get().strip().lower()
        for card in self.cards.values():
            if card["outer"].winfo_exists():
                card["outer"].configure(bg=WFM_EDGE)
        if not q:
            self.canvas.yview_moveto(0)
            return
        # display order matters: it decides which of several matches wins
        hit = wfm_listings_vm.find_match(
            [(oid, self.cards[oid]["listing"].name.lower())
             for oid in self._display_order if oid in self.cards], q)
        if hit is None:
            return
        card = self.cards[hit]
        card["outer"].configure(bg=ACCENT)      # search hit: gilded border
        self.body.update_idletasks()
        total = max(1, self.body.winfo_height())
        self.canvas.yview_moveto(min(1.0, card["outer"].winfo_y() / total))

    def _render(self, shown: list[wfm_market.Listing]) -> None:
        if not self.winfo_exists():
            return
        for child in self.body.winfo_children():
            child.destroy()
        self.cards.clear()
        self._display_order = [l.order_id for l in shown]
        self.body.columnconfigure(0, weight=1, uniform="lc")
        self.body.columnconfigure(1, weight=1, uniform="lc")
        for i, l in enumerate(shown):
            # pin the session baseline on first sight of this order
            self.limits.reference(l.order_id, l.platinum)
            r, c = divmod(i, 2)
            self._card(l).grid(row=r, column=c, sticky="nsew", padx=6, pady=6)
        self._load_thumbs(shown)

    # -- card ---------------------------------------------------------------

    # Card rhythm IS the app's spacing scale - aliases, not a second scale,
    # so retuning SP_* retunes the cards too. (SP_XL card padding,
    # SP_LG between the card's three sections, SP_MD between lines within
    # a section, SP_SM between adjacent buttons.)
    PAD_CARD = SP_XL
    PAD_SECTION = SP_LG
    PAD_LINE = SP_MD
    PAD_GAP = SP_SM
    ICON = 96              # fixed square icon container (1.5x the original 64)

    def _card(self, l: wfm_market.Listing) -> tk.Frame:
        outer = tk.Frame(self.body, bg=WFM_EDGE, padx=1, pady=1)
        # unified padding: the same PAD_SECTION on all four sides
        f = tk.Frame(outer, bg=WFM_CARD, padx=self.PAD_SECTION,
                     pady=self.PAD_SECTION)
        f.pack(fill="both", expand=True)
        f.columnconfigure(1, weight=1)

        # Fixed 96x96 icon container: every icon occupies the same square
        # regardless of the source image's size (pack_propagate(False) stops
        # the frame collapsing to the image, keeping the aspect box stable).
        # A 1px WFM_EDGE border + darker ICON_BG backdrop give every image a
        # distinct frame.
        icon_frame = tk.Frame(f, bg=WFM_EDGE, padx=1, pady=1)
        icon_frame.grid(row=0, column=0, rowspan=3, sticky="nw",
                        padx=(0, self.PAD_SECTION))
        icon_box = tk.Frame(icon_frame, bg=ICON_BG, width=self.ICON,
                            height=self.ICON)
        icon_box.pack()
        icon_box.pack_propagate(False)
        # placeholder glyph at display size - derived from the probed h1
        # family, never a hardcoded family (style guide: App.fonts roles)
        icon = tk.Label(icon_box, text="◍", bg=ICON_BG, fg=WFM_EDGE,
                        font=(self.app.fonts["h1"].actual("family"), 30))
        icon.pack(fill="both", expand=True)

        # Title row: wts/wtb tag inline, then the name owning the rest of the
        # width from the icon to the card edge.
        title = tk.Frame(f, bg=WFM_CARD)
        title.grid(row=0, column=1, sticky="ew")
        tk.Label(title, text=self.badge_text, bg=self.badge_bg,
                 fg=self.badge_fg, font=self.app.fonts["small"]).pack(
                     side="left", padx=(0, 8))
        name = tk.Label(title, text=l.name, bg=WFM_CARD, fg=WFM_TEAL,
                        font=self.app.fonts["h2"], anchor="w")
        name.pack(side="left")
        wiki_link(title, self.app, l.name, WFM_CARD).pack(
            side="left", padx=(SP_SM, 0))
        # spacer keeps the name block left and the row full-width
        tk.Frame(title, bg=WFM_CARD).pack(side="left", fill="x", expand=True)

        # One info line under it: quantity · price (with the plat gem) · best.
        info = tk.Frame(f, bg=WFM_CARD)
        info.grid(row=1, column=1, sticky="e", pady=(self.PAD_LINE, 0))
        qty = tk.Label(info, text=f"{l.quantity} ❒", bg=WFM_CARD,
                       fg=WFM_MUTED, font=self.app.fonts["body"])
        qty.pack(side="left")
        tk.Label(info, text="  ·  ", bg=WFM_CARD, fg=WFM_EDGE,
                 font=self.app.fonts["body"]).pack(side="left")
        # platinum numerals in the metal's own silver (style guide: PLAT)
        price = tk.Label(info, text=str(l.platinum), bg=WFM_CARD,
                         fg=PLAT, font=self.app.fonts["price"])
        price.pack(side="left")
        tk.Label(info, image=plat_icon(WFM_CARD), bg=WFM_CARD).pack(
            side="left", padx=(3, 3))
        tk.Label(info, text="each", bg=WFM_CARD, fg=WFM_MUTED,
                 font=self.app.fonts["body"]).pack(side="left")
        tk.Label(info, text="  ·  ", bg=WFM_CARD, fg=WFM_EDGE,
                 font=self.app.fonts["body"]).pack(side="left")
        low = tk.Label(info, text=f"{self.BEST} …", bg=WFM_CARD,
                       fg=WFM_MUTED, font=self.app.fonts["small"])
        low.pack(side="left")

        # One row of actions, right-aligned under the info line.
        acts = tk.Frame(f, bg=WFM_CARD)
        acts.grid(row=2, column=1, sticky="se", pady=(self.PAD_SECTION, 0))
        # Sold/Bought confirms money changed hands -> it gets the gold outline
        self._btn(acts, f"✔ {self.done_verb}",
                  lambda oid=l.order_id: self._sold(oid),
                  fg=ACCENT, edge=GOLD_DIM
                  ).pack(side="left", padx=(0, self.PAD_GAP))
        self._btn(acts, "✎ Edit", lambda oid=l.order_id: self._edit(oid)
                  ).pack(side="left", padx=(0, self.PAD_GAP))
        self._btn(acts, "+1", lambda oid=l.order_id: self._adjust_qty(oid, +1)
                  ).pack(side="left", padx=(0, self.PAD_GAP))
        self._btn(acts, "−1", lambda oid=l.order_id: self._adjust_qty(oid, -1)
                  ).pack(side="left", padx=(0, self.PAD_GAP))
        vis = self._btn(acts, "◉ Visible" if l.visible else "◌ Hidden",
                        lambda oid=l.order_id: self._toggle_visible(oid))
        if not l.visible:
            vis.btn.configure(fg=WARN)
        vis.pack(side="left")

        # bottom rail: floor + result + reprice
        bot = tk.Frame(f, bg=WFM_CARD)
        bot.grid(row=3, column=0, columnspan=2, sticky="ew",
                 pady=(self.PAD_SECTION, 0))
        tk.Label(bot, text=self.LIMIT_SHORT, bg=WFM_CARD, fg=WFM_MUTED,
                 font=self.app.fonts["small"]).pack(side="left")
        floor_var = tk.StringVar()
        fe = tk.Entry(bot, textvariable=floor_var, width=5,
                      justify="center", font=self.app.fonts["body"],
                      **field_style(True))
        fe.pack(side="left", padx=(6, 2), ipady=CTRL_IPADY - 1)
        fe.bind("<Return>", lambda _e, oid=l.order_id: self._commit_floor(oid))
        fe.bind("<FocusOut>", lambda _e, oid=l.order_id: self._commit_floor(oid))
        tk.Label(bot, image=plat_icon(WFM_CARD), bg=WFM_CARD).pack(side="left")
        floor_mode = tk.Label(bot, text="auto", bg=WFM_CARD, fg=WFM_MUTED,
                              font=self.app.fonts["small"])
        floor_mode.pack(side="left", padx=(6, 0))
        # trash sits at the card's far right, just right of Reprice
        self._btn(bot, "\uE74D", lambda oid=l.order_id: self._delete(oid),
                  fg=WFM_RED, edge=WFM_RED_DIM,
                  font_key="icon").pack(side="right")     # Fluent: Delete
        # money action -> gold primary
        rp = tk.Button(bot, text="⟳ Reprice", bg=ACCENT, fg=INK,
                       relief="flat", bd=0, padx=12, pady=3, cursor="hand2",
                       font=self.app.fonts["small"],
                       activebackground=GOLD_HI,
                       command=lambda oid=l.order_id: self._reprice_one(oid))
        rp.pack(side="right", padx=(0, self.PAD_GAP))
        result = tk.Label(bot, text="", bg=WFM_CARD, fg=WFM_MUTED, anchor="w",
                          font=self.app.fonts["small"])
        result.pack(side="left", fill="x", expand=True, padx=(12, 8))

        self.cards[l.order_id] = {
            "listing": l, "outer": outer, "icon": icon, "qty": qty,
            "price": price, "low": low, "floor_var": floor_var,
            "floor_mode": floor_mode, "result": result, "vis": vis,
        }
        self._refresh_floor_field(l.order_id)
        if l.slug in self._thumbs:
            icon.configure(image=self._thumbs[l.slug], text="")
        if l.market_low is not None or l.online_count:
            self._set_market_low(l.order_id, l.market_low, l.online_count)
        return outer

    # -- item thumbnails ------------------------------------------------------

    def _load_thumbs(self, listings: list[wfm_market.Listing]) -> None:
        """Fetch item icons in the background, disk-cached across sessions."""
        market = self.app.market
        todo = [(l.slug, l.thumb) for l in listings
                if l.slug not in self._thumbs and l.thumb]
        if not todo or market is None:
            return
        cache_dir = Path(__file__).resolve().parent / ".cache" / "thumbs"

        def work() -> None:
            # Per-item guards: one unreadable/unwritable file (locked by AV,
            # disk full, half-written png) must not cancel the sweep and
            # leave every later listing showing a placeholder.
            try:
                cache_dir.mkdir(parents=True, exist_ok=True)
            except OSError:
                pass                    # no disk cache; still fetch below
            for slug, thumb in todo:
                path = cache_dir / f"{slug}.png"
                raw: bytes | None = None
                try:
                    if path.exists():
                        raw = path.read_bytes()
                except OSError:
                    raw = None
                if raw is None:
                    raw = market.fetch_thumb(thumb)
                    if raw:
                        try:
                            path.write_bytes(raw)
                        except OSError:
                            pass        # cache miss next time; icon still shows
                if raw:
                    self.after(0, lambda s=slug, r=raw: self._apply_thumb(s, r))

        threading.Thread(target=work, daemon=True).start()

    def _apply_thumb(self, slug: str, raw: bytes) -> None:
        if not self.winfo_exists() or slug in self._thumbs:
            return
        try:
            img = tk.PhotoImage(data=base64.b64encode(raw))
            # Scale to fit the icon box by the LARGER dimension so non-square
            # art never overflows. PhotoImage only scales by integer factors,
            # so approximate the ratio as a small fraction (e.g. 128->96 is
            # zoom 3 / subsample 4) - intermediates stay tiny.
            biggest = max(img.width(), img.height())
            if biggest > self.ICON:
                frac = Fraction(self.ICON, biggest).limit_denominator(8)
                if frac.numerator > 1:
                    img = img.zoom(frac.numerator)
                img = img.subsample(frac.denominator)
        except tk.TclError:
            return
        self._thumbs[slug] = img
        for card in self.cards.values():
            if card["listing"].slug == slug and card["icon"].winfo_exists():
                card["icon"].configure(image=img, text="")

    # -- card state updates ----------------------------------------------------

    def _set_market_low(self, order_id: str, low: int | None, n: int) -> None:
        # Record on the listing even when its card is filtered out right now,
        # so sorting by market low and later renders still have the data.
        l = next((x for x in self.listings if x.order_id == order_id), None)
        if l is not None:
            l.market_low, l.online_count = low, n
        card = self.cards.get(order_id)
        if not card or not card["low"].winfo_exists() or l is None:
            return
        if low is None:
            card["low"].configure(text=f"{self.BEST}: none online",
                                  fg=WFM_MUTED)
            return
        # "Beaten" means someone online has a better position than you:
        # a cheaper seller on WTS, a higher-paying buyer on WTB. Same rule
        # core.repricer uses to decide whether the floor/cap clamp bit.
        beaten = wfm_repricer.better_than(self.side, low, l.platinum)
        prefix = "⚠ " if beaten else ""
        card["low"].configure(
            text=f"{prefix}{self.BEST} {low}p · {n} online",
            fg=WARN if beaten else OK)

    def _apply_listing(self, order_id: str) -> None:
        """Push a listing's current fields back into its card labels."""
        card = self.cards.get(order_id)
        if not card or not card["price"].winfo_exists():
            return
        l = card["listing"]
        card["price"].configure(text=str(l.platinum))
        card["qty"].configure(text=f"{l.quantity} ❒")
        card["vis"].btn.configure(text="◉ Visible" if l.visible else "◌ Hidden",
                                  fg=WFM_TEAL if l.visible else WARN)

    def _remove_listing(self, order_id: str) -> None:
        self.listings = [x for x in self.listings if x.order_id != order_id]
        self._apply_view()

    def _card_result(self, order_id: str, msg: str, color: str) -> None:
        """Write a per-card status line, UI-thread only. Re-looks the card
        up (it may have been re-rendered) and checks it still exists."""
        card = self.cards.get(order_id)
        if card and card["result"].winfo_exists():
            card["result"].configure(text=msg, fg=color)

    def _op_done(self, order_id: str, msg: str, color: str) -> None:
        self._set_busy(False, "")
        card = self.cards.get(order_id)
        if card and card["result"].winfo_exists():
            card["result"].configure(text=msg, fg=color)

    def _async_op(self, order_id: str, work) -> None:
        """Run work() (returns (msg, color) or a callable to finish on the UI
        thread) off the UI thread with per-card status."""
        if self._busy:
            return
        card = self.cards.get(order_id)
        if not card or self.app.market is None:
            return
        self._set_busy(True)
        card["result"].configure(text="working…", fg=WFM_MUTED)

        def run() -> None:
            try:
                res = work()
            except wfm_market.MarketError as exc:
                self.after(0, lambda: self._op_done(order_id, str(exc), ERR))
                return
            if callable(res):
                self.after(0, res)
            else:
                msg, color = res
                self.after(0, lambda: self._op_done(order_id, msg, color))

        threading.Thread(target=run, daemon=True).start()

    # -- WFM-style actions -------------------------------------------------------

    def _sold(self, order_id: str) -> None:
        card = self.cards.get(order_id)
        if not card:
            return
        l = card["listing"]
        verb = self.done_verb.lower()
        if wfm_listings_vm.closes_listing(l.quantity) and not messagebox.askyesno(
                f"Mark {verb}", f"Mark the last {l.name} {verb}?\n\n"
                "This closes the listing and records the trade on your "
                "profile.", parent=self):
            return

        def work():
            self.app.market.close_order(order_id, 1)
            if wfm_listings_vm.closes_listing(l.quantity):
                def fin():
                    self._set_busy(False,
                                   f"{l.name} {verb} out - listing closed.")
                    self._remove_listing(order_id)
                return fin
            l.quantity -= 1
            def fin():
                self._op_done(order_id, f"{verb} 1 ✔", OK)
                self._apply_listing(order_id)
            return fin

        self._async_op(order_id, work)

    def _bulk_visibility(self, visible: bool) -> None:
        """Set every order on this tab visible/hidden on the market -
        one write per order, so it confirms first."""
        if self._busy or not self.listings or self.app.market is None:
            return
        targets = wfm_listings_vm.needs_visibility(self.listings, visible)
        word = "visible" if visible else "hidden"
        if not targets:
            self.status.configure(text=f"All listings are already {word}.",
                                  fg=MUTED)
            return
        if not messagebox.askyesno(
                f"Make all {word}",
                f"Set {len(targets)} listing(s) {word} on warframe.market?",
                parent=self):
            return
        self._set_busy(True, f"Setting {len(targets)} listing(s) {word}…")

        def work() -> None:
            done = fails = 0
            for l in targets:
                try:
                    self.app.market.update_order(
                        l.order_id, l.platinum, l.quantity, visible)
                    l.visible = visible
                    done += 1
                    self.after(0, lambda oid=l.order_id:
                               self._apply_listing(oid))
                except wfm_market.MarketError:
                    fails += 1
                self.after(0, lambda d=done, f=fails: self.status.configure(
                    text=f"Visibility: {d} done"
                         + (f", {f} failed" if f else "") + "…", fg=MUTED))
            tail = f"{done} set {word}" + (f", {fails} FAILED" if fails else "")
            self.after(0, lambda: self._set_busy(False, tail))
            self.after(0, self._apply_view)   # respect the Show filter

        threading.Thread(target=work, daemon=True).start()

    def _adjust_qty(self, order_id: str, delta: int) -> None:
        card = self.cards.get(order_id)
        if not card:
            return
        l = card["listing"]
        new_q = wfm_listings_vm.adjust_quantity(l.quantity, delta)
        if new_q is None:
            self._op_done(order_id,
                          "quantity can't go below 1 - use Delete", WARN)
            return

        def work():
            self.app.market.update_order(order_id, l.platinum, new_q, l.visible)
            l.quantity = new_q
            def fin():
                self._op_done(order_id, f"quantity → {new_q}", OK)
                self._apply_listing(order_id)
            return fin

        self._async_op(order_id, work)

    def _toggle_visible(self, order_id: str) -> None:
        card = self.cards.get(order_id)
        if not card:
            return
        l = card["listing"]
        new_vis = not l.visible

        def work():
            self.app.market.update_order(order_id, l.platinum, l.quantity,
                                         new_vis)
            l.visible = new_vis
            def fin():
                self._op_done(order_id,
                              "visible" if new_vis else "hidden", OK)
                self._apply_listing(order_id)
            return fin

        self._async_op(order_id, work)

    def _delete(self, order_id: str) -> None:
        card = self.cards.get(order_id)
        if not card:
            return
        l = card["listing"]
        if not messagebox.askyesno(
                "Delete listing",
                f"Delete your {l.name} listing ({l.quantity} at {l.platinum}p)?"
                "\n\nNo sale is recorded - the order is just removed.",
                parent=self):
            return

        def work():
            self.app.market.delete_order(order_id)
            def fin():
                self._set_busy(False, f"{l.name} listing deleted.")
                self._remove_listing(order_id)
            return fin

        self._async_op(order_id, work)

    def _edit(self, order_id: str) -> None:
        card = self.cards.get(order_id)
        if card:
            EditListingDialog(self, card["listing"])

    # -- repricing ---------------------------------------------------------

    def _reprice_one(self, order_id: str) -> None:
        self._commit_floor(order_id)

        def work():
            msg, color = self._do_reprice(order_id)
            def fin():
                self._op_done(order_id, msg, color)
            return fin

        self._async_op(order_id, work)

    def _reprice_all(self) -> None:
        if self._busy or not self.listings:
            return
        blurb = ("matching each to the lowest online seller (never below "
                 "its floor)" if self.side == "sell" else
                 "matching each to the highest online buyer (never above "
                 "its cap)")
        if not messagebox.askyesno(
                "Reprice all",
                f"Reprice all {len(self.listings)} listings now?\n\n"
                f"This writes real price changes to your warframe.market "
                f"orders, {blurb}.",
                parent=self):
            return
        for oid in list(self.cards):
            self._commit_floor(oid)
        self._set_busy(True, "Repricing all…")
        order_ids = [l.order_id for l in self.listings]

        def work() -> None:
            for i, oid in enumerate(order_ids, 1):
                # Look the card up on the UI thread inside the callback and
                # guard it: a sort/filter change mid-sweep re-renders and
                # destroys every card, and a captured widget would then be
                # configured after destruction (TclError, silent under
                # pythonw, and the remaining results stop appearing).
                self.after(0, lambda o=oid: self._card_result(
                    o, "working…", WFM_MUTED))
                msg, color = self._do_reprice(oid)
                self.after(0, lambda o=oid, m=msg, col=color:
                           self._card_result(o, m, col))
                self.after(0, lambda i=i: self.status.winfo_exists() and
                           self.status.configure(
                               text=f"Repricing all… {i}/{len(order_ids)}",
                               fg=MUTED))
            self.after(0, lambda: self._set_busy(False, "Reprice all complete."))

        threading.Thread(target=work, daemon=True).start()

    def _do_reprice(self, order_id: str) -> tuple[str, str]:
        """Runs on a worker thread. Returns (message, colour).

        The decision and the network work are core.repricer's; what stays
        here is finding the listing, scheduling the card repaint, and picking
        a colour - the three things that need a widget."""
        # Source the listing from the data model, NOT the card: cards exist
        # only for rows passing the current Show filter, and "Reprice all"
        # covers every listing on the tab (matching its confirm dialog).
        l = next((x for x in self.listings if x.order_id == order_id), None)
        if l is None:
            return "gone", ERR

        res = wfm_repricer.reprice(l, self.app.market,
                                   self.app.session.username, self.side,
                                   self._floor_for(l))
        if not res.ok:
            return res.message, ERR
        self.after(0, lambda: self._apply_listing(order_id))
        self.after(0, lambda: self._set_market_low(order_id, res.best,
                                                   res.online))
        return res.message, OK


class EditListingDialog(tk.Toplevel):
    """WFM's Edit action: price, quantity, visibility - plus this app's
    floor (WTS) or cap (WTB). Saving writes the order once; a manually set
    price becomes the item's new reference, so its default floor/cap follows
    the price you chose."""

    def __init__(self, view: "ListingsTab",
                 listing: wfm_market.Listing) -> None:
        super().__init__(view)
        self.view = view
        self.listing = listing
        f = view.app.fonts
        self.title(f"Edit - {listing.name}")
        self.configure(bg=WFM_CARD, padx=22, pady=18)
        self.resizable(False, False)
        self.transient(view.app)
        self.grab_set()

        # header: item image (when already cached by the card view) + the
        # wts/wtb tag + title, mirroring the card itself
        head = tk.Frame(self, bg=WFM_CARD)
        head.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))
        img = view._thumbs.get(listing.slug)
        if img is not None:
            box = tk.Frame(head, bg=WFM_EDGE, padx=1, pady=1)
            box.pack(side="left", padx=(0, 10))
            ic = tk.Label(box, image=img, bg=ICON_BG)
            ic.image = img                     # keep a reference alive
            ic.pack()
        tk.Label(head, text=view.badge_text, bg=view.badge_bg,
                 fg=view.badge_fg, font=f["small"]).pack(side="left",
                                                         padx=(0, 8))
        tk.Label(head, text=listing.name, bg=WFM_CARD, fg=WFM_TEAL,
                 font=f["h2"]).pack(side="left")

        def field(row: int, label: str, value: str) -> tk.StringVar:
            tk.Label(self, text=label, bg=WFM_CARD, fg=WFM_MUTED,
                     font=f["small"]).grid(row=row, column=0, sticky="w",
                                           pady=3)
            var = tk.StringVar(value=value)
            # style guide: every input goes through field_style (gold inlay
            # border, gold caret, gold-wash selection); dialogs are panels
            tk.Entry(self, textvariable=var, width=10, justify="center",
                     font=f["body"], **field_style(False)).grid(
                         row=row, column=1, sticky="w",
                         ipady=CTRL_IPADY, padx=(SP_LG, 0))
            return var

        self.price = field(1, "Price (platinum)", str(listing.platinum))
        self.qty = field(2, "Quantity", str(listing.quantity))
        override = view.limits.overrides.get(listing.slug)
        self.floor = field(3, f"{view.LIMIT_TITLE} (blank = auto)",
                           "" if override is None else str(override))
        self.visible = tk.BooleanVar(value=listing.visible)
        tk.Checkbutton(self, text="Visible", variable=self.visible,
                       bg=WFM_CARD, fg=TEXT, selectcolor=CONSOLE_BG,
                       activebackground=WFM_CARD, activeforeground=TEXT,
                       font=f["small"], highlightthickness=0).grid(
                           row=4, column=1, sticky="w", pady=3)

        self.status = tk.Label(self, text="", bg=WFM_CARD, fg=ERR,
                               font=f["small"])
        self.status.grid(row=5, column=0, columnspan=2, sticky="w")

        btns = tk.Frame(self, bg=WFM_CARD)
        btns.grid(row=6, column=0, columnspan=2, sticky="e", pady=(12, 0))
        self.save_btn = tk.Button(btns, text="Save", command=self._save,
                                  bg=WFM_TEAL, fg=INK, relief="flat",
                                  bd=0, padx=16, pady=5, cursor="hand2",
                                  font=f["small"], activebackground=PANEL_HI)
        self.save_btn.pack(side="right", padx=(8, 0))
        tk.Button(btns, text="Cancel", command=self.destroy,
                  **secondary_style(f["small"], wide=True)).pack(side="right")
        self.bind("<Return>", lambda _e: self._save())

        # center over the app window
        self.update_idletasks()
        try:
            a = view.app
            x = a.winfo_rootx() + (a.winfo_width()
                                   - self.winfo_reqwidth()) // 2
            y = a.winfo_rooty() + (a.winfo_height()
                                   - self.winfo_reqheight()) // 2
            self.geometry(f"+{max(0, x)}+{max(0, y)}")
        except tk.TclError:
            pass

    def _save(self) -> None:
        l, view = self.listing, self.view
        try:
            price = max(1, int(self.price.get().strip()))
            qty = max(1, int(self.qty.get().strip()))
            floor_text = self.floor.get().strip()
            floor = max(1, int(floor_text)) if floor_text else None
        except ValueError:
            self.status.configure(text="Price, quantity and floor must be "
                                       "whole numbers.")
            return
        visible = self.visible.get()
        self.save_btn.configure(state="disabled", text="Saving…")

        def work() -> None:
            try:
                view.app.market.update_order(l.order_id, price, qty, visible)
            except wfm_market.MarketError as exc:
                msg = str(exc)
                self.after(0, lambda: self._fail(msg))
                return
            self.after(0, lambda: self._done(price, qty, visible, floor))

        threading.Thread(target=work, daemon=True).start()

    def _fail(self, msg: str) -> None:
        if not self.winfo_exists():
            return
        self.save_btn.configure(state="normal", text="Save")
        self.status.configure(text=msg)

    def _done(self, price: int, qty: int, visible: bool,
              floor: int | None) -> None:
        l, view = self.listing, self.view
        manual_change = price != l.platinum
        l.platinum, l.quantity, l.visible = price, qty, visible
        if manual_change:
            # A hand-set price is the new reference the default limit hangs off.
            view.limits.rebase(l.order_id, price)
        view.limits.set_override(l.slug, floor)
        wfm_market.save_prefs(view.prefs)
        view._apply_listing(l.order_id)
        view._refresh_floor_field(l.order_id)
        view._op_done(l.order_id, "saved ✔", OK)
        self.destroy()


def main() -> int:
    app = App()
    app.mainloop()
    if app.webhost.started:
        # pythonnet can't survive interpreter finalization once WebView2
        # has run - its CLR callbacks throw during teardown. Everything is
        # already shut down cleanly at this point, so just leave.
        os._exit(0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
