"""Saved links for the embedded web apps - the rules, with no widgets.

Bookmarks are stored PER WEB APP rather than in one pile. A wiki article and
an overframe build are not interchangeable: showing them together would mean
every list needed filtering at read time, and clicking a wiki link while the
Overframe tab is open would have to decide which tab to send you to. Keying
by app makes both questions disappear.

File shape, one JSON object keyed by the web-app key:

    {"web_wiki": [{"url": "...", "title": "..."}, ...], ...}

Same convention as the market watchlists (`core/market.py`): a dotfile beside
the session, tolerant of a missing or corrupt file, rewritten whole.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from . import atomic
from . import session as wfm_session

BOOKMARKS_PATH = wfm_session.ROOT / ".web_bookmarks.json"


def normalize(url: str) -> str:
    """The key two bookmarks are compared on.

    A page is one page whether you arrived at `.../Rhino_Prime`,
    `.../Rhino_Prime/` or `.../Rhino_Prime#Abilities`. Without this the star
    would read as un-bookmarked on the very page you just saved, because the
    browser had quietly appended a fragment - which is the kind of bug that
    makes a toggle feel broken rather than wrong.
    """
    parts = urlsplit(url.strip())
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path,
                       parts.query, ""))


def load() -> dict[str, list[dict[str, str]]]:
    try:
        data = json.loads(BOOKMARKS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, list[dict[str, str]]] = {}
    for key, entries in data.items():
        if not isinstance(entries, list):
            continue
        out[key] = [e for e in entries
                    if isinstance(e, dict) and isinstance(e.get("url"), str)]
    return out


def save(data: dict[str, list[dict[str, str]]]) -> None:
    atomic.write_json(BOOKMARKS_PATH, data)


def for_app(data: dict[str, Any], key: str) -> list[dict[str, str]]:
    return list(data.get(key, []))


def is_bookmarked(data: dict[str, Any], key: str, url: str) -> bool:
    target = normalize(url)
    return any(normalize(e["url"]) == target for e in data.get(key, []))


def add(data: dict[str, Any], key: str, url: str,
        title: str) -> dict[str, list[dict[str, str]]]:
    """A NEW dict with this page saved. Newest first - you are far more
    likely to want the thing you just saved than the thing you saved a month
    ago, and a list that only ever grows downwards buries it."""
    out = {k: list(v) for k, v in data.items()}
    entries = [e for e in out.get(key, [])
               if normalize(e["url"]) != normalize(url)]
    entries.insert(0, {"url": url, "title": (title or url).strip()})
    out[key] = entries
    return out


def remove(data: dict[str, Any], key: str,
           url: str) -> dict[str, list[dict[str, str]]]:
    out = {k: list(v) for k, v in data.items()}
    target = normalize(url)
    out[key] = [e for e in out.get(key, []) if normalize(e["url"]) != target]
    return out


def toggle(data: dict[str, Any], key: str, url: str,
           title: str) -> dict[str, list[dict[str, str]]]:
    if is_bookmarked(data, key, url):
        return remove(data, key, url)
    return add(data, key, url, title)


def clear_app(data: dict[str, Any],
              key: str) -> dict[str, list[dict[str, str]]]:
    """Empty ONE app's list, leaving the others untouched. The key is dropped
    rather than set to `[]`, so a file written afterwards carries no record of
    an app you have never bookmarked anything for."""
    return {k: list(v) for k, v in data.items() if k != key}


def clear_all() -> dict[str, list[dict[str, str]]]:
    """Every app's bookmarks, gone. Returns the new (empty) store so the
    caller saves it the same way as any other change - there is no separate
    'delete the file' path that could leave the two out of step."""
    return {}


def count(data: dict[str, Any], key: str | None = None) -> int:
    """How many bookmarks - for one app, or across all of them. Used to say
    what a delete is about to destroy, which is the difference between a
    confirmation someone reads and one they click through."""
    if key is not None:
        return len(data.get(key, []))
    return sum(len(v) for v in data.values())


def label(entry: dict[str, str]) -> str:
    """What to show in the list. Falls back to the URL's last path segment,
    then to the URL, so an entry saved before its title loaded still reads as
    something rather than as a blank row."""
    title = (entry.get("title") or "").strip()
    if title:
        return title
    path = urlsplit(entry.get("url", "")).path.rstrip("/")
    return path.rsplit("/", 1)[-1].replace("_", " ") or entry.get("url", "")
