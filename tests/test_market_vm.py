"""Behaviour tests for core.market_vm."""
import sys
# These tests print the glyphs the UI actually uses. A Windows console
# defaults to cp1252, which cannot encode them, so a PASSING test could
# still die in its own print statement.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
from core import config, market_vm as vm

fails = []


def check(name, got, want=True):
    ok = got == want
    if not ok:
        fails.append(f"{name}: got {got!r}, want {want!r}")
    print(f"  {'ok  ' if ok else 'FAIL'} {name}")


INDEX = [("Ash Prime Set", "ash_prime_set", "t.png"),
         ("Banshee Prime Set", "banshee_prime_set", "t.png"),
         ("Ash Prime Blueprint", "ash_prime_blueprint", "t.png")]

print("suggest_pairs")
check("prefix before substring", vm.suggest_pairs(INDEX, "as"),
      [("Ash Prime Set", "ash_prime_set"),
       ("Ash Prime Blueprint", "ash_prime_blueprint")])
check("one char is too short", vm.suggest_pairs(INDEX, "a"), [])
check("case-insensitive", len(vm.suggest_pairs(INDEX, "BANSHEE")), 1)
check("substring hit", vm.suggest_pairs(INDEX, "prime")[0][1],
      "ash_prime_set")
# the same helper serves the weapon pools, whose rows have only two columns
check("works on 2-column rows",
      vm.suggest_pairs([("Kuva Bramma", "kuva_bramma")], "bram"),
      [("Kuva Bramma", "kuva_bramma")])
check("respects the limit",
      len(vm.suggest_pairs([(f"Ash {i}", f"a{i}") for i in range(40)], "ash")),
      10)

print("\nscope_filter — in-game NARROWS online")
check("both off is everyone", vm.scope_filter(False, False),
      (None, "total"))
check("online only", vm.scope_filter(False, True),
      (("ingame", "online"), "online"))
check("in-game only", vm.scope_filter(True, False), (("ingame",), "in-game"))
check("in-game wins over online", vm.scope_filter(True, True),
      (("ingame",), "in-game"))

print("\nfilter_orders")
rows = [{"status": "ingame"}, {"status": "online"}, {"status": "offline"}]
check("None keeps everything", len(vm.filter_orders(rows, None)), 3)
check("online keeps two", len(vm.filter_orders(rows, ("ingame", "online"))), 2)
check("ingame keeps one", len(vm.filter_orders(rows, ("ingame",))), 1)

print("\nstatus_dot returns a ROLE, never a colour")
check("ingame", vm.status_dot("ingame"), ("●", "ingame"))
check("online", vm.status_dot("online"), ("●", "ok"))
check("offline", vm.status_dot("offline"), ("●", "muted"))
check("unknown status degrades", vm.status_dot("???"), ("●", "muted"))
check("no hex leaks out", any("#" in r for _g, r in
                              [vm.status_dot(s) for s in
                               ("ingame", "online", "offline")]), False)

print("\nwhisper_message — a WTS row means I am BUYING")
row = {"user": "Tenno", "platinum": 42}
buy = vm.whisper_message({}, "sell", row, "Ash Prime Set")
sell = vm.whisper_message({}, "buy", row, "Ash Prime Set")
check("wts row uses the buy template", buy, config.DEFAULTS["msg_buy"].format(
    user="Tenno", item="Ash Prime Set", price=42))
check("wtb row uses the sell template", sell,
      config.DEFAULTS["msg_sell"].format(user="Tenno", item="Ash Prime Set",
                                         price=42))
check("they differ", buy != sell)
check("a custom template is honoured",
      vm.whisper_message({"msg_buy": "hi {user} {price}"}, "sell", row, "X"),
      "hi Tenno 42")
# a user can edit these in Settings, so a bad one must not raise
check("an unknown field falls back to the default",
      vm.whisper_message({"msg_buy": "{nope}"}, "sell", row, "X"),
      config.DEFAULTS["msg_buy"].format(user="Tenno", item="X", price=42))
check("malformed braces fall back",
      vm.whisper_message({"msg_buy": "{"}, "sell", row, "X").startswith("/w"),
      True)

print("\nwatchlist")
check("watched is gilded", vm.watch_label(True), ("★ Watched", "accent"))
check("unwatched is muted", vm.watch_label(False), ("☆ Watch", "muted"))
check("toggle adds", vm.toggle_watch(["a"], "b"), ["a", "b"])
check("toggle removes", vm.toggle_watch(["a", "b"], "b"), ["a"])
original = ["a"]
vm.toggle_watch(original, "b")
check("toggle does not mutate its input", original, ["a"])

print("\nbest_live_prices — offline orders are not prices you can trade at")
book = {"sell": [{"platinum": 40, "status": "ingame"},
                 {"platinum": 10, "status": "offline"}],
        "buy": [{"platinum": 25, "status": "online"},
                {"platinum": 99, "status": "offline"}]}
check("cheapest LIVE seller", vm.best_live_prices(book)[0], 40)
check("richest LIVE buyer", vm.best_live_prices(book)[1], 25)
check("empty book", vm.best_live_prices({"sell": [], "buy": []}),
      (None, None))
check("price line", vm.price_line(40, 25), "  sell 40p · buy 25p")
check("price line with nothing", vm.price_line(None, None),
      "  sell — · buy —")
check("half a price line", vm.price_line(40, None), "  sell 40p · buy —")

print("\ncontract_row")
riv = {"status": "ingame", "name": "Visi-critacan", "mastery": 14,
       "rerolls": 3, "polarity": "madurai",
       "attributes": ["+120% Damage", "-50% Zoom"],
       "buyout": 800, "starting": 400, "owner": "Tenno"}
r = vm.contract_row("riven", "Kuva Bramma", riv)
check("riven title", r["title"], " Kuva Bramma Visi-critacan")
check("riven meta has mr/rr/polarity", "mr14 · rr3 · madurai" in r["meta"])
check("riven meta has attributes", "+120% Damage" in r["meta"])
check("buyout wins when present", (r["price"], r["price_label"]),
      (800, "buyout"))

lich = {"status": "online", "element": "Heat", "damage": 58,
        "ephemera": True, "quirk": "laughs", "buyout": None,
        "starting": 150, "owner": "Tenno"}
r = vm.contract_row("lich", "Kuva Kohm", lich)
check("lich title", r["title"], " Kuva Kohm")
check("lich meta", r["meta"], "   Heat +58% · ephemera · laughs")
check("falls back to the opening bid", (r["price"], r["price_label"]),
      (150, "start"))
plain = dict(lich, ephemera=False, quirk=None)
check("no ephemera or quirk", vm.contract_row("lich", "K", plain)["meta"],
      "   Heat +58%")

print("\nsummaries")
check("book summary", vm.book_summary(3, 4, "online", 12),
      "3 sellers · 4 buyers (online) — showing best 12 per side")
check("contracts summary caps the shown count",
      vm.contracts_summary(50, "riven", "Kuva Bramma", 12),
      "50 riven contract(s) for Kuva Bramma — showing 12")
check("contracts summary under the cap",
      vm.contracts_summary(3, "lich", "Kuva Kohm", 12),
      "3 lich contract(s) for Kuva Kohm — showing 3")
# descriptive, not a bare arrow - the control names the order it produces,
# matching My Listings (a ▲/▼ is ambiguous about which way it sorts)
check("sort label ascending", vm.sort_label(True), "price low → high")
check("sort label descending", vm.sort_label(False), "price high → low")
check("pretty slug", vm.pretty_slug("ash_prime_set"), "Ash Prime Set")

print("\nrank_text - the column that was silently dropped")
check("a ranked arcane", vm.rank_text({"rank": 5}), "R-5")
# R0 is meaningful for a RANKABLE good: "this one is unranked" is exactly
# what a buyer needs to know, and it is why rank 0 is not treated as absent
check("unranked but rankable still shows R-0", vm.rank_text({"rank": 0}), "R-0")
check("a good that does not rank shows nothing",
      vm.rank_text({"rank": None}), "")
check("missing key shows nothing", vm.rank_text({}), "")
check("a relic subtype wins over rank",
      vm.rank_text({"rank": 0, "subtype": "radiant"}), "radiant")
check("the 'regular' subtype is not worth showing",
      vm.rank_text({"rank": 3, "subtype": "regular"}), "R-3")

print("\nstatus key")
check("one entry per dot colour", len(vm.STATUS_KEY), 3)
check("it names every status the book can show",
      sorted(r for r, _t in vm.STATUS_KEY), ["ingame", "muted", "ok"])
check("the key roles match what status_dot returns",
      {vm.status_dot(s)[1] for s in ("ingame", "online", "offline")},
      {r for r, _t in vm.STATUS_KEY})

print("\ncontract watchlist - a separate store from item slugs")
lst = vm.toggle_contract_watch([], "riven", "kuva_bramma", "Kuva Bramma")
check("adding stores kind, slug and name", lst,
      [{"kind": "riven", "slug": "kuva_bramma", "name": "Kuva Bramma"}])
check("it reads back as watched",
      vm.is_contract_watched(lst, "riven", "kuva_bramma"))
# kind is part of the identity: a lich Kuva Bramma is a different watch
check("the same weapon under another kind is NOT watched",
      vm.is_contract_watched(lst, "lich", "kuva_bramma"), False)
check("toggling again removes it",
      vm.toggle_contract_watch(lst, "riven", "kuva_bramma", "Kuva Bramma"), [])
before = list(lst)
vm.toggle_contract_watch(lst, "riven", "kuva_bramma", "x")
check("toggle does not mutate its input", lst, before)
check("scope_note covers every scope word",
      [vm.scope_note(w) for w in ("in-game", "online", "total")] != [], True)

print("\nreputation - arrows, and a muted role rather than a colour")
# the arrow is coloured, the NUMBER is not - a coloured digit stops reading
# as a quantity, which is why these are separate fields
r = vm.reputation({"reputation": 18})
check("positive gets an up arrow", (r.arrow, r.value, r.role),
      ("↑", "18", "rep_up"))
r = vm.reputation({"reputation": -4})
check("negative gets a down arrow and no minus sign",
      (r.arrow, r.value, r.role), ("↓", "4", "rep_down"))
# zero rep is not a verdict either way, so the row stays clean
check("zero shows nothing", bool(vm.reputation({"reputation": 0})), False)
check("missing shows nothing", bool(vm.reputation({})), False)
check("no hex crosses the boundary",
      "#" in vm.reputation({"reputation": 1}).role, False)

print("\nbest_contract_price - cheapest way in")
rows = [{"buyout": 800, "starting": 400}, {"buyout": None, "starting": 150}]
check("an opening bid can beat every buyout",
      vm.best_contract_price(rows), 150)
check("buyout used when present",
      vm.best_contract_price([{"buyout": 300, "starting": 900}]), 300)
check("nothing listed", vm.best_contract_price([]), None)
check("price line", vm.contract_price_line(150, 2), "  from 150p · 2 listed")
check("empty price line", vm.contract_price_line(None, 0), "  none listed")

print("\navailable_ranks - only what is actually listed")
book = {"sell": [{"rank": 5}, {"rank": 0}, {"rank": 3}],
        "buy": [{"rank": 3}]}
# ranks 1, 2 and 4 are absent from the book, so they must not be offered -
# picking a rank nobody sells is a dead end, and the gaps are information
check("sorted, deduplicated, gaps preserved", vm.available_ranks(book),
      [0, 3, 5])
check("both sides contribute",
      vm.available_ranks({"sell": [{"rank": 1}], "buy": [{"rank": 9}]}),
      [1, 9])
check("a good that does not rank offers nothing",
      vm.available_ranks({"sell": [{"rank": None}], "buy": []}), [])
check("an empty book", vm.available_ranks({}), [])

print("\nfilter_rank")
rows = [{"rank": 0}, {"rank": 5}, {"rank": 5}, {"rank": None}]
check("None means any", len(vm.filter_rank(rows, None)), 4)
check("an exact rank", len(vm.filter_rank(rows, 5)), 2)
check("rank 0 is a real choice, not 'unset'",
      len(vm.filter_rank(rows, 0)), 1)
check("a rank nobody has", vm.filter_rank(rows, 3), [])

print()
if fails:
    print(f"{len(fails)} FAILURES:")
    for f in fails:
        print("   ", f)
    sys.exit(1)
print("ALL MARKET VIEW-MODEL CHECKS PASSED")
