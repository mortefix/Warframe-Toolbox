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

from core import onboarding
from core import theme as t
from core import wf_profile
from ui.widgets import LoadingVeil, alive

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

#: How long the first page load may take before it is called a failure and
#: the veil offers Try again. Generous: a cold Chromium start on a busy
#: connection has been seen to take half a minute.
_LOAD_TIMEOUT_MS = 60_000
#: How long after a failed load to wait for a replacement load to start
#: before believing the failure (see _load_finished).
_FAIL_GRACE_MS = 1500
#: How long past the login page, with no account ID, before saying so. The
#: ID normally lands within about three seconds of signing in.
_STUCK_MS = 20_000


class WarframeCaptureWidget(QWidget):
    """The embedded warframe.com login + account-id capture, shared by
    ConnectWarframeDialog and the setup wizard. Nothing web-related is
    created until start(), so constructing (and importing) this widget
    needs no QtWebEngine."""

    captured = Signal(str)
    #: The page's state changed: 'loading' (veiled, spinner), 'ready' (the
    #: site is on screen, waiting for a sign-in), 'failed' (veiled, with a
    #: Try again button), 'stuck' (signed in by the look of it, yet no ID -
    #: the page stays usable and the capture keeps trying) or 'done'.
    status = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._done = False
        self.state = ""
        self.view = None
        self._veil = None
        self._loads = 0                 # loadStarted count (see _load_finished)
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(t.SP_MD)
        self._timer = QTimer(self)
        self._timer.setInterval(_POLL_MS)
        self._timer.timeout.connect(self._probe)
        self._load_timer = QTimer(self)
        self._load_timer.setSingleShot(True)
        self._load_timer.setInterval(_LOAD_TIMEOUT_MS)
        self._load_timer.timeout.connect(self._load_timed_out)
        self._stuck_timer = QTimer(self)
        self._stuck_timer.setSingleShot(True)
        self._stuck_timer.setInterval(_STUCK_MS)
        self._stuck_timer.timeout.connect(self._stuck)

    def start(self) -> bool:
        """Bring up the embedded browser. False when QtWebEngine is
        unavailable - the caller shows its fallback copy instead."""
        if self.view is not None:
            if not self._done and self.state != "failed":
                self._timer.start()
            return True
        try:
            from PySide6.QtGui import QColor
            from PySide6.QtWebEngineCore import QWebEnginePage
            from PySide6.QtWebEngineWidgets import QWebEngineView
            from ui import web as ui_web
        except Exception:                                   # noqa: BLE001
            return False
        self.view = QWebEngineView(self)
        page = QWebEnginePage(ui_web.profile(), self.view)
        # the app's own background wherever the site has not painted yet,
        # not Chromium's white (the same choice as the Wiki/Overframe tabs)
        page.setBackgroundColor(QColor(t.BG))
        self.view.setPage(page)
        self._lay.addWidget(self.view, 1)
        # the veil is created AFTER the view so it is the newer sibling and
        # stacks above it
        self._veil = LoadingVeil(self)
        self.view.loadStarted.connect(self._load_started)
        self.view.loadFinished.connect(self._load_finished)
        self.view.urlChanged.connect(self._watch_for_stuck)
        self._load()
        return True

    def stop(self) -> None:
        self._timer.stop()
        self._load_timer.stop()
        self._stuck_timer.stop()

    # -- page states ----------------------------------------------------------

    def _set_state(self, state: str) -> None:
        if state != self.state:
            self.state = state
            self.status.emit(state)

    def _load(self) -> None:
        """(Re)load the sign-in page behind the veil. Also the Try again
        button's action."""
        self._set_state("loading")
        self._veil.loading(onboarding.PROFILE_LOADING)
        self._load_timer.start()
        self.view.load(QUrl(LOGIN_URL))
        self._timer.start()

    def _load_started(self) -> None:
        self._loads += 1

    def _load_finished(self, ok: bool) -> None:
        if self.state != "loading":
            return              # a later navigation inside the site
        if ok:
            self._load_timer.stop()
            self._veil.clear()
            self._set_state("ready")
            self._watch_for_stuck()
            return
        # A load that is REPLACED by another (a redirect done in script)
        # also reports failure, an instant before the replacement starts.
        # Only a failure that nothing follows is a real one.
        seen = self._loads
        QTimer.singleShot(_FAIL_GRACE_MS, lambda: self._confirm_failed(seen))

    def _confirm_failed(self, loads_then: int) -> None:
        if not alive(self) or self.state != "loading":
            return
        if self._loads == loads_then:
            self._fail()

    def _load_timed_out(self) -> None:
        if self.state == "loading":
            self._fail()
            self.view.stop()

    def _fail(self) -> None:
        self._set_state("failed")
        self._timer.stop()
        self._load_timer.stop()
        self._veil.message(onboarding.PROFILE_UNREACHABLE,
                           onboarding.PROFILE_RETRY, self._load)

    def _watch_for_stuck(self, *_args) -> None:
        """Arm (or disarm) the "signed in but no ID" timer from where the
        browser is. Past the site's login page with no ID yet means the
        sign-in worked and the capture has not - which, before this, was an
        endless wait with nothing on screen to say so."""
        if self._done or self.view is None or self.state != "ready":
            return
        url = self.view.url()
        past_login = (url.host().endswith("warframe.com")
                      and "/login" not in url.path())
        if past_login:
            if not self._stuck_timer.isActive():
                self._stuck_timer.start()
        else:
            self._stuck_timer.stop()

    def _stuck(self) -> None:
        # Report it, and keep polling: if the ID does turn up, it is taken.
        if not self._done and self.state == "ready":
            self._set_state("stuck")

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
            self.stop()
            if self._veil is not None:
                self._veil.clear()
            self._set_state("done")
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
        self.capture.status.connect(self._capture_status)
        lay.addWidget(self.capture, 1)

        row = QHBoxLayout()
        row.addStretch(1)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        row.addWidget(self.cancel_btn)
        lay.addLayout(row)

        if not self.capture.start():
            raise RuntimeError("QtWebEngine unavailable")

    def _capture_status(self, state: str) -> None:
        if state == "stuck":
            self.status.setText(onboarding.PROFILE_STUCK)

    def _captured(self, aid: str) -> None:
        self.status.setText("Account ID captured — you're connected.")
        self._on_captured(aid)
        self.accept()

    def reject(self) -> None:
        self.capture.stop()
        super().reject()
