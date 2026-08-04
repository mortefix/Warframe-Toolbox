"""Repricing one listing against the live order book - no widgets, no colours.

The pricing arithmetic itself already lives in `core.market`
(`target_price` / `target_price_buy`); what was still stranded in the UI was
the surrounding decision: which side's book to read, what limit to clamp
against, whether the clamp actually bit, and how to say what happened.

`reprice()` is safe to call from a worker thread - it does network I/O and
must not be called from the UI one. It returns a record of facts; turning
those into a message colour, a card repaint or a status line is the front
end's job, which is the whole point of it living here.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import market as _market

Side = str  # "sell" | "buy"


def better_than(side: Side, other: int | None, reference: int) -> bool:
    """Is `other` a better offer than `reference`, from this side's point of
    view? Sellers are beaten by a LOWER price, buyers by a HIGHER one - the
    one asymmetry running through every side-aware branch in this feature.

    Two callers, deliberately the same rule:
      * vs. my posted price -> "am I undercut?", for the market-low readout
      * vs. my floor/cap    -> "did the clamp bite?", for the reprice note
    """
    if other is None:
        return False
    return other < reference if side == "sell" else other > reference


def limit_label(side: Side) -> str:
    """What the clamp is called to a user on this side."""
    return "min" if side == "sell" else "max"


@dataclass(frozen=True)
class Result:
    ok: bool
    message: str
    #  book snapshot, for the caller to feed back into the card
    best: int | None = None
    online: int = 0
    old_price: int | None = None
    new_price: int | None = None
    clamped: bool = False
    #  True when the listing was found and priced but the price did not move
    held: bool = False


def reprice(listing, market, username: str, side: Side, limit: int) -> Result:
    """Read the book, compute the target, push it, and describe the outcome.

    MUTATES `listing.platinum` to the new price on success - deliberately, so
    a caller repainting the card immediately afterwards sees the new value
    without an ordering hazard. Everything else about `listing` is untouched.
    """
    if market is None:
        return Result(False, "no account linked")

    try:
        # rank/subtype so the benchmark is the SAME good, not the whole book
        rank, subtype = listing.rank, listing.subtype
        if side == "sell":
            best, n = market.lowest_online(listing.slug, exclude=username,
                                           rank=rank, subtype=subtype)
            target = _market.target_price(listing.platinum, best, limit)
        else:
            best, n = market.highest_online(listing.slug, exclude=username,
                                            rank=rank, subtype=subtype)
            target = _market.target_price_buy(listing.platinum, best, limit)
        clamped = better_than(side, best, limit)
        market.update_order(listing.order_id, target, listing.quantity,
                            listing.visible)
    except _market.MarketError as exc:
        return Result(False, str(exc))

    was = listing.platinum
    listing.platinum = target

    if target == was:
        return Result(True, f"held {target}p — moved to top of band",
                      best=best, online=n, old_price=was, new_price=target,
                      clamped=clamped, held=True)
    arrow = "↓" if target < was else "↑"
    note = f" ({limit_label(side)} {limit}p held)" if clamped else ""
    return Result(True, f"{was}p {arrow} {target}p{note}",
                  best=best, online=n, old_price=was, new_price=target,
                  clamped=clamped)
