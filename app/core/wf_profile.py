"""core/wf_profile.py - the player's PROGRESSION/PROFILE data from Digital
Extremes' own public endpoint, no credentials, no AlecaFrame, no Overwolf.

`getProfileViewingData` is the same backend the in-game "view profile" feature
uses. It is a plain unauthenticated GET keyed by the account's 24-hex id and
returns a large JSON document: mastery rank, per-item mastery XP for everything
ever levelled, the equipped loadout with cosmetics, star-chart / Steel Path node
completion, Railjack/Drifter intrinsics, syndicate standings, operator loadouts,
guild, challenge progress and more. It does NOT contain owned quantities, relics,
resources, unequipped mods, riven rolls or credits - that is inventory, which has
no credential-free source (see core.wf_inventory / the Overwolf companion).

This adapter is a REFRESHER: refresh() fetches the whole document and writes the
raw Results[0] object into the local store under the "profile" namespace. The raw
blob is the single source of truth; the accessors below derive normalized views
on read, so a future feature can pull a field this code never named without any
change to collection. The UI reads the store (instant, offline); the network call
happens only on refresh, off the GUI thread.

The account id is NOT in EE.log on current game builds, and is not the
warframe.market id. It is captured once from warframe.com/api/user-data (a website
login, handled by the UI's Connect-Warframe.com flow) or pasted in Settings, and
stored via core.config. Until it is set, read_mastery_cached() returns None and
Home falls back to the existing AlecaFrame reader - no behaviour change.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from core import config, store, wf_http

NAMESPACE = "profile"

#: getProfileViewingData is hosted per-platform; PC is the default. The others
#: are here so a console/mobile account only needs a settings value, not a code
#: change. Verified 2026-08-02: PC host returns 200, no auth.
PLATFORM_HOSTS = {
    "pc": "https://api.warframe.com",
    "ps4": "https://api-ps4.warframe.com",
    "xb1": "https://api-xb1.warframe.com",
    "swi": "https://api-swi.warframe.com",
    "mob": "https://api-mob.warframe.com",
    "and": "https://api-and.warframe.com",
}

#: DE account ids are Mongo ObjectIds: 24 lowercase hex chars. Validating the
#: shape stops a fat-fingered paste from becoming a doomed request every refresh.
_ACCOUNT_ID_RX = re.compile(r"^[0-9a-f]{24}$")


def valid_account_id(value: object) -> bool:
    return isinstance(value, str) and bool(_ACCOUNT_ID_RX.match(value))


def profile_url(account_id: str, platform: str = "pc") -> str:
    host = PLATFORM_HOSTS.get(platform, PLATFORM_HOSTS["pc"])
    return f"{host}/cdn/getProfileViewingData.php?playerId={account_id}"


#: Key names that hold the account id in warframe.com/api/user-data, best first.
_ID_KEYS = ("user_id", "userid", "accountid", "account_id", "id")


def _find_id(obj: object, key_ok: Callable[[str], bool]) -> str | None:
    """First 24-hex string in `obj` under a key satisfying `key_ok` (depth-first,
    known keys checked before recursing)."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str) and key_ok(k.lower()) \
                    and valid_account_id(v.lower()):
                return v.lower()
        for v in obj.values():
            hit = _find_id(v, key_ok)
            if hit:
                return hit
    elif isinstance(obj, list):
        for v in obj:
            hit = _find_id(v, key_ok)
            if hit:
                return hit
    return None


def extract_account_id(user_data_text: str) -> str | None:
    """Pull the 24-hex account id out of a warframe.com/api/user-data JSON body.

    Known keys (user_id, accountId, ...) are tried first, then any key merely
    containing 'id' whose value is a valid account id - so a shift in the
    payload's shape doesn't silently break capture. Returns None when the body
    is not JSON or holds no valid id (e.g. it was the login page, not the API)."""
    try:
        data = json.loads(user_data_text)
    except (ValueError, TypeError):
        return None
    # Known keys in PRIORITY order (user_id before a bare 'id'), then any key
    # merely containing 'id' as a last resort.
    for key in _ID_KEYS:
        hit = _find_id(data, lambda k, want=key: k == want)
        if hit:
            return hit
    return _find_id(data, lambda k: "id" in k)


# ---- identity (persisted in settings) --------------------------------------

def account_id() -> str | None:
    """The configured DE account id, or None if unset/malformed."""
    val = config.load_settings().get("wf_account_id", "")
    return val if valid_account_id(val) else None


def platform() -> str:
    p = config.load_settings().get("wf_platform", "pc")
    return p if p in PLATFORM_HOSTS else "pc"


def set_account_id(value: str, platform_: str = "pc") -> bool:
    """Persist the account id (and platform) to settings. Returns False without
    writing if the id is malformed - the caller shows the error."""
    if not valid_account_id(value):
        return False
    s = config.load_settings()
    s["wf_account_id"] = value
    s["wf_platform"] = platform_ if platform_ in PLATFORM_HOSTS else "pc"
    config.save_settings(s)
    return True


def configured() -> bool:
    return account_id() is not None


# ---- refresh (network) + store ---------------------------------------------

def fetch(account_id_: str, platform_: str = "pc", *,
          _get: Callable[[str], Any] = wf_http.get_json) -> dict | None:
    """Fetch and return the profile's Results[0] object, or None if the response
    has no usable result (bad id, private, or an empty Results array). Raises
    wf_http.WFHttpError on a transport failure - refresh() turns that into 'keep
    the cached value'. `_get` is injectable for tests."""
    data = _get(profile_url(account_id_, platform_))
    if not isinstance(data, dict):
        return None
    results = data.get("Results")
    if not isinstance(results, list) or not results:
        return None
    first = results[0]
    return first if isinstance(first, dict) else None


def refresh(*, _get: Callable[[str], Any] = wf_http.get_json) -> dict | None:
    """Fetch the configured account's profile and write it to the store. Returns
    the stored object on success, or None (leaving any existing cache untouched)
    when no account is configured or the fetch yields nothing usable. Network
    errors are swallowed to None - the UI keeps reading the last good cache.

    Safe to call from a worker thread; this is the only method that hits the
    network."""
    aid = account_id()
    if aid is None:
        return None
    try:
        result = fetch(aid, platform(), _get=_get)
    except wf_http.WFHttpError:
        return None
    if result is None:
        return None
    store.write(NAMESPACE, result)
    return result


#: A profile changes slowly (a rank-up, a loadout tweak), so a refresh a few
#: times a day is plenty. refresh_if_stale() skips the network while the cached
#: copy is younger than this - polite to DE's CDN and instant for the UI.
STALE_AFTER = 6 * 3600


def refresh_if_stale(*, _get: Callable[[str], Any] = wf_http.get_json) \
        -> dict | None:
    """refresh() only when the cached profile is missing or older than
    STALE_AFTER; otherwise return the cached object untouched. Safe on a worker
    thread; a no-op (None) when no account is configured."""
    if not configured():
        return None
    age = store.age(NAMESPACE)
    if age is not None and age < STALE_AFTER:
        return stored()
    return refresh(_get=_get)


def stored() -> dict | None:
    """The raw Results[0] object last written to the store, or None."""
    data = store.read(NAMESPACE)
    return data if isinstance(data, dict) else None


def has_data() -> bool:
    return stored() is not None


# ---- normalized accessors (read from the stored raw blob) ------------------
# Each derives a view on read so raw stays the one source of truth and a new
# feature can add an accessor without touching collection. All degrade to None.

def _int(value: object) -> int | None:
    # bool is an int subclass; a stray True must not read as 1.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def mastery_rank() -> int | None:
    """The player's mastery rank (profile PlayerLevel), or None."""
    p = stored()
    return _int(p.get("PlayerLevel")) if p else None


def read_mastery_cached() -> int | None:
    """Mastery rank straight from the local store - instant, offline, safe on a
    worker thread. Named to match core.arcane_inv.read_mastery_cached() so Home
    swaps its source with a one-line change; returns None (Home falls back to
    AlecaFrame) until a profile has been fetched."""
    return mastery_rank()


def display_name() -> str | None:
    p = stored()
    name = p.get("DisplayName") if p else None
    return name if isinstance(name, str) and name else None


def loadout() -> dict | None:
    """The equipped loadout preset (frame, weapons, cosmetics, FocusSchool)."""
    p = stored()
    lp = p.get("LoadOutPreset") if p else None
    return lp if isinstance(lp, dict) else None


def item_xp() -> list | None:
    """Per-item mastery XP for everything ever levelled (LoadOutInventory.XPInfo)
    - the complete mastery record, e.g. {ItemType, XP} entries."""
    p = stored()
    inv = p.get("LoadOutInventory") if p else None
    xp = inv.get("XPInfo") if isinstance(inv, dict) else None
    return xp if isinstance(xp, list) else None


def intrinsics() -> dict | None:
    """Railjack + Drifter intrinsics (PlayerSkills)."""
    p = stored()
    ps = p.get("PlayerSkills") if p else None
    return ps if isinstance(ps, dict) else None


def syndicate_standings() -> list | None:
    """Syndicate standings (Affiliations: [{Tag, Standing, Title}, ...])."""
    p = stored()
    aff = p.get("Affiliations") if p else None
    return aff if isinstance(aff, list) else None


def node_completion() -> list | None:
    """Star-chart / Steel Path node completion (Missions)."""
    p = stored()
    missions = p.get("Missions") if p else None
    return missions if isinstance(missions, list) else None


def created_at() -> float | None:
    """Account creation time in epoch seconds, or None. DE encodes it as
    {"$date": {"$numberLong": "<ms>"}}."""
    p = stored()
    created = p.get("Created") if p else None
    try:
        ms = int(created["$date"]["$numberLong"])
    except (TypeError, KeyError, ValueError):
        return None
    return ms / 1000.0
