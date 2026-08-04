"""The autocomplete popup, reproduced key-for-key from the Tk SuggestBox.

Deliberately NOT QCompleter. Its popup takes a keyboard grab, which breaks the
one behaviour this control is defined by:

    Down moves into the list WITHOUT closing the popup and WITHOUT running a
    search, and Up/Down inside the list only browse - nothing is chosen until
    Enter or a click.

That matters because the search fires on every keystroke: if arrowing through
the list counted as typing, browsing five suggestions would fire five
searches. So the popup is a plain frameless QListWidget positioned by hand.

Tk placed it with `place(in_=entry, relx=0, rely=1.0, ...)`, which has no Qt
analogue. Here it is a top-level Qt.Popup mapped from the entry's bottom-left,
which also gets click-outside dismissal for free.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer
from PySide6.QtWidgets import (QApplication, QLineEdit, QListWidget,
                               QListWidgetItem)

MIN_WIDTH = 300        # Tk: width=max(300, entry width)
MAX_ROWS = 8           # Tk: height=min(8, len(items))
GAP = 3                # Tk: y=3 below the entry

#: Keys that must NOT re-run the search when released. The Tk original spells
#: this out as _NAV_KEYS; the same idea, in Qt's vocabulary.
NAV_KEYS = frozenset({
    Qt.Key_Up, Qt.Key_Down, Qt.Key_Left, Qt.Key_Right,
    Qt.Key_Return, Qt.Key_Enter, Qt.Key_Escape, Qt.Key_Tab, Qt.Key_Backtab,
    Qt.Key_Shift, Qt.Key_Control, Qt.Key_Alt, Qt.Key_Meta,
    Qt.Key_Home, Qt.Key_End, Qt.Key_PageUp, Qt.Key_PageDown,
})


class SuggestBox:
    """Attaches to a QLineEdit. `supplier(query)` returns [(label, payload)];
    `on_pick(label, payload)` fires on Enter or click."""

    def __init__(self, entry: QLineEdit,
                 supplier: Callable[[str], list[tuple[str, object]]],
                 on_pick: Callable[[str, object], None]) -> None:
        self.entry = entry
        self.supplier = supplier
        self.on_pick = on_pick
        self.items: list[tuple[str, object]] = []

        # A CHILD WIDGET, not a Qt.Popup window. Showing a popup window
        # activates it and takes focus off the entry, which fires FocusOut,
        # hides the popup again and leaves typing going nowhere. A child only
        # takes focus when something calls setFocus() - which is exactly what
        # Down should do and nothing else should. This is the arrangement the
        # Tk original used (a Listbox parented to the tab frame).
        # NB: no parent yet. entry.window() is WRONG here - this runs while
        # the owning tab is still being constructed, so the entry has no
        # parent chain and window() returns the entry ITSELF. The list then
        # becomes a child of the 280x25 search box and is clipped out of
        # existence, while isVisible() still cheerfully reports True.
        # The real window is resolved lazily in _place().
        self.list = QListWidget()
        self.list.setProperty("role", "suggest")   # styled in ui/qss.py
        self.list.setFocusPolicy(Qt.StrongFocus)   # Down browses inside it
        self.list.setUniformItemSizes(True)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.hide()
        self.list.itemClicked.connect(lambda it: self._pick(self.list.row(it)))

        entry.installEventFilter(_EntryFilter(self))
        self.list.installEventFilter(_ListFilter(self))
        self._filters = (entry, self.list)       # keep the filters referenced
        # _place() reparents the list to the top-level window (so the popup is
        # not clipped by the tiny search box), which lifts it OUT of the owning
        # tab's subtree - so when the tab is dropped (unlink / adopt / wipe)
        # nothing deletes the list and it leaks, along with its _ListFilter.
        # Tie its lifetime to the entry, which DOES die with that subtree.
        entry.destroyed.connect(self.list.deleteLater)

    # -- population ----------------------------------------------------------

    def refresh(self) -> None:
        """Re-query the supplier for the entry's current text."""
        text = self.entry.text().strip()
        self.items = list(self.supplier(text)) if text else []
        if not self.items:
            self.hide()
            return
        self.list.clear()
        for lbl, _payload in self.items:
            # two leading spaces, as in the Tk original
            self.list.addItem(QListWidgetItem(f"  {lbl}"))
        self._place()
        self.list.show()
        self.list.setCurrentRow(-1)              # nothing selected until Down

    def _place(self) -> None:
        """Just under the entry, in WINDOW coordinates - the Qt equivalent of
        Tk's place(in_=entry, relx=0, rely=1.0, y=3)."""
        window = self.entry.window()
        # Reparent on first use: only now is the entry actually inside the
        # window it will live in, so only now is window() meaningful.
        if self.list.parentWidget() is not window:
            self.list.setParent(window)
        below = self.entry.mapTo(window, QPoint(0, self.entry.height() + GAP))
        width = max(MIN_WIDTH, self.entry.width())
        rows = min(MAX_ROWS, len(self.items))
        row_h = self.list.sizeHintForRow(0) if self.list.count() else 20
        self.list.setGeometry(below.x(), below.y(), width,
                              rows * row_h + 2 * self.list.frameWidth())
        self.list.raise_()          # above its siblings, as Tk's lift() did

    def hide(self) -> None:
        self.list.hide()

    def _maybe_hide(self) -> None:
        """Hide unless focus went INTO the list. Checked a turn later because
        focusOut fires before the new focus widget is set."""
        focus = QApplication.focusWidget()
        if focus is not self.list and focus is not self.entry:
            self.hide()

    def visible(self) -> bool:
        return self.list.isVisible()

    # -- selection -----------------------------------------------------------

    def _pick(self, row: int) -> None:
        if 0 <= row < len(self.items):
            label, payload = self.items[row]
            self.hide()
            self.entry.setFocus()
            self.on_pick(label, payload)

    def enter_list(self) -> None:
        """Down from the entry: step into the list. Does NOT close the popup
        and does NOT run a search - browsing is not choosing."""
        if self.visible() and self.list.count():
            self.list.setCurrentRow(0)
            self.list.setFocus()


# Qt event filters must be QObjects. Defined after SuggestBox purely so their
# type hints can name it; Python resolves the reference in __init__ at call
# time, so the ordering is fine.


class _EntryFilter(QObject):
    def __init__(self, box: SuggestBox) -> None:
        super().__init__(box.entry)
        self.box = box

    def eventFilter(self, obj, event):
        if event.type() == QEvent.KeyPress:
            key = event.key()
            if key == Qt.Key_Down:
                self.box.enter_list()
                return True                      # swallow: no search
            if key in (Qt.Key_Return, Qt.Key_Enter):
                if self.box.visible():
                    self.box._pick(0)            # Enter takes the first hit
                    return True
            elif key == Qt.Key_Escape:
                if self.box.visible():
                    self.box.hide()
                    return True
        elif event.type() == QEvent.KeyRelease:
            # the search runs here, but never for navigation keys
            if event.key() not in NAV_KEYS:
                self.box.refresh()
        elif event.type() == QEvent.FocusOut:
            # NOT an unconditional hide: Down moves focus into the list, and
            # hiding here is what made the popup flash and vanish
            QTimer.singleShot(0, self.box._maybe_hide)
        return False


class _ListFilter(QObject):
    def __init__(self, box: SuggestBox) -> None:
        super().__init__(box.list)
        self.box = box

    def eventFilter(self, obj, event):
        if event.type() == QEvent.KeyPress:
            key = event.key()
            if key in (Qt.Key_Return, Qt.Key_Enter):
                self.box._pick(self.box.list.currentRow())
                return True
            if key == Qt.Key_Escape:
                self.box.hide()
                self.box.entry.setFocus()
                return True
            if key == Qt.Key_Up and self.box.list.currentRow() == 0:
                # back out of the list at its top, as Tk's focus model did
                self.box.entry.setFocus()
                return True
        return False
