"""The Qt Settings screen.

The thing most likely to go wrong in a port of a settings screen is a SILENT
omission: a control that never got carried over reads as "that option was
removed" rather than as a bug. So the central check here is a census - every
key in `config.DEFAULTS` is either bound to a control on some page, or named
in the list of keys deliberately edited elsewhere. A new default with no home
fails the suite.
"""
import os
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "data"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS",
                      "--disable-gpu --disable-software-rasterizer "
                      "--no-sandbox --in-process-gpu")

try:
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtWidgets import (QApplication, QCheckBox, QLineEdit,
                                   QMessageBox)
except ImportError:
    print("PySide6 not installed - skipping Qt settings checks")
    raise SystemExit(0)

fails = []


def check(name, got, want=True):
    ok = got == want
    if not ok:
        fails.append(f"{name}: got {got!r}, want {want!r}")
    print(f"  {'ok  ' if ok else 'FAIL'} {name}")


app = QApplication([])
from core import bookmarks as bm                                  # noqa: E402
from core import config as core_config                            # noqa: E402
from ui import qss, web as ui_web                                 # noqa: E402
ui_web.isolate_for_tests()   # NEVER the running app's profile
ui_web.AUTOLOAD = False
app.setStyleSheet(qss.build())

# never touch the real files
SAVED = []
core_config.save_settings = lambda s: SAVED.append(dict(s))
core_config.set_start_with_windows = lambda on: True
core_config.set_watch_warframe = lambda on: True
core_config.spawn_watcher = lambda: True
bm.BOOKMARKS_PATH = Path(__file__).parent / "__set_bookmarks.json"
bm.BOOKMARKS_PATH.unlink(missing_ok=True)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)

from ui import settings as st                                     # noqa: E402
# the type-the-word gate always passes here; it has its own checks below
st.GoodbyeDialog.confirmed = staticmethod(lambda *a, **k: True)


class FakeShell:
    def __init__(self):
        self.settings = core_config.load_settings()
        self.session = None
        self.market = None
        self.unlinked = 0
        self.wiped = 0
        self.marks_changed = 0

    def unlink_account(self):
        self.unlinked += 1

    def wipe_user_data(self):
        self.wiped += 1

    def bookmarks_changed(self):
        self.marks_changed += 1


shell = FakeShell()
# DevTools visibility is asserted below; pin the gate so the test doesn't depend
# on whatever the real .wfm_settings.json currently has.
shell.settings["dev_panels"] = False
view = st.SettingsView(shell)
view.resize(1100, 700)
view.show()
app.processEvents()

print("the tree is alphabetical, top and bottom")
sections = [s for s, _p in st.TREE]
check("sections sorted", sections, sorted(sections, key=str.lower))
for section, pages in st.TREE:
    names = [n for _k, n in pages]
    check(f"{section}'s pages sorted", names, sorted(names, key=str.lower))
check("and it opens on the first one", view.current, st.TREE[0][1][0][0])

print("\nthe arrow browses; the header chooses")
before = view.current
view._toggle("Market")
check("the arrow opened a section", view._open_section, "Market")
check("without changing the page", view.current, before)
view._header_click("Market")
check("the header opened its first page", view.current, "messaging")

print("\nselecting a page reveals it in the tree")
view.select("toolbox")
check("the section expands to show it", view._open_section, "Data")

print("\nDevTools is gated behind the 'Enable Developer Panels' setting")
check("hidden by default", "DevTools" in view._hidden_sections)
check("its header is hidden", view.section_rows["DevTools"].isVisible(), False)
view.set_devtools_visible(True)
check("toggle on reveals it", "DevTools" not in view._hidden_sections)
check("header now visible", view.section_rows["DevTools"].isVisible(), True)
view.set_devtools_visible(False)
check("toggle off hides it again", "DevTools" in view._hidden_sections)
check("and its pages stay hidden even if selected",
      (view.select("dev_worldstate"),
       view.leaf_hosts["DevTools"].isVisible())[1], False)
view.select("toolbox")            # back to a real page for the checks below

print("\nEVERY default has a home")
# Build every page, then look for a control bound to each settings key.
for key, _lbl in [(k, n) for _s, pages in st.TREE for k, n in pages]:
    view.select(key)
    app.processEvents()
pages = [view.stack.widget(i) for i in range(view.stack.count())]
# `bound_keys` is RECORDED by the helpers that build the controls, not
# declared by hand - so it cannot claim a binding that does not exist.
bound = set()
for page in pages:
    bound |= getattr(page, "bound_keys", set())

#: Edited from another screen on purpose - the Vosfor planner owns both.
ELSEWHERE = {"vosfor_balance", "vosfor_methods"}
missing = sorted(set(core_config.DEFAULTS) - bound - ELSEWHERE)
check("no default is unreachable from Settings", missing, [])
check("and the census found real bindings", len(bound) >= 7)

print("\nsettings persist the moment they change")
view.select("window")
app.processEvents()
page = view.stack.currentWidget()
n_before = len(SAVED)
box = next(c for c in page.findChildren(QCheckBox)
           if "tray" in c.text().lower())
box.setChecked(not box.isChecked())
app.processEvents()
check("flipping a box writes settings", len(SAVED) > n_before)
check("and the value went to the model",
      shell.settings["minimize_to_tray"], box.isChecked())

print("\nregistry-backed boxes report the REGISTRY, not the json")
# start_with_windows lives in HKCU; the json is only a mirror, and someone can
# remove the Run entry from outside the app
startup = next(c for c in page.findChildren(QCheckBox)
               if "Windows startup" in c.text())
check("the box matches the registry",
      startup.isChecked(), core_config.start_with_windows_enabled())

print("\nblank message templates fall back to the shipped default")
view.select("messaging")
app.processEvents()
msg = view.stack.currentWidget()
msg.entries["msg_buy"].setText("   ")
msg._commit("msg_buy")
check("blank is refused, not saved",
      shell.settings["msg_buy"], core_config.DEFAULTS["msg_buy"])
msg.entries["msg_buy"].setText("/w {user} custom {item} {price}")
msg._commit("msg_buy")
check("a real template is kept",
      shell.settings["msg_buy"], "/w {user} custom {item} {price}")
msg._reset()
check("reset restores both",
      (shell.settings["msg_buy"], shell.settings["msg_sell"]),
      (core_config.DEFAULTS["msg_buy"], core_config.DEFAULTS["msg_sell"]))

print("\ndelete all bookmarks, from the web page")
bm.save({"web_wiki": [{"url": "https://wiki.warframe.com/w/A", "title": "A"},
                      {"url": "https://wiki.warframe.com/w/B", "title": "B"}],
         "web_builds": [{"url": "https://overframe.gg/x", "title": "X"}]})
view.select("web")
app.processEvents()
webp = view.stack.currentWidget()
check("it counts what it will destroy", "3 saved" in webp.mark_note.text())
check("and names the apps", "wiki: 2" in webp.mark_note.text())
check("the button is live", webp.clear_marks.isEnabled())
webp._clear_bookmarks()
app.processEvents()
check("every app's bookmarks are gone", bm.count(bm.load()), 0)
check("the open web tabs were told", shell.marks_changed, 1)
check("and the button disables itself", webp.clear_marks.isEnabled(), False)
webp._clear_bookmarks()
check("clearing nothing does nothing", shell.marks_changed, 1)

print("\nthe type-the-word gate")
real = st.GoodbyeDialog(view, "Delete", "body")
check("OK starts disabled", real.ok.isEnabled(), False)
real.entry.setText("goodby")
check("a near miss stays disabled", real.ok.isEnabled(), False)
real.entry.setText("GOODBYE")
check("the word enables it, any case", real.ok.isEnabled())
real.entry.setText("")
check("clearing it disables again", real.ok.isEnabled(), False)
real.reject()

print("\nsearch jumps to the first match, on every keystroke")
check("the index found real controls", len(view._index()) > 40)
for query, page_key, expect in (("tray", "window", "tray"),
                                ("cook", "web", "cookies"),
                                ("whisper", "messaging", "Whisper"),
                                ("monitor", "window", "monitor")):
    view.search.setText(query)
    app.processEvents()
    check(f"{query!r} lands on {page_key}", view.current, page_key)
    check(f"and highlights the {expect} control",
          expect.lower() in view._highlighted.text().lower())
# a prefix match beats a mention buried in a sentence
view.search.setText("web")
app.processEvents()
check("'web' finds the PAGE, not a sentence mentioning it",
      view._highlighted.text(), "Web apps")
# nothing found must not move you somewhere arbitrary
was = view.current
view.search.setText("zzzznothing")
app.processEvents()
check("a miss says so", view.hits.text(), "no match")
check("and leaves you where you were", view.current, was)
check("with nothing highlighted", view._highlighted, None)
view.search.setText("")
app.processEvents()
check("clearing the box clears the count", view.hits.text(), "")

print("\nnuclear actions route through the shell, not the page")
view.select("toolbox")
app.processEvents()
tb = view.stack.currentWidget()
tb._del_all()
check("delete-all asks the shell to wipe", shell.wiped, 1)

bm.BOOKMARKS_PATH.unlink(missing_ok=True)

print()
if fails:
    print(f"{len(fails)} FAILURES:")
    for f in fails:
        print("   ", f)
    sys.exit(1)
print("ALL QT SETTINGS CHECKS PASSED")
