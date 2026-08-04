"""core/collect.py - the startup background refresh of every collected namespace.

Called once, a beat after launch and OFF the GUI thread. Each source
self-throttles (world state ~1/min, profile ~6h, Public Export ~daily) and
swallows its own errors, so a down endpoint or a closed game just leaves that
namespace at its last good value - never a failed launch. The store is the app's
source of truth; this is what keeps it warm without any screen having to ask.

Adding a source to the collect set is one row in run_startup_refresh() - the same
"collection is a superset the UI reads from" shape as the store itself.
"""

from __future__ import annotations

from core import (ee_events, public_export, store, wf_inventory, wf_profile,
                  worldstate)

#: Public Export is ~20 MB on the first sync and only changes on a game update,
#: so re-checking its index more than daily is pointless traffic.
EXPORT_MIN_INTERVAL = 24 * 3600


def _sync_export() -> bool:
    """Sync the item DB, but at most once a day (the index barely changes)."""
    age = store.age(public_export.INDEX_NS)
    if age is not None and age < EXPORT_MIN_INTERVAL:
        return False
    return bool(public_export.sync().get("index"))


def run_startup_refresh() -> dict:
    """Refresh/populate every collected namespace, best-effort. Returns a
    {source: did_something} map (for logging/tests). Never raises - a failing
    source is recorded False and the rest still run. Call from a worker thread;
    each refresher may touch disk or the network."""
    steps = (
        ("profile", lambda: wf_profile.refresh_if_stale() is not None),
        ("worldstate", lambda: worldstate.refresh_if_stale() is not None),
        ("ee_events", lambda: bool(ee_events.tail())),
        ("inventory", lambda: wf_inventory.refresh_overview() is not None),
        ("export", _sync_export),
    )
    out: dict[str, bool] = {}
    for name, fn in steps:
        try:
            out[name] = bool(fn())
        except Exception:                       # noqa: BLE001 - never fatal
            out[name] = False
    return out
