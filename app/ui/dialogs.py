"""Modal dialogs the shell owns.

Sign-in is the only one that talks to the network, and the rule it exists to
enforce is worth stating at the top: the password is read from the field,
sent to warframe.market once, and dropped. It is never written to disk, never
put in the settings, and never handed to a tool - only the session token that
comes back is kept, and tools reach the API through the host's gateway rather
than ever seeing that either.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QButtonGroup, QDialog, QHBoxLayout, QLineEdit,
                               QPushButton, QRadioButton, QVBoxLayout)

from core import session as core_session
from core import theme as t
from ui import work
from ui.widgets import hairline, label

PLATFORMS = ("pc", "xbox", "ps4", "switch")


class LoginDialog(QDialog):
    """Link a warframe.market account.

    The sign-in call is a network round trip, so it runs on a worker and the
    dialog stays responsive - a modal that freezes while it waits reads as a
    crash, and warframe.market is slow often enough to matter.
    """

    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.session = None
        self._job = None
        self.setWindowTitle("Link warframe.market account")
        self.setModal(True)
        self.setMinimumWidth(t.DIALOG_MIN_W)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(t.SP_XL, t.SP_XL, t.SP_XL, t.SP_XL)
        lay.setSpacing(t.SP_MD)
        lay.addWidget(label("Link your warframe.market account", role="h2"))
        blurb = label("Credentials are sent only to api.warframe.market. Your "
                      "password is never saved — only the session token is "
                      "kept.", role="muted")
        blurb.setWordWrap(True)
        lay.addWidget(blurb)
        lay.addWidget(hairline())

        prev = core_session.load()

        lay.addWidget(label("Email", role="small"))
        self.email = QLineEdit(prev.email if prev and prev.email else "")
        lay.addWidget(self.email)

        lay.addWidget(label("Password", role="small"))
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        lay.addWidget(self.password)

        lay.addWidget(label("Platform", role="small"))
        row = QHBoxLayout()
        row.setSpacing(t.SP_LG)
        self.platforms = QButtonGroup(self)
        want = prev.platform if prev else "pc"
        for name in PLATFORMS:
            b = QRadioButton(name)
            b.setChecked(name == want)
            self.platforms.addButton(b)
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)

        # The token is stored app-locally by design (everything the app writes
        # lives under its own folder), so the old "outside your user profile"
        # warning was removed - it flagged a deliberate choice as a problem.
        self.status = label("", role="small")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        self.ok = QPushButton("Sign in")
        self.ok.setProperty("kind", "money")
        self.ok.setDefault(True)
        self.ok.setCursor(Qt.PointingHandCursor)
        self.ok.clicked.connect(self._submit)
        buttons.addWidget(self.ok)
        lay.addLayout(buttons)

        # focus the field that still needs filling in
        (self.password if prev and prev.email else self.email).setFocus()

    def platform(self) -> str:
        button = self.platforms.checkedButton()
        return button.text() if button else "pc"

    def _submit(self) -> None:
        email = self.email.text().strip()
        password = self.password.text()
        if not email or not password:
            self._say("Email and password are required.", "err")
            return
        self.ok.setEnabled(False)
        self.ok.setText("Signing in…")
        self._say("")
        platform = self.platform()
        self._job = work.run(
            lambda: core_session.login(email, password, platform),
            self._ok, self._failed)

    def _say(self, text: str, level: str = "") -> None:
        self.status.setText(text)
        self.status.setStyleSheet(
            f"color: {t.ERR if level == 'err' else t.MUTED};")

    def _failed(self, message: str) -> None:
        self.ok.setEnabled(True)
        self.ok.setText("Sign in")
        self._say(message, "err")

    def _ok(self, session) -> None:
        self.session = session
        self.accept()
