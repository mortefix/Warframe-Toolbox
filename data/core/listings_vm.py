"""View-model for the My Listings screen: sorting, filtering, searching and
the small rules around quantity and bulk edits. No widgets.

The screen is one class rendered twice - once for sell orders (WTS) and once
for buy (WTB) - and nearly every difference between the two is a string or a
comparison direction. `SIDES` collects all of them in one place, so adding a
side-aware behaviour means editing one table rather than hunting `if side ==
"sell"` through 800 lines.

Colours are deliberately absent. `SideSpec` names the badge but not its
plum-vs-blue; that mapping is the front end's, out of core.theme.
"""

from __future__ import annotations

from typing import Callable, Iterable, NamedTuple, Sequence

# Sort keys for the header dropdown. Market data arrives asynchronously, so
# "Market best" sorts whatever is known at the time - the `is None` leading
# element pushes unknowns to the end regardless of direction.
SORTS: dict[str, Callable] = {
    "Name": lambda l: l.name.lower(),
    "Price": lambda l: l.platinum,
    "Quantity": lambda l: l.quantity,
    "Market best": lambda l: (l.market_low is None, l.market_low or 0),
}

#: What each sort reads like in each direction, as (ascending, descending).
#: A bare up/down arrow is genuinely ambiguous - people disagree about whether
#: it names the direction of travel or where the big values end up - so the
#: control says what the resulting order actually IS and the question cannot
#: come up.
SORT_WORDS: dict[str, tuple[str, str]] = {
    "Name":        ("A → Z", "Z → A"),
    "Price":       ("low → high", "high → low"),
    "Quantity":    ("few → many", "many → few"),
    "Market best": ("low → high", "high → low"),
}


def direction_label(sort_name: str, desc: bool) -> str:
    return SORT_WORDS[sort_name][1 if desc else 0]


SUGGEST_LIMIT = 10          # rows in the search dropdown
MIN_QUERY = 2               # shorter than this and everything matches


class SideSpec(NamedTuple):
    """Everything that differs between the sell and buy tabs, except colour."""
    side: str
    offset_key: str         # prefs key for the tab-wide +/- nudge
    override_key: str       # prefs key for per-item floors/caps
    limit_word: str         # "floor" / "cap"
    best_word: str          # "low" / "high" - the better price on this side
    done_verb: str          # "Sold" / "Bought"
    limit_title: str        # full label above the offset field
    limit_short: str        # compact label on a card
    badge_text: str         # " wts " / " wtb "
    reprice_blurb: str      # the one-line explanation under the offset field
    best_method: str        # MarketClient method that finds this side's best


SIDES: dict[str, SideSpec] = {
    "sell": SideSpec(
        "sell", "global_offset", "floors", "floor", "low", "Sold",
        "Repricer minimum", "repricer min:", " wts ",
        "plat.  Reprice matches the lowest online seller — never undercuts, "
        "never below an item's minimum.", "lowest_online"),
    "buy": SideSpec(
        "buy", "global_offset_buy", "caps", "cap", "high", "Bought",
        "Repricer maximum", "repricer max:", " wtb ",
        "plat.  Reprice matches the highest online buyer — never overbids, "
        "never above an item's maximum.", "highest_online"),
}


def spec(side: str) -> SideSpec:
    return SIDES[side]


# -- filtering and sorting ---------------------------------------------------

def visible_filter(listings: Iterable, mode: str) -> list:
    """`mode` is the Show dropdown: "All", "Visible" or "Hidden"."""
    if mode == "Visible":
        return [l for l in listings if l.visible]
    if mode == "Hidden":
        return [l for l in listings if not l.visible]
    return list(listings)


def arrange(listings: Iterable, mode: str, sort_name: str,
            desc: bool = False) -> list:
    """Filter then sort - the full pipeline behind one render."""
    return sorted(visible_filter(listings, mode), key=SORTS[sort_name],
                  reverse=desc)


# -- search ------------------------------------------------------------------

def suggest(names: Iterable[str], query: str,
            limit: int = SUGGEST_LIMIT) -> list[str]:
    """Autocomplete candidates: prefix matches first, then substring matches,
    deduplicated and alphabetical within each group. Empty below MIN_QUERY
    characters, because one letter matches nearly everything."""
    q = query.lower()
    if len(q) < MIN_QUERY:
        return []
    uniq = sorted(set(names))
    pre = [n for n in uniq if n.lower().startswith(q)]
    sub = [n for n in uniq if q in n.lower() and not n.lower().startswith(q)]
    return (pre + sub)[:limit]


def find_match(pairs: Sequence[tuple[str, str]], query: str) -> str | None:
    """First id whose name matches - prefix beats substring, and the caller's
    ordering decides ties, so `pairs` must already be in display order."""
    q = query.strip().lower()
    if not q:
        return None
    return (next((i for i, n in pairs if n.startswith(q)), None)
            or next((i for i, n in pairs if q in n), None))


# -- small rules -------------------------------------------------------------

def is_rankable(listing) -> bool:
    """Read straight off the order: an order for a mod or arcane carries a
    rank (0 included), one for a Prime part does not."""
    return getattr(listing, "rank", None) is not None


def rank_text(listing) -> str:
    """The rank badge, or "" for goods that do not rank. A subtype (relics'
    intact/radiant) wins where both exist, because that is the distinction
    the buyer is actually shopping on."""
    subtype = getattr(listing, "subtype", None)
    if subtype and subtype != "regular":
        return str(subtype)
    return f"R-{listing.rank}" if is_rankable(listing) else ""


def limit_key(listing) -> str:
    """The key a per-item price floor/cap is stored under.

    Rank is part of the identity, not a detail of it: a rank-5 Arcane Energize
    and a rank-0 one are different goods at very different prices, so one
    floor cannot serve both. Unranked goods keep the bare slug, so nothing
    already stored has to move.
    """
    return (f"{listing.slug}#r{listing.rank}" if is_rankable(listing)
            else listing.slug)


def ledger_total(listings: Iterable) -> int:
    """Total platinum represented by a set of orders - price times quantity,
    not a count of rows."""
    return sum(l.platinum * l.quantity for l in listings)


def needs_visibility(listings: Iterable, visible: bool) -> list:
    """Only the orders a bulk visibility change would actually write. Nothing
    to do is a distinct outcome from a failure, so the caller can say so."""
    return [l for l in listings if l.visible != visible]


def closes_listing(quantity: int) -> bool:
    """Marking the last unit sold/bought closes the order rather than
    decrementing it - which is why that path confirms first."""
    return quantity <= 1


def adjust_quantity(quantity: int, delta: int) -> int | None:
    """New quantity, or None when the change is not allowed. Zero is not a
    quantity: removing the last one is Delete, a different and destructive
    action, so it must not be reachable by nudging the stepper down."""
    new = quantity + delta
    return new if new >= 1 else None
