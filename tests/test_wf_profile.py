"""core.wf_profile - the getProfileViewingData adapter. No network: fetches are
injected. Settings and the store are redirected to a temp dir so the real
.wfm_settings.json and .wf_data/ are never touched."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
from core import config, store, wf_http, wf_profile

fails = []


def check(name, got, want):
    ok = got == want
    if not ok:
        fails.append(f"{name}: got {got!r}, want {want!r}")
    print(f"  {'ok  ' if ok else 'FAIL'} {name}")


# A trimmed but shape-accurate getProfileViewingData response.
SAMPLE = {"Results": [{
    "AccountId": {"$oid": "5420be04384632143a707618"},
    "DisplayName": "TestTenno",
    "PlayerLevel": 30,
    "Created": {"$date": {"$numberLong": "1411431828850"}},
    "LoadOutPreset": {"FocusSchool": "AP_ATTACK"},
    "LoadOutInventory": {"XPInfo": [{"ItemType": "/Lotus/Powersuits/Ember/Ember",
                                     "XP": 1533478}]},
    "PlayerSkills": {"LPS_GUNNERY": 10},
    "Affiliations": [{"Tag": "ArbitersSyndicate", "Standing": -71000}],
    "Missions": [{"Tag": "ClanNode12", "Completes": 6}],
}]}

AID = "5420be04384632143a707618"

print("valid_account_id")
check("accepts 24-hex", wf_profile.valid_account_id(AID), True)
check("rejects short", wf_profile.valid_account_id("abc"), False)
check("rejects uppercase", wf_profile.valid_account_id(AID.upper()), False)
check("rejects non-str", wf_profile.valid_account_id(123), False)

print("\nprofile_url")
check("pc host",
      wf_profile.profile_url(AID),
      f"https://api.warframe.com/cdn/getProfileViewingData.php?playerId={AID}")
check("swi host uses swi",
      wf_profile.profile_url(AID, "swi").startswith("https://api-swi.warframe.com"),
      True)

print("\nfetch (injected)")
check("returns Results[0]",
      wf_profile.fetch(AID, _get=lambda url: SAMPLE)["DisplayName"], "TestTenno")
check("empty Results -> None",
      wf_profile.fetch(AID, _get=lambda url: {"Results": []}), None)
check("non-dict -> None",
      wf_profile.fetch(AID, _get=lambda url: "nope"), None)

print("\nextract_account_id (auto-capture brain)")
import json as _json
check("top-level user_id",
      wf_profile.extract_account_id(_json.dumps({"user_id": AID})), AID)
check("nested under data",
      wf_profile.extract_account_id(_json.dumps({"data": {"user_id": AID}})), AID)
check("uppercase is lowered",
      wf_profile.extract_account_id(_json.dumps({"user_id": AID.upper()})), AID)
check("prefers user_id over a decoy loadout id",
      wf_profile.extract_account_id(_json.dumps(
          {"currentLoadoutId": "a" * 24, "user_id": AID})), AID)
check("loose 'id'-containing key as fallback",
      wf_profile.extract_account_id(_json.dumps({"someId": AID})), AID)
check("HTML (login page) -> None",
      wf_profile.extract_account_id("<html><body>sign in</body></html>"), None)
check("json without any id -> None",
      wf_profile.extract_account_id(_json.dumps({"name": "x", "n": 3})), None)
check("empty string -> None", wf_profile.extract_account_id(""), None)

with tempfile.TemporaryDirectory() as d:
    config.SETTINGS_PATH = Path(d) / ".wfm_settings.json"
    store.WF_DATA_DIR = Path(d) / ".wf_data"

    print("\nidentity persistence")
    check("unconfigured", wf_profile.configured(), False)
    check("account_id None when unset", wf_profile.account_id(), None)
    check("rejects bad id", wf_profile.set_account_id("bogus"), False)
    check("accepts good id", wf_profile.set_account_id(AID, "pc"), True)
    check("reads back", wf_profile.account_id(), AID)
    check("configured now", wf_profile.configured(), True)

    print("\nrefresh stores + normalizes")
    result = wf_profile.refresh(_get=lambda url: SAMPLE)
    check("refresh returned data", result is not None, True)
    check("stored in namespace", store.read("profile")["DisplayName"], "TestTenno")
    check("mastery_rank", wf_profile.mastery_rank(), 30)
    check("read_mastery_cached matches", wf_profile.read_mastery_cached(), 30)
    check("display_name", wf_profile.display_name(), "TestTenno")
    check("loadout focus", wf_profile.loadout()["FocusSchool"], "AP_ATTACK")
    check("item_xp length", len(wf_profile.item_xp()), 1)
    check("intrinsics", wf_profile.intrinsics()["LPS_GUNNERY"], 10)
    check("syndicate standing",
          wf_profile.syndicate_standings()[0]["Tag"], "ArbitersSyndicate")
    check("node completion", wf_profile.node_completion()[0]["Completes"], 6)
    check("created_at seconds", round(wf_profile.created_at()), 1411431829)

    print("\nnetwork error keeps the cached value")
    def boom(url):
        raise wf_http.WFHttpError("down", status=503)
    check("refresh swallows error", wf_profile.refresh(_get=boom), None)
    check("cache still present", wf_profile.read_mastery_cached(), 30)

    print("\nrefresh_if_stale honours the cache window")
    def explode(url):
        raise AssertionError("must not fetch while the cache is fresh")
    check("fresh cache -> no fetch",
          wf_profile.refresh_if_stale(_get=explode) is not None, True)
    saved_window = wf_profile.STALE_AFTER
    wf_profile.STALE_AFTER = 0                      # force everything stale
    check("stale cache -> fetches",
          wf_profile.refresh_if_stale(_get=lambda url: SAMPLE)["PlayerLevel"],
          30)
    wf_profile.STALE_AFTER = saved_window

    print("\nunconfigured refresh is a no-op")
    config.SETTINGS_PATH = Path(d) / ".empty_settings.json"    # fresh, no id
    check("refresh None when unconfigured",
          wf_profile.refresh(_get=lambda url: SAMPLE), None)

if fails:
    print("\n" + "\n".join(fails))
    raise SystemExit(1)
print("\nall wf_profile checks passed")
