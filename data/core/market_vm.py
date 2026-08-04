"""View-model for the Market browser: the three tabs' derivations. No widgets.

Following the rest of `core/`, anything about severity crosses this boundary
as a ROLE NAME - "ingame", "ok", "muted", "err", "accent" - never a hex value.
The front end resolves those against core.theme, which is what lets the Tk and
Qt shells share this file without sharing a palette.
"""

from __future__ import annotations

from typing import Any, Iterable, NamedTuple, Sequence

from . import config

MIN_QUERY = 2          # shorter than this and everything matches
SUGGEST_LIMIT = 10
LIVE = ("ingame", "online")     # statuses that count as "actually here"


# -- suggestions -------------------------------------------------------------

def suggest_pairs(pool: Iterable[Sequence], query: str,
                  limit: int = SUGGEST_LIMIT) -> list[tuple[str, str]]:
    """(label, payload) candidates: prefix matches first, then substring.

    Serves both the item index (rows are `(name, slug, thumb)`) and the
    weapon pools (rows are `(name, slug)`), so it reads only the first two
    columns and ignores whatever else the row carries.
    """
    q = query.lower()
    if len(q) < MIN_QUERY:
        return []
    rows = list(pool)
    pre = [r for r in rows if str(r[0]).lower().startswith(q)]
    sub = [r for r in rows
           if q in str(r[0]).lower() and not str(r[0]).lower().startswith(q)]
    return [(r[0], r[1]) for r in (pre + sub)[:limit]]


# -- order book --------------------------------------------------------------

def counterpart_action(side: str) -> str:
    """The action label for the order book: a WTS row lists a SELLER, so your
    counterpart move is to BUY. Owned here rather than inlined in the view via
    `if side ==`, so the inversion lives with the other side-aware rules."""
    return "+ Buy" if side == "sell" else "+ Sell"


def own_action(side: str) -> str:
    """The label for posting YOUR OWN order on this side of the book: the WTS
    panel lists sellers, so your own move there is to SELL, joining that same
    side. The panel's + button posts your order (counterpart_action is the
    opposite - the move against a row you're looking at)."""
    return "+ Sell" if side == "sell" else "+ Buy"


def counterpart_verb(side: str) -> str:
    """Lower-case verb form of counterpart_action, for a sentence."""
    return "buy" if side == "sell" else "sell"


def status_dot(status: str) -> tuple[str, str]:
    """('●', role) for a warframe.market user status."""
    return "●", {"ingame": "ingame", "online": "ok"}.get(status, "muted")


class Scope(NamedTuple):
    allowed: tuple[str, ...] | None   # None means "no filter"
    word: str                         # what to call it in the status line


def scope_filter(ingame_only: bool, online_only: bool) -> Scope:
    """In-game only NARROWS online only; both off means everyone."""
    if ingame_only:
        return Scope(("ingame",), "in-game")
    if online_only:
        return Scope(LIVE, "online")
    return Scope(None, "total")


def filter_orders(rows: Iterable[dict], allowed: tuple[str, ...] | None
                  ) -> list[dict]:
    if allowed is None:
        return list(rows)
    return [r for r in rows if r["status"] in allowed]


def book_summary(sell_n: int, buy_n: int, scope_word: str, cap: int) -> str:
    """The combined line, still used by the Tk front end."""
    return (f"{sell_n} sellers · {buy_n} buyers ({scope_word}) — "
            f"showing best {cap} per side")


def scope_note(scope_word: str) -> str:
    """Just the filter state, for a layout that puts each side's count in its
    own column header instead of sharing one line."""
    return {"in-game": "showing in-game traders only",
            "online": "showing online traders",
            "total": "showing everyone, including offline"}[scope_word]


def whisper_message(settings: dict, side: str, row: dict,
                    item_name: str) -> str:
    """The ready-to-paste trade message.

    A WTS row means I am BUYING from them, so it uses the buy template - the
    inversion is the whole subtlety here. A user-edited template that does not
    format falls back to the shipped default rather than raising.
    """
    key = "msg_buy" if side == "sell" else "msg_sell"
    tpl = settings.get(key) or config.DEFAULTS[key]
    fields = {"user": row["user"], "item": item_name,
              "price": row["platinum"]}
    try:
        return tpl.format(**fields)
    except (KeyError, IndexError, ValueError):
        return config.DEFAULTS[key].format(**fields)


def contract_whisper(settings: dict, kind: str, weapon: str,
                     row: dict) -> str:
    """A ready-to-paste whisper for a riven/lich contract - you are BUYING it,
    so it uses the buy template with the weapon+kind as the 'item'."""
    tpl = settings.get("msg_buy") or config.DEFAULTS["msg_buy"]
    fields = {"user": row["owner"], "item": f"{weapon} {kind}".strip(),
              "price": row["price"]}
    try:
        return tpl.format(**fields)
    except (KeyError, IndexError, ValueError):
        return config.DEFAULTS["msg_buy"].format(**fields)


# -- watchlist ---------------------------------------------------------------

class Reputation(NamedTuple):
    """The arrow is coloured and the NUMBER is not.

    Colouring both made the digits sit on their own hue and stop reading as
    a quantity - the arrow already carries the sign, so the count can stay in
    the ordinary muted grey the rest of the row uses.
    """
    arrow: str
    value: str
    role: str          # for the arrow only

    def __bool__(self) -> bool:
        return bool(self.arrow)


def reputation(row: dict) -> Reputation:
    """Arrows rather than +/- because the sign IS the message and a glyph
    carries it faster than punctuation. Nothing at all at zero: that is not a
    verdict either way, so the row stays clean."""
    rep = row.get("reputation") or 0
    if rep > 0:
        return Reputation("↑", str(rep), "rep_up")
    if rep < 0:
        return Reputation("↓", str(abs(rep)), "rep_down")
    return Reputation("", "", "muted")


def available_ranks(book: dict) -> list[int]:
    """Every rank actually on sale, low to high, across both sides.

    Derived from the book rather than from the item's theoretical 0..N range:
    offering rank 7 in the picker when nobody is selling one is a dead end,
    and the gaps themselves are information."""
    ranks = {r.get("rank") for side in ("sell", "buy")
             for r in book.get(side, [])}
    return sorted(r for r in ranks if isinstance(r, int))


def filter_rank(rows: Iterable[dict], rank: int | None) -> list[dict]:
    """`rank` None means any."""
    if rank is None:
        return list(rows)
    return [r for r in rows if r.get("rank") == rank]


def best_contract_price(rows: Iterable[dict]) -> int | None:
    """The cheapest way into a weapon's contracts: lowest buyout, or lowest
    opening bid where there is no buyout. None when nothing is listed."""
    prices = [r.get("buyout") if r.get("buyout") is not None else
              r.get("starting") for r in rows]
    prices = [p for p in prices if p is not None]
    return min(prices) if prices else None


def contract_price_line(price: int | None, n: int) -> str:
    if price is None:
        return "  none listed"
    return f"  from {price}p · {n} listed"


def rank_text(row: dict) -> str:
    """The rank column. Empty for goods that do not rank at all, so a plain
    Prime part shows nothing rather than a meaningless "R0"; unranked
    RANKABLE goods do show R0, because "this one is unranked" is exactly the
    thing a buyer needs to see."""
    rank = row.get("rank")
    subtype = row.get("subtype")
    if subtype and subtype != "regular":
        return str(subtype)
    if rank is None:
        return ""
    return f"R-{rank}"


#: The status key shown beside the filter checkboxes, so the coloured dots in
#: the book have a legend rather than being folklore.
STATUS_KEY = (("ingame", "in-game"), ("ok", "online"), ("muted", "offline"))


def contract_key(entry: dict) -> tuple[str, str]:
    return (entry.get("kind", ""), entry.get("slug", ""))


def is_contract_watched(entries: list[dict], kind: str, slug: str) -> bool:
    return any(contract_key(e) == (kind, slug) for e in entries)


def toggle_contract_watch(entries: list[dict], kind: str, slug: str,
                          name: str) -> list[dict]:
    """A new list with this weapon's contracts added or removed."""
    out = [e for e in entries if contract_key(e) != (kind, slug)]
    if len(out) == len(entries):
        out.append({"kind": kind, "slug": slug, "name": name})
    return out


def watch_label(watched: bool) -> tuple[str, str]:
    """A watched item is gilded, not warned about."""
    return ("★ Watched", "accent") if watched else ("☆ Watch", "muted")


def toggle_watch(watchlist: list[str], slug: str) -> list[str]:
    """A new list with `slug` added or removed. Persisting it is the
    caller's job (core.market owns the file)."""
    out = list(watchlist)
    if slug in out:
        out.remove(slug)
    else:
        out.append(slug)
    return out


def best_live_prices(book: dict) -> tuple[int | None, int | None]:
    """(cheapest live seller, richest live buyer). Offline orders are
    excluded - a price you cannot actually trade at is not a price."""
    sells = [r["platinum"] for r in book.get("sell", [])
             if r["status"] in LIVE]
    buys = [r["platinum"] for r in book.get("buy", []) if r["status"] in LIVE]
    return (min(sells) if sells else None, max(buys) if buys else None)


def price_line(min_sell: int | None, max_buy: int | None) -> str:
    text = f"  sell {min_sell}p" if min_sell is not None else "  sell —"
    text += f" · buy {max_buy}p" if max_buy is not None else " · buy —"
    return text


def pretty_slug(slug: str) -> str:
    """A readable name for a watched item before the catalogue has loaded."""
    return slug.replace("_", " ").title()


# -- contracts ---------------------------------------------------------------

def sort_label(ascending: bool) -> str:
    # Spelled out, like My Listings' sort control: a bare ▲/▼ is ambiguous
    # (does the arrow mean the direction pressed, or the resulting order?), so
    # the control names the order it actually produces.
    return "price low → high" if ascending else "price high → low"


def contracts_summary(n: int, kind: str, weapon: str, cap: int) -> str:
    return (f"{n} {kind} contract(s) for {weapon} — "
            f"showing {min(n, cap)}")


def contract_row(kind: str, weapon: str, r: dict) -> dict[str, Any]:
    """One auction line. Rivens and liches carry completely different stats,
    and this is the only place that difference is spelled out."""
    if kind == "riven":
        title = f" {weapon} {r['name']}"
        meta = (f"   mr{r['mastery']} · rr{r['rerolls']} · {r['polarity']}   "
                + "  ".join(r["attributes"]))
    else:
        eph = " · ephemera" if r.get("ephemera") else ""
        quirk = f" · {r['quirk']}" if r.get("quirk") else ""
        title = f" {weapon}"
        meta = f"   {r['element']} +{r['damage']}%{eph}{quirk}"
    # buyout when there is one, else the opening bid - and say which
    buyout = r.get("buyout")
    return {
        "status": r["status"],
        "title": title,
        "meta": meta,
        "owner": r["owner"],
        "price": buyout if buyout is not None else r["starting"],
        "price_label": "buyout" if buyout is not None else "start",
    }


# A handful of riven stats warframe.market reports as flat numbers, not
# percentages, so the card must not stamp a "%" on them. Everything else is a
# percentage. (Kept small and explicit; grow it if a flat stat shows a stray %.)
_FLAT_STATS = {"punch_through", "ammo_maximum", "combo_duration",
               "initial_combo", "range"}


def _attr_display(url_name: str) -> str:
    """url_name -> the label warframe.market shows, near enough: 'melee_damage'
    -> 'Melee Damage', 'critical_chance' -> 'Critical Chance', 'heat' -> 'Heat'."""
    return url_name.replace("_", " ").title()


def _stat_text(stat: dict) -> str:
    value = stat.get("value")
    # plain ASCII "-" (not U+2212): guaranteed in every font, so no stray tofu
    sign = "+" if stat.get("positive", True) else "-"
    unit = "" if stat.get("url_name") in _FLAT_STATS else "%"
    num = f"{abs(value):g}" if isinstance(value, (int, float)) else "?"
    return f"{sign}{num}{unit} {_attr_display(stat.get('url_name', ''))}"


def contract_stat_lines(kind: str, row: dict) -> list[dict[str, Any]]:
    """The stacked, colour-coded description for one contract card. Each entry is
    {'text', 'positive'} - a positive stat reads jade, a negative one coral, the
    way AlecaFrame paints a riven. Rivens list their rolled attributes; liches
    show their element bonus (always a gain) and an Ephemera line when present."""
    lines: list[dict[str, Any]] = []
    if kind == "riven":
        for stat in row.get("stats", []):
            lines.append({"text": _stat_text(stat),
                          "positive": stat.get("positive", True)})
    else:
        element = str(row.get("element", "")).title()
        damage = row.get("damage")
        if element:
            num = f"+{damage:g}% " if isinstance(damage, (int, float)) else ""
            lines.append({"text": f"{num}{element}", "positive": True})
        if row.get("ephemera"):
            lines.append({"text": "Ephemera", "positive": True})
    return lines
