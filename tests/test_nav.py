"""core.nav - the sidebar model: Home pinned top, Settings pinned bottom, and
the apps between them grouped into three ordered containers (trading / tools /
web) the shell draws as gold-bordered boxes."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
from core import nav
from registry import TOOLS

fails = []


def check(name, got, want):
    ok = got == want
    if not ok:
        fails.append(f"{name}: got {got!r}, want {want!r}")
    print(f"  {'ok  ' if ok else 'FAIL'} {name}")


print("pinned head/tail")
items = nav.nav_items(TOOLS)
check("home pinned at top", items[0].key, "home")
check("settings pinned at bottom", items[-1].key, "settings")

print("\nthree containers, in functional order")
sections = nav.sidebar_sections(TOOLS)
check("exactly three containers", len(sections), 3)
check("container titles", [s.title for s in sections],
      ["Market", "Toolbox", "Web Apps"])
check("container membership + order",
      [[i.label for i in s.items] for s in sections],
      [["Market", "My Listings"], ["Vosfor"], ["Wiki", "Overframe"]])

print("\nmiddle_items flattens the containers in display order")
check("flattened order", [i.label for i in nav.middle_items(TOOLS)],
      ["Market", "My Listings", "Vosfor", "Wiki", "Overframe"])

print("\nno collapsible-folder model (that was reverted)")
check("no NavGroup type", hasattr(nav, "NavGroup"), False)
check("no nav_groups()", hasattr(nav, "nav_groups"), False)

print("\nnav_items in display order, ending at Settings")
keys = [i.key for i in items]
check("home first", keys[0], "home")
check("settings last", keys[-1], "settings")
check("every key unique", len(keys), len(set(keys)))
check("dev apps are NOT sidebar nav items",
      any(k.startswith("dev_") for k in keys), False)
check("api_check hidden from sidebar", "api_check" in keys, False)

print("\nlabels + session gating still work")
check("label lookup", nav.labels(TOOLS)["market"], "Market")
check("My Listings needs a session",
      nav.requires_session("listings", TOOLS), True)
check("Vosfor does not", nav.requires_session("vosfor", TOOLS), False)

if fails:
    print("\n" + "\n".join(fails))
    raise SystemExit(1)
print("\nall nav checks passed")
