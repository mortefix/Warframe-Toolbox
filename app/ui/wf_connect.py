"""ui/wf_connect.py - one-time capture of your Warframe.com account id.

Opens warframe.com in an embedded browser (the app's shared web profile, so the
login persists exactly as it does in the Wiki/Overframe tabs). While you are
signed in, the site keeps a small `user-info` cookie for its own pages to read
(display name, mastery rank, and `user_id`); a tiny script reads that cookie
and we lift the 24-hex id out of its JSON.

(Until late 2026 the id came from the site's /api/user-data endpoint. That
endpoint now answers 404 even when signed in - measured 2026-11-22 - so the
capture silently never fired: the wizard sat on a signed-in page for ever.
The old request is kept as a fallback, in case it returns.)

No password ever reaches the app: the embedded browser holds the session cookie,
the app only reads the resulting id. This is the automatic path; Settings also
offers a manual copy-paste from the same URL for anyone who prefers it.

Why a poll instead of one shot: runJavaScript cannot await a fetch, so the probe
kicks the fetch off, parks the result on `window`, and each timer tick reads it
back. A tick that finds no id re-arms the fetch, so an AJAX login with no page
navigation is still caught the moment the session cookie appears.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QTimer, QUrl, Signal
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout, QWidget)

from core import theme as t
from core import wf_profile

LOGIN_URL = "https://www.warframe.com/login"

#: Read the signed-in site's own `user-info` cookie; fall back to a same-origin
#: fetch of the old account endpoint. Returns:
#:   <text>      the cookie's JSON, or the endpoint's response body
#:   '__WAIT__'  no cookie, and the fallback fetch is still in flight
#:   '__ERR__'   no cookie, and the endpoint refused us or the fetch threw
_PROBE_JS = """
(function () {
  var m = document.cookie.match(/(?:^|;\\s*)user-info=([^;]*)/);
  if (m) {
    try { return decodeURIComponent(m[1]); } catch (e) { return m[1]; }
  }
  if (typeof window.__wfCap === 'undefined') {
    window.__wfCap = null;
    fetch('/api/user-data', {credentials: 'include'})
      .then(function (r) { return r.ok ? r.text() : '__ERR__'; })
      .then(function (t) { window.__wfCap = t; })
      .catch(function () { window.__wfCap = '__ERR__'; });
    return '__WAIT__';
  }
  return window.__wfCap === null ? '__WAIT__' : window.__wfCap;
})();
"""

#: One poll starts the request and a later one reads the answer, so the ID
#: lands two polls after sign-in at best. 1500 ms made that a 3-second wait.
_POLL_MS = 700


class WarframeCaptureWidget(QWidget):
    """The embedded warframe.com login + account-id capture, shared by
    ConnectWarframeDialog and the setup wizard. Nothing web-related is
    created until start(), so constructing (and importing) this widget
    needs no QtWebEngine."""

    captured = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._done = False
        self.view = None
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(t.SP_MD)
        self._timer = QTimer(self)
        self._timer.setInterval(_POLL_MS)
        self._timer.timeout.connect(self._probe)

    def start(self) -> bool:
        """Bring up the embedded browser. False when QtWebEngine is
        unavailable - the caller shows its fallback copy instead."""
        if self.view is not None:
            if not self._done:
                self._timer.start()
            return True
        try:
            from PySide6.QtWebEngineCore import QWebEnginePage
            from PySide6.QtWebEngineWidgets import QWebEngineView
            from ui import web as ui_web
        except Exception:                                   # noqa: BLE001
            return False
        self.view = QWebEngineView(self)
        self.view.setPage(QWebEnginePage(ui_web.profile(), self.view))
        self._lay.addWidget(self.view, 1)
        self.view.load(QUrl(LOGIN_URL))
        self._timer.start()
        return True

    def stop(self) -> None:
        self._timer.stop()

    def _probe(self) -> None:
        if self._done or self.view is None:
            return
        page = self.view.page()
        if page is not None:
            page.runJavaScript(_PROBE_JS, self._got)

    def _got(self, result) -> None:
        if self._done or not isinstance(result, str):
            return
        if result == "__WAIT__":
            return                     # fetch in flight; look next tick
        aid = (wf_profile.extract_account_id(result)
               if result not in ("__ERR__", "") else None)
        if aid:
            self._done = True
            self._timer.stop()
            self.captured.emit(aid)
            return
        # No id this cycle: re-arm the fetch so the next tick tries again,
        # catching AJAX logins with no navigation.
        if self.view is None:
            return
        page = self.view.page()
        if page is not None:
            page.runJavaScript("window.__wfCap = undefined;")


class ConnectWarframeDialog(QDialog):
    """Modal capture window. Calls `on_captured(account_id)` once, closes.

    Raises RuntimeError if QtWebEngine is unavailable (WarframeCaptureWidget
    itself never raises - only this caller-facing wrapper does, so
    ui.settings._connect_wf's try/except can fall back to the manual
    copy-paste flow instead of showing a permanently blank capture area)."""

    def __init__(self, parent, on_captured: Callable[[str], None]) -> None:
        super().__init__(parent)
        self._on_captured = on_captured
        self.setWindowTitle("Connect Warframe.com")
        self.resize(780, 760)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(*t.DIALOG_MARGINS)
        lay.setSpacing(t.SP_MD)

        self.status = QLabel(
            "Sign in to Warframe.com below. Your account ID is captured "
            "automatically once you're signed in — no password is shared "
            "with the Toolbox.")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)

        self.capture = WarframeCaptureWidget(self)
        self.capture.captured.connect(self._captured)
        lay.addWidget(self.capture, 1)

        row = QHBoxLayout()
        row.addStretch(1)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        row.addWidget(self.cancel_btn)
        lay.addLayout(row)

        if not self.capture.start():
            raise RuntimeError("QtWebEngine unavailable")

    def _captured(self, aid: str) -> None:
        self.status.setText("Account ID captured — you're connected.")
        self._on_captured(aid)
        self.accept()

    def reject(self) -> None:
        self.capture.stop()
        super().reject()
