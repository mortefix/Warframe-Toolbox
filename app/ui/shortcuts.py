"""ui/shortcuts.py - the window's keyboard shortcuts.

  Ctrl+1 … Ctrl+9   go to the sidebar's 1st … 9th entry, top to bottom
  Ctrl+0            the 10th (the row of digits, left to right)
  Ctrl+F            put the cursor in the current screen's search box
  F5                refresh the current screen

The screens are not told about any of this. Each already has a search box
and a refresh action reachable from its own buttons; `find_search` and
`refresh` below locate those by the names the screens already use, so a new
screen that follows the same conventions gets both keys for free, and one
that has neither simply ignores them.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QLineEdit, QStackedWidget, QWidget

#: Attribute names a screen (or one of its tabs) gives its search box.
SEARCH_ATTRS = ("search", "search_all", "weapon")

#: A screen's refresh action, by method name and arguments - first match
#: wins. Looked up on the screen itself, then on the tab it is showing.
REFRESH_METHODS = (
    ("refresh_page", ()),
    ("refresh", ()),
    ("refresh_all", ()),            # Market > Watchlist
    ("refresh_inventory", (True,)),  # Vosfor: force a re-read
    ("refresh_source", ()),         # the DevTools explorers
)

MAX_PAGES = 10


def page_hint(index: int) -> str:
    """The shortcut that opens the sidebar's `index`th entry (0-based), as
    text for its tooltip: Ctrl+1 … Ctrl+9, then Ctrl+0 for the tenth, as
    the digit row reads. '' past that."""
    return f"Ctrl+{(index + 1) % 10}" if 0 <= index < MAX_PAGES else ""


def _shown_tab(page: QWidget) -> QWidget | None:
    """The tab a tabbed screen is showing (Market, My Listings, Settings)."""
    stack = getattr(page, "stack", None)
    if isinstance(stack, QStackedWidget):
        return stack.currentWidget()
    return None


def find_search(page: QWidget | None) -> QLineEdit | None:
    """The search box of what is on screen: a visible, enabled QLineEdit
    that some ancestor inside `page` knows by one of SEARCH_ATTRS, or whose
    placeholder says "search". With several, the one nearest the top-left,
    which is where every screen puts its main search."""
    if page is None:
        return None
    found = []
    for edit in page.findChildren(QLineEdit):
        if not edit.isVisibleTo(page) or not edit.isEnabled() \
                or edit.isReadOnly():
            continue
        named = False
        owner = edit.parentWidget()
        while owner is not None and not named:
            named = any(getattr(owner, a, None) is edit for a in SEARCH_ATTRS)
            if owner is page:
                break
            owner = owner.parentWidget()
        if named or "search" in edit.placeholderText().lower():
            at = edit.mapTo(page, QPoint(0, 0))
            found.append((at.y(), at.x(), edit))
    if not found:
        return None
    return min(found, key=lambda f: f[:2])[2]


def focus_search(page: QWidget | None) -> bool:
    edit = find_search(page)
    if edit is None:
        return False
    edit.setFocus(Qt.ShortcutFocusReason)
    edit.selectAll()
    return True


def refresh(page: QWidget | None) -> str:
    """Run the current screen's refresh action. Returns what was called
    ('' when the screen has nothing to refresh), for the tests."""
    if page is None:
        return ""
    tab = _shown_tab(page)
    for target in (page, tab):
        if target is None:
            continue
        for name, args in REFRESH_METHODS:
            fn = getattr(target, name, None)
            if callable(fn):
                fn(*args)
                return name
    # Market > Contracts: its search IS its refresh, once a weapon is picked
    if tab is not None and getattr(tab, "slug", "") \
            and callable(getattr(tab, "open", None)):
        tab.open()
        return "open"
    # an embedded web app reloads its page
    view = getattr(page, "view", None)
    if view is not None and callable(getattr(view, "reload", None)):
        view.reload()
        return "reload"
    # a Settings page re-reads what it displays
    if tab is not None and callable(getattr(tab, "on_show", None)):
        tab.on_show()
        return "on_show"
    return ""


def install(win, keys: list[str]) -> list[QShortcut]:
    """Bind the shortcuts on the main window. `keys` are the sidebar's page
    keys in display order; `win` provides navigate(key) and a `stack` of
    pages. Window-scoped, so an open dialog keeps its own keys."""
    made = []

    def bind(sequence, slot) -> None:
        sc = QShortcut(QKeySequence(sequence), win)
        sc.setContext(Qt.WindowShortcut)
        sc.activated.connect(slot)
        made.append(sc)

    for i, key in enumerate(keys[:MAX_PAGES]):
        bind(page_hint(i), lambda k=key: win.navigate(k))
    bind(QKeySequence.Find, lambda: focus_search(win.stack.currentWidget()))
    bind(QKeySequence.Refresh, lambda: refresh(win.stack.currentWidget()))
    return made
