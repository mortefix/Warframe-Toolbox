"""Behaviour tests for core.listings_vm."""
import sys
# These tests print the glyphs the UI actually uses. A Windows console
# defaults to cp1252, which cannot encode them, so a PASSING test could
# still die in its own print statement.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
from core import listings_vm as vm

fails = []


def check(name, got, want):
    ok = got == want
    if not ok:
        fails.append(f"{name}: got {got!r}, want {want!r}")
    print(f"  {'ok  ' if ok else 'FAIL'} {name}")


class L:
    def __init__(self, name, plat, qty=1, visible=True, low=None):
        self.name, self.platinum, self.quantity = name, plat, qty
        self.visible, self.market_low = visible, low

    def __repr__(self):
        return f"<{self.name} {self.platinum}p x{self.quantity}>"


DATA = [
    L("Ash Prime Set", 120, 2, True, 100),
    L("banshee prime set", 45, 1, False, None),
    L("Chroma Prime Set", 80, 3, True, 90),
    L("Ash Prime Blueprint", 20, 5, False, 15),
]

print("SideSpec")
s, b = vm.spec("sell"), vm.spec("buy")
check("sell offset key", s.offset_key, "global_offset")
check("buy offset key", b.offset_key, "global_offset_buy")
check("sell override key", s.override_key, "floors")
check("buy override key", b.override_key, "caps")
check("sell limit word", s.limit_word, "floor")
check("buy limit word", b.limit_word, "cap")
check("sell best word", s.best_word, "low")
check("buy best word", b.best_word, "high")
check("sell verb", s.done_verb, "Sold")
check("buy verb", b.done_verb, "Bought")
check("sell title", s.limit_title, "Repricer minimum")
check("buy title", b.limit_title, "Repricer maximum")
check("sell short", s.limit_short, "repricer min:")
check("buy short", b.limit_short, "repricer max:")
check("sell badge", s.badge_text, " wts ")
check("buy badge", b.badge_text, " wtb ")
check("no colours leaked into core",
      any("bg" in f or "fg" in f for f in vm.SideSpec._fields), False)

print("\nvisible_filter")
check("All keeps everything", len(vm.visible_filter(DATA, "All")), 4)
check("Visible", [l.name for l in vm.visible_filter(DATA, "Visible")],
      ["Ash Prime Set", "Chroma Prime Set"])
check("Hidden", [l.name for l in vm.visible_filter(DATA, "Hidden")],
      ["banshee prime set", "Ash Prime Blueprint"])
check("unknown mode -> all", len(vm.visible_filter(DATA, "???")), 4)

print("\narrange")
check("by name is case-insensitive",
      [l.name for l in vm.arrange(DATA, "All", "Name")],
      ["Ash Prime Blueprint", "Ash Prime Set", "banshee prime set",
       "Chroma Prime Set"])
check("by price", [l.platinum for l in vm.arrange(DATA, "All", "Price")],
      [20, 45, 80, 120])
check("descending",
      [l.platinum for l in vm.arrange(DATA, "All", "Price", desc=True)],
      [120, 80, 45, 20])
check("by quantity", [l.quantity for l in vm.arrange(DATA, "All", "Quantity")],
      [1, 2, 3, 5])
# the one with a trap: unknown market data must sort last EITHER WAY
asc = vm.arrange(DATA, "All", "Market best")
check("market best: unknown last ascending", asc[-1].market_low, None)
desc = vm.arrange(DATA, "All", "Market best", desc=True)
check("market best: unknown first descending", desc[0].market_low, None)
check("market best ordering", [l.market_low for l in asc[:3]], [15, 90, 100])
check("filter+sort compose",
      [l.name for l in vm.arrange(DATA, "Visible", "Price")],
      ["Chroma Prime Set", "Ash Prime Set"])

print("\nsuggest")
names = [l.name for l in DATA]
check("one char is too short", vm.suggest(names, "a"), [])
check("empty is too short", vm.suggest(names, ""), [])
check("prefix before substring", vm.suggest(names, "as"),
      ["Ash Prime Blueprint", "Ash Prime Set"])
check("case-insensitive prefix", vm.suggest(names, "BAN"),
      ["banshee prime set"])
check("substring matches too", vm.suggest(names, "prime")[0],
      "Ash Prime Blueprint")
check("no match", vm.suggest(names, "zzz"), [])
check("deduplicates", vm.suggest(["Ash", "Ash", "Ash"], "as"), ["Ash"])
check("respects the limit", len(vm.suggest([f"Ash {i}" for i in range(50)],
                                           "ash")), 10)
# a name that both starts with AND contains the query must appear once
check("prefix hit not repeated in substring group",
      vm.suggest(["abcabc"], "abc"), ["abcabc"])

print("\nfind_match")
pairs = [("o1", "chroma prime set"), ("o2", "ash prime set"),
         ("o3", "ash prime blueprint")]
check("prefix wins over earlier substring", vm.find_match(pairs, "ash"), "o2")
check("substring when no prefix", vm.find_match(pairs, "prime set"), "o1")
check("display order breaks ties", vm.find_match(pairs, "ash prime"), "o2")
check("no match -> None", vm.find_match(pairs, "zzz"), None)
check("empty query -> None", vm.find_match(pairs, "   "), None)

print("\nsmall rules")
check("ledger multiplies by quantity", vm.ledger_total(DATA),
      120 * 2 + 45 + 80 * 3 + 20 * 5)
check("ledger of nothing", vm.ledger_total([]), 0)
check("needs_visibility -> hide",
      [l.name for l in vm.needs_visibility(DATA, False)],
      ["Ash Prime Set", "Chroma Prime Set"])
check("needs_visibility -> show",
      [l.name for l in vm.needs_visibility(DATA, True)],
      ["banshee prime set", "Ash Prime Blueprint"])
check("nothing to do is empty",
      vm.needs_visibility([L("x", 1, 1, True)], True), [])
check("last unit closes", vm.closes_listing(1), True)
check("zero closes", vm.closes_listing(0), True)
check("two does not close", vm.closes_listing(2), False)
check("increment", vm.adjust_quantity(3, +1), 4)
check("decrement", vm.adjust_quantity(3, -1), 2)
check("cannot reach zero", vm.adjust_quantity(1, -1), None)
check("cannot go negative", vm.adjust_quantity(2, -5), None)
check("one is allowed", vm.adjust_quantity(2, -1), 1)

print()
if fails:
    print(f"{len(fails)} FAILURES:")
    for f in fails:
        print("   ", f)
    sys.exit(1)
print("ALL LISTINGS VIEW-MODEL CHECKS PASSED")
