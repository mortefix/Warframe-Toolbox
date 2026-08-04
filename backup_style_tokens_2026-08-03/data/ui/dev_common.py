"""ui/dev_common.py - shared scaffolding for the Dev data-explorer views.

These are READ-ONLY inspectors over the local collected-data store (core.store):
each shows what a source adapter has cached, so we can see the data before any
production screen is built on it. Deliberately plain - a title, a Refresh button
that re-runs the source off-thread, a freshness line, and a scrolling column of
label/value cards. For large libraries (mods, mastery-XP records, fissures) these
enumerate a COUNT rather than every row: they are dev panels, not inventory UI.
"""

from __future__ import annotations

import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from core import store
from core import theme as t
from ui import work
from ui.widgets import label, panel


def fmt_epoch(seconds) -> str:
    """A UTC timestamp string for an epoch-seconds value, or an em dash."""
    if not seconds:
        return "—"
    try:
        return time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(seconds))
    except (ValueError, OSError, TypeError):
        return "—"


def fmt_age(seconds) -> str:
    """'updated 5m ago' / 'not collected yet' for a store namespace's age."""
    if seconds is None:
        return "not collected yet"
    s = int(seconds)
    if s < 60:
        return f"updated {s}s ago"
    if s < 3600:
        return f"updated {s // 60}m ago"
    if s < 86400:
        return f"updated {s // 3600}h ago"
    return f"updated {s // 86400}d ago"


class Card(QWidget):
    """A titled panel of label/value rows - the one building block here."""

    def __init__(self, title: str, rows) -> None:
        super().__init__()
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setProperty("surface", "card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(t.SP_XL, t.SP_LG, t.SP_XL, t.SP_LG)
        lay.setSpacing(t.SP_MD)
        lay.addWidget(label(title, role="h2"))
        rows = list(rows)
        if not rows:
            lay.addWidget(label("—", role="muted"))
            return
        grid = QGridLayout()
        grid.setHorizontalSpacing(t.SP_LG)
        grid.setVerticalSpacing(t.SP_SM)
        grid.setColumnStretch(1, 1)
        for i, (key, value) in enumerate(rows):
            cap = label(str(key), role="muted")
            grid.addWidget(cap, i, 0, Qt.AlignTop)
            val = label(str(value), role="body")
            val.setWordWrap(True)
            grid.addWidget(val, i, 1)
        lay.addLayout(grid)


class DevView(QWidget):
    """Base inspector: header (title + Refresh + freshness) over a scrolling
    column of Cards. Subclasses set TITLE + NAMESPACE and implement build_cards()
    (reads the store, on the GUI thread) and refresh_source() (runs on a worker).
    """

    TITLE = "Dev"
    NAMESPACE = ""
    ICON = ""              # optional core.theme.ICONS key shown in the header

    def __init__(self, view=None) -> None:
        # `view` is the SettingsView when hosted as a DevTools page; ignored -
        # these read the store directly and own no settings.
        super().__init__()
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._job = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        head = QHBoxLayout()
        head.setContentsMargins(t.SP_SCREEN, t.SP_XL, t.SP_SCREEN, t.SP_MD)
        head.setSpacing(t.SP_MD)
        if self.ICON:
            icon = label(t.glyph(self.ICON), role="icon")
            head.addWidget(icon)
        head.addWidget(label(self.TITLE, role="h1"))
        self.freshness = label("", role="small")
        head.addWidget(self.freshness)
        head.addStretch(1)
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setProperty("size", "small")
        self.refresh_btn.setCursor(Qt.PointingHandCursor)
        self.refresh_btn.clicked.connect(self._on_refresh)
        head.addWidget(self.refresh_btn)
        outer.addLayout(head)

        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = panel()
        self.body = QVBoxLayout(inner)
        self.body.setContentsMargins(t.SP_SCREEN, 0, t.SP_SCREEN, t.SP_XL)
        self.body.setSpacing(t.SP_LG)
        area.setWidget(inner)
        outer.addWidget(area, 1)

        self.rebuild()

    def rebuild(self) -> None:
        """Repaint every card from the current store contents."""
        while self.body.count():
            item = self.body.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for card in self.build_cards():
            self.body.addWidget(card)
        self.body.addStretch(1)
        self.freshness.setText(fmt_age(store.age(self.NAMESPACE))
                               if self.NAMESPACE else "")

    def on_show(self) -> None:
        """Re-read the store when the page is (re)opened, so it reflects any
        background refresh that happened while it was hidden. Called by the
        Settings host when this page is selected."""
        self.rebuild()

    def _on_refresh(self) -> None:
        self.refresh_btn.setEnabled(False)
        self.refresh_btn.setText("Refreshing…")
        # Bound-method callbacks: Qt drops them if this view is gone, so a slow
        # network refresh can never fire into a deleted widget (see the
        # wf-toolbox-qt-callback-receiver rule).
        self._job = work.run(self.refresh_source, self._refreshed,
                             self._refreshed)

    def _refreshed(self, _result) -> None:
        self.refresh_btn.setEnabled(True)
        self.refresh_btn.setText("Refresh")
        self.rebuild()

    # -- subclass hooks ------------------------------------------------------

    def build_cards(self) -> list:
        return []

    def refresh_source(self):
        return None
