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
from ui.widgets import hairline, label

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

        self.setWindowTitle("Warframe Toolbox setup")
        self.setModal(True)
        self.resize(760, 640)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(t.SP_XL, t.SP_XL, t.SP_XL, t.SP_XL)
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
        if index == PROFILE and self._capture is not None:
            self._capture.stop()

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
            self._profile_holder.addWidget(self._capture, 1)
        if not self._capture.start():
            self.profile_note.setText(onboarding.PROFILE_FALLBACK)

    def _profile_captured(self, aid: str) -> None:
        self._set_account_id(aid)
        self.profile_note.setText(onboarding.PROFILE_DONE)

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
