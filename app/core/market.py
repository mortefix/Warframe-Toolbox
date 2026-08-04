"""
core/market.py - the host's own authenticated warframe.market client.

This is used by the host application itself (e.g. the My Listings view), not
by tools. Tools reach the API only through core/gateway.py; the host, which
owns the session, may talk to the API directly - exactly as core/session.py
already does for login and validation.

Everything here uses the v2 API:

  GET    /v2/me                      -> your account (id, ingameName)
  GET    /v2/orders/user/{accountId} -> your own orders
  GET    /v2/orders/item/{slug}      -> the public order book for one item
  GET    /v2/items                   -> the item catalogue (id <-> slug/name)
  PATCH  /v2/order/{orderId}         -> update one of your orders
  DELETE /v2/order/{orderId}         -> remove an order
  POST   /v2/order/{orderId}/close   -> mark sold ({"quantity": n})

Auth is 'Bearer <token>' (session.bearer). The old v1 profile endpoints were
retired and now 404.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from typing import Any

import requests

from core import atomic
from core import paths
from core import session as wfm_session

API = wfm_session.API
USER_AGENT = wfm_session.USER_AGENT

# Floors are absolute platinum values. By default an item's floor is derived
# from its reference price (the posted price when the session started, or the
# last price you set by hand) plus a global +/- offset:
#     floor = reference_price + global_offset
# -2 means "never let a reprice drop more than 2p below my set price". Typing
# a value into an item's floor field overrides the derived floor for that item.
GLOBAL_OFFSET_DEFAULT = -2

# warframe.market serves item thumbnails from here (paths come from /v2/items).
STATIC_BASE = "https://warframe.market/static/assets/"


#: Cloudflare's origin-side codes. These do NOT mean our request was
#: rejected - they mean Cloudflare could not get an answer out of
#: warframe.market at all, so changing anything about the request cannot help.
_ORIGIN_DOWN = {
    520: "returned something Cloudflare could not read",
    521: "is down",
    522: "timed out",
    523: "is unreachable",
    524: "took too long to answer",
}


def http_error_message(status: int, body: str) -> str:
    """What an HTTP failure means, in a sentence someone can act on.

    The raw body is worse than useless for the failures that actually happen:
    a Cloudflare error page is a kilobyte of HTML, and its first 200
    characters - which is exactly what this used to show - are a doctype, a
    charset meta tag and the start of a stylesheet. Someone reading that
    cannot tell an outage from an expired login from a bug in this app.
    """
    if status in _ORIGIN_DOWN:
        return (f"warframe.market {_ORIGIN_DOWN[status]} (HTTP {status}). "
                f"This is their end - nothing to do but wait.")
    if status == 429:
        return ("warframe.market is rate-limiting us (HTTP 429). "
                "Give it a minute.")
    if status in (500, 502, 503, 504):
        return (f"warframe.market had a server error (HTTP {status}). "
                f"Try again shortly.")
    body = body.strip()
    if body[:1] == "<":            # an HTML page where JSON was promised
        return (f"warframe.market returned a web page instead of data "
                f"(HTTP {status}).")
    return f"HTTP {status}: {body[:200]}"


class MarketError(Exception):
    """Any API-level failure; .args[0] is printable."""


@dataclass
class Listing:
    order_id: str
    slug: str
    name: str
    platinum: int
    quantity: int
    visible: bool
    updated: str
    thumb: str = ""                   # static asset path for the item icon
    # `rank` is None for goods that do not rank at all, and an int (0 upwards)
    # for mods and arcanes - INCLUDING rank 0, because "this one is unranked"
    # is a fact a buyer needs, not an absence. So rankability is simply
    # `rank is not None`, read straight off the order: no table of rankable
    # items to compile and keep current.
    rank: int | None = None
    subtype: str | None = None
    # Filled in lazily by a market-low sweep; None until fetched.
    market_low: int | None = None
    online_count: int = 0
    #: Highest rank this item goes to, from /v2/item/<slug>. None until
    #: fetched; only ever fetched for goods that actually rank.
    max_rank: int | None = None


class MarketClient:
    """Direct, authenticated v2 client for host-side use. Not thread-safe for
    concurrent writes, but reads space themselves out to stay polite."""

    def __init__(self, session: wfm_session.Session | None):
        # session=None makes a public, unauthenticated client: every read of
        # public data (order books, item index, auctions) still works; only
        # the account-scoped calls (my_listings, writes) need a session.
        self.session = session
        self._items_by_id: dict[str, dict[str, str]] | None = None
        self._name_index: list[tuple[str, str, str]] | None = None
        self._slug_names: dict[str, str] | None = None   # name_of() lookup
        self._item_detail: dict[str, dict] = {}
        self._riven_weapons: list[tuple[str, str]] | None = None
        self._lich_weapons: list[tuple[str, str]] | None = None
        self._weapon_thumbs: dict[str, str] | None = None
        self._account_id: str | None = None
        self._s = requests.Session()
        self._min_gap = 0.35          # be a good citizen on bursts
        self._last = 0.0
        self._lock = threading.Lock()
        # A SEPARATE lock for the lazy catalogue build. It must not be self._lock:
        # the build calls _req() -> _space(), which takes self._lock, so holding
        # self._lock across the fetch would deadlock (a plain, non-reentrant Lock).
        self._items_lock = threading.Lock()

    # -- transport -------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        h = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Content-Type": "application/json; charset=utf-8",
            "platform": (self.session.platform if self.session else "pc"),
            "language": "en",
            "crossplay": "true",
        }
        if self.session is not None:
            h["Authorization"] = self.session.bearer
        return h

    def _space(self) -> None:
        with self._lock:
            gap = self._min_gap - (time.monotonic() - self._last)
            if gap > 0:
                time.sleep(gap)
            self._last = time.monotonic()

    def _req(self, method: str, path: str, body: Any = None,
             v1_auth: bool = False) -> Any:
        headers = self._headers()
        if v1_auth and self.session is not None:
            # v1 (the auction house) authenticates with the signin's original
            # 'JWT <token>' header form, not v2's 'Bearer'.
            headers["Authorization"] = self.session.v1_auth
        self._space()
        try:
            r = self._s.request(
                method, f"{API}{path}", headers=headers,
                data=json.dumps(body) if body is not None else None,
                timeout=25)
        except requests.RequestException as exc:
            raise MarketError(f"network error: {exc}") from exc
        if r.status_code == 401:
            raise MarketError("session rejected by warframe.market "
                              "(HTTP 401) - re-link your account.")
        if r.status_code == 403:
            # NOT the same thing as 401: a valid session can still be told
            # "you may not do THIS" - a price-edit PUT on an auction, for
            # instance, 403s while every read on the same session works.
            raise MarketError("warframe.market refused this action "
                              "(HTTP 403). If other actions work, your "
                              "session is fine and this operation simply "
                              "isn't allowed.")
        if not r.ok:
            raise MarketError(http_error_message(r.status_code, r.text))
        try:
            return r.json()
        except ValueError as exc:
            # a 200 with a non-JSON body - a Cloudflare page, a captive
            # portal - would otherwise raise a bare ValueError past every
            # caller's `except MarketError`
            raise MarketError(http_error_message(r.status_code, r.text)) \
                from exc

    # -- catalogue -------------------------------------------------------

    def _items(self) -> dict[str, dict[str, str]]:
        # One MarketClient is shared by three worker threads (Market search,
        # My Listings, the Vosfor price sweep). The cache MUST be published only
        # once fully built: assigning self._items_by_id = {} and then filling it
        # let a second thread see the half-built dict - it would either iterate
        # .values() mid-insert (dictionary changed size during iteration) or
        # cache a truncated catalogue for the whole session. Build a LOCAL dict,
        # then publish it in one atomic assignment, under a lock that also stops
        # two threads from both fetching on a cold cache.
        if self._items_by_id is not None:
            return self._items_by_id
        with self._items_lock:
            if self._items_by_id is None:          # lost the race? use theirs
                data = self._req("GET", "/v2/items")["data"]
                built: dict[str, dict[str, str]] = {}
                for it in data:
                    en = (it.get("i18n", {}).get("en", {}) or {})
                    built[it["id"]] = {
                        "slug": it.get("slug", ""),
                        "name": en.get("name", it.get("slug", "")),
                        "thumb": en.get("thumb", ""),
                    }
                self._items_by_id = built          # publish fully-built only
        return self._items_by_id

    def account_id(self) -> str:
        if self._account_id is None:
            self._account_id = self._req("GET", "/v2/me")["data"]["id"]
        return self._account_id

    def item_names(self) -> list[tuple[str, str, str]]:
        """The whole catalogue as (name, slug, thumb), sorted by name - the
        search index for the Market view."""
        if self._name_index is None:
            self._name_index = sorted(
                (v["name"], v["slug"], v["thumb"])
                for v in self._items().values() if v["slug"])
        return self._name_index

    def name_of(self, slug: str, default: str | None = None) -> str | None:
        """Display name for a slug IF the catalogue is already in memory -
        never triggers a fetch (UI helpers call this from paint paths).
        Returns `default` when nothing is loaded yet or the slug is unknown;
        callers fall back to prettifying the slug.

        Either loader satisfies this: item_names() (the search index) or
        my_listings()/_items() (the id map) - opening My Listings first is
        enough, so the Watchlist doesn't show de-slugged names."""
        if self._slug_names is None:
            if self._name_index is not None:
                self._slug_names = {s: n for n, s, _t in self._name_index}
            elif self._items_by_id is not None:
                self._slug_names = {v["slug"]: v["name"]
                                    for v in self._items_by_id.values()
                                    if v.get("slug")}
            else:
                return default
        return self._slug_names.get(slug, default)

    def riven_weapons(self) -> list[tuple[str, str]]:
        """(name, slug) of every riven-capable weapon, sorted by name."""
        if self._riven_weapons is None:
            data = self._req("GET", "/v2/riven/weapons")["data"]
            self._riven_weapons = sorted(
                ((w.get("i18n", {}).get("en", {}) or {}).get(
                    "name", w.get("slug", "?")), w.get("slug", ""))
                for w in data if w.get("slug"))
        return self._riven_weapons

    def lich_weapons(self) -> list[tuple[str, str]]:
        """(name, slug) of every lich/sister weapon, sorted by name."""
        if self._lich_weapons is None:
            data = self._req("GET", "/v2/lich/weapons")["data"]
            self._lich_weapons = sorted(
                ((w.get("i18n", {}).get("en", {}) or {}).get(
                    "name", w.get("slug", "?")), w.get("slug", ""))
                for w in data if w.get("slug"))
        return self._lich_weapons

    def weapon_thumbs(self) -> dict[str, str]:
        """slug -> static thumb path for every riven-capable and lich weapon,
        cached for the session. This is what puts a picture on a contract
        card: a riven's weapon is not a tradeable item, so it is missing from
        /v2/items - but /v2/riven/weapons and /v2/lich/weapons each carry an
        i18n thumb served from the same static assets base."""
        if self._weapon_thumbs is not None:
            return self._weapon_thumbs
        with self._items_lock:
            if self._weapon_thumbs is None:
                built: dict[str, str] = {}
                for path in ("/v2/riven/weapons", "/v2/lich/weapons"):
                    for w in self._req("GET", path)["data"]:
                        slug = w.get("slug", "")
                        en = (w.get("i18n", {}).get("en", {}) or {})
                        if slug and en.get("thumb"):
                            built[slug] = en["thumb"]
                self._weapon_thumbs = built
        return self._weapon_thumbs

    # -- reads -----------------------------------------------------------

    def my_listings(self) -> dict[str, list[Listing]]:
        """All your orders, split {"sell": [...], "buy": [...]}, resolved to
        item names and sorted by name."""
        items = self._items()
        orders = self._req("GET", f"/v2/orders/user/{self.account_id()}")["data"]
        out: dict[str, list[Listing]] = {"sell": [], "buy": []}
        for o in orders:
            side = o.get("type")
            if side not in out:
                continue
            info = items.get(o.get("itemId"), {})
            out[side].append(Listing(
                order_id=o["id"],
                slug=info.get("slug", o.get("itemId", "?")),
                name=info.get("name", info.get("slug", "?")),
                platinum=o["platinum"],
                quantity=o.get("quantity", 1),
                visible=o.get("visible", True),
                updated=o.get("updatedAt", ""),
                thumb=info.get("thumb", ""),
                rank=o.get("rank"),
                subtype=o.get("subtype"),
            ))
        for side in out:
            out[side].sort(key=lambda l: l.name.lower())
        return out

    def my_sell_orders(self) -> list[Listing]:
        return self.my_listings()["sell"]

    def order_book(self, slug: str) -> dict[str, list[dict]]:
        """The public order book for one item, mirroring what warframe.market
        shows: {"sell": [rows, price ascending], "buy": [rows, descending]}.
        Each row: {user, status, reputation, platinum, quantity, rank,
        subtype}.

        `rank` is load-bearing for anything rankable: a rank-5 Arcane Energize
        and a rank-0 one are different goods at very different prices, so a
        book that hides it misleads. None for items that do not rank at all.
        `subtype` carries the same idea for relics ("intact"/"radiant")."""
        data = self._req("GET", f"/v2/orders/item/{slug}")["data"]
        book: dict[str, list[dict]] = {"sell": [], "buy": []}
        for o in data:
            side = o.get("type")
            if side not in book:
                continue
            user = o.get("user") or {}
            book[side].append({
                "user": user.get("ingameName", "?"),
                "status": (user.get("status") or "offline").lower(),
                "reputation": user.get("reputation", 0),
                "platinum": o.get("platinum", 0),
                "quantity": o.get("quantity", 1),
                "rank": o.get("rank"),
                "subtype": o.get("subtype"),
            })
        book["sell"].sort(key=lambda r: r["platinum"])
        book["buy"].sort(key=lambda r: -r["platinum"])
        return book

    # -- contracts (WFM's auction house: rivens + liches, v1 API) ---------

    def auctions(self, kind: str, weapon_slug: str,
                 ascending: bool = True) -> list[dict]:
        """Public contract search, as on warframe.market's Contracts page.
        kind is 'riven' or 'lich'; rows are trimmed to what the UI shows."""
        sort = "price_asc" if ascending else "price_desc"
        path = (f"/v1/auctions/search?type={kind}"
                f"&weapon_url_name={weapon_slug}&sort_by={sort}")
        payload = self._req("GET", path).get("payload", {})
        rows = []
        for a in payload.get("auctions", []):
            item = a.get("item") or {}
            owner = a.get("owner") or {}
            rows.append({
                "name": item.get("name", ""),
                "weapon": item.get("weapon_url_name", weapon_slug),
                "mastery": item.get("mastery_level"),
                "rerolls": item.get("re_rolls"),
                "polarity": item.get("polarity", ""),
                "rank": item.get("mod_rank"),
                "attributes": [
                    ("+" if at.get("positive") else "-")
                    + str(at.get("url_name", "")).replace("_", " ")
                    for at in item.get("attributes") or []],
                # lich-specific extras (absent on rivens)
                "element": item.get("element", ""),
                "damage": item.get("damage"),
                "ephemera": item.get("having_ephemera"),
                "quirk": item.get("quirk", ""),
                "starting": a.get("starting_price"),
                "buyout": a.get("buyout_price"),
                "top_bid": a.get("top_bid"),
                "owner": owner.get("ingame_name", "?"),
                "status": (owner.get("status") or "offline").lower(),
            })
        return rows

    def my_auctions(self) -> list[dict]:
        """The current user's OWN riven/lich auctions - My Listings > Contracts.
        Rows match auctions()' shape (so vm.contract_row can format them) plus
        id/kind/visible; the weapon name is derived from the slug, since the
        profile payload carries no pretty name. Closed (sold) auctions dropped."""
        user = self.session.username if self.session else ""
        if not user:
            return []
        payload = self._req(
            "GET", f"/v1/profile/{user}/auctions").get("payload", {})
        rows = []
        for a in payload.get("auctions", []):
            if a.get("closed"):
                continue
            item = a.get("item") or {}
            slug = item.get("weapon_url_name", "")
            rows.append({
                "id": a.get("id", ""),
                "kind": item.get("type", "riven"),
                "visible": bool(a.get("visible", True)),
                "name": item.get("name", ""),
                "weapon": slug.replace("_", " ").title(),
                "weapon_slug": slug,      # keys the weapon_thumbs() lookup
                "mastery": item.get("mastery_level"),
                "rerolls": item.get("re_rolls"),
                "polarity": item.get("polarity", ""),
                "rank": item.get("mod_rank"),
                "attributes": [
                    ("+" if at.get("positive") else "-")
                    + str(at.get("url_name", "")).replace("_", " ")
                    for at in item.get("attributes") or []],
                # rich per-attribute data for the My Listings contract card's
                # stacked, colour-coded description (value + sign + display name).
                # The flat `attributes` above stays for the whisper/summary path.
                "stats": [
                    {"url_name": at.get("url_name", ""),
                     "value": at.get("value"),
                     "positive": bool(at.get("positive"))}
                    for at in item.get("attributes") or []],
                "element": item.get("element", ""),
                "damage": item.get("damage"),
                "ephemera": item.get("having_ephemera"),
                "quirk": item.get("quirk", ""),
                "starting": a.get("starting_price"),
                "buyout": a.get("buyout_price"),
                "top_bid": a.get("top_bid"),
                # carried so a relist (see relist_auction) reproduces the
                # original listing faithfully, not a default-flavoured copy
                "note": a.get("note") or "",
                "minimal_reputation": a.get("minimal_reputation") or 0,
                "minimal_increment": a.get("minimal_increment") or 1,
                "owner": user,        # you - the My Listings view won't show it
                "status": "ingame",
            })
        return rows

    def set_auction_visibility(self, auction_id: str, visible: bool) -> None:
        """Show or hide one of your own contracts. Endpoint and body taken
        from what warframe.market's own frontend sends for its eye toggle:
        PUT /v1/auctions/entry/{id} with {"visible": bool}."""
        self._req("PUT", f"/v1/auctions/entry/{auction_id}",
                  {"visible": visible}, v1_auth=True)

    def relist_auction(self, row: dict, *, starting: int | None,
                       buyout: int | None, mod_rank: int | None = None,
                       visible: bool = True) -> str:
        """Change a contract's price or rank the only way the API allows:
        close and relist. A PUT with price fields comes back 401/403 on a
        session every other action accepts (confirmed live, 2026-08-02) -
        consistent with warframe.market's own client, which has no price
        edit at all; their flow is close-and-relist, so this is that flow.

        Ordering is the safety property: CREATE the replacement first, close
        the original only once the new one exists. A momentary duplicate is
        visible and recoverable; a close that succeeds followed by a create
        that fails would have silently unlisted the item. The item payload
        mirrors the create body pywmapi ships (the only public
        implementation): rivens carry their rolled attributes verbatim from
        the profile payload. Returns the new auction id."""
        kind = row.get("kind", "riven")
        if kind == "riven":
            item: dict[str, Any] = {
                "type": "riven",
                "weapon_url_name": row.get("weapon_slug", ""),
                "name": row.get("name", ""),
                "mod_rank": (row.get("rank") or 0) if mod_rank is None
                            else mod_rank,
                "re_rolls": row.get("rerolls") or 0,
                "polarity": row.get("polarity") or "madurai",
                "mastery_level": row.get("mastery") or 8,
                "attributes": row.get("stats") or [],
            }
        else:
            item = {
                "type": "lich",
                "weapon_url_name": row.get("weapon_slug", ""),
                "element": row.get("element", ""),
                "damage": row.get("damage"),
                "having_ephemera": bool(row.get("ephemera")),
                "quirk": row.get("quirk") or "",
            }
        body = {
            "note": row.get("note") or "",
            "starting_price": starting,
            "buyout_price": buyout,
            "minimal_reputation": row.get("minimal_reputation") or 0,
            "minimal_increment": row.get("minimal_increment") or 1,
            "private": not visible,
            "item": item,
        }
        created = self._req("POST", "/v1/auctions/create", body, v1_auth=True)
        payload = created.get("payload") or {}
        new = payload.get("auction") or payload.get("auctions") or {}
        self.close_auction(row.get("id", ""))
        return new.get("id", "")

    def close_auction(self, auction_id: str) -> None:
        """Remove one of your own contracts. The site's trash button is a
        bodyless PUT /v1/auctions/entry/{id}/close - v1 has no DELETE for an
        auction entry (its DELETE verbs are for bids and bans only). A closed
        auction then drops out of my_auctions()."""
        self._req("PUT", f"/v1/auctions/entry/{auction_id}/close",
                  v1_auth=True)

    def _online_prices(self, slug: str, side: str, exclude: str,
                       rank: int | None = None,
                       subtype: str | None = None) -> list[int]:
        data = self._req("GET", f"/v2/orders/item/{slug}")["data"]
        me = exclude.lower()
        prices = []
        for o in data:
            if o.get("type") != side:
                continue
            # Rank and subtype are part of the good's IDENTITY, not a detail
            # of it: a rank-0 Arcane Energize and a rank-5 one are different
            # goods at very different prices, so repricing one against the
            # whole book pushes a wrong price to a live order. `None` means
            # "this good does not rank" - then every order is the same good
            # and rank is not compared.
            if rank is not None and o.get("rank") != rank:
                continue
            if subtype is not None and o.get("subtype") != subtype:
                continue
            user = o.get("user") or {}
            if (user.get("ingameName") or "").lower() == me:
                continue
            if (user.get("status") or "").lower() not in ("ingame", "online"):
                continue
            prices.append(o["platinum"])
        return prices

    def lowest_online(self, slug: str, exclude: str = "",
                      rank: int | None = None,
                      subtype: str | None = None) -> tuple[int | None, int]:
        """(lowest price among online SELLERS, how many are online), skipping
        your own orders. 'Online' means in-game or online, not offline.
        `rank`/`subtype` restrict to the matching good - see _online_prices."""
        live = self._online_prices(slug, "sell", exclude, rank, subtype)
        return (min(live), len(live)) if live else (None, 0)

    def highest_online(self, slug: str, exclude: str = "",
                       rank: int | None = None,
                       subtype: str | None = None) -> tuple[int | None, int]:
        """(highest offer among online BUYERS, how many are online) - the buy
        side's competitive benchmark, mirroring lowest_online."""
        live = self._online_prices(slug, "buy", exclude, rank, subtype)
        return (max(live), len(live)) if live else (None, 0)

    # -- writes ----------------------------------------------------------

    def update_order(self, order_id: str, platinum: int, quantity: int,
                     visible: bool = True, rank: int | None = None) -> None:
        """`rank` is omitted from the payload when None rather than sent as
        null: an order for a good that does not rank has no rank field, and
        sending one would be asking the API to invent one."""
        body = {"platinum": platinum, "quantity": quantity,
                "visible": visible}
        if rank is not None:
            body["rank"] = rank
        self._req("PATCH", f"/v2/order/{order_id}", body)

    def create_order(self, item_id: str, order_type: str, platinum: int,
                     quantity: int = 1, per_trade: int = 1,
                     visible: bool = True, rank: int | None = None,
                     subtype: str | None = None) -> str:
        """POST a NEW order. `order_type` is 'sell'/'buy'. `perTrade` is the max
        units exchanged in one trade and is REQUIRED by the v2 API (the create
        400s without it). `rank`/`subtype` are omitted when None (an order for a
        good that does not rank has no rank field). Returns the new order id."""
        body = {"itemId": item_id, "type": order_type, "platinum": platinum,
                "quantity": quantity, "perTrade": per_trade, "visible": visible}
        if rank is not None:
            body["rank"] = rank
        if subtype:
            body["subtype"] = subtype
        data = self._req("POST", "/v2/order", body)
        return (data.get("data") or {}).get("id", "")

    def item_detail(self, slug: str) -> dict:
        """The full record for one item, cached for the session. The bulk
        /v2/items list does NOT carry maxRank, so this is the only way to
        learn how far a mod or arcane ranks."""
        hit = self._item_detail.get(slug)
        if hit is None:
            hit = self._req("GET", f"/v2/item/{slug}")["data"]
            self._item_detail[slug] = hit
        return hit

    def max_rank(self, slug: str) -> int | None:
        """How far this item ranks, or None if it does not rank at all.

        Derived from the API rather than from a list kept in this repo -
        a hand-maintained table of rankable items is exactly the thing that
        goes stale the week after a new arcane ships."""
        return self.item_detail(slug).get("maxRank")

    def close_order(self, order_id: str, quantity: int = 1) -> None:
        """Mark 'quantity' of the order sold (WFM's Sold button). Closing the
        last unit removes the order and records the sale in your stats."""
        self._req("POST", f"/v2/order/{order_id}/close",
                  {"quantity": quantity})

    def delete_order(self, order_id: str) -> None:
        """Remove the order outright (no sale recorded)."""
        self._req("DELETE", f"/v2/order/{order_id}")

    # -- assets ----------------------------------------------------------

    def fetch_thumb(self, thumb_path: str) -> bytes | None:
        """Raw PNG bytes for an item thumbnail; None on any failure. Static
        assets aren't the API, so this skips the rate-limit spacing."""
        if not thumb_path:
            return None
        try:
            r = self._s.get(STATIC_BASE + thumb_path, timeout=15,
                            headers={"User-Agent": USER_AGENT})
            return r.content if r.ok else None
        except requests.RequestException:
            return None


# ---------------------------------------------------------------- prefs

# Listings preferences, host-managed, next to the session file:
#   global_offset      +/- applied to a SELL item's reference price to derive
#                      its default floor (floor = reference + global_offset)
#   global_offset_buy  +/- applied to a BUY order's reference price to derive
#                      its default cap (cap = reference + global_offset_buy)
#   floors / caps      absolute per-item overrides in platinum, keyed by slug
PREFS_PATH = paths.USERDATA / "wfm_listings.json"

GLOBAL_OFFSET_BUY_DEFAULT = 2      # willing to pay up to 2p over my set price


def load_prefs() -> dict:
    try:
        raw = json.loads(PREFS_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        raw = {}
    if not isinstance(raw, dict):
        raw = {}                    # valid JSON of the wrong shape ([]/null):
                                    # raw.get() below would raise, not fall back
    def _int(value, default):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default          # a hand-edited prefs file must not crash

    def _int_map(m):
        out = {}
        for k, v in (m or {}).items():
            try:
                out[k] = int(v)
            except (TypeError, ValueError):
                continue            # drop the bad entry, keep the rest
        return out

    return {
        "global_offset": _int(raw.get("global_offset"), GLOBAL_OFFSET_DEFAULT),
        "global_offset_buy": _int(raw.get("global_offset_buy"),
                                  GLOBAL_OFFSET_BUY_DEFAULT),
        "floors": _int_map(raw.get("floors")),
        "caps": _int_map(raw.get("caps")),
    }


def save_prefs(prefs: dict) -> None:
    atomic.write_json(PREFS_PATH, prefs)


# The Market view's watchlist: bookmarked item slugs, in the order added.
WATCHLIST_PATH = paths.USERDATA / "wfm_watchlist.json"


def load_watchlist() -> list[str]:
    try:
        data = json.loads(WATCHLIST_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []                   # {}/null iterate wrong or crash the loop
    return [s for s in data if isinstance(s, str)]


def save_watchlist(slugs: list[str]) -> None:
    atomic.write_json(WATCHLIST_PATH, slugs)


# Watched CONTRACTS live in their own file, deliberately not mixed into the
# item watchlist above. That list is a flat list[str] of market slugs and both
# front ends feed every entry to order_book(); a riven weapon is not an item
# slug, so smuggling one in there would just produce a permanent "fetch
# failed" row in an older build. A separate file keeps both readable by both.
CONTRACT_WATCHLIST_PATH = paths.USERDATA / "wfm_contract_watchlist.json"


def load_contract_watchlist() -> list[dict]:
    """[{"kind": "riven"|"lich", "slug": str, "name": str}, ...]"""
    try:
        data = json.loads(CONTRACT_WATCHLIST_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []                   # a hand-edited {}/null must not crash the loop
    return [e for e in data
            if isinstance(e, dict) and e.get("kind") and e.get("slug")]


def save_contract_watchlist(entries: list[dict]) -> None:
    atomic.write_json(CONTRACT_WATCHLIST_PATH, entries)


def target_price(current: int, market_low: int | None, floor: int) -> int:
    """SELL: match the lowest online seller exactly, never below the floor.

    Never undercuts (matches, never beats). With no competition online, holds
    the current price - but never below the floor."""
    if market_low is None:
        return max(floor, current)
    return max(floor, market_low)


def target_price_buy(current: int, market_high: int | None, cap: int) -> int:
    """BUY: match the highest online buyer exactly, never above the cap.

    Never overbids (matches, never beats). With no competition online, holds
    the current offer - but never above the cap."""
    if market_high is None:
        return min(cap, current)
    return min(cap, market_high)
