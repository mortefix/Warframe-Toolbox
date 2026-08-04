"""core.worldstate - the worldState.php adapter. No network: fetches are
injected and the store is redirected to a temp dir."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "data"))
from core import store, wf_http, worldstate

fails = []


def check(name, got, want):
    ok = got == want
    if not ok:
        fails.append(f"{name}: got {got!r}, want {want!r}")
    print(f"  {'ok  ' if ok else 'FAIL'} {name}")


# A trimmed but shape-accurate worldState document.
SAMPLE = {
    "Time": 1785693256,
    "WorldSeed": "abc",
    "ActiveMissions": [{"Node": "SolNode1"}, {"Node": "SolNode2"}],
    "VoidStorms": [{"Node": "VeilNode"}],
    "Sorties": [{"Boss": "SORTIE_BOSS_HEK"}],
    "LiteSorties": [{"Boss": "ARCHON"}],
    "SeasonInfo": {"Season": 15, "Phase": 0},
    "VoidTraders": [{"Character": "Baro"}],
    "Invasions": [{"Node": "N"}],
    "Events": [{"Msg": "x"}],
    "Alerts": [],
    "DailyDeals": [{"StoreItem": "d"}],
    "SyndicateMissions": [{"Tag": "SteelMeridian"}],
}

print("url + structural validation")
check("pc url", worldstate.worldstate_url(),
      "https://api.warframe.com/cdn/worldState.php")
check("valid doc accepted",
      worldstate.fetch(_get=lambda url: SAMPLE)["WorldSeed"], "abc")
check("garbage (no Time/WorldSeed) -> None",
      worldstate.fetch(_get=lambda url: {"nope": 1}), None)
check("non-dict -> None", worldstate.fetch(_get=lambda url: "x"), None)

with tempfile.TemporaryDirectory() as d:
    store.WF_DATA_DIR = Path(d)

    print("\nrefresh stores raw + accessors read back")
    check("refresh returns doc", worldstate.refresh(_get=lambda url: SAMPLE) is not None, True)
    check("stored raw", store.read("worldstate")["WorldSeed"], "abc")
    check("source_mtime = Time", store.source_mtime("worldstate"), 1785693256)
    check("server_time", worldstate.server_time(), 1785693256)
    check("fissures (ActiveMissions)", len(worldstate.fissures()), 2)
    check("void_storms", len(worldstate.void_storms()), 1)
    check("sorties", worldstate.sorties()[0]["Boss"], "SORTIE_BOSS_HEK")
    check("archon_hunt (LiteSorties)", worldstate.archon_hunt()[0]["Boss"], "ARCHON")
    check("nightwave (SeasonInfo)", worldstate.nightwave()["Season"], 15)
    check("baro (VoidTraders)", worldstate.baro()[0]["Character"], "Baro")
    check("invasions", len(worldstate.invasions()), 1)
    check("daily_deals", len(worldstate.daily_deals()), 1)
    check("syndicate_missions", worldstate.syndicate_missions()[0]["Tag"], "SteelMeridian")
    check("generic section()", worldstate.section("Sorties")[0]["Boss"], "SORTIE_BOSS_HEK")
    check("missing section -> default", worldstate.section("Nope", "x"), "x")

    print("\nrefresh window + error handling")
    def explode(url):
        raise AssertionError("must not fetch while fresh")
    check("fresh -> no fetch",
          worldstate.refresh_if_stale(_get=explode) is not None, True)
    saved = worldstate.STALE_AFTER
    worldstate.STALE_AFTER = 0
    check("stale -> fetches",
          worldstate.refresh_if_stale(_get=lambda url: SAMPLE) is not None, True)
    worldstate.STALE_AFTER = saved

    def boom(url):
        raise wf_http.WFHttpError("down", status=503)
    check("network error keeps cache", worldstate.refresh(_get=boom), None)
    check("cache still present", worldstate.server_time(), 1785693256)

if fails:
    print("\n" + "\n".join(fails))
    raise SystemExit(1)
print("\nall worldstate checks passed")
