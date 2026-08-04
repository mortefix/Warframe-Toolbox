"""The QtWebEngine web tabs: profile persistence, ad blocking, lazy loading.

Three things here fail SILENTLY in production, which is why each gets a
direct check rather than a "does it render" smoke test:

  1. An unnamed `QWebEngineProfile()` is off-the-record. It works perfectly
     and throws every cookie away on exit, so the bug surfaces a day later as
     "the sites keep logging me out".
  2. The default user agent advertises QtWebEngine, and overframe.gg answers
     that with a Cloudflare challenge instead of the site.
  3. An interceptor installed after the first page load blocks nothing on
     that page.

The block test runs over a LOCAL HTTP SERVER, not file://. That is not
fussiness: an earlier version of this check was served from file://, where
Chromium blocks all cross-origin subresource loads itself, so the interceptor
never saw the requests and the test passed for the wrong reason. `requests
seen` was the tell - it was 1.

Nothing here touches the internet. Every "ad" host is blocked before DNS, and
everything else is served from 127.0.0.1.
"""
import os
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "data"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Chromium has no GPU surface under the offscreen platform; without these it
# loses its D3D context and takes the process down with SIGSEGV on exit.
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS",
                      "--disable-gpu --disable-software-rasterizer "
                      "--no-sandbox --in-process-gpu")

try:
    from PySide6.QtWidgets import QApplication
    from PySide6.QtWebEngineCore import QWebEngineProfile
except ImportError:
    print("PySide6 QtWebEngine not installed - skipping web checks")
    raise SystemExit(0)

fails = []


def check(name, got, want=True):
    ok = got == want
    if not ok:
        fails.append(f"{name}: got {got!r}, want {want!r}")
    print(f"  {'ok  ' if ok else 'FAIL'} {name}")


# -- a page that asks for both blocked and allowed subresources --------------

PAGE = b"""<!doctype html><html><head>
<script src="http://www.googletagmanager.com/gtag/js"></script>
<script src="http://ads.adthrive.com/sites/x/ads.min.js"></script>
<link rel="stylesheet" href="http://doubleclick.net/x.css">
</head><body>
<img src="/allowed-one.png"><img src="/allowed-two.png">
<div class="adthrive-ad" id="AdThrive_slot">AD</div>
<div id="real-content">content</div>
</body></html>"""

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
       b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00"
       b"\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body, ctype = ((PAGE, "text/html") if self.path == "/"
                       else (PNG, "image/png"))
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


server = HTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{server.server_port}/"

app = QApplication([])
from core import adblock, webapps                                # noqa: E402
from ui import web                                               # noqa: E402
web.isolate_for_tests()   # NEVER the running app's profile

print("the profile is configured to actually persist")
p = web.profile()
# the silent one: an unnamed profile is off-the-record and drops every cookie
check("it is NAMED", p.storageName(), web.PROFILE_NAME)
check("so it is not off the record", p.isOffTheRecord(), False)
check("cookies are forced to disk",
      p.persistentCookiesPolicy(),
      QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies)
check("storage has a home", bool(p.persistentStoragePath()))
check("separate from the Tk app's .webview, which is process-locked",
      ".webview" not in p.persistentStoragePath())

print("\nthe user agent presents as plain Chrome")
# Measured, and it OVERTURNED the migration plan: claiming to be Edge is what
# makes overframe.gg serve a Cloudflare challenge, because Edge sends Sec-CH-UA
# client hints that QtWebEngine does not, and the mismatch reads as a bot.
# One throwaway profile per variant, so no cf_clearance could carry over:
#     default (QtWebEngine token) -> loads    Edge -> "Just a moment..."
import re as _re                                                  # noqa: E402
check("no QtWebEngine token", "QtWebEngine" in p.httpUserAgent(), False)
check("and it does NOT claim to be Edge", "Edg/" in p.httpUserAgent(), False)
check("it still names a Chrome version", "Chrome/" in p.httpUserAgent())
# derived from the engine, so a Qt upgrade cannot leave a stale version behind
# - and a stale version is exactly what a bot check looks for
check("the version matches the engine's own",
      _re.search(r"Chrome/([\d.]+)", p.httpUserAgent()).group(1),
      _re.search(r"Chrome/([\d.]+)",
                 QWebEngineProfile.defaultProfile().httpUserAgent()).group(1))

print("\nthe cosmetic sweeper is installed profile-wide")
found = [s for s in p.scripts().find("adblock")]
check("one adblock script", len(found), 1)
check("injected at document creation - before the page can paint an ad",
      found[0].injectionPoint(), found[0].InjectionPoint.DocumentCreation)
check("in the main world, or it could not touch the page's own nodes",
      found[0].worldId(), found[0].ScriptWorldId.MainWorld)

print("\nlazy: nothing is fetched until the tab is first shown")
web.AUTOLOAD = False
idle = web.WebAppView(webapps.BY_KEY["web_builds"])
check("not navigated at construction", idle.is_navigated(), False)
idle.resize(400, 300)
idle.show()
app.processEvents()
check("and not by being shown, with autoload off", idle.is_navigated(), False)
# a deep link arriving before the tab exists is REMEMBERED, not dropped
pending = web.WebAppView(webapps.BY_KEY["web_wiki"])
pending.open_url("https://wiki.warframe.com/w/Rhino_Prime")
check("a deep link to an unshown tab is held",
      pending._want_url, "https://wiki.warframe.com/w/Rhino_Prime")

print("\nblocking, over a real HTTP server")
view = web.WebAppView(webapps.BY_KEY["web_builds"])
view.resize(800, 600)
view.show()
app.processEvents()
inter = web.interceptor()
before_blocked, before_allowed = inter.blocked, inter.allowed
view.view.setUrl(__import__("PySide6.QtCore", fromlist=["QUrl"]).QUrl(BASE))

done = []
view.view.loadFinished.connect(lambda ok: done.append(ok))
deadline = time.time() + 30
while not done and time.time() < deadline:
    app.processEvents()
    time.sleep(0.01)
for _ in range(60):                      # let subresources settle
    app.processEvents()
    time.sleep(0.01)

blocked = inter.blocked - before_blocked
allowed = inter.allowed - before_allowed
print(f"       {blocked} blocked, {allowed} allowed")
check("the page loaded", done[:1], [True])
# THE tell that the earlier file:// version of this test was bogus: if the
# interceptor is not really seeing subresources, this number is ~1
check("the interceptor saw the subresources, not just the document",
      allowed >= 3)
check("all three ad hosts were blocked", blocked, 3)

print("\nthe stuck-black self-heal nudges the page lifecycle, not the surface")
# Design note, learned in THIS suite: pixel-probing was rejected because a
# healthy rendered page still grabs as pure black under the engine, so any
# probe-then-teardown scheme would tear down working pages. The nudge is
# unconditional and harmless instead: page hidden for one beat, then shown,
# forcing Chromium to re-submit a frame into the existing surface.
check("a loaded, visible view takes the nudge", view.isVisible())
view._loaded = True     # the block test navigated the page directly
view._nudge()
check("the page is lifecycle-hidden for the beat",
      view.view.page().isVisible(), False)
deadline = time.time() + 3
while not view.view.page().isVisible() and time.time() < deadline:
    app.processEvents()
    time.sleep(0.01)
check("and restored once it lands", view.view.page().isVisible())
# a tab that is not on screen must not be nudged into rendering - whatever
# visibility the widget's own hide handling left the page in stays put
view.hide()
app.processEvents()
before = view.view.page().isVisible()
view._nudge()
check("a hidden tab is not touched", view.view.page().isVisible(), before)
view.show()
app.processEvents()

print("\nthe cookie store is disk-backed, not in memory")
# The BEHAVIOURAL version of "is it named". An off-the-record profile creates
# no files at all, so this fails if the profile is ephemeral no matter what
# its configuration claims - and configuration is exactly what lied when this
# was first written.
#
# The full cross-process round trip cannot live here: Chromium does not
# persist cookies for localhost or bare-IP origins (measured - both were
# accepted in memory and absent from disk afterwards), so a local server
# cannot stand in for a real site. It was verified live instead: three
# separate processes loading wiki.warframe.com all reported the SAME
# `wg_visitor` UUID, which is generated once per visitor - so it came off
# disk, not from a new session.
db = Path(p.persistentStoragePath()) / "Cookies"
check("a Cookies database exists on disk", db.exists())
# stat(), not read_bytes(): the live profile holds an exclusive lock on this
# file, which is the same single-process lock that stops two copies of the app
# sharing a profile directory. Opening it here fails with PermissionError.
check("and it has been written to", db.stat().st_size > 0 if db.exists()
      else False)

print("\nthe block rule is suffix-based, and only suffix-based")
bl = adblock.load_blocklist()
for host, want in (("doubleclick.net", True),
                   ("ads.g.doubleclick.net", True),
                   ("googletagmanager.com", True),
                   ("wiki.warframe.com", False),
                   ("127.0.0.1", False),
                   # the dot in "." + entry is what stops this one matching
                   ("notdoubleclick.net", False),
                   ("api.warframe.market", False)):
    check(f"{host} blocked={want}", adblock.host_blocked(host, bl), want)

print("\nthe cosmetic filter removed the ad box but kept the content")


def js(script):
    out = []
    view.view.page().runJavaScript(script, 0, lambda r: out.append(r))
    end = time.time() + 5
    while not out and time.time() < end:
        app.processEvents()
        time.sleep(0.01)
    return out[0] if out else None


check("the ad div is gone from the DOM",
      js("document.querySelectorAll('.adthrive-ad').length"), 0)
check("and the real content is untouched",
      js("document.getElementById('real-content') ? 1 : 0"), 1)

print("\nthe bookmarks drawer")
from core import bookmarks as bm                                  # noqa: E402
from PySide6.QtCore import QPoint                                 # noqa: E402
from PySide6.QtCore import Qt as _Qt                              # noqa: E402
from PySide6.QtTest import QTest                                  # noqa: E402
from PySide6.QtWidgets import QPushButton                         # noqa: E402

# never touch the real file
bm.BOOKMARKS_PATH = Path(__file__).parent / "__test_bookmarks.json"
bm.BOOKMARKS_PATH.unlink(missing_ok=True)
bm.save({"web_wiki": [{"url": "https://wiki.warframe.com/w/Rhino_Prime",
                       "title": "Rhino Prime"},
                      {"url": "https://wiki.warframe.com/w/Volt",
                       "title": "Volt"}],
         "web_builds": [{"url": "https://overframe.gg/builds/",
                         "title": "Top Builds"}]})

wiki = web.WebAppView(webapps.BY_KEY["web_wiki"])
wiki.resize(900, 600)
wiki.show()
app.processEvents()
wiki.drawer.reload()

check("the drawer starts closed", wiki.drawer.is_open(), False)
check("and its scrim is hidden", wiki.drawer.scrim.isVisible(), False)

wiki._toggle_drawer()
for _ in range(40):
    app.processEvents()
    time.sleep(0.01)
check("opening shows it", wiki.drawer.is_open())
check("the scrim comes with it", wiki.drawer.scrim.isVisible())
# flush to the RIGHT edge, full height - it is a drawer, not a popup
g, host = wiki.drawer.geometry(), wiki.rect()
check("it is flush to the right edge", g.right(), host.right())
check("and full height", g.height(), host.height())

# The scrim exists because mouse events inside a QWebEngineView are consumed
# by Chromium and never reach a Qt event filter on the page - so "click
# outside to close" cannot be done by watching the page.
check("the scrim covers the whole view", wiki.drawer.scrim.geometry(),
      wiki.rect())
check("and sits under the drawer, not over it",
      wiki.drawer.scrim.geometry().contains(wiki.drawer.geometry()))

print("\nonly THIS app's bookmarks are listed")
labels = [b.text() for b in wiki.drawer.findChildren(QPushButton)
          if b.text() and b is not wiki.drawer.clear_btn]
check("both wiki pages", sorted(labels), ["Rhino Prime", "Volt"])
check("and not overframe's", "Top Builds" in labels, False)

print("\nclear-all is scoped to this app, and says how much it will take")
check("it knows the count", wiki.drawer.count.text(), "2 saved")
check("and offers to clear", wiki.drawer.clear_btn.isEnabled())
# Answer the confirm-delete modal "Yes" with no human present. Without this
# _clear_all() opens QMessageBox.question(), which spins a nested modal event
# loop that never returns headless - the process hangs forever, and because
# run_all.py captures output through subprocess.run(), that one frozen modal
# silently freezes the whole suite with nothing printed. Replace the module
# name web.py resolves at call time (module globals always assign; Shiboken
# class attributes can refuse).
from PySide6.QtWidgets import QMessageBox as _QMB                  # noqa: E402


class _AutoYes:
    Yes, No = _QMB.Yes, _QMB.No

    @staticmethod
    def question(*_a, **_k):
        return _QMB.Yes


web.QMessageBox = _AutoYes
wiki.drawer._clear_all()          # the modal now auto-answers Yes
app.processEvents()
check("this app's list is empty", bm.count(bm.load(), "web_wiki"), 0)
check("the other app is untouched", bm.count(bm.load(), "web_builds"), 1)
check("and the button disables itself", wiki.drawer.clear_btn.isEnabled(),
      False)
check("with nothing left to count", wiki.drawer.count.text(), "")
# put them back for the checks below
bm.save({"web_wiki": [{"url": "https://wiki.warframe.com/w/Rhino_Prime",
                       "title": "Rhino Prime"},
                      {"url": "https://wiki.warframe.com/w/Volt",
                       "title": "Volt"}],
         "web_builds": [{"url": "https://overframe.gg/builds/",
                         "title": "Top Builds"}]})
wiki.drawer.reload()

print("\nclicking a saved link navigates AND closes")
opened = []
wiki.open_url = lambda u=None: opened.append(u)
link = next(b for b in wiki.drawer.findChildren(QPushButton)
            if b.text() == "Volt")
link.click()
for _ in range(40):
    app.processEvents()
    time.sleep(0.01)
check("it navigated", opened, ["https://wiki.warframe.com/w/Volt"])
check("and the drawer closed itself", wiki.drawer.is_open(), False)

print("\nclicking outside closes it")
wiki._toggle_drawer()
for _ in range(30):
    app.processEvents()
    time.sleep(0.01)
check("open again", wiki.drawer.is_open())
QTest.mousePress(wiki.drawer.scrim, _Qt.LeftButton, _Qt.NoModifier,
                 QPoint(20, 300))
for _ in range(40):
    app.processEvents()
    time.sleep(0.01)
check("a click on the scrim shuts it", wiki.drawer.is_open(), False)

print("\nthe ribbon reflects whether THIS page is saved")
from ui.widgets import bookmark_icon                              # noqa: E402


def ribbon_ink(filled):
    """A filled ribbon paints more pixels than an outline of the same size -
    that is the whole visual difference, so measure it rather than trusting
    that two different QIcons were requested."""
    img = bookmark_icon(filled, 16, "#ffffff").pixmap(22, 22).toImage()
    return sum(1 for x in range(img.width()) for y in range(img.height())
               if img.pixelColor(x, y).alpha() > 128)


check("a filled ribbon is visibly more ink than an outline",
      ribbon_ink(True) > ribbon_ink(False) * 1.4)

data = bm.load()
check("a saved page reads as bookmarked",
      bm.is_bookmarked(data, "web_wiki",
                       "https://wiki.warframe.com/w/Rhino_Prime"))
check("an unsaved one does not",
      bm.is_bookmarked(data, "web_wiki",
                       "https://wiki.warframe.com/w/Nowhere"), False)

bm.BOOKMARKS_PATH.unlink(missing_ok=True)

print("\nthe adblock setting actually gates blocking")
# It used to be written and never read - unticking it changed nothing.
inter = web.interceptor()


class _Info:
    def __init__(self, host):
        self._host, self.blocked_ = host, False

    def requestUrl(self):
        h = self._host

        class _U:
            def host(self_):
                return h
        return _U()

    def block(self, b):
        self.blocked_ = b


web.set_adblock(True)
on = _Info("ads.adthrive.com")
inter.interceptRequest(on)
check("an ad host is blocked when adblock is ON", on.blocked_)
web.set_adblock(False)
off = _Info("ads.adthrive.com")
inter.interceptRequest(off)
check("and NOT blocked when adblock is OFF", off.blocked_, False)
web.set_adblock(True)                    # restore for anything after

print()
if fails:
    print(f"{len(fails)} FAILURES:")
    for f in fails:
        print("   ", f)
    sys.stdout.flush()
    os._exit(1)
print("ALL QT WEB CHECKS PASSED")
sys.stdout.flush()
# Chromium's teardown races its own GPU process under the offscreen platform
# and can abort AFTER every check has passed. Exiting here reports the result
# we actually measured instead of a crash in the cleanup path.
os._exit(0)
