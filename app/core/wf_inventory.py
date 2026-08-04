"""core/wf_inventory.py - owned inventory, behind a source-agnostic provider seam.

Owned inventory (mods, arcanes, relics, currencies) has no credential-free public
source - it lives in the running game's memory. This module hides WHICH reader
supplies it behind a tiny provider interface, so the source can change without any
consumer changing, and a Linux reader can drop in the day one exists (the
linux-parity principle).

Providers, first available wins - our OWN companion is preferred over AlecaFrame:
  * OverwolfCompanionProvider - our minimal Overwolf app (see overwolf-companion/)
    subscribes to the game-events inventory feature and writes the raw inventory
    JSON to %LOCALAPPDATA%/WarframeToolbox/inventory.json. We just read it: no
    AlecaFrame, no decrypt.
  * AlecaFrameProvider - decrypts AlecaFrame's lastData.dat (the pre-Phase-3
    path), kept as a fallback so the app still works where AlecaFrame runs but our
    companion isn't installed.
  * LinuxGepProvider - reserved. available() is False until a Linux inventory
    source exists (Overwolf-on-Linux, a native/Proton reader); implementing it is
    one class, zero consumer changes.

Every provider yields the SAME shape - the game's inventory dict (RawUpgrades,
Upgrades, PremiumCredits, ...) - because AlecaFrame's cache IS the game-events
inventory. So one normalizer (arcane_inv.build_overview) serves them all, and the
normalized result carries a "_source" stamp so the UI can say where it came from.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from core import arcane_inv, store

INVENTORY_NS = "inventory"


class RawInventoryProvider:
    """Yields the game's inventory dict from some source. Read-only, degrade to
    None - never raise into a caller's thread."""
    name = "base"

    def available(self) -> bool:
        return False

    def source_mtime(self) -> float | None:
        return None

    def read_raw(self) -> dict | None:
        return None


class OverwolfCompanionProvider(RawInventoryProvider):
    """Reads the JSON our own Overwolf companion writes. Plaintext - the raw
    game-events inventory - so no decrypt; `_inventory_of` still normalizes the
    two shapes AlecaFrame taught us (top-level, or InventoryJson-wrapped)."""
    name = "overwolf-companion"
    PATH = (Path(os.environ.get("LOCALAPPDATA", "")) / "WarframeToolbox"
            / "inventory.json")

    def available(self) -> bool:
        return self.PATH.is_file()

    def source_mtime(self) -> float | None:
        try:
            return self.PATH.stat().st_mtime
        except OSError:
            return None

    def read_raw(self) -> dict | None:
        try:
            data = json.loads(self.PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return arcane_inv._inventory_of(data)


class AlecaFrameProvider(RawInventoryProvider):
    """Decrypts AlecaFrame's lastData.dat via the existing arcane_inv path."""
    name = "alecaframe"

    def available(self) -> bool:
        return arcane_inv.LASTDATA.is_file()

    def source_mtime(self) -> float | None:
        return arcane_inv.source_mtime()

    def read_raw(self) -> dict | None:
        try:
            raw = arcane_inv.LASTDATA.read_bytes()
            return arcane_inv._inventory_of(arcane_inv._decrypt_lastdata(raw))
        except Exception:                                   # noqa: BLE001
            return None


class LinuxGepProvider(RawInventoryProvider):
    """Reserved. No cross-process game-memory reader exists on Linux yet; when
    one does, implement available()/read_raw() here and it slots in with no
    consumer change. Kept in the list as a visible seam, not dead weight."""
    name = "linux-gep"


#: Order = preference. Our companion first (cuts AlecaFrame), AlecaFrame as the
#: fallback, the Linux seam last.
PROVIDERS: list[RawInventoryProvider] = [
    OverwolfCompanionProvider(),
    AlecaFrameProvider(),
    LinuxGepProvider(),
]


def active_provider() -> RawInventoryProvider | None:
    """The first available provider, or None when no inventory source is present."""
    for provider in PROVIDERS:
        if provider.available():
            return provider
    return None


def available() -> bool:
    return active_provider() is not None


def source_name() -> str | None:
    """Which provider is currently supplying inventory (for the UI), or None."""
    provider = active_provider()
    return provider.name if provider is not None else None


# In-process raw cache keyed by (provider, mtime): the AlecaFrame decrypt is
# ~0.9s, so parse the inventory at most once per change.
_RAW: dict = {"key": None, "inv": None}


def _raw_inv() -> tuple[dict | None, RawInventoryProvider | None]:
    provider = active_provider()
    if provider is None:
        return None, None
    key = (provider.name, provider.source_mtime())
    if _RAW["key"] == key and _RAW["inv"] is not None:
        return _RAW["inv"], provider
    inv = provider.read_raw()
    if inv is not None:
        _RAW["key"], _RAW["inv"] = key, inv
    return inv, provider


#: In-process item-count cache, keyed like the raw cache.
_COUNTS: dict = {"key": None, "map": None}

#: Durable arcane cache: survives the source going away, so the Vosfor planner
#: keeps a dated checklist rather than none. Stored (not in-process) for the same
#: reason arcane_inv used a disk file.
ARCANES_NS = "inventory_arcanes"


def invalidate() -> None:
    """Drop the in-process caches (manual 'refresh inventory')."""
    _RAW["key"] = None
    _RAW["inv"] = None
    _COUNTS["key"] = None
    _COUNTS["map"] = None


def refresh_overview(force: bool = False) -> dict | None:
    """Build the inventory overview from the active provider and cache it to the
    store 'inventory' namespace, stamped with the source. mtime-gated; off-thread
    by contract. Returns the last cached overview on any failure (degrade to
    stale, never empty)."""
    provider = active_provider()
    if provider is None:
        return store.read(INVENTORY_NS)
    cur = provider.source_mtime()
    cached = store.read(INVENTORY_NS)
    if (not force and isinstance(cached, dict)
            and store.source_mtime(INVENTORY_NS) == cur
            and cached.get("_source") == provider.name):
        return cached
    inv, _ = _raw_inv()
    if inv is None:
        return cached
    overview = arcane_inv.build_overview(inv)
    overview["_source"] = provider.name
    try:
        store.write(INVENTORY_NS, overview, source_mtime=cur)
    except OSError:
        pass
    return overview


# ---- arcanes (durable cache) + item counts, source-agnostic ----------------
# These replace arcane_inv's AlecaFrame-specific readers for the Vosfor planner
# and the Market "Inventory: N" label, so both follow whatever provider is active.

def read_arcanes_cached(force: bool = False) \
        -> tuple[dict | None, float | None, bool]:
    """(owned map, source mtime, stale) - the cache-aware road to owned arcanes.

    Fresh cache (same source + mtime) is served from the store with no re-read.
    Stale/absent -> read live from the active provider, then cache. When no
    source is available the last cached arcanes are served with stale=True (a
    dated checklist beats none); (None, None, False) only before any read."""
    provider = active_provider()
    cur = provider.source_mtime() if provider is not None else None
    cached = store.read(ARCANES_NS)
    cached_owned = cached.get("arcanes") if isinstance(cached, dict) else None
    cached_src = cached.get("source") if isinstance(cached, dict) else None
    cached_mt = store.source_mtime(ARCANES_NS)

    if (not force and cached_owned is not None and cur is not None
            and cached_mt == cur and provider is not None
            and cached_src == provider.name):
        return cached_owned, cur, False

    if provider is not None and cur is not None:
        inv, _ = _raw_inv()
        if inv is not None:
            owned = arcane_inv.arcanes_from_inv(inv)
            try:
                store.write(ARCANES_NS, {"source": provider.name,
                                         "arcanes": owned}, source_mtime=cur)
            except OSError:
                pass
            return owned, cur, False

    if cached_owned is not None:
        return cached_owned, cached_mt, True
    return None, None, False


def cache_is_stale(cached_mtime: float | None) -> bool:
    """Would a re-read find newer arcane data? A bare stat() comparison against
    the active provider's mtime. False when no source is present."""
    provider = active_provider()
    cur = provider.source_mtime() if provider is not None else None
    if cur is None:
        return False
    return cached_mtime is None or cur != cached_mtime


def count_owned(game_ref: str | None) -> int | None:
    """How many of the item at `game_ref` (a `/Lotus/` path) the player owns, per
    the active provider. 0 if none, None if there is no inventory. In-process
    cached by (source, mtime); safe on a worker thread."""
    if not game_ref:
        return None
    provider = active_provider()
    if provider is None:
        return None
    key = (provider.name, provider.source_mtime())
    if _COUNTS["key"] == key and _COUNTS["map"] is not None:
        return _COUNTS["map"].get(game_ref, 0)
    inv, _ = _raw_inv()
    if inv is None:
        return None
    counts = arcane_inv.counts_from_inv(inv)
    _COUNTS["key"], _COUNTS["map"] = key, counts
    return counts.get(game_ref, 0)
