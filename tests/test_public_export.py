"""core.public_export - the DE Public Export item DB adapter. No network: byte
fetchers are injected (the index is a real LZMA blob built with lzma.compress, so
the DE-quirk decode path is exercised); the store is redirected to a temp dir."""
import json
import lzma
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "data"))
from core import public_export as pe
from core import store

fails = []


def check(name, got, want):
    ok = got == want
    if not ok:
        fails.append(f"{name}: got {got!r}, want {want!r}")
    print(f"  {'ok  ' if ok else 'FAIL'} {name}")


def lzma_index(lines):
    return lzma.compress("\n".join(lines).encode("utf-8"), format=lzma.FORMAT_ALONE)


WF_LINE = "ExportWarframes_en.json!00_HASHWF"
UP_LINE = "ExportUpgrades_en.json!00_HASHUP"

MANIFESTS = {
    WF_LINE: {"ExportWarframes": [
        {"uniqueName": "/Lotus/Powersuits/Ember/Ember", "name": "Ember"}]},
    UP_LINE: {"ExportUpgrades": [
        {"uniqueName": "/Lotus/Upgrades/Mods/Vitality", "name": "Vitality"}]},
}

# Mutable so a test can simulate a game update (a manifest hash changing).
STATE = {"lines": [WF_LINE, UP_LINE], "manifests": dict(MANIFESTS)}


def fake_get_bytes(url):
    if url == pe.INDEX_URL:
        return lzma_index(STATE["lines"])
    if url.startswith(pe.MANIFEST_BASE):
        line = url[len(pe.MANIFEST_BASE):]
        return json.dumps(STATE["manifests"][line]).encode("utf-8")
    raise AssertionError(f"unexpected url {url}")


print("index parse + DE-LZMA round-trip")
check("parse splits stem/line",
      pe._parse_index("ExportWarframes_en.json!00_X\n")[0],
      {"stem": "ExportWarframes", "line": "ExportWarframes_en.json!00_X"})
check("decompress round-trips",
      pe._decompress_index(lzma_index(["a!00_1", "b!00_2"])).splitlines(),
      ["a!00_1", "b!00_2"])

with tempfile.TemporaryDirectory() as d:
    store.WF_DATA_DIR = Path(d)
    pe.invalidate_name_index()

    print("\nrefresh_index")
    entries = pe.refresh_index(_get_bytes=fake_get_bytes)
    check("two entries", len(entries), 2)
    check("stored index readable", len(pe.index()), 2)

    print("\nsync fetches all, then skips unchanged")
    r1 = pe.sync(_get_bytes=fake_get_bytes)
    check("index refreshed", r1["index"], True)
    check("both fetched", sorted(r1["fetched"]),
          ["ExportUpgrades", "ExportWarframes"])
    check("none failed", r1["failed"], [])

    check("category entries", pe.category("ExportWarframes")[0]["name"], "Ember")
    check("resolve_name /Lotus path",
          pe.resolve_name("/Lotus/Powersuits/Ember/Ember"), "Ember")
    check("resolve upgrade",
          pe.resolve_name("/Lotus/Upgrades/Mods/Vitality"), "Vitality")
    check("resolve unknown -> None", pe.resolve_name("/Lotus/Nope"), None)

    r2 = pe.sync(_get_bytes=fake_get_bytes)
    check("second sync skips both", sorted(r2["skipped"]),
          ["ExportUpgrades", "ExportWarframes"])
    check("second sync fetches none", r2["fetched"], [])

    print("\ngame update: one manifest's hash changes -> only it refetches")
    new_up = "ExportUpgrades_en.json!00_HASHUP2"
    STATE["lines"] = [WF_LINE, new_up]
    STATE["manifests"][new_up] = {"ExportUpgrades": [
        {"uniqueName": "/Lotus/Upgrades/Mods/Vitality", "name": "Vitality Prime"}]}
    r3 = pe.sync(_get_bytes=fake_get_bytes)
    check("only changed one fetched", r3["fetched"], ["ExportUpgrades"])
    check("unchanged one skipped", r3["skipped"], ["ExportWarframes"])
    check("resolve reflects update",
          pe.resolve_name("/Lotus/Upgrades/Mods/Vitality"), "Vitality Prime")

if fails:
    print("\n" + "\n".join(fails))
    raise SystemExit(1)
print("\nall public_export checks passed")
