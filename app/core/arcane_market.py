"""warframe.market prices for arcanes, for the Vosfor planner's
'purchasability' metric: the cheapest online sell for the unranked (rank 0)
arcane. Prices are fetched through the host's shared MarketClient (the
host owns the session and talks to WFM directly - the gateway is the road
for TOOL subprocesses; the client's own rate limiter still applies) and
cached to `.vosfor_prices.json`, so the ~140 lookups only happen when you
ask and persist between sessions.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

from core import config as wfm_config
from core import paths

PRICE_FILE = paths.USERDATA / "vosfor_prices.json"


def load_prices() -> dict:
    """{"fetched_at": ts|None, "prices": {name_lower: plat}}."""
    try:
        d = json.loads(PRICE_FILE.read_text(encoding="utf-8"))
        if isinstance(d, dict) and "prices" in d:
            return d
    except (OSError, ValueError):
        pass
    return {"fetched_at": None, "prices": {}}


def _save(prices: dict, when: float | None) -> str | None:
    """Persist the sweep. Returns None on success or a printable error -
    never raises: this runs at the END of the worker, and an exception here
    would skip the on_done callback and wedge the UI's fetch state."""
    tmp = PRICE_FILE.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(
            {"fetched_at": when, "prices": prices}, indent=1),
            encoding="utf-8")
        os.replace(tmp, PRICE_FILE)
        return None
    except OSError as exc:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return f"couldn't save prices: {exc}"


def _rank0(row: dict) -> bool:
    """Only UNRANKED (rank 0, or rankless) arcanes count. The planner prices
    copies-to-max in unranked copies, so a rank-5 listing - which is a
    different, dearer good - must not set the per-copy price. The docstring
    has always claimed this; the filter was missing."""
    r = row.get("rank")
    return r in (None, 0)


def _lowest_online_sell(book: dict) -> int | None:
    best = None
    for row in book.get("sell", []):
        if _rank0(row) and row.get("status") in ("ingame", "online"):
            p = row.get("platinum")
            if isinstance(p, (int, float)) and (best is None or p < best):
                best = int(p)
    # fall back to the cheapest UNRANKED sell of any status if nobody is online
    if best is None:
        for row in book.get("sell", []):
            if not _rank0(row):
                continue
            p = row.get("platinum")
            if isinstance(p, (int, float)) and (best is None or p < best):
                best = int(p)
    return best


class PriceFetcher:
    """Runs a price sweep on a background thread with progress callbacks."""

    def __init__(self, market, names: list[str]):
        self.market = market
        self.names = names
        self.cancelled = False
        self.thread: threading.Thread | None = None

    def start(self, on_progress, on_done) -> None:
        self.thread = threading.Thread(
            target=self._run, args=(on_progress, on_done), daemon=True)
        self.thread.start()

    def cancel(self) -> None:
        self.cancelled = True

    def _run(self, on_progress, on_done) -> None:
        # on_done MUST fire on every path - the UI clears its in-flight
        # handle there, so skipping it leaves the fetch button dead for the
        # rest of the session.
        try:
            prices = load_prices()["prices"]
            try:
                index = {n.lower(): s
                         for n, s, _t in self.market.item_names()}
            except Exception:                               # noqa: BLE001
                on_done(None, "couldn't load the warframe.market item index")
                return
            total = len(self.names)
            done = 0
            for name in self.names:
                if self.cancelled:
                    break
                slug = index.get(name.lower())
                if slug:
                    try:
                        book = self.market.order_book(slug)
                        p = _lowest_online_sell(book)
                        if p is not None:
                            prices[name.lower()] = p
                    except Exception:                       # noqa: BLE001
                        pass
                done += 1
                on_progress(done, total)
            err = _save(prices, time.time())
            on_done(prices, err or ("cancelled" if self.cancelled else None))
        except Exception as exc:                            # noqa: BLE001
            on_done(None, f"price sweep failed: {exc}")
