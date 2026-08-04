"""core.home.player_status - the Home status-panel lights, including the new
Warframe.com Profile light. Settings path is redirected to a temp file so the
real .wfm_settings.json is never touched."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "data"))
from core import config, home as core_home, wf_profile

fails = []


def check(name, got, want):
    ok = got == want
    if not ok:
        fails.append(f"{name}: got {got!r}, want {want!r}")
    print(f"  {'ok  ' if ok else 'FAIL'} {name}")


with tempfile.TemporaryDirectory() as d:
    config.SETTINGS_PATH = Path(d) / ".wfm_settings.json"

    print("profile light tracks account configuration")
    st = core_home.player_status("Me", True)
    check("has profile field", hasattr(st, "profile"), True)
    check("unconfigured -> off", st.profile, False)
    check("name passthrough", st.name, "Me")
    check("market passthrough", st.market, True)

    wf_profile.set_account_id("5420be04384632143a707618", "pc")
    st2 = core_home.player_status("Me", True)
    check("configured -> on", st2.profile, True)

if fails:
    print("\n" + "\n".join(fails))
    raise SystemExit(1)
print("\nall home-status checks passed")
