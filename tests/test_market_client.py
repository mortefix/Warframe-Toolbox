"""Behaviour tests for the price-benchmarking core in core.market.

These are the functions that decide what price a live order is set to, and
they ran in NO test before - every screen test used a FakeMarket stub, so the
real rank/subtype/self/online filtering (the whole point of rank-aware
repricing) was unverified. A regression here reprices a rank-5 arcane against
rank-0 or offline sellers and pushes a wrong price to a real order, silently.

We drive the real MarketClient with a monkeypatched _req (no network), feeding
one order book with mixed ranks, subtypes, statuses, sides and a self-order.
"""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
from core import market as m

fails = []


def check(name, got, want=True):
    ok = got == want
    if not ok:
        fails.append(f"{name}: got {got!r}, want {want!r}")
    print(f"  {'ok  ' if ok else 'FAIL'} {name}")


def order(side, plat, rank, subtype, who, status):
    return {"type": side, "platinum": plat, "rank": rank, "subtype": subtype,
            "user": {"ingameName": who, "status": status}}


# One book. 'me' is the account we're repricing for and must never count.
BOOK = {"data": [
    order("sell", 100, 5, "radiant", "alice", "ingame"),    # counts
    order("sell",  90, 5, "radiant", "bob",   "online"),    # counts (the min)
    order("sell",  10, 0, "radiant", "carol", "ingame"),    # WRONG RANK
    order("sell",  50, 5, "flawless", "dave", "ingame"),    # WRONG SUBTYPE
    order("sell",  20, 5, "radiant", "erin",  "offline"),   # OFFLINE
    order("sell",   5, 5, "radiant", "ME",    "ingame"),    # SELF (case-insensitive)
    order("buy",  200, 5, "radiant", "frank", "ingame"),    # buy-side, counts
    order("buy",  210, 5, "radiant", "gwen",  "online"),    # buy-side max
    order("buy",  999, 5, "radiant", "me",    "ingame"),    # buy self, excluded
]}

client = m.MarketClient(None)
# instance attribute shadows the bound method; _online_prices calls
# self._req("GET", path), so the stub takes (method, path[, body]).
client._req = lambda method, path, body=None: BOOK

print("lowest_online: rank + subtype + online + not-self")
check("only rank-5 radiant online non-self sellers, min of them",
      client.lowest_online("x", exclude="me", rank=5, subtype="radiant"),
      (90, 2))

print("\nhighest_online mirrors it on the buy side")
check("only rank-5 radiant online non-self buyers, max of them",
      client.highest_online("x", exclude="me", rank=5, subtype="radiant"),
      (210, 2))

print("\nrank=None / subtype=None means 'do not filter by identity'")
check("the whole online non-self sell book (all ranks/subtypes)",
      client.lowest_online("x", exclude="me"),
      (10, 4))               # alice100, bob90, carol10, dave50 -> min 10, n 4

print("\nno matching good online -> (None, 0), never a crash")
check("a rank nobody is offering",
      client.lowest_online("x", exclude="me", rank=3, subtype="radiant"),
      (None, 0))

print("\nself-exclusion is case-insensitive")
check("'me' excludes the 'ME' seller (would otherwise be the 5p min)",
      client.lowest_online("x", exclude="ME", rank=5, subtype="radiant"),
      (90, 2))

print("\ntarget_price (SELL): match lowest, never below floor")
check("match the low above the floor", m.target_price(30, 25, 20), 25)
check("floor bites when low is under it", m.target_price(30, 10, 20), 20)
check("hold current when nobody online", m.target_price(30, None, 20), 30)
check("but never below the floor even holding", m.target_price(10, None, 20), 20)

print("\ntarget_price_buy (BUY): match highest, never above cap")
check("match the high below the cap", m.target_price_buy(30, 40, 50), 40)
check("cap bites when high is over it", m.target_price_buy(30, 60, 50), 50)
check("hold current when nobody online", m.target_price_buy(45, None, 50), 45)
check("but never above the cap even holding", m.target_price_buy(70, None, 50), 50)

print("\nSession.bearer normalises any stored form to 'Bearer <raw>'")
from core import session as s
check("a JWT-prefixed token", s.Session(jwt="JWT abc", username="u").bearer,
      "Bearer abc")
check("an already-Bearer token is not double-wrapped",
      s.Session(jwt="Bearer abc", username="u").bearer, "Bearer abc")
check("a bare token", s.Session(jwt="abc", username="u").bearer, "Bearer abc")
check("all three normalise to the same header",
      s.Session(jwt="JWT abc", username="u").bearer
      == s.Session(jwt="Bearer abc", username="u").bearer
      == s.Session(jwt="abc", username="u").bearer, True)

print()
if fails:
    print(f"{len(fails)} FAILURES:")
    for f in fails:
        print("   ", f)
    sys.exit(1)
print("ALL MARKET-CLIENT CHECKS PASSED")
