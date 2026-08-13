"""Modal dialogs the shell owns.

Sign-in is the only one that talks to the network, and the rule it exists to
enforce is worth stating at the top: the password is read from the field,
sent to warframe.market once, and dropped. It is never written to disk, never
put in the settings, and never handed to a tool - only the session token that
comes back is kept, and tools reach the API through the host's gateway rather
than ever seeing that either.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QButtonGroup, QDialog, QHBoxLayout, QLineEdit,
                               QPushButton, QRadioButton, QVBoxLayout, QWidget)

from core import session as core_session
from core import theme as t
from ui import work
from ui.widgets import hairline, label

PLATFORMS = ("pc", "xbox", "ps4", "switch")


class LoginForm(QWidget):
    """The warframe.market sign-in form, shared by LoginDialog and the
    setup wizard. Emits linked(Session) on success; failures stay inline."""

    linked = Signal(object)          # Session

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._job = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(t.SP_MD)

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

        self.status = label("", role="small")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
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
        self.ok.setEnabled(True)
        self.ok.setText("Sign in")
        self.linked.emit(session)


class LoginDialog(QDialog):
    """Link a warframe.market account. A thin modal wrapper around
    LoginForm: heading + blurb + Cancel, closing Accepted on success."""

    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.session = None
        self.setWindowTitle("Link warframe.market account")
        self.setModal(True)
        self.setMinimumWidth(t.DIALOG_MIN_W)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(t.SP_XL, t.SP_XL, t.SP_XL, t.SP_XL)
        lay.setSpacing(t.SP_MD)
        lay.addWidget(label("Link your warframe.market account", role="h2"))
        blurb = label("Credentials are sent only to api.warframe.market. "
                      "Your password is never saved — only the session "
                      "token is kept.", role="muted")
        blurb.setWordWrap(True)
        lay.addWidget(blurb)
        lay.addWidget(hairline())

        self.form = LoginForm(self)
        self.form.linked.connect(self._linked)
        lay.addWidget(self.form)

        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        lay.addLayout(row)

    def _linked(self, session) -> None:
        self.session = session
        self.accept()
