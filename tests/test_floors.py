"""Behaviour tests for core.floors and core.repricer.

These pin the rules that were previously only expressible by reading
ListingsTab, notably the one that is easy to get wrong: an override equal to
the derived default is NOT an override.
"""
import sys
# These tests print the glyphs the UI actually uses. A Windows console
# defaults to cp1252, which cannot encode them, so a PASSING test could
# still die in its own print statement.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
from core import floors, repricer

fails = []


def check(name, got, want):
    ok = got == want
    if not ok:
        fails.append(f"{name}: got {got!r}, want {want!r}")
    print(f"  {'ok  ' if ok else 'FAIL'} {name}")


def fresh(offset=0, overrides=None):
    prefs = {"global_offset": offset, "floors": dict(overrides or {})}
    return floors.Limits({}, prefs, "global_offset", "floors")


print("core.floors")
# -- reference pins on first sight, then never moves on its own
L = fresh()
check("reference pins first sight", L.reference("o1", 100), 100)
check("reference ignores later price", L.reference("o1", 250), 100)

# -- auto limit = reference + offset, floored at 1
L = fresh(offset=-10)
check("auto applies offset", L.auto("o1", 100), 90)
L = fresh(offset=-500)
check("auto floors at 1", L.auto("o1", 100), 1)
L = fresh(offset=+7)
check("auto positive offset", L.auto("o1", 100), 107)

# -- override wins over auto
L = fresh(offset=-10, overrides={"ash_prime_set": 55})
check("override wins", L.limit("ash_prime_set", "o1", 100), 55)
check("no override -> auto", L.limit("other", "o2", 100), 90)

# -- commit rules
L = fresh(offset=-10)
check("commit empty clears", L.commit("", "s", "o1", 100).action, "cleared")
check("commit junk rejects", L.commit("abc", "s", "o1", 100).action, "rejected")
check("commit junk writes nothing", L.overrides, {})
check("commit value sets", L.commit("42", "s", "o1", 100).action, "set")
check("commit stored", L.overrides["s"], 42)
# THE rule: typing exactly the derived value means "follow the default"
check("commit == auto clears", L.commit("90", "s", "o1", 100).action, "cleared")
check("commit == auto removed it", "s" in L.overrides, False)
check("commit clamps to >= 1", L.commit("0", "s", "o1", 100).value, 1)
check("whitespace tolerated", L.commit("  33  ", "t", "o1", 100).value, 33)

# -- rebase: a hand-set price becomes the new reference
L = fresh(offset=-10)
L.reference("o1", 100)
L.rebase("o1", 200)
check("rebase moves the default", L.auto("o1", 100), 190)

# -- set_offset reports whether a save is needed
L = fresh(offset=5)
check("set_offset same -> no save", L.set_offset(5), False)
check("set_offset changed -> save", L.set_offset(6), True)
check("set_offset applied", L.offset, 6)

# -- parsers
check("parse_offset '+5'", floors.parse_offset("+5", 0), 5)
check("parse_offset '-3'", floors.parse_offset("-3", 0), -3)
check("parse_offset empty -> 0", floors.parse_offset("  ", 9), 0)
check("parse_offset junk -> None", floors.parse_offset("x", 9), None)

# -- Limits shares the caller's dicts, it does not copy them
prefs = {"global_offset": 0, "floors": {}}
base = {}
L = floors.Limits(base, prefs, "global_offset", "floors")
L.commit("77", "s", "o1", 100)
L.reference("o9", 5)
check("writes through to caller prefs", prefs["floors"], {"s": 77})
check("writes through to caller baseline", base, {"o9": 5, "o1": 100})

print("\ncore.repricer.better_than")
check("sell: cheaper is better", repricer.better_than("sell", 40, 50), True)
check("sell: dearer is not", repricer.better_than("sell", 60, 50), False)
check("sell: equal is not", repricer.better_than("sell", 50, 50), False)
check("buy: higher is better", repricer.better_than("buy", 60, 50), True)
check("buy: lower is not", repricer.better_than("buy", 40, 50), False)
check("None is never better", repricer.better_than("sell", None, 50), False)
check("limit_label sell", repricer.limit_label("sell"), "min")
check("limit_label buy", repricer.limit_label("buy"), "max")

print("\ncore.repricer.reprice")


class FakeMarket:
    MarketError = None

    def __init__(self, best, n=3, fail=None):
        self.best, self.n, self.fail, self.wrote = best, n, fail, None
        self.asked_rank = self.asked_subtype = "unset"

    def lowest_online(self, slug, exclude=None, rank=None, subtype=None):
        # record what was asked, so a test can prove the repricer benchmarks
        # against the SAME good rather than the whole order book
        self.asked_rank, self.asked_subtype = rank, subtype
        return self.best, self.n
    highest_online = lowest_online

    def update_order(self, oid, price, qty, vis):
        if self.fail:
            raise self.fail
        self.wrote = (oid, price, qty, vis)


class L2:
    def __init__(self, plat, rank=None, subtype=None):
        self.order_id, self.slug = "o1", "s"
        self.platinum, self.quantity, self.visible = plat, 2, True
        self.rank, self.subtype = rank, subtype


check("no market -> not ok",
      repricer.reprice(L2(50), None, "me", "sell", 10).ok, False)

l = L2(50)
m = FakeMarket(best=40)
r = repricer.reprice(l, m, "me", "sell", 10)
check("sell undercut -> ok", r.ok, True)
check("sell pushed the order", m.wrote is not None, True)
check("sell mutated the listing", l.platinum, r.new_price)
check("book snapshot carried", (r.best, r.online), (40, 3))

l = L2(50)
m = FakeMarket(best=5)          # market is below our floor of 10
r = repricer.reprice(l, m, "me", "sell", 10)
check("clamp detected", r.clamped, True)
check("clamp mentioned in message", "min 10p held" in r.message, True)

l = L2(50)
m = FakeMarket(best=None)       # nobody online
r = repricer.reprice(l, m, "me", "sell", 10)
check("empty book still ok", r.ok, True)
check("empty book is not clamped", r.clamped, False)

from core import market as core_market
l = L2(50)
m = FakeMarket(best=40, fail=core_market.MarketError("boom"))
r = repricer.reprice(l, m, "me", "sell", 10)
check("MarketError -> not ok", r.ok, False)
check("MarketError message", r.message, "boom")
check("failed reprice left price alone", l.platinum, 50)

# the reprice must benchmark against the SAME good: a rank-5 arcane's price
# is not set by rank-0 listings. Regression guard for the audit finding.
ranked = L2(50, rank=5, subtype="radiant")
mm = FakeMarket(best=40)
repricer.reprice(ranked, mm, "me", "sell", 10)
check("reprice passes the listing's rank through", mm.asked_rank, 5)
check("and its subtype", mm.asked_subtype, "radiant")
plain = L2(50)                  # a good that does not rank
repricer.reprice(plain, FakeMarket(best=40), "me", "sell", 10)
check("an unranked good asks with rank=None (whole book)", plain.rank, None)

# --- BUY side: highest_online + target_price_buy + the buy-side clamp. The
#     whole side!='sell' branch was exercised by no test (audit finding). The
#     asymmetry: a buyer is beaten by a HIGHER offer and clamped by a cap, the
#     mirror of the seller's floor. ---
l = L2(30)
r = repricer.reprice(l, FakeMarket(best=40), "me", "buy", 50)   # top buyer under cap
check("buy match -> ok", r.ok, True)
check("buy matches the top buyer exactly", r.new_price, 40)
check("buy under cap is not clamped", r.clamped, False)

l = L2(30)
r = repricer.reprice(l, FakeMarket(best=60), "me", "buy", 50)   # top buyer over cap
check("buy above cap clamps to the cap", r.new_price, 50)
check("buy clamp detected", r.clamped, True)
check("buy clamp says 'max', not 'min'", "max 50p held" in r.message, True)

l = L2(30)
r = repricer.reprice(l, FakeMarket(best=None), "me", "buy", 50)  # nobody buying
check("buy empty book holds current under cap", r.new_price, 30)
check("buy empty book is ok and unclamped", (r.ok, r.clamped), (True, False))

rb = L2(30, rank=5, subtype="radiant")
mb = FakeMarket(best=40)
repricer.reprice(rb, mb, "me", "buy", 50)
check("buy benchmarks the SAME good: rank passed through", mb.asked_rank, 5)
check("and its subtype", mb.asked_subtype, "radiant")

print()
if fails:
    print(f"{len(fails)} FAILURES:")
    for f in fails:
        print("   ", f)
    sys.exit(1)
print("ALL FLOOR/REPRICER CHECKS PASSED")
