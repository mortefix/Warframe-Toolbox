"""Read the player's arcane holdings - READ ONLY, ToS-safe.

Warframe's inventory is not in EE.log; AlecaFrame (which the user already
runs, via Overwolf's ToS-compliant game-events plugin) caches the game's
inventory response to `%LOCALAPPDATA%/AlecaFrame/lastData.dat`, AES-128-CBC
encrypted. We only ever READ that file - never the game's own files, never
anything writable - and decrypt it in-process with core.aes, a pure-Python
AES: no third-party crypto dependency to ship, and no OS binding either.
(This used to call Windows' CNG via bcrypt.dll, which pinned the module to
Windows for nothing but an AES primitive.)

Arcanes live in the inventory under `/Lotus/Upgrades/CosmeticEnhancers/...`:
  - RawUpgrades: unranked stacks   -> {"ItemType", "ItemCount"}
  - Upgrades:    ranked instances  -> {"ItemType", "UpgradeFingerprint":
                                       "{\"lvl\":N}"}
This module returns, per arcane path, the best rank owned and the total
copy count - enough to tell "maxed", "owned but not maxed", or "missing".
When AlecaFrame data isn't present it returns None and the app falls back
to manual check-off, so the feature still works on a friend's machine.

The parsed result is cached to `.arcane_inv.json` (read_arcanes_cached):
a fresh cache is served straight from disk with no decrypt, staleness is
a single stat() of lastData.dat's mtime, and the last good inventory
survives even if AlecaFrame's cache disappears. Consumers re-check on
open (cache_is_stale) and keep a manual force-refresh.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from . import aes

ROOT = Path(__file__).resolve().parent.parent

LASTDATA = (Path(os.environ.get("LOCALAPPDATA", "")) / "AlecaFrame"
            / "lastData.dat")

# AlecaFrame's fixed AES-128-CBC key/IV (community-known; the cache is not a
# secret - it mirrors what the game already showed the running client).
_KEY = b"LEO-ALEC\tEO-ALEC"
_IV = bytes([49, 50, 70, 71, 66, 51, 54, 45, 76, 69, 51, 45, 113, 61, 57, 0])

# Fallback only - see _decrypt_lastdata. The first 16 plaintext bytes of each
# format AlecaFrame has been observed to write, newest first. Adding an entry
# here is the whole fix if the format shifts again.
_KNOWN_PREFIXES = (
    b'{"ActiveAvatarIm',        # seen 2026-07-29: inventory at the top level
    b'{"InventoryJson"',        # older: inventory nested under InventoryJson
)

_ARCANE_PREFIX = "/Lotus/Upgrades/CosmeticEnhancers/"


def rank_copies(rank: int) -> int:
    """How many single (unranked) arcanes a rank-`rank` arcane represents.
    Ranking costs 1,2,3,4,5,6 copies per step, so the cumulative total to
    reach rank R is (R+1)(R+2)/2  -> rank 0 = 1, rank 5 = 21. A fused
    instance therefore embodies this many copies, not one."""
    if rank < 0:
        return 0
    return (rank + 1) * (rank + 2) // 2


# -- decrypt AlecaFrame's cache ----------------------------------------------

def _decrypt_lastdata(raw: bytes) -> dict:
    """Decrypt and parse lastData.dat.

    History worth keeping: this used to back-derive the IV from an assumed
    plaintext prefix of `{"InventoryJson"`, on the belief that `_IV`'s first
    byte was wrong. `_IV` is in fact correct, and when AlecaFrame's format
    changed the assumed prefix stopped matching - so the "correction" computed
    a bad IV, corrupted the first block, and every read failed the JSON parse.
    Because both this layer and read_arcanes() degrade to "no data" rather than
    raising, the app quietly served a stale cache instead of reporting it.

    So: use `_IV` as given. Only if that fails to parse do we fall back to
    prefix recovery, trying each prefix AlecaFrame has been seen to emit -
    which keeps older files, and a friend's older AlecaFrame, working."""
    dec = aes.strip_pkcs7(aes.decrypt_cbc(raw, _KEY, _IV))
    try:
        return json.loads(dec.decode("utf-8", "replace"))
    except ValueError:
        pass

    # Only the first block depends on the IV, so blocks 1.. are already right;
    # recovering the IV means guessing just those 16 bytes.
    block0 = aes.decrypt_block_ecb(raw[:16], _KEY)
    for prefix in _KNOWN_PREFIXES:
        iv = bytes(a ^ b for a, b in zip(block0, prefix))
        cand = aes.strip_pkcs7(aes.decrypt_cbc(raw, _KEY, iv))
        try:
            return json.loads(cand.decode("utf-8", "replace"))
        except ValueError:
            continue
    raise ValueError("lastData.dat did not decrypt to JSON under any known IV")


# -- mastery rank ------------------------------------------------------------
# The player's mastery rank rides in the SAME inventory blob as the arcanes
# (top-level "PlayerLevel"), but the decrypt is ~0.9s on a full lastData.dat -
# far too slow for the GUI thread. So Home reads it via ui.work and this caches
# the number by the file's mtime: the value only changes when the player ranks
# up and AlecaFrame rewrites its cache, so the decrypt runs at most once per.
MASTERY_CACHE = ROOT / ".mastery.json"


def read_mastery() -> int | None:
    """The player's mastery rank (inventory PlayerLevel), or None when the
    AlecaFrame cache is absent or does not decrypt. Same read-only,
    degrade-to-None contract as read_arcanes(); the ~0.9s decrypt means callers
    should run this OFF the GUI thread."""
    if not LASTDATA.is_file():
        return None
    try:
        inv = _inventory_of(_decrypt_lastdata(LASTDATA.read_bytes()))
        if inv is None:
            return None
        lvl = inv.get("PlayerLevel")
        # bool is an int subclass; a stray True must not read as MR 1
        if isinstance(lvl, bool) or not isinstance(lvl, (int, float)):
            return None
        return int(lvl)
    except Exception:                                   # noqa: BLE001
        return None


def read_mastery_cached() -> int | None:
    """read_mastery(), served from a tiny mtime-keyed cache so the decrypt runs
    at most once per inventory change. Safe to call from a worker thread; a
    corrupt or missing cache is simply re-earned by the next read."""
    cur = source_mtime()
    if cur is None:
        return None
    try:
        c = json.loads(MASTERY_CACHE.read_text(encoding="utf-8"))
        if (isinstance(c, dict) and c.get("mtime") == cur
                and isinstance(c.get("mastery"), int)):
            return c["mastery"]
    except (OSError, ValueError):
        pass
    mr = read_mastery()
    if mr is not None:
        try:
            MASTERY_CACHE.write_text(
                json.dumps({"mtime": cur, "mastery": mr}), encoding="utf-8")
        except OSError:
            pass
    return mr


# -- inventory overview (currencies + bucket counts) --------------------------
# A summary of the whole inventory blob: the currencies (platinum, credits, endo,
# ...) and the SIZES of the big libraries (mods, arcanes, misc). These are PURE
# functions over an inventory dict, so core.wf_inventory reuses them for whatever
# provider (Overwolf companion, AlecaFrame, ...) supplied that dict - the caching
# and the "inventory" store namespace live there, not here.


def _num(inv: dict, key: str) -> int:
    v = inv.get(key)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return 0
    return int(v)


def _count(inv: dict, key: str) -> int:
    v = inv.get(key)
    return len(v) if isinstance(v, list) else 0


def _distinct_arcanes(inv: dict) -> int:
    seen = set()
    for bucket in ("RawUpgrades", "Upgrades"):
        for it in inv.get(bucket, []) or []:
            t = it.get("ItemType", "") if isinstance(it, dict) else ""
            if isinstance(t, str) and t.startswith(_ARCANE_PREFIX):
                seen.add(t)
    return len(seen)


def build_overview(inv: dict) -> dict:
    """Currencies + library counts, derived from a decrypted inventory dict."""
    return {
        "platinum": _num(inv, "PremiumCredits"),
        "platinum_free": _num(inv, "PremiumCreditsFree"),
        "credits": _num(inv, "RegularCredits"),
        "endo": _num(inv, "FusionPoints"),
        "regal_aya": _num(inv, "PrimeTokens"),
        "trades_remaining": _num(inv, "TradesRemaining"),
        "mastery_rank": _num(inv, "PlayerLevel"),
        "ranked_mod_arcane_instances": _count(inv, "Upgrades"),
        "unranked_stacks": _count(inv, "RawUpgrades"),
        "misc_items": _count(inv, "MiscItems"),
        "recipes": _count(inv, "Recipes"),
        "consumables": _count(inv, "Consumables"),
        "distinct_arcanes": _distinct_arcanes(inv),
        "top_level_keys": len(inv),
    }


# Inventory buckets that carry {ItemType, ItemCount} for a tradable good; used
# by counts_from_inv (below), which core.wf_inventory calls for the Market
# "Inventory: N" count against whatever provider is active.
_COUNT_BUCKETS = ("MiscItems", "RawUpgrades", "Consumables", "Recipes")


def source_mtime() -> float | None:
    try:
        return LASTDATA.stat().st_mtime
    except OSError:
        return None


def _inventory_of(data: dict) -> dict | None:
    """Find the inventory inside the decrypted blob, whichever shape it is in.

    AlecaFrame used to wrap it: `{"InventoryJson": "<json string>"}`. As of
    2026-07-29 the decrypted object *is* the inventory, with RawUpgrades and
    Upgrades at the top level. Accept both, and identify it structurally
    rather than by any one key name, so the next reshuffle is likelier to be
    a no-op here. Returns None when nothing inventory-shaped is present."""
    def looks_like_inventory(d) -> bool:
        return isinstance(d, dict) and ("RawUpgrades" in d or "Upgrades" in d)

    if looks_like_inventory(data):
        return data
    inner = data.get("InventoryJson")
    if isinstance(inner, str):
        try:
            inner = json.loads(inner)
        except ValueError:
            return None
    return inner if looks_like_inventory(inner) else None


def _accumulate(inv: dict, bump) -> None:
    """Walk the inventory's arcane entries into `bump`. Tolerates odd
    records individually - a single malformed row is skipped, not fatal."""
    # unranked stacks: each copy in the stack is one single arcane
    for x in inv.get("RawUpgrades", []) or []:
        if not isinstance(x, dict):
            continue
        p = x.get("ItemType", "")
        if isinstance(p, str) and p.startswith(_ARCANE_PREFIX):
            try:
                count = int(x.get("ItemCount", 1))
            except (TypeError, ValueError):
                count = 1
            bump(p, 0, count)

    # ranked instances: a rank-N instance embodies rank_copies(N) singles
    for x in inv.get("Upgrades", []) or []:
        if not isinstance(x, dict):
            continue
        p = x.get("ItemType", "")
        if isinstance(p, str) and p.startswith(_ARCANE_PREFIX):
            rank = 0
            fp = x.get("UpgradeFingerprint")
            if isinstance(fp, str):
                try:
                    rank = int(json.loads(fp).get("lvl", 0))
                except (ValueError, TypeError):
                    rank = 0
            bump(p, rank, rank_copies(rank))


# -- pure extraction from an inventory dict (any provider) ---------------------
# core.wf_inventory feeds these the inventory dict from whichever provider is
# active (Overwolf companion, AlecaFrame, ...); they own no source/cache.

def arcanes_from_inv(inv: dict) -> dict[str, dict]:
    """path -> {"best_rank": int, "copies": int}, from an inventory dict. Same
    contract as read_arcanes(), minus the AlecaFrame decrypt. Tolerates odd
    records (a malformed row is skipped, not fatal)."""
    owned: dict[str, dict] = {}

    def bump(path: str, rank: int, copies: int) -> None:
        e = owned.setdefault(path, {"best_rank": -1, "copies": 0})
        e["best_rank"] = max(e["best_rank"], rank)
        e["copies"] += copies

    _accumulate(inv, bump)
    return owned


def counts_from_inv(inv: dict) -> dict[str, int]:
    """ItemType -> owned count, from an inventory dict (a ranked instance counts
    as one owned item; stacks sum their ItemCount)."""
    counts: dict[str, int] = {}
    for bucket in _COUNT_BUCKETS:
        for x in inv.get(bucket, []) or []:
            if not isinstance(x, dict):
                continue
            p = x.get("ItemType")
            if isinstance(p, str):
                try:
                    counts[p] = counts.get(p, 0) + int(x.get("ItemCount", 0))
                except (TypeError, ValueError):
                    pass
    for x in inv.get("Upgrades", []) or []:
        if isinstance(x, dict) and isinstance(x.get("ItemType"), str):
            counts[x["ItemType"]] = counts.get(x["ItemType"], 0) + 1
    return counts
