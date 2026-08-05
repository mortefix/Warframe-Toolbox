"""Check core.vosfor_vm against the real collections + the user's inventory.

The point is equivalence: every derivation here replaced an inline expression
in VosforView, so each one is re-implemented independently below and compared.
"""
import sys
# These tests print the glyphs the UI actually uses. A Windows console
# defaults to cp1252, which cannot encode them, so a PASSING test could
# still die in its own print statement.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
from core import vosfor, vosfor_vm as vm, wf_inventory

fails = []


def check(name, got, want):
    ok = got == want
    if not ok:
        fails.append(f"{name}: got {got!r}, want {want!r}")
    print(f"  {'ok  ' if ok else 'FAIL'} {name}")


print("parse_balance")
check("plain", vm.parse_balance("150000"), 150000)
check("blank -> 0", vm.parse_balance("  "), 0)
check("junk -> 0", vm.parse_balance("abc"), 0)
check("negative clamped", vm.parse_balance("-5"), 0)

print("\nprice_age")
now = 1_000_000_000.0
check("None when never fetched", vm.price_age(None, now), None)
fresh = vm.price_age(now - 2 * 86400, now)
check("fresh is ok", fresh.level, "ok")
check("fresh has no age suffix", "d old" in fresh.text, False)
old = vm.price_age(now - 9 * 86400, now)
check("9 days is warn", old.level, "warn")
check("9 days shows age", "(9d old)" in old.text, True)
check("6 days still ok", vm.price_age(now - 6 * 86400, now).level, "ok")
check("7 days warns", vm.price_age(now - 7 * 86400, now).level, "warn")

print("\nsource_line")
check("no inventory", vm.source_line(None, None, False).level, "warn")
check("no inventory copy",
      "tick arcanes manually" in vm.source_line(None, None, False).text, True)
check("stale cache warns", vm.source_line({}, now, True, "alecaframe").level, "warn")
check("stale mentions unavailable",
      "AlecaFrame unavailable" in vm.source_line({}, now, True, "alecaframe").text,
      True)
check("fresh is ok", vm.source_line({}, now, False, "alecaframe").level, "ok")
check("fresh names the source",
      "inventory from AlecaFrame" in vm.source_line({}, now, False, "alecaframe").text,
      True)
check("names the companion source",
      "the Overwolf companion"
      in vm.source_line({}, now, False, "overwolf-companion").text, True)
check("unknown source is generic",
      "the inventory source" in vm.source_line({}, now, False, None).text, True)
check("missing mtime tolerated",
      "?" in vm.source_line({}, None, False, "alecaframe").text, True)

print("\nall_arcane_names (against the real collections file)")
cols = vosfor.load_collections()
names = vm.all_arcane_names(cols)
old_way = sorted({a["name"] for c in cols.values()
                  for t in c["tiers"].values() for a in t["arcanes"]})
check("matches the expression it replaced", names, old_way)
check("non-trivial", len(names) > 100, True)

print("\nrow derivations (against the real evaluated model)")
owned, mtime, stale = wf_inventory.read_arcanes_cached()
model = vosfor.evaluate(owned, vosfor.load_overrides(),
                        {"farm": True, "market": True}, {})
rows = [a for c in model["collections"].values() for a in c["arcanes"]]
print(f"   {len(rows)} arcane rows in the live model")

bad_frac = bad_farm = bad_price = 0
for arc in rows:
    r = vm.arcane_row(arc)
    # fraction: re-derive the old inline expression
    mc = arc.get("max_copies") or 0
    have = min(arc.get("copies") or 0, mc)
    if r["fraction"] != f"{have:02d}/{min(mc,99):02d}":
        bad_frac += 1
    # farm band
    fe = arc.get("farm_ease", 0.5)
    want = ("farm: easy" if fe >= 0.6 else
            "farm: hard" if fe <= 0.2 else "farm: med")
    if r["farm_text"] != want:
        bad_farm += 1
    # price cell
    price, buyout = arc.get("price"), arc.get("buyout")
    if buyout and arc["status"] != vosfor.MAXED:
        wt, wc = f"{buyout}p", buyout < vosfor.FULL_MAX_PLAT
    elif price is not None:
        wt, wc = f"{price}p", False
    else:
        wt, wc = "—", False
    if (r["price_text"], r["price_cheap"]) != (wt, wc):
        bad_price += 1

check("fraction matches on every row", bad_frac, 0)
check("farm band matches on every row", bad_farm, 0)
check("price cell matches on every row", bad_price, 0)
check("every row has a name", all(vm.arcane_row(a)["name"] for a in rows), True)

print("\nnext_override cycle")
ov = {}
arc = {"path": "/L/x", "status": "missing"}
vm.next_override(ov, arc)
check("absent -> records the opposite", ov, {"/L/x": True})
vm.next_override(ov, arc)
check("present -> clears", ov, {})
maxed = {"path": "/L/y", "status": vosfor.MAXED}
vm.next_override(ov, maxed)
check("maxed records False", ov, {"/L/y": False})
check("no path is a no-op", vm.next_override(ov, {"status": "missing"}), False)

print("\nreco_lines (live model)")
lines0 = vm.reco_lines(model, {"farm": True, "market": True}, 0)
check("returns lines with no balance", len(lines0) >= 1, True)
big = vm.reco_lines(model, {"farm": True, "market": True}, 200_000)
check("balance adds a split plan", len(big) > len(lines0), True)
check("plan mentions Vosfor", any("Vosfor" in l for l in big), True)
done = {"ranking": ["A"], "collections": {"A": {"completed": True}},
        "weighting": False}
check("all complete -> single line", len(vm.reco_lines(done, {}, 0)), 1)
check("all complete copy",
      "Save your Vosfor" in vm.reco_lines(done, {}, 0)[0], True)

print("\ncollection progress is measured in COPIES, not finished arcanes")
# The flaw this replaces: `maxed / total` scored an arcane at 20/21 exactly
# the same as one at 0/21, so grinding 20 copies moved the bar by nothing. On
# the real inventory it understated Hollvania as 9% when it was 56%.


def coll(pairs, completed=None):
    """`pairs` are (owned, max) per arcane."""
    maxed = sum(1 for h, m in pairs if m and h >= m)
    return {"total": len(pairs), "maxed": maxed,
            "copies_owned": sum(min(h, m) for h, m in pairs if m),
            "copies_total": sum(m for _h, m in pairs if m),
            "completed": (maxed == len(pairs)) if completed is None
            else completed}


nothing = coll([(0, 21), (0, 21)])
half = coll([(21, 21), (0, 21)])
nearly = coll([(20, 21), (20, 21)])
check("nothing owned is 0", vm.collection_progress(nothing), 0.0)
check("one of two maxed is half", vm.collection_progress(half), 0.5)
# THE point: two arcanes one copy short each are all but done, and the old
# arcane-count model scored that identically to owning nothing at all
check("40 of 42 copies reads as nearly complete",
      round(vm.collection_progress(nearly), 3), 0.952)
check("where the old model called it zero",
      nearly["maxed"] / nearly["total"], 0.0)

full = coll([(21, 21), (10, 10)])
check("everything maxed is exactly 1.0", vm.collection_progress(full), 1.0)

spares = {"total": 2, "maxed": 2, "copies_owned": 60, "copies_total": 42,
          "completed": True}
check("hoarded spares cap at 100%", vm.collection_progress(spares), 1.0)

# an arcane whose maximum is unknown is left OUT of the copy count, so every
# copy it CAN measure may be owned while the collection is still unfinished
unknown_size = {"total": 3, "maxed": 2, "copies_owned": 42,
                "copies_total": 42, "completed": False}
check("an unfinished collection never shows a FULL bar",
      vm.collection_progress(unknown_size) < 1.0, True)
check("but still reads as nearly there",
      vm.collection_progress(unknown_size), 0.99)

no_sizes = {"total": 4, "maxed": 1, "copies_owned": 0, "copies_total": 0,
            "completed": False}
check("with no copy data at all it falls back to the arcane count",
      vm.collection_progress(no_sizes), 0.25)
check("an empty collection does not divide by zero",
      vm.collection_progress({"total": 0, "maxed": 0, "copies_total": 0,
                              "completed": False}), 0.0)

print("\nand the header reports both counts")
row = vm.collection_row("Ostron", dict(half, needed=1, per_buy=2.32,
                                       vosfor=200), False)
check("arcanes still needed", "needs 1/2" in row["stat"], True)
check("and copies owned", "21/42 copies" in row["stat"], True)
check("the bar follows the copies", row["fraction"], 0.5)

print("\nagainst the REAL inventory, nothing regressed")
_owned, _m, _s = vosfor.refresh_inventory()
live = vosfor.evaluate(_owned)
for _name, _c in live["collections"].items():
    old = _c["maxed"] / _c["total"] if _c["total"] else 0.0
    new = vm.collection_progress(_c)
    # copies can only ever be ahead of finished-arcane count, never behind
    check(f"{_name} never reads LOWER than before",
          new >= old - 1e-9, True)
    check(f"{_name} stays in range", 0.0 <= new <= 1.0, True)
    if _c["completed"]:
        check(f"{_name} is complete and shows 100%", new, 1.0)

print()
if fails:
    print(f"{len(fails)} FAILURES:")
    for f in fails:
        print("   ", f)
    sys.exit(1)
print("ALL VOSFOR VIEW-MODEL CHECKS PASSED")
