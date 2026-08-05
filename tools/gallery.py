"""Render every visible surface + state to PNG for the UI/UX audit.

Stands up the REAL widgets (reusing the offscreen tests' fake-data fixtures),
parks each off-screen, and captures the actual composited pixels at true 300%
via tools/winshot.PrintWindow - so the audit judges what the app renders, not
what the code predicts.

Run:  python3.11 tools/gallery.py
Out:  $CLAUDE_JOB_DIR/gallery/*.png  (+ manifest.txt)
"""
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "tools"))
# NOT offscreen - PrintWindow needs a real HWND. Keep web isolated + CPU-composited.
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu-compositing")

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget
import winshot

app = QApplication([])
from core import config as core_config
from core import market as core_market
from ui import qss, web as ui_web
ui_web.isolate_for_tests()      # never the running app's profile
ui_web.AUTOLOAD = False
app.setStyleSheet(qss.build(set(QFontDatabase.families())))

# --- stubs: never touch the user's real files / network ---------------------
core_market.save_prefs = lambda prefs: None
core_config.save_settings = lambda s: None
core_config.set_start_with_windows = lambda on: True
core_config.set_watch_warframe = lambda on: True
core_config.spawn_watcher = lambda: True
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)

GALLERY = Path(os.environ["CLAUDE_JOB_DIR"]) / "gallery"
GALLERY.mkdir(parents=True, exist_ok=True)
manifest = []


def pump(rounds=12):
    for _ in range(rounds):
        app.processEvents()
        time.sleep(0.01)


def shoot(widget, name, w=1280, h=720, rounds=14):
    """Park off-screen, show, settle, PrintWindow to gallery/<name>.png."""
    try:
        widget.resize(w, h)
        widget.move(-9000, 120)            # off the visible desktop, primary DPI
        widget.show()
        pump(rounds)
        hwnd = int(widget.winId())
        path = GALLERY / f"{name}.png"
        pw, ph, ok, _ = winshot.capture(hwnd, str(path))
        manifest.append((name, f"{pw}x{ph}", ok))
        print(f"  shot {name:26} {pw}x{ph} ok={ok}")
    except Exception as exc:               # noqa: BLE001 - one bad scene must not kill the gallery
        manifest.append((name, "ERROR", str(exc)[:80]))
        print(f"  FAIL {name:26} {exc!r}")


# ===========================================================================
# Shell surfaces (one real MainWindow, navigated)
# ===========================================================================
from ui.app import MainWindow

win = MainWindow()
if hasattr(win, "presence"):
    try:
        win.presence.set_state = lambda *a, **k: None
    except Exception:
        pass

print("shell")
shoot(win, "01_home_1280", 1280, 720)
shoot(win, "02_home_small", 1000, 640)

# Market — inject an order book (no network), then render it
try:
    win.navigate("market")
    pump()
    mv = win.stack.currentWidget()
    mt = mv.tabs["market"]
    mt._index = [("Ash Prime Set", "ash_prime_set", "t"),
                 ("Ash Prime Blueprint", "ash_prime_bp", "t"),
                 ("Banshee Prime Set", "banshee_prime_set", "t")]
    mt.slug, mt.name = "ash_prime_set", "Ash Prime Set"
    mt._book = {
        "sell": [{"user": "Trader_A", "platinum": 40, "quantity": 1, "status": "ingame"},
                 {"user": "Trader_B", "platinum": 42, "quantity": 3, "status": "online"},
                 {"user": "Trader_C", "platinum": 45, "quantity": 1, "status": "ingame"}],
        "buy": [{"user": "Buyer_X", "platinum": 30, "quantity": 2, "status": "ingame"},
                {"user": "Buyer_Y", "platinum": 28, "quantity": 1, "status": "online"}]}
    mt._rerender()
    if hasattr(mt, "_paint_query"):
        mt._paint_query()
    pump()
    shoot(win, "10_market_book", 1280, 720)
    # contracts + watchlist tabs (empty states)
    mv.select("contracts")
    pump()
    shoot(win, "11_market_contracts", 1280, 720)
    mv.select("watchlist")
    pump()
    shoot(win, "12_market_watchlist", 1280, 720)
except Exception as exc:                    # noqa: BLE001
    print(f"  market scene error: {exc!r}")

# Vosfor (real cached data)
try:
    win.navigate("vosfor")
    pump(20)
    shoot(win, "20_vosfor", 1280, 720)
    v = win.stack.currentWidget()
    from ui.vosfor import CollectionCard
    cards = v.findChildren(CollectionCard)
    if cards and hasattr(cards[0], "name"):
        v._toggle(cards[0].name)
        pump()
        shoot(win, "21_vosfor_expanded", 1280, 720)
except Exception as exc:                    # noqa: BLE001
    print(f"  vosfor scene error: {exc!r}")

# Web tab chrome. NOTE: PrintWindow CANNOT capture a window containing a
# QtWebEngine view - Chromium's native child surface overpaints the whole client
# area white, whether or not the view is hidden. So for this one surface we use
# QWidget.grab() (Qt's own paint engine), which renders the native chrome bar;
# the un-grabbable web content comes back blank, which is fine (it is
# third-party - only our chrome is ours to audit).
try:
    win.navigate("web_wiki")
    pump()
    wv = win.stack.currentWidget()
    wv.grab().save(str(GALLERY / "30_web_chrome.png"))
    manifest.append(("30_web_chrome", "grab()", True))
    print("  shot 30_web_chrome            (grab: PrintWindow can't see QtWebEngine)")
except Exception as exc:                    # noqa: BLE001
    print(f"  web scene error: {exc!r}")


# ===========================================================================
# My Listings (standalone view + FakeClient - deterministic cards & states)
# ===========================================================================
print("listings")


def listing(oid, name, plat, qty=1, visible=True, slug=None, rank=None, subtype=None):
    return core_market.Listing(order_id=oid, slug=slug or name.lower(), name=name,
                               platinum=plat, quantity=qty, visible=visible,
                               updated="", rank=rank, subtype=subtype)


class FakeClient:
    def __init__(self):
        self.sell = [listing("a", "Ash Prime Set", 40, 2),
                     listing("b", "Banshee Prime Set", 15, 1),
                     listing("c", "Cernos Prime Set", 90, 3, visible=False),
                     listing("d", "Arcane Energize", 120, 1, rank=5, subtype="radiant")]
        self.buy = [listing("x", "Loki Prime Set", 55, 1),
                    listing("y", "Nova Prime Set", 30, 2)]
        self.best = {"ash prime set": (35, 4), "banshee prime set": (18, 2),
                     "cernos prime set": (95, 1), "arcane energize": (110, 3),
                     "loki prime set": (60, 5), "nova prime set": (28, 4)}

    def my_listings(self):
        return {"sell": list(self.sell), "buy": list(self.buy)}

    def lowest_online(self, slug, exclude="", rank=None, subtype=None):
        return self.best.get(slug, (None, 0))
    highest_online = lowest_online

    def update_order(self, *a, **k): pass
    def close_order(self, *a, **k): pass
    def delete_order(self, *a, **k): pass
    def max_rank(self, slug): return {"arcane energize": 5}.get(slug)
    def fetch_thumb(self, path): return None


class FakeSession:
    username = "Dzwsin"


try:
    from ui.listings import EditListingDialog, ListingsView
    lview = ListingsView(FakeClient(), FakeSession(), {})
    shoot(lview, "40_listings_wts", 1280, 720)
    shoot(lview, "41_listings_wts_small", 1000, 640)
    lview.tabs and lview  # keep ref
    # WTB tab
    try:
        for key, btn in getattr(lview, "tab_btns", {}).items():
            if key == "WTB":
                btn.click()
        pump()
        shoot(lview, "42_listings_wtb", 1280, 720)
    except Exception:
        pass
    # Edit dialog on a card
    try:
        wts = lview.tabs["WTS"]
        card = wts.cards.get("a") or next(iter(wts.cards.values()))
        dlg = EditListingDialog(wts, card)
        shoot(dlg, "43_edit_listing_dialog", 520, 560)
    except Exception as exc:
        print(f"  edit dialog error: {exc!r}")
except Exception as exc:                    # noqa: BLE001
    print(f"  listings scene error: {exc!r}")


# ===========================================================================
# Settings (standalone view + FakeShell - every page + GoodbyeDialog)
# ===========================================================================
print("settings")
try:
    from core import bookmarks as bm
    bm.BOOKMARKS_PATH = Path(os.environ["CLAUDE_JOB_DIR"]) / "tmp" / "__gallery_bm.json"
    bm.BOOKMARKS_PATH.unlink(missing_ok=True)
    from ui import settings as st
    st.GoodbyeDialog.confirmed = staticmethod(lambda *a, **k: True)

    class FakeShell:
        def __init__(self):
            self.settings = core_config.load_settings()
            self.session = None
            self.market = None
        def unlink_account(self): pass
        def wipe_user_data(self): pass
        def bookmarks_changed(self): pass

    sview = st.SettingsView(FakeShell())
    for key, name in [("window", "50_settings_display"),
                      ("market", "51_settings_market"),
                      ("web", "52_settings_web"),
                      ("toolbox", "53_settings_toolbox"),
                      ("messaging", "54_settings_messaging"),
                      ("warframe", "55_settings_warframe")]:
        try:
            sview.select(key)
            pump()
            shoot(sview, name, 1100, 720)
        except Exception as exc:
            print(f"  settings page {key} error: {exc!r}")
    # GoodbyeDialog
    try:
        gd = st.GoodbyeDialog(sview, "Delete ALL user data?",
                              "This erases every setting, watchlist, bookmark and "
                              "cached image. Type goodbye to confirm.")
        shoot(gd, "56_goodbye_dialog", 480, 260)
    except Exception as exc:
        print(f"  goodbye dialog error: {exc!r}")
except Exception as exc:                    # noqa: BLE001
    print(f"  settings scene error: {exc!r}")


# ===========================================================================
# Login dialog
# ===========================================================================
print("dialogs")
try:
    from ui.dialogs import LoginDialog
    host = QWidget()
    ld = LoginDialog(host)
    shoot(ld, "60_login_dialog", 460, 420)
except Exception as exc:                     # noqa: BLE001
    print(f"  login dialog error: {exc!r}")


# --- manifest ---------------------------------------------------------------
(GALLERY / "manifest.txt").write_text(
    "\n".join(f"{n}\t{d}\t{ok}" for n, d, ok in manifest), encoding="utf-8")
print(f"\n{len(manifest)} scenes -> {GALLERY}")
sys.stdout.flush()
os._exit(0)     # Chromium offscreen teardown can crash after success
