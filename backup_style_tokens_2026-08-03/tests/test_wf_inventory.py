"""core.wf_inventory - the owned-inventory provider seam. No AlecaFrame decrypt
and no Overwolf: a fake companion inventory.json is read, provider availability is
monkeypatched, and the store is redirected to a temp dir."""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "data"))
from core import arcane_inv, store, wf_inventory

fails = []


def check(name, got, want):
    ok = got == want
    if not ok:
        fails.append(f"{name}: got {got!r}, want {want!r}")
    print(f"  {'ok  ' if ok else 'FAIL'} {name}")


# A plaintext game-events inventory (what the companion writes) - same shape as a
# decrypted lastData.dat, so one normalizer serves both.
FAKE_INV = {
    "RawUpgrades": [
        {"ItemType": "/Lotus/Upgrades/CosmeticEnhancers/ArcaneGrace", "ItemCount": 3}],
    "Upgrades": [
        {"ItemType": "/Lotus/Upgrades/Mods/Vitality",
         "UpgradeFingerprint": "{\"lvl\":5}"}],
    "PremiumCredits": 68, "RegularCredits": 25965737, "FusionPoints": 8205,
    "MiscItems": [], "Recipes": [], "Consumables": [],
}

companion = wf_inventory.PROVIDERS[0]
aleca = wf_inventory.PROVIDERS[1]

with tempfile.TemporaryDirectory() as d:
    store.WF_DATA_DIR = Path(d) / ".wf_data"
    inv_path = Path(d) / "inventory.json"
    companion.PATH = inv_path
    # keep AlecaFrame out of the picture unless a test opts in
    arcane_inv.LASTDATA = Path(d) / "no_such_lastData.dat"

    print("no source present")
    wf_inventory.invalidate()
    check("nothing available", wf_inventory.available(), False)
    check("no active provider", wf_inventory.active_provider(), None)
    check("source_name None", wf_inventory.source_name(), None)
    check("refresh returns None (no cache yet)",
          wf_inventory.refresh_overview(), None)

    print("\nOverwolf companion supplies inventory")
    inv_path.write_text(json.dumps(FAKE_INV), encoding="utf-8")
    wf_inventory.invalidate()
    check("companion available", wf_inventory.available(), True)
    check("active is the companion",
          wf_inventory.source_name(), "overwolf-companion")
    ov = wf_inventory.refresh_overview()
    check("overview built", ov is not None, True)
    check("stamped with source", ov["_source"], "overwolf-companion")
    check("platinum", ov["platinum"], 68)
    check("endo", ov["endo"], 8205)
    check("distinct arcanes", ov["distinct_arcanes"], 1)
    check("ranked instances", ov["ranked_mod_arcane_instances"], 1)
    check("stored + readable", store.read("inventory")["platinum"], 68)

    print("\narcanes + counts come from the active provider")
    wf_inventory.invalidate()
    owned, mt, stale = wf_inventory.read_arcanes_cached(force=True)
    check("arcane owned map",
          owned["/Lotus/Upgrades/CosmeticEnhancers/ArcaneGrace"],
          {"best_rank": 0, "copies": 3})
    check("not stale on a live read", stale, False)
    check("fresh cache is not stale", wf_inventory.cache_is_stale(mt), False)
    check("a bogus mtime is stale", wf_inventory.cache_is_stale(None), True)
    check("count_owned arcane",
          wf_inventory.count_owned("/Lotus/Upgrades/CosmeticEnhancers/ArcaneGrace"), 3)
    check("count_owned mod",
          wf_inventory.count_owned("/Lotus/Upgrades/Mods/Vitality"), 1)
    check("count_owned unknown -> 0",
          wf_inventory.count_owned("/Lotus/Nope"), 0)

    print("\ncompanion is PREFERRED over AlecaFrame")
    aleca.available = lambda: True          # pretend AlecaFrame is also present
    aleca.source_mtime = lambda: 1.0
    aleca.read_raw = lambda: {"PremiumCredits": 1}
    check("companion still wins", wf_inventory.source_name(), "overwolf-companion")

    print("\nfalls back to AlecaFrame when the companion is gone")
    inv_path.unlink()
    wf_inventory.invalidate()
    check("active is AlecaFrame now", wf_inventory.source_name(), "alecaframe")
    ov2 = wf_inventory.refresh_overview(force=True)
    check("re-sourced overview", ov2["_source"], "alecaframe")
    check("new source's data", ov2["platinum"], 1)

    print("\nno source -> keep the last cached overview, don't wipe it")
    aleca.available = lambda: False
    wf_inventory.invalidate()
    check("nothing available again", wf_inventory.available(), False)
    check("refresh returns the cache", wf_inventory.refresh_overview()["platinum"], 1)

    print("\nLinux seam is reserved (present but unavailable)")
    linux = wf_inventory.PROVIDERS[2]
    check("linux provider named", linux.name, "linux-gep")
    check("linux not available", linux.available(), False)

if fails:
    print("\n" + "\n".join(fails))
    raise SystemExit(1)
print("\nall wf_inventory checks passed")
