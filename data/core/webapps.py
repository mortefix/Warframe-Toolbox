"""The embedded web apps table - which sites get a browser pane, and how the
shell labels them. No toolkit imports; the front end decides how to render.

A NamedTuple rather than a plain tuple so `app.url` reads better than
`entry[3]`, while `for key, label, icon, url in WEB_APPS` keeps working
exactly as before for the existing call sites.
"""

from __future__ import annotations

from typing import NamedTuple

from . import theme


class WebApp(NamedTuple):
    key: str        # nav key, also the WebHost window key
    label: str      # sidebar text
    icon: str       # core.theme.ICONS key for the sidebar
    url: str        # home page, loaded on first visit (never at launch)


# These render the live site in a browser pane inside the content area.
WEB_APPS: tuple[WebApp, ...] = (
    # the glyph is theme.WIKI_ICON on purpose, not a copy of it: a wiki link
    # anywhere in the app carries the same mark as the tab it opens, and
    # sharing the constant makes that true by construction rather than by
    # comment
    WebApp("web_wiki", "Wiki", theme.WIKI_ICON, "https://wiki.warframe.com/"),
    WebApp("web_builds", "Overframe", "builds", "https://overframe.gg/"),
)

# One source of truth for "is this nav key a web tab": Home labels its card
# button Visit instead of Open for these, and only these resolve to a browser
# pane rather than a native view.
WEB_KEYS = frozenset(a.key for a in WEB_APPS)

# key -> entry, for the lookups that would otherwise scan the list
BY_KEY: dict[str, WebApp] = {a.key: a for a in WEB_APPS}


def url_for(key: str) -> str | None:
    a = BY_KEY.get(key)
    return a.url if a else None
