"""View-model for the Vosfor screen: turns `core.vosfor`'s model into the
strings, fractions and severity levels a front end draws. No widgets.

`core.vosfor` answers "what should I buy"; this module answers "what does that
row say". Keeping them apart matters because the second half is where all the
formatting lives - fraction padding, farm bands, the buyout-vs-unit-price
choice - and that is exactly the part a Qt port would otherwise retype.

Severity levels are returned as strings ("ok" / "warn"), never colours: which
hex a warning is belongs to core.theme, and the front end maps it.
"""

from __future__ import annotations

import time
from typing import Any, Literal, NamedTuple

from . import vosfor

Level = Literal["ok", "warn"]

FARM_EASY = 0.6         # farm_ease at or above this reads "easy"
FARM_HARD = 0.2         # at or below, "hard"
PRICE_STALE_DAYS = 7    # cached market prices older than this are called out


class Text(NamedTuple):
    """A piece of UI copy plus how loudly to say it."""
    text: str
    level: Level = "ok"


def resolve_methods(settings: dict, defaults: dict[str, bool]) -> dict:
    """The weighting toggles, saved settings merged over the defaults."""
    merged = dict(defaults)
    merged.update(settings.get("vosfor_methods") or {})
    return merged


def all_arcane_names(collections: dict) -> list[str]:
    """Every arcane name across every collection, deduplicated and sorted -
    the price fetcher's work list.

    Note the shape: this takes the RAW `vosfor.load_collections()` data, which
    nests arcanes under per-rarity tiers. The evaluated model that `evaluate()`
    returns has a flat `c["arcanes"]` instead - do not feed that one here."""
    return sorted({a["name"]
                   for c in collections.values()
                   for tier in c["tiers"].values()
                   for a in tier["arcanes"]})


def parse_balance(text: str) -> int:
    """The Vosfor balance field. Never negative, never raises."""
    try:
        return max(0, int(text.strip() or 0))
    except ValueError:
        return 0


def price_age(fetched_at: float | None, now: float | None = None) -> Text | None:
    """How stale the cached market prices are. None when there is nothing to
    say. Prices never refresh on their own - the file is used as-is until a
    new sweep runs - so the age is the only signal the user gets."""
    if not fetched_at:
        return None
    now = time.time() if now is None else now
    age_d = max(0, int((now - fetched_at) // 86400))
    when = time.strftime("%b %d", time.localtime(fetched_at))
    old = age_d >= PRICE_STALE_DAYS
    return Text(f"prices from {when}" + (f" ({age_d}d old)" if old else ""),
                "warn" if old else "ok")


#: Provider name (core.wf_inventory) -> how the source line names it.
_SOURCE_LABELS = {
    "overwolf-companion": "the Overwolf companion",
    "alecaframe": "AlecaFrame",
    "linux-gep": "the Linux reader",
}


def _source_label(source: str | None) -> str:
    return _SOURCE_LABELS.get(source, "the inventory source")


def source_line(owned: dict | None, cached_mtime: float | None,
                stale: bool, source: str | None = None) -> Text:
    """Where the inventory came from. Three cases, and the middle one is the
    easy one to forget: we are serving OUR cache because the source could not be
    read this time. `source` is the active provider's name (wf_inventory), so the
    line names whatever supplied the data - our companion, AlecaFrame, ..."""
    if owned is None:
        return Text("No inventory source - tick arcanes manually", "warn")
    label = _source_label(source)
    when = (time.strftime("%b %d %H:%M", time.localtime(cached_mtime))
            if cached_mtime else "?")
    if stale:
        return Text(f"inventory cached {when} · {label} unavailable", "warn")
    return Text(f"inventory from {label} · {when}", "ok")


def copies_fraction(arc: dict) -> str:
    """owned/needed as fixed-width digits so the column aligns in a mono
    font. Clamped both ways: never show more copies than the max, and never
    let a three-digit max break the alignment."""
    mx = arc.get("max_copies") or 0
    have = min(arc.get("copies") or 0, mx)
    return f"{have:02d}/{min(mx, 99):02d}"


def farm_band(arc: dict) -> Text:
    """Farmability as a word. `farm_ease` folds drop rate together with how
    often the source even spawns, so this is not just the drop percentage."""
    fe = arc.get("farm_ease", 0.5)
    if fe >= FARM_EASY:
        return Text("farm: easy", "ok")
    if fe <= FARM_HARD:
        return Text("farm: hard", "warn")
    return Text("farm: med", "ok")


def farm_tooltip(arc: dict) -> str | None:
    note = arc.get("farm_note")
    if not note:
        return None
    return f"{note} — farm ease {arc.get('farm_ease', 0.5):.2f}"


class Price(NamedTuple):
    text: str
    #  True when finishing this arcane on the market is cheap enough that
    #  buying Vosfor packs for it is the worse deal
    cheap: bool
    tooltip: str | None


def price_cell(arc: dict) -> Price:
    """The market column: total plat to buy every copy still needed - the
    buy-out cost the planner weighs - falling back to the unit price when
    there is nothing left to buy."""
    price, buyout = arc.get("price"), arc.get("buyout")
    tip = (f"{price}p each × {arc.get('left', 0)} to finish"
           if price is not None else None)
    if buyout and arc["status"] != vosfor.MAXED:
        return Price(f"{buyout}p", buyout < vosfor.FULL_MAX_PLAT, tip)
    if price is not None:
        return Price(f"{price}p", False, tip)
    return Price("—", False, tip)


def arcane_row(arc: dict) -> dict[str, Any]:
    """Everything one arcane line displays, derived in one place."""
    p = price_cell(arc)
    farm = farm_band(arc)
    return {
        "name": arc["name"],
        "rarity": arc["rarity"],
        "status": arc["status"],
        "maxed": arc["status"] == vosfor.MAXED,
        "fraction": copies_fraction(arc),
        "drop_text": f"{arc['drop_pct']:.2f}%",
        "farm_text": farm.text,
        "farm_level": farm.level,
        # "easy" and "med" both carry level "ok" but only "easy" is painted
        # jade. The distinction belongs here, not sniffed from the copy in the
        # view (which did `farm_text.endswith("easy")`).
        "farm_easy": farm.text.endswith("easy"),
        "farm_tooltip": farm_tooltip(arc),
        "price_text": p.text,
        "price_cheap": p.cheap,
        "price_tooltip": p.tooltip,
        "path": arc.get("path"),
    }


# Status marks: the glyph, and a severity word rather than a colour.
#: status -> (core.theme.ICONS key, severity role). The key rather than a
#: glyph, because the two front ends draw it with different fonts - see
#: core.theme.ICONS.
STATUS_MARK = {
    vosfor.MAXED:   ("maxed", "ok"),
    vosfor.OWNED:   ("owned", "warn"),
    vosfor.MISSING: ("missing", "muted"),
}


def status_mark(status: str) -> tuple[str, str]:
    return STATUS_MARK.get(status, ("missing", "muted"))


def collection_progress(c: dict) -> float:
    """How far through a collection you are, counted in COPIES.

    This was `maxed / total` - the fraction of arcanes FINISHED - and that
    threw away everything already ground. An arcane at 20/21 scored exactly
    the same as one at 0/21, so a collection two copies from done could read
    as barely started. Copies are the unit the work is actually done in, so
    they are the unit the bar should measure.

    Falls back to the arcane count where no copy maximum is known, which is
    the only honest answer available: a collection whose sizes cannot be read
    is not thereby complete.
    """
    total = c.get("copies_total") or 0
    if total:
        frac = c.get("copies_owned", 0) / total
    else:
        frac = c["maxed"] / c["total"] if c.get("total") else 0.0
    # Never past full. core.vosfor already caps each arcane at its own
    # maximum, but this must not depend on its caller having done that -
    # spare copies are common and a bar overflowing its track is a bug that
    # only shows up on somebody else's inventory.
    frac = min(frac, 1.0)
    # A FULL bar must mean finished. Arcanes whose maximum is unknown are left
    # out of the copy count, so a collection containing one can own every copy
    # it is able to measure while still being incomplete - and a bar that says
    # done when it is not is worse than one that says nothing.
    return frac if c.get("completed") else min(frac, 0.99)


def collection_row(name: str, c: dict, is_open: bool) -> dict[str, Any]:
    """A collection card's header: title, the right-hand stat line, and how
    far its progress bar is filled."""
    total = c["total"]
    copies_total = c.get("copies_total") or 0
    copies = (f"{c.get('copies_owned', 0)}/{copies_total} copies   ·   "
              if copies_total else "")
    return {
        "title": f"{name} Arcane Collection",
        "completed": c["completed"],
        "stat": (f"needs {c['needed']}/{total}   ·   {copies}"
                 f"{c['per_buy']:.2f}/pack   ·   {c['vosfor']} Vosfor"),
        # never exactly 0: a hairline of gold reads as "started", and an
        # empty bar is indistinguishable from a broken one
        "fraction": max(collection_progress(c), 0.001),
        "arrow_open": is_open,
    }


def next_override(override: dict, arc: dict) -> bool:
    """Cycle a manual override: absent -> the opposite of what was detected,
    present -> cleared. Mutates `override` and reports whether it now holds an
    entry for this arcane. No-op (False) for an arcane with no path."""
    path = arc.get("path")
    if not path:
        return False
    if path in override:
        del override[path]                      # back to auto-detected
        return False
    override[path] = arc["status"] != vosfor.MAXED
    return True


#: One leading marker for every recommendation line - the inverted rightwards
#: arrow the app is asked to use. Kept as a named constant so the block reads
#: uniformly and a future change touches one place, not five f-strings.
RECO_MARK = "➢"


def reco_lines(model: dict, methods: dict, balance: int) -> list[str]:
    """The recommendation block. Returns the lines to join with newlines, or
    a single line when there is nothing left to buy.

    Deliberately terse: every line is one glanceable sentence, all sharing the
    RECO_MARK bullet, because this sits above a 500-row planner and long prose
    there is skipped, not read.
    """
    m = RECO_MARK
    rank = model["ranking"]
    best = next((n for n in rank
                 if not model["collections"][n]["completed"]), None)
    if best is None:
        return [f"{m}  All collections complete — every arcane maxed. "
                "Save your Vosfor!"]

    c = model["collections"][best]
    unit = "priority/200 VF" if model["weighting"] else "copies/200 VF"
    note = ""
    if model["weighting"]:
        on = [{"farm": "farming", "market": "market"}[k]
              for k in ("farm", "market") if methods.get(k)]
        note = " (weighs " + " + ".join(on) + ")"
    lines = [
        f"{m}  Best value: {best} — ~{c['per_buy']:.2f} {unit}{note}; "
        f"{c['hit_chance']*100:.0f}% pack hit, {c['needed']}/{c['total']} left"]

    if balance >= vosfor.VOSFOR_PER_PACK:
        plan = vosfor.plan_budget(model, balance)
        parts = [f"{r['collection']} ×{r['packs']}" for r in plan["plan"]]
        lines.append(
            f"{m}  {balance:,} Vosfor ({plan['packs']} packs) → "
            + "  ·  ".join(parts) if parts
            else f"{m}  {balance:,} Vosfor buys {plan['packs']} packs.")
        lines.append(
            f"     ~{plan['expected']:.0f} copies for {plan['spent']:,} Vosfor"
            + (f" ({plan['leftover']:,} left, short of a pack)."
               if plan['leftover'] else "."))
    else:
        sb = vosfor.suggest_batch(model)
        if sb:
            tail = f" before {sb['rival']} wins" if sb["rival"] else ""
            lines.append(
                f"{m}  Buy ~{sb['packs']} {sb['collection']} packs{tail} "
                f"(~{sb['expected']:.0f} copies). Add your Vosfor above for a "
                f"split plan.")
    return lines
