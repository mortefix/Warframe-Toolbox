"""ui/wf_connect.py - one-time capture of your Warframe.com account id.

Opens warframe.com in an embedded browser (the app's shared web profile, so the
login persists exactly as it does in the Wiki/Overframe tabs). While you are
signed in, a tiny script asks the site's OWN same-origin endpoint,
/api/user-data, for your account id - the same request the website makes about
itself - and we lift the 24-hex id out of the JSON.

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

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout)

from core import wf_profile
from ui import web as ui_web

LOGIN_URL = "https://www.warframe.com/login"

#: Same-origin fetch of the site's own account endpoint. Returns:
#:   '__WAIT__'  the fetch is still in flight (or not started this document)
#:   '__ERR__'   the endpoint refused us (not signed in) or the fetch threw
#:   <text>      the response body (JSON when signed in; HTML if redirected)
_PROBE_JS = """
(function () {
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

_POLL_MS = 1500


class ConnectWarframeDialog(QDialog):
    """Modal capture window. Calls `on_captured(account_id)` once, then closes."""

    def __init__(self, parent, on_captured: Callable[[str], None]) -> None:
        super().__init__(parent)
        self._on_captured = on_captured
        self._done = False

        self.setWindowTitle("Connect Warframe.com")
        self.resize(780, 760)
        lay = QVBoxLayout(self)

        self.status = QLabel(
            "Sign in to Warframe.com below. Your account ID is captured "
            "automatically once you're signed in — no password is shared "
            "with the Toolbox.")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)

        self.view = QWebEngineView(self)
        # A page bound to the SHARED profile, so the session cookie lives in the
        # same jar as the rest of the app (and a prior login is reused).
        self.view.setPage(QWebEnginePage(ui_web.profile(), self.view))
        lay.addWidget(self.view, 1)

        row = QHBoxLayout()
        row.addStretch(1)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        row.addWidget(self.cancel_btn)
        lay.addLayout(row)

        self.view.load(QUrl(LOGIN_URL))

        self._timer = QTimer(self)
        self._timer.setInterval(_POLL_MS)
        self._timer.timeout.connect(self._probe)
        self._timer.start()

    def _probe(self) -> None:
        if self._done:
            return
        page = self.view.page()
        if page is not None:
            page.runJavaScript(_PROBE_JS, self._got)

    def _got(self, result) -> None:
        if self._done or not isinstance(result, str):
            return
        if result == "__WAIT__":
            return                              # fetch in flight; look next tick
        aid = (wf_profile.extract_account_id(result)
               if result not in ("__ERR__", "") else None)
        if aid:
            self._done = True
            self._timer.stop()
            self.status.setText("Account ID captured — you're connected.")
            self._on_captured(aid)
            self.accept()
            return
        # No id this cycle (not signed in yet, or a redirect to HTML): re-arm the
        # fetch so the next tick tries again, catching AJAX logins with no nav.
        page = self.view.page()
        if page is not None:
            page.runJavaScript("window.__wfCap = undefined;")

    def reject(self) -> None:
        self._timer.stop()
        super().reject()
