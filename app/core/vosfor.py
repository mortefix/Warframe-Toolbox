"""Vosfor planner: which Arcane Collection is worth buying into.

Combines the static collection data (`vosfor_collections.json` - every
collection's arcanes grouped by rarity, with per-arcane drop chance and
copies-to-max, scraped from the wiki + WFCD item data) with the player's
owned arcanes (`core.wf_inventory`) to score each collection.

Efficiency metric
-----------------
One purchase costs 200 Vosfor and yields 3 arcanes, each drawn
independently. A pulled arcane is "useful" if it's one the player still
needs (not owned at max rank). For a collection:

    p       = sum of drop-chance of every still-needed arcane   (per pull)
    per buy = 3 * p                       expected useful arcanes / purchase
    hit     = 1 - (1 - p)**3              chance a purchase gives >=1 useful

Collections are ranked by `per_buy` (expected useful arcanes per 200
Vosfor) - the higher, the more your Vosfor moves you toward completion.
A completed collection (everything maxed) scores 0 and sorts last.

Manual overrides let a player without AlecaFrame (no inventory cache) tick
arcanes off by hand; overrides always win over the auto-read state.
"""

from __future__ import annotations

import json
from pathlib import Path

from core import wf_inventory
from core import config as wfm_config
from core import paths

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "vosfor_collections.json"   # shipped data - stays in app/
OVERRIDE_FILE = paths.USERDATA / "vosfor_owned.json"   # manual check-offs

# status of one arcane for the player
MISSING, OWNED, MAXED = "missing", "owned", "maxed"

from core import atomic


def load_collections() -> dict:
    """The shipped collection data. Returns {} rather than raising if the file
    is missing or corrupt, so the Vosfor screen shows an empty-but-alive state
    instead of taking the whole app down on a bad install."""
    try:
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def load_overrides() -> dict:
    try:
        return json.loads(OVERRIDE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _status(arc: dict, owned: dict | None, override: dict) -> str:
    """MAXED / OWNED / MISSING for one arcane. A manual override (True =
    maxed, False = missing) beats the auto-read."""
    path = arc.get("path")
    if path in override:
        return MAXED if override[path] else MISSING
    if not owned or path not in owned:
        return MISSING
    e = owned[path]
    ranks = arc.get("ranks") or 0
    max_rank = ranks - 1 if ranks else 0
    if e["best_rank"] >= max_rank:
        return MAXED
    return OWNED


# A player can get an arcane three ways; the planner weighs whether Vosfor
# is the smart choice for each one. "worth Vosfor" rises when the arcane is
# hard to farm and/or expensive to buy.
DEFAULT_METHODS = {"vosfor": True, "farm": False, "market": False}
MARKET_WORTH_PLAT = 15      # per-copy price under which a single is "cheap"
                            # (display coloring only; the weighting below uses
                            #  the total cost to FINISH the arcane, not this)
FULL_MAX_PLAT = 60          # total plat to buy every copy you still need,
                            # at/above which buying out is as much of a chore
                            # as farming -> Vosfor is fully worth it


def arcane_weight(farm_ease: float, price, copies_left: int,
                  methods: dict) -> float:
    """How much an arcane is worth spending Vosfor on, 0..1, given which
    alternative acquisition methods the player will also use.

    A player doesn't decide per single copy - they weigh the total effort to
    FINISH the arcane. So farming is discounted by how easy it is to farm, and
    the market is discounted by the total plat to buy every copy still needed
    (`price * copies_left`), not by one copy's price - a 2p arcane you need 21
    of is 42p, a real spend that Vosfor can spare you. With both methods
    enabled the player uses whichever is easier, so the Vosfor worth is the
    difficulty of that easiest alternative. No alternatives -> full worth."""
    alts = []
    if methods.get("farm"):
        alts.append(max(0.0, 1.0 - float(farm_ease)))       # farm difficulty
    if methods.get("market"):
        if price is None:
            alts.append(1.0)         # unknown price -> don't discount
        else:
            total = float(price) * max(1, int(copies_left))
            alts.append(min(1.0, total / FULL_MAX_PLAT))     # buy-out difficulty
    if not alts:
        return 1.0
    return min(alts)


def evaluate(owned: dict | None = None,
             override: dict | None = None,
             methods: dict | None = None,
             prices: dict | None = None) -> dict:
    """Return the full planner model: per-collection arcane statuses,
    completion, and the efficiency ranking. `methods` selects which
    acquisition methods to weigh (vosfor/farm/market); `prices` is the
    name->plat map from core.arcane_market (for the market weighting)."""
    if override is None:
        override = load_overrides()
    if methods is None:
        methods = dict(DEFAULT_METHODS)
    prices = prices or {}
    weighting = methods.get("farm") or methods.get("market")
    colls = load_collections()
    result = {"collections": {}, "ranking": [], "methods": methods,
              "weighting": weighting, "has_inventory": owned is not None}

    for name, cdata in colls.items():
        arcs_out = []
        needed_prob = 0.0          # sum of drop-chance of not-maxed arcanes
        copies_left = 0
        needed = []                # {q, left} per not-maxed arcane (for plan)
        n_total = n_maxed = 0
        copies_have = copies_max = 0
        for rarity, tier in cdata["tiers"].items():
            per = tier["per_arcane_pct"] / 100.0
            for arc in tier["arcanes"]:
                st = _status(arc, owned, override)
                n_total += 1
                mc = arc.get("max_copies") or 0
                have = 0
                if owned and arc.get("path") in owned:
                    have = owned[arc["path"]]["copies"]
                if st == MAXED:
                    n_maxed += 1
                    have = max(have, mc)   # a maxed arcane is 21/21
                left = max(0, mc - have)   # copies still needed to finish
                # Progress is counted in COPIES, not in finished arcanes. An
                # arcane at 20/21 is all but done and used to score exactly
                # the same as one at 0/21, so a collection someone had ground
                # for weeks could still read as untouched. Capped at the max
                # so spare copies cannot push a collection past 100%, and
                # skipped entirely where the max is unknown - an arcane we
                # cannot measure must not silently count as complete.
                if mc:
                    copies_have += min(have, mc)
                    copies_max += mc
                fe = arc.get("farm_ease", 0.5)
                price = prices.get(arc["name"].lower())
                weight = arcane_weight(fe, price, left, methods)
                buyout = price * left if price is not None else None
                if st != MAXED:
                    needed_prob += per
                    copies_left += left
                    if per > 0 and left > 0:
                        needed.append({"q": per, "left": left, "w": weight})
                arcs_out.append({
                    "name": arc["name"], "rarity": rarity, "status": st,
                    "path": arc.get("path"),
                    "drop_pct": tier["per_arcane_pct"],
                    "max_copies": mc, "copies": have, "left": left,
                    "farm_ease": fe, "farm_note": arc.get("farm_note"),
                    "price": price, "buyout": buyout, "weight": weight,
                })
        # value per pack = expected worth-weighted needed copies
        weighted_prob = sum(a["q"] * a["w"] for a in needed)
        per_buy = 3.0 * weighted_prob
        hit = 1.0 - (1.0 - needed_prob) ** 3
        completed = n_maxed == n_total
        result["collections"][name] = {
            "vosfor": cdata["vosfor"], "credits": cdata["credits"],
            "arcanes": arcs_out, "total": n_total, "maxed": n_maxed,
            "needed": n_total - n_maxed, "completed": completed,
            "per_buy": per_buy, "hit_chance": hit, "copies_left": copies_left,
            # how far through the collection you are, in copies
            "copies_owned": copies_have, "copies_total": copies_max,
            "_needed": needed,
        }

    ranking = sorted(
        result["collections"].items(),
        key=lambda kv: (kv[1]["completed"], -kv[1]["per_buy"]))
    result["ranking"] = [name for name, _ in ranking]
    return result


def refresh_inventory(force: bool = False) \
        -> tuple[dict | None, float | None, bool]:
    """(owned map, source mtime, stale). Cache-aware: a fresh cache is served
    without re-reading the inventory source; stale=True flags data served from
    cache because the live read wasn't possible. owned is None only when there
    has never been a successful read - the UI then relies on manual overrides.
    force=True re-reads regardless (the manual Update button). The source is
    whichever inventory provider is active (see core.wf_inventory)."""
    return wf_inventory.read_arcanes_cached(force=force)


VOSFOR_PER_PACK = 200
ARCANES_PER_PACK = 3


def _useful_copies(needed: list, packs: int) -> float:
    """Expected worth-weighted still-needed copies from `packs` packs.

    Each of the 3 pulls per pack is an independent draw; arcane i is hit
    with probability q_i per pull, so after `packs` packs you expect
    3*packs*q_i copies of it - capped at the `left_i` you still need. Each
    arcane's contribution is scaled by its worth weight `w_i` (1 unless the
    farm/market toggles discount easily-obtained arcanes). Summing over
    every not-yet-maxed arcane gives the value, which flattens out
    (diminishing returns) as arcanes reach the copies they need."""
    pulls = ARCANES_PER_PACK * packs
    return sum(a.get("w", 1.0) * min(a["left"], pulls * a["q"])
               for a in needed)


def _marginal(needed: list, packs_already: int) -> float:
    """Expected useful copies the NEXT pack adds after `packs_already`."""
    return (_useful_copies(needed, packs_already + 1)
            - _useful_copies(needed, packs_already))


def suggest_batch(model: dict) -> dict | None:
    """For the single best collection, how many packs to buy before the
    next pack is worth less than a first pack of the runner-up - i.e. the
    point where you should stop and reassess. Budget-free guidance."""
    order = [n for n in model["ranking"]
             if not model["collections"][n]["completed"]]
    if not order:
        return None
    top = model["collections"][order[0]]
    rival = _marginal(model["collections"][order[1]]["_needed"], 0) \
        if len(order) > 1 else 0.0
    packs = 0
    while packs < 500 and _marginal(top["_needed"], packs) >= rival \
            and _marginal(top["_needed"], packs) > 0.01:
        packs += 1
    return {"collection": order[0], "packs": max(1, packs),
            "expected": _useful_copies(top["_needed"], max(1, packs)),
            "rival": order[1] if len(order) > 1 else None}


def plan_budget(model: dict, vosfor: int) -> dict:
    """Greedy marginal allocation of a Vosfor budget across collections:
    each pack goes to whichever collection's NEXT pack is expected to yield
    the most still-needed copies, recomputed as pools shrink. Naturally
    concentrates on the best collection, then spreads to the runner-up(s)
    once its marginal value drops below theirs."""
    max_packs = max(0, vosfor // VOSFOR_PER_PACK)
    live = {n: dict(bought=0, needed=list(c["_needed"]))
            for n, c in model["collections"].items()
            if not c["completed"] and c["_needed"]}
    bought = {n: 0 for n in live}
    gained = 0.0
    for _ in range(min(max_packs, 500)):
        best_n, best_m = None, 0.0
        for n, st in live.items():
            m = _marginal(st["needed"], st["bought"])
            if m > best_m:
                best_n, best_m = n, m
        if best_n is None or best_m <= 0.001:
            break                       # nothing left worth buying
        live[best_n]["bought"] += 1
        bought[best_n] += 1
        gained += best_m
    plan = [{"collection": n, "packs": p,
             "vosfor": p * VOSFOR_PER_PACK,
             "credits": p * 50000,
             "expected": _useful_copies(model["collections"][n]["_needed"], p)}
            for n, p in bought.items() if p > 0]
    plan.sort(key=lambda r: -r["packs"])
    spent = sum(r["packs"] for r in plan) * VOSFOR_PER_PACK
    return {"packs": max_packs, "plan": plan, "expected": gained,
            "spent": spent, "leftover": vosfor - spent}
