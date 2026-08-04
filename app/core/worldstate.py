"""core/worldstate.py - Warframe's live world state, from DE's own public feed.

worldState.php is an open, unauthenticated JSON document describing the game's
current live state: void fissures, sorties, the Archon Hunt, Nightwave, Baro
Ki'Teer, invasions, events, Darvo's deal and more. No player data and no
credentials - the same feed community sites (warframestat.us, tenno.tools) have
read for years.

This adapter is a REFRESHER: refresh() fetches the WHOLE document and writes it
raw to the local store under the "worldstate" namespace. Raw is the single
source of truth; the accessors below derive the well-known sections on read, so
a future feature can pull any section - named here or not - without a change to
collection. The UI reads the store (instant, offline); refresh() self-throttles
to at most once a minute, the community etiquette for this endpoint.
"""

from __future__ import annotations

from typing import Any, Callable

from core import store, wf_http

NAMESPACE = "worldstate"

#: PC uses api.warframe.com/cdn (verified 2026-08-02; the old
#: content.warframe.com/dynamic host 404s). Console/mobile feeds live on
#: separate hosts and can be added here if ever needed.
WORLDSTATE_HOSTS = {"pc": "https://api.warframe.com/cdn"}

#: Fissures rotate every few minutes, but hammering the CDN is rude and pointless
#: - a refresh a minute is plenty and matches community norms.
STALE_AFTER = 60


def worldstate_url(platform: str = "pc") -> str:
    host = WORLDSTATE_HOSTS.get(platform, WORLDSTATE_HOSTS["pc"])
    return f"{host}/worldState.php"


def _looks_like_worldstate(data: object) -> bool:
    """Structural check (never a byte prefix): the real document always carries
    a server Time and a WorldSeed. A truncated or error body fails this and is
    treated as 'no fresh data', leaving the cache intact."""
    return (isinstance(data, dict)
            and "Time" in data and "WorldSeed" in data)


def fetch(platform: str = "pc", *,
          _get: Callable[[str], Any] = wf_http.get_json) -> dict | None:
    """Fetch and return the whole world-state document, or None if the response
    doesn't look like one. Raises wf_http.WFHttpError on a transport failure -
    refresh() turns that into 'keep the cached copy'."""
    data = _get(worldstate_url(platform))
    return data if _looks_like_worldstate(data) else None


def refresh(platform: str = "pc", *,
            _get: Callable[[str], Any] = wf_http.get_json) -> dict | None:
    """Fetch and store the whole document. Returns the stored object, or None
    (leaving any existing cache untouched) on a failed/garbage fetch. Safe on a
    worker thread; this is the only method that hits the network."""
    try:
        doc = fetch(platform, _get=_get)
    except wf_http.WFHttpError:
        return None
    if doc is None:
        return None
    store.write(NAMESPACE, doc, source_mtime=doc.get("Time"))
    return doc


def refresh_if_stale(platform: str = "pc", *,
                     _get: Callable[[str], Any] = wf_http.get_json) \
        -> dict | None:
    """refresh() only when the cached document is missing or older than
    STALE_AFTER seconds; otherwise return the cached copy untouched."""
    age = store.age(NAMESPACE)
    if age is not None and age < STALE_AFTER:
        return stored()
    return refresh(platform, _get=_get)


def stored() -> dict | None:
    """The whole world-state document last written to the store, or None."""
    data = store.read(NAMESPACE)
    return data if isinstance(data, dict) else None


# ---- accessors (derived from the stored raw document) ----------------------

def section(name: str, default: Any = None) -> Any:
    """Any top-level section of the document by its DE key (e.g. 'Sorties'), or
    `default` when absent. The escape hatch for sections without a named
    accessor below - nothing is lost by not enumerating them all."""
    doc = stored()
    if doc is None:
        return default
    return doc.get(name, default)


def server_time() -> int | None:
    """The document's server timestamp (epoch seconds), or None."""
    t = section("Time")
    return t if isinstance(t, int) else None


def fissures() -> list:
    """Void fissures (ActiveMissions)."""
    return section("ActiveMissions", []) or []


def void_storms() -> list:
    """Railjack/Empyrean fissures (VoidStorms)."""
    return section("VoidStorms", []) or []


def sorties() -> list:
    return section("Sorties", []) or []


def archon_hunt() -> list:
    """The weekly Archon Hunt (LiteSorties)."""
    return section("LiteSorties", []) or []


def nightwave() -> dict | None:
    """Nightwave season info (SeasonInfo), or None."""
    s = section("SeasonInfo")
    return s if isinstance(s, dict) else None


def baro() -> list:
    """Baro Ki'Teer / Void Trader arrivals (VoidTraders)."""
    return section("VoidTraders", []) or []


def invasions() -> list:
    return section("Invasions", []) or []


def events() -> list:
    return section("Events", []) or []


def alerts() -> list:
    return section("Alerts", []) or []


def daily_deals() -> list:
    """Darvo's daily deal (DailyDeals)."""
    return section("DailyDeals", []) or []


def syndicate_missions() -> list:
    return section("SyndicateMissions", []) or []
