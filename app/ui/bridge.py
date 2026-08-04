"""Thread bridges for the three places core calls back off the UI thread.

Under Tk these needed `self.after(0, ...)` to hop threads. Qt does it for
free: a `Signal.emit()` from a non-GUI thread is queued to the receiver's
thread automatically, so each bridge is a QObject with one signal and a plain
callable that core can hold.

The core modules themselves need no changes - that was the point of keeping
them toolkit-free.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class PresenceBridge(QObject):
    """core.presence.on_change fires on the websocket's own thread.

    Carries all three arguments core hands over - the state, whether the
    socket is actually up, and a detail line - because "In-game" with a dead
    socket is a different thing from "In-game", and only `connected` can
    tell them apart.
    """
    changed = Signal(str, bool, object)      # state, connected, detail

    def callback(self, state: str, connected: bool, detail) -> None:
        self.changed.emit(state, connected, detail)


class FetchBridge(QObject):
    """core.arcane_market.PriceFetcher reports from a worker thread."""
    progress = Signal(int, int)      # done, total
    finished = Signal(object)        # the price map, or None on failure

    def on_progress(self, done: int, total: int) -> None:
        self.progress.emit(done, total)

    def on_done(self, prices) -> None:
        self.finished.emit(prices)


class TrayBridge(QObject):
    """QSystemTrayIcon already emits on the GUI thread, so this exists only
    so the shell can treat every off-thread source the same way."""
    activated = Signal()

    def callback(self) -> None:
        self.activated.emit()
