"""What the sidebar contains, and in what order. No toolkit imports.

The sidebar has Home pinned at the top and Settings pinned at the bottom. Between
them the apps sit in THREE visual containers (each a gold-bordered, dark box the
shell draws): trading (Market + My Listings), tools (Vosfor + any registry
tool), and the embedded web apps (Wiki + Overframe). `sidebar_sections()`
describes that layout; `nav_items()` is the same thing flattened in display order
for the header title and width measurement.

These containers are pure presentation - always open, no collapse, no folder
finials - so the shell renders one plain row per app exactly as before; only the
parenting changes.

The tool catalogue is passed in rather than imported, because `registry.py` sits
above `core/` and core must not reach upwards. Everything else - the fixed items,
which tools are hidden and which need an account - lives here so the shells
cannot disagree about the app's own shape.
"""

from __future__ import annotations

from typing import Iterable, NamedTuple

from . import theme
from .webapps import WEB_APPS

# Tools that exist but are reached from somewhere other than the sidebar.
HIDDEN_FROM_SIDEBAR = frozenset({"api_check"})   # lives in Settings > Data


class NavItem(NamedTuple):
    key: str
    label: str
    icon: str                 # core.theme.ICONS key, not a codepoint
    requires_session: bool    # gated behind a linked warframe.market account


class NavSection(NamedTuple):
    title: str                # flat caption drawn above the container
    items: tuple[NavItem, ...]


# Pinned, ungrouped: Home at the very top, Settings at the very bottom.
HOME = NavItem("home", "Home", theme.HOME_ICON, False)
SETTINGS = NavItem("settings", "Settings", "settings", False)


def sidebar_sections(tools: Iterable = ()) -> list[NavSection]:
    """The apps between Home and Settings, grouped into the visual containers the
    shell draws - one gold-bordered box per section, each under a flat title, in a
    fixed functional order: trading, then tools, then the embedded web apps. (The
    data-explorer Dev apps live inside Settings under DevTools, not the sidebar.)"""
    trading = NavSection("Market", (
        NavItem("market", "Market", "market", False),
        NavItem("listings", "My Listings", theme.LISTINGS_ICON, True),
    ))
    toolbox = NavSection("Toolbox", (
        NavItem("vosfor", "Vosfor", "vosfor", False),
        *(NavItem(t.id, t.name, t.icon, t.requires_session)
          for t in tools if t.id not in HIDDEN_FROM_SIDEBAR),
    ))
    web = NavSection("Web Apps", tuple(
        NavItem(a.key, a.label, a.icon, False) for a in WEB_APPS))
    return [trading, toolbox, web]


def middle_items(tools: Iterable = ()) -> tuple[NavItem, ...]:
    """Every app between Home and Settings, flattened in display (section)
    order - what the header title and width measurement iterate over."""
    return tuple(i for section in sidebar_sections(tools) for i in section.items)


def nav_items(tools: Iterable = ()) -> list[NavItem]:
    """The whole sidebar in DISPLAY order: Home, each container's apps in order,
    then Settings. Used by the shell, the header title, and the width
    measurement."""
    return [HOME, *middle_items(tools), SETTINGS]


def labels(tools: Iterable = ()) -> dict[str, str]:
    """key -> label, for the header title. Includes hidden tools, which still
    deserve a title when opened from elsewhere."""
    out = {i.key: i.label for i in nav_items(tools)}
    out.update({t.id: t.name for t in tools})
    return out


def requires_session(key: str, tools: Iterable = ()) -> bool:
    return any(i.key == key and i.requires_session for i in nav_items(tools))
