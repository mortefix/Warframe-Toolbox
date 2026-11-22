"""ui/wizard.py - the first-launch setup wizard (also run from Settings).

Placement only: every sentence and the detection rules live in
core/onboarding.py. Four pages in a QStackedWidget - Welcome, Warframe.com
profile, warframe.market, AlecaFrame Data. No page can block progress: the
account steps are skippable and closing the dialog counts as done (the
shell sets the `welcomed` flag on close, whatever the path here).

The profile page touches QtWebEngine only when it is first shown, through
WarframeCaptureWidget.start() - constructing the wizard needs no web stack,
which keeps first-launch cost low and lets the offscreen tests build it
with QtWebEngine forbidden.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QPushButton,
                               QStackedWidget, QVBoxLayout, QWidget)

from core import onboarding
from core import theme as t
from ui.dialogs import LoginForm
from ui.widgets import hairline, label, restyle

#: page indices, in visit order
WELCOME, PROFILE, MARKET, DATA = range(4)


class WelcomeWizard(QDialog):
    def __init__(self, parent,
                 get_session: Callable[[], object | None],
                 adopt_session: Callable[[object], None],
                 set_account_id: Callable[[str], None]) -> None:
        super().__init__(parent)
        self._get_session = get_session
        self._adopt_session = adopt_session
        self._set_account_id = set_account_id
        self._capture = None            # built on first entry to PROFILE
        self._profile_done = False      # an account ID was captured this run

        self.setWindowTitle("Warframe Toolbox setup")
        self.setModal(True)
        self.resize(760, 640)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(*t.DIALOG_MARGINS)
        lay.setSpacing(t.SP_MD)

        self.stack = QStackedWidget(self)
        self.stack.addWidget(self._page_welcome())
        self.stack.addWidget(self._page_profile())
        self.stack.addWidget(self._page_market())
        self.stack.addWidget(self._page_data())
        lay.addWidget(self.stack, 1)
        lay.addWidget(hairline())

        rail = QHBoxLayout()
        self.back_btn = QPushButton("Back")
        self.back_btn.clicked.connect(self._back)
        rail.addWidget(self.back_btn)
        # bottom left: the step's success line, in the OK colour. Empty until
        # the step on screen has actually succeeded (see _sync_rail).
        self.done_note = label("", role="small", level="ok")
        rail.addWidget(self.done_note)
        rail.addStretch(1)
        self.skip_btn = QPushButton("Skip")
        self.skip_btn.clicked.connect(self._advance)
        rail.addWidget(self.skip_btn)
        self.next_btn = QPushButton("Next")
        self.next_btn.setProperty("kind", "money")
        self.next_btn.setCursor(Qt.PointingHandCursor)
        self.next_btn.clicked.connect(self._next)
        rail.addWidget(self.next_btn)
        lay.addLayout(rail)

        self._sync_rail()

    # -- pages ----------------------------------------------------------------

    def _page_welcome(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        # no inset of its own: the dialog's margin already frames the page,
        # and Qt's default here (11px) pushed every page's text out of line
        # with the hairline and the button rail below it
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(t.SP_MD)
        lay.addWidget(label(onboarding.WELCOME_TITLE, role="h1"))
        body = label(onboarding.WELCOME_BODY, role="body")
        body.setWordWrap(True)
        lay.addWidget(body)
        lay.addStretch(1)
        return page

    def _page_profile(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        # no inset of its own: the dialog's margin already frames the page,
        # and Qt's default here (11px) pushed every page's text out of line
        # with the hairline and the button rail below it
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(t.SP_MD)
        lay.addWidget(label(onboarding.PROFILE_TITLE, role="h2"))
        body = label(onboarding.PROFILE_BODY, role="muted")
        body.setWordWrap(True)
        lay.addWidget(body)
        self.profile_note = label("", role="small")
        self.profile_note.setWordWrap(True)
        lay.addWidget(self.profile_note)
        self._profile_holder = QVBoxLayout()
        lay.addLayout(self._profile_holder, 1)
        return page

    def _page_market(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        # no inset of its own: the dialog's margin already frames the page,
        # and Qt's default here (11px) pushed every page's text out of line
        # with the hairline and the button rail below it
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(t.SP_MD)
        lay.addWidget(label(onboarding.MARKET_TITLE, role="h2"))
        body = label(onboarding.MARKET_BODY, role="muted")
        body.setWordWrap(True)
        lay.addWidget(body)
        self.market_note = label("", role="small")
        lay.addWidget(self.market_note)
        self.market_form = LoginForm(page)
        self.market_form.linked.connect(self._market_linked)
        lay.addWidget(self.market_form)
        lay.addStretch(1)
        return page

    def _page_data(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        # no inset of its own: the dialog's margin already frames the page,
        # and Qt's default here (11px) pushed every page's text out of line
        # with the hairline and the button rail below it
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(t.SP_MD)
        lay.addWidget(label(onboarding.DATA_TITLE, role="h2"))
        body = label(onboarding.DATA_BODY, role="muted")
        body.setWordWrap(True)
        lay.addWidget(body)
        self.game_files_line = label("", role="small")
        lay.addWidget(self.game_files_line)
        self.inventory_line = label("", role="small")
        lay.addWidget(self.inventory_line)
        retry_row = QHBoxLayout()
        retry = QPushButton("Retry")
        retry.clicked.connect(self._refresh_data)
        retry_row.addWidget(retry)
        retry_row.addStretch(1)
        lay.addLayout(retry_row)
        notice = label(onboarding.ALECAFRAME_NOTICE, role="muted")
        notice.setWordWrap(True)
        lay.addWidget(notice)
        lay.addStretch(1)
        return page

    # -- flow -----------------------------------------------------------------

    def _next(self) -> None:
        if self.stack.currentIndex() == DATA:
            self.accept()
            return
        self._advance()

    def _advance(self) -> None:
        self._leave(self.stack.currentIndex())
        self.stack.setCurrentIndex(self.stack.currentIndex() + 1)
        self._enter(self.stack.currentIndex())
        self._sync_rail()

    def _back(self) -> None:
        self._leave(self.stack.currentIndex())
        self.stack.setCurrentIndex(self.stack.currentIndex() - 1)
        self._enter(self.stack.currentIndex())
        self._sync_rail()

    def _leave(self, index: int) -> None:
        # The profile capture keeps polling after its page is left. The ID
        # arrives a few seconds after the site shows you as signed in (one
        # poll starts the request, a later one reads the answer), and stopping
        # here meant that pressing Next in that gap lost it for good: the
        # wizard finished with a signed-in browser and no account ID. It stops
        # when it has the ID, or when the wizard closes (accept / reject).
        pass

    def _enter(self, index: int) -> None:
        if index == PROFILE:
            self._start_capture()
        elif index == MARKET:
            self._sync_market()
        elif index == DATA:
            self._refresh_data()

    def _sync_rail(self) -> None:
        index = self.stack.currentIndex()
        self.back_btn.setVisible(index > WELCOME)
        self.skip_btn.setVisible(index in (PROFILE, MARKET))
        self.next_btn.setText("Finish" if index == DATA else "Next")
        done = ""
        if index == PROFILE and self._profile_done:
            done = onboarding.PROFILE_SUCCESS
        elif index == MARKET and self._get_session() is not None:
            done = onboarding.MARKET_SUCCESS.format(
                name=self._get_session().username)
        waiting = ""
        # only while the sign-in page is actually on screen: the capture's
        # own veil speaks for "loading" and "couldn't reach the site", and
        # the page note for "signed in, but no ID" (see _profile_status)
        if index == PROFILE and not done and self._capture is not None \
                and self._capture.state == "ready":
            waiting = onboarding.PROFILE_WAITING
        self.done_note.setText(done or waiting)
        # green only for a success; the "still waiting" hint is plain
        level = "ok" if done else ""
        if self.done_note.property("level") != level:
            self.done_note.setProperty("level", level)
            restyle(self.done_note)
        # nothing left to skip once the step has succeeded
        if done:
            self.skip_btn.setVisible(False)

    def reject(self) -> None:
        if self._capture is not None:
            self._capture.stop()
        super().reject()

    def accept(self) -> None:
        if self._capture is not None:
            self._capture.stop()
        super().accept()

    # -- page behaviour ---------------------------------------------------------

    def _start_capture(self) -> None:
        if self._capture is None:
            try:
                from ui.wf_connect import WarframeCaptureWidget
            except Exception:                               # noqa: BLE001
                self.profile_note.setText(onboarding.PROFILE_FALLBACK)
                return
            self._capture = WarframeCaptureWidget(self)
            self._capture.captured.connect(self._profile_captured)
            self._capture.status.connect(self._profile_status)
            self._profile_holder.addWidget(self._capture, 1)
        if not self._capture.start():
            self.profile_note.setText(onboarding.PROFILE_FALLBACK)

    def _profile_status(self, state: str) -> None:
        """The sign-in page changed state. Only 'stuck' needs words from the
        wizard (the page itself shows loading and failure); every change
        re-evaluates the rail's waiting line."""
        if state == "stuck":
            self._set_profile_note(onboarding.PROFILE_STUCK, "warn")
        self._sync_rail()

    def _set_profile_note(self, text: str, level: str = "") -> None:
        self.profile_note.setText(text)
        if (self.profile_note.property("level") or "") != level:
            self.profile_note.setProperty("level", level)
            restyle(self.profile_note)

    def _profile_captured(self, aid: str) -> None:
        self._set_account_id(aid)
        self._set_profile_note(onboarding.PROFILE_DONE)
        self._profile_done = True
        self._sync_rail()

    def _sync_market(self) -> None:
        sess = self._get_session()
        if sess is not None:
            self.market_note.setText(
                onboarding.MARKET_LINKED.format(name=sess.username))
        else:
            self.market_note.setText("")

    def _market_linked(self, session) -> None:
        self._adopt_session(session)
        self._sync_market()
        self._sync_rail()

    def _refresh_data(self) -> None:
        s = onboarding.detect()
        self.game_files_line.setText(
            onboarding.GAME_FILES_OK if s.game_files
            else onboarding.GAME_FILES_MISSING)
        self.game_files_line.setStyleSheet(
            f"color: {t.OK if s.game_files else t.WARN};")
        self.inventory_line.setText(
            onboarding.INVENTORY_OK.format(source=s.source) if s.inventory
            else onboarding.INVENTORY_MISSING)
        self.inventory_line.setStyleSheet(
            f"color: {t.OK if s.inventory else t.WARN};")
