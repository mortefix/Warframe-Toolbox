"""The Warframe.com auto-capture dialog's state machine, offscreen and with NO
network: the probe results are fed to _got() directly (about:blank is loaded so
no real request is made), which is where the WAIT/ERR/HTML/JSON handling lives.

The account-id extraction itself is covered in test_wf_profile; here we prove the
dialog captures once, on the first valid JSON, and ignores everything after."""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS",
                      "--disable-gpu --disable-software-rasterizer "
                      "--no-sandbox --in-process-gpu")

try:
    from PySide6.QtWidgets import QApplication
    from PySide6.QtWebEngineWidgets import QWebEngineView          # noqa: F401
except ImportError:
    print("PySide6 (WebEngine) not installed - skipping wf_connect checks")
    raise SystemExit(0)

fails = []


def check(name, got, want=True):
    ok = got == want
    if not ok:
        fails.append(f"{name}: got {got!r}, want {want!r}")
    print(f"  {'ok  ' if ok else 'FAIL'} {name}")


app = QApplication([])
from ui import web as ui_web                                       # noqa: E402
ui_web.isolate_for_tests()        # NEVER the running app's profile
from ui import wf_connect                                          # noqa: E402

# about:blank so constructing the dialog makes no network request; we drive the
# state machine by hand instead of waiting on the poll timer.
wf_connect.LOGIN_URL = "about:blank"

AID = "5420be04384632143a707618"

captured = []
dlg = wf_connect.ConnectWarframeDialog(None, captured.append)

print("state machine ignores non-final results")
dlg._got("__WAIT__")
dlg._got("__ERR__")
dlg._got("<html><body>please sign in</body></html>")
check("nothing captured before a valid body", captured, [])
check("not marked done", dlg._done, False)

print("\nfirst valid JSON body captures exactly once")
dlg._got(json.dumps({"user_id": AID}))
check("captured the id", captured, [AID])
check("marked done", dlg._done, True)

dlg._got(json.dumps({"user_id": "b" * 24}))
check("later results are ignored once done", captured, [AID])

dlg.reject()

if fails:
    print("\n" + "\n".join(fails))
    raise SystemExit(1)
print("\nall wf_connect checks passed")
