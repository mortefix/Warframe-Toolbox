"""Saved For Later - the local listing-archive rules, with no widgets.

warframe.market has no archive feature, so parking a listing is a LOCAL
fact: the order stays alive on the site, permanently hidden, and this file
records which orders are parked and what price would make them worth
relisting. The listings themselves are never cached here - every render
still comes from a live fetch; this file only says which side of the
partition each order lands on.

File shape, accounts keyed at the top level:

    {"accounts": {"<account_id>": {"<order_id>": {"side": "sell",
                                                  "target": 45}}}}

Keyed by order_id, not slug: the order exists on warframe.market the whole
time it is parked, so its id is stable, and `reconcile` is exactly "the id
vanished from the fetch". Scoped per account - deliberately stricter than
floors/caps - because reconcile DELETES entries missing from a fetch, and
an unscoped file would let one account's refresh wipe another's archive.

`target` is optional: absent means "parked, no price watch". `target_met`
carries the sell/buy asymmetry (a sell target is met from BELOW, a buy
target from ABOVE) so the front end never writes an `if side ==`.
"""

from __future__ import annotations

import json
from typing import Iterable

from . import atomic
from . import paths

ARCHIVE_PATH = paths.USERDATA / "wfm_archive.json"

SIDES = ("sell", "buy")


def load() -> dict:
    """The archive, or an empty one. A missing, corrupt or hand-mangled file
    degrades to {"accounts": {}} - fail-open to VISIBLE IN THE APP (rows land
    back in WTS/WTB), never to un-hidden on warframe.market: loading makes
    no API writes."""
    try:
        data = json.loads(ARCHIVE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"accounts": {}}
    accounts = data.get("accounts") if isinstance(data, dict) else None
    if not isinstance(accounts, dict):
        return {"accounts": {}}
    out: dict = {"accounts": {}}
    for acct, entries_ in accounts.items():
        if not isinstance(entries_, dict):
            continue
        kept: dict[str, dict] = {}
        for oid, e in entries_.items():
            if not isinstance(e, dict) or e.get("side") not in SIDES:
                continue
            entry = {"side": e["side"]}
            target = e.get("target")
            # bool is an int subclass; True as a target would be nonsense
            if isinstance(target, int) and not isinstance(target, bool) \
                    and target >= 1:
                entry["target"] = target
            kept[oid] = entry
        if kept:
            out["accounts"][acct] = kept
    return out


def save(data: dict) -> None:
    atomic.write_json(ARCHIVE_PATH, data)


def _copy(data: dict) -> dict:
    return {"accounts": {a: {o: dict(e) for o, e in v.items()}
                         for a, v in data.get("accounts", {}).items()}}


def entries(data: dict, account: str) -> dict[str, dict]:
    """This account's parked orders, as copies - mutating the result must
    not silently edit the store."""
    return {o: dict(e)
            for o, e in data.get("accounts", {}).get(account, {}).items()}


def is_archived(data: dict, account: str, order_id: str) -> bool:
    return order_id in data.get("accounts", {}).get(account, {})


def add(data: dict, account: str, order_id: str, side: str) -> dict:
    out = _copy(data)
    out["accounts"].setdefault(account, {})[order_id] = {"side": side}
    return out


def remove(data: dict, account: str, order_id: str) -> dict:
    """A NEW dict without this entry. An account left empty is dropped
    rather than kept as {}, so the file carries no record of accounts that
    have nothing parked."""
    out = _copy(data)
    acct = out["accounts"].get(account, {})
    acct.pop(order_id, None)
    if not acct:
        out["accounts"].pop(account, None)
    return out


def set_target(data: dict, account: str, order_id: str,
               target: int | None) -> dict:
    """None clears the watch. Setting a target on an order that is not
    parked is a no-op - the entry is created by `add`, never here."""
    out = _copy(data)
    entry = out["accounts"].get(account, {}).get(order_id)
    if entry is None:
        return out
    if target is None:
        entry.pop("target", None)
    else:
        entry["target"] = target
    return out


def parse_target(text: str) -> int | None | str:
    """int >= 1, None for blank (clear the watch), or "invalid". Mirrors the
    floors convention: a nonsense edit repaints to the stored value rather
    than raising or silently storing garbage."""
    s = text.strip()
    if not s:
        return None
    try:
        value = int(s)
    except ValueError:
        return "invalid"
    return value if value >= 1 else "invalid"


def reconcile(data: dict, account: str,
              live_order_ids: Iterable[str]) -> dict:
    """Drop THIS account's entries whose orders no longer exist on
    warframe.market. Other accounts are untouched - their orders were not
    in this fetch, so their absence proves nothing."""
    out = _copy(data)
    acct = out["accounts"].get(account)
    if not acct:
        return out
    alive = set(live_order_ids)
    for oid in [o for o in acct if o not in alive]:
        del acct[oid]
    if not acct:
        out["accounts"].pop(account, None)
    return out


def target_met(side: str, market_price: int | None,
               target: int | None) -> bool:
    """Has the market reached this target? Sell targets are met from BELOW
    (the lowest seller rose to your price); buy targets from ABOVE (the
    highest buyer fell to it). Unknown market or no target is never met -
    a dot that lights on missing data is a false alarm."""
    if market_price is None or target is None:
        return False
    return market_price >= target if side == "sell" else market_price <= target


def any_target_met(archived: dict[str, dict],
                   market: dict[str, int | None]) -> bool:
    """The tab dot: does ANY parked order's target check out against the
    latest sweep? `market` maps order_id -> best live price (None/absent =
    unknown)."""
    return any(target_met(e.get("side", "sell"), market.get(oid),
                          e.get("target"))
               for oid, e in archived.items())


def partition(orders: dict[str, list],
              archived: dict[str, dict]) -> tuple[dict[str, list], list]:
    """Split a my_listings fetch: ({"sell": [...], "buy": [...]} for the
    WTS/WTB tabs, [rows] for Saved For Later). This single cut is what
    excludes parked orders from the repricer, the sweep, bulk visibility,
    search, sort and the ledger - none of those ever see them."""
    kept: dict[str, list] = {"sell": [], "buy": []}
    saved: list = []
    for side in ("sell", "buy"):
        for l in orders.get(side, []):
            (saved if l.order_id in archived else kept[side]).append(l)
    return kept, saved
