"""A drawer that slides in from the right, over whatever is behind it.

Built for the web tabs, where "whatever is behind it" is a Chromium surface
rather than ordinary Qt painting. Two things follow from that:

  * The panel must be RAISED explicitly. A QWebEngineView composites through
    its own delegate widget, and a sibling added later is not automatically
    on top of it.
  * Clicks outside the panel cannot be caught with an event filter on the
    page, because mouse events inside the web view are consumed by Chromium
    and never surface as Qt events the parent can inspect. So the drawer
    brings a SCRIM - a full-size widget underneath it that swallows the click
    and closes the panel. That is why the standard drawer pattern has one,
    and it doubles as the dimming that says "this is modal-ish".

Everything here is geometry and animation; what goes IN the drawer is the
caller's business.
"""

from __future__ import annotations

from PySide6.QtCore import (QEasingCurve, QEvent, QPropertyAnimation, QRect,
                            Qt, Signal)
from PySide6.QtWidgets import QVBoxLayout, QWidget

from core import theme as t

WIDTH = 320
SLIDE_MS = 180


class Scrim(QWidget):
    """A full-size click catcher that also dims the page behind the drawer."""

    clicked = Signal()

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"background: {t.SCRIM};")
        self.setCursor(Qt.ArrowCursor)
        self.hide()

    def mousePressEvent(self, event) -> None:
        self.clicked.emit()
        event.accept()


class SlideOver(QWidget):
    """A right-hand drawer. `body` is the layout callers fill."""

    closed = Signal()

    def __init__(self, parent: QWidget, width: int = WIDTH) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._width = width
        self._open = False
        self.setProperty("surface", "drawer")
        self.setStyleSheet(
            f"QWidget[surface=\"drawer\"] {{ background: {t.PANEL};"
            f" border-left: 1px solid {t.HAIRLINE}; }}")

        self.scrim = Scrim(parent)
        self.scrim.clicked.connect(self.close_panel)

        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(0)

        self._anim = QPropertyAnimation(self, b"geometry", self)
        self._anim.setDuration(SLIDE_MS)
        # decelerating: it arrives rather than stops, which is what makes a
        # drawer feel attached to the edge instead of teleported
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        # connected ONCE. Disconnecting and reconnecting per close warns
        # ("Failed to disconnect (None) from signal") the first time round,
        # and the handler can just ask whether the drawer is still shut.
        self._anim.finished.connect(self._finish_close)
        self.hide()
        parent.installEventFilter(self)

    # -- geometry ------------------------------------------------------------

    def _rects(self) -> tuple[QRect, QRect]:
        """(off screen, on screen), in the parent's coordinates."""
        p = self.parentWidget().rect()
        return (QRect(p.width(), 0, self._width, p.height()),
                QRect(p.width() - self._width, 0, self._width, p.height()))

    def eventFilter(self, obj, event):
        # follow the parent when the window resizes, or the drawer would hang
        # off the edge after a maximise
        if obj is self.parentWidget() and event.type() == QEvent.Resize:
            self.scrim.setGeometry(self.parentWidget().rect())
            if self._open:
                self.setGeometry(self._rects()[1])
        return False

    # -- open / close --------------------------------------------------------

    def is_open(self) -> bool:
        return self._open

    def open_panel(self) -> None:
        if self._open:
            return
        self._open = True
        off, on = self._rects()
        self.scrim.setGeometry(self.parentWidget().rect())
        self.scrim.show()
        self.scrim.raise_()
        self.setGeometry(off)
        self.show()
        # explicitly, and AFTER show(): a QWebEngineView sibling is not
        # otherwise guaranteed to be underneath us
        self.raise_()
        self.setFocus(Qt.OtherFocusReason)
        self._anim.stop()
        self._anim.setStartValue(off)
        self._anim.setEndValue(on)
        self._anim.start()

    def close_panel(self) -> None:
        if not self._open:
            return
        self._open = False
        off, on = self._rects()
        self._anim.stop()
        self._anim.setStartValue(self.geometry())
        self._anim.setEndValue(off)
        self._anim.start()
        self.scrim.hide()
        self.closed.emit()

    def _finish_close(self) -> None:
        """Fires at the end of EVERY animation, opening included - so it asks
        the state rather than assuming. A re-open that lands mid-close must
        win, or the drawer would slide in and then vanish."""
        if not self._open:
            self.hide()

    def toggle(self) -> None:
        self.close_panel() if self._open else self.open_panel()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self.close_panel()
            event.accept()
            return
        super().keyPressEvent(event)
