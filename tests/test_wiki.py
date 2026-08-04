import sys
# These tests print the glyphs the UI actually uses. A Windows console
# defaults to cp1252, which cannot encode them, so a PASSING test could
# still die in its own print statement.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
from core import wiki

CASES = [
    # (market/arcane name, expected wiki title)
    ("Rhino Prime Set",            "Rhino Prime"),
    ("Rhino Prime Blueprint",      "Rhino Prime"),
    ("Rhino Prime Neuroptics",     "Rhino Prime"),
    ("Rhino Prime Chassis Blueprint", "Rhino Prime"),
    ("Braton Prime Barrel",        "Braton Prime"),
    ("Dual Kamas Prime Blade",     "Dual Kamas Prime"),
    ("Forma Blueprint",            "Forma"),
    ("Orokin Reactor Blueprint",   "Orokin Reactor"),
    ("Arcane Energize",            "Arcane Energize"),
    ("Magus Elevate",              "Magus Elevate"),
    ("Primed Continuity",          "Primed Continuity"),
    ("Vitality",                   "Vitality"),
    # base items whose last word is ALSO a component name must survive
    ("Broken War",                 "Broken War"),
    ("Heat Sword",                 "Heat Sword"),
    ("Ceramic Dagger",             "Ceramic Dagger"),
    # non-Prime components strip too - their part pages never existed
    ("Braton Vandal Barrel",       "Braton Vandal"),
    ("Agkuza Guard",               "Agkuza"),
    ("Wolf Sledge Head",           "Wolf Sledge"),
    ("Mystery Blade",              "Mystery"),
    # mods and skins that merely END in a component word are articles and
    # must survive (the _KEEP list, generated from catalogue tags)
    ("Rolling Guard",              "Rolling Guard"),
    ("Ammo Chain",                 "Ammo Chain"),
    ("Neutron Star",               "Neutron Star"),
    ("Tempered Blade",             "Tempered Blade"),
    ("Ayatan Amber Star",          "Ayatan Amber Star"),
    # arcane helmets are their own articles - Helmet is not a component
    ("Arcane Aura Helmet",         "Arcane Aura Helmet"),
    # companion imprints document the breed, not the imprint listing
    ("Chesa Kubrow Imprint",       "Chesa Kubrow"),
    ("Smeeta Kavat Imprint",       "Smeeta Kavat"),
    ("Panzer Vulpaphyla Imprint",  "Panzer Vulpaphyla"),
    # rivens describe a mechanic, not an item
    ("Boltor Riven Mod",           "Riven Mods"),
    # whitespace hygiene
    ("  Rhino   Prime  Set ",      "Rhino Prime"),
    # degenerate input must not crash or produce a bare BASE
    ("",                           ""),
    ("Set",                        "Set"),
    ("Blueprint",                  "Blueprint"),
]

URLS = [
    ("Rhino Prime Set",  "https://wiki.warframe.com/w/Rhino_Prime"),
    ("Arcane Energize",  "https://wiki.warframe.com/w/Arcane_Energize"),
    ("Dark Split-Sword", "https://wiki.warframe.com/w/Dark_Split-Sword"),
    ("",                 ""),
]

fails = 0
for name, want in CASES:
    got = wiki.normalize(name)
    ok = got == want
    fails += not ok
    print(f"{'ok  ' if ok else 'FAIL'} normalize({name!r}) -> {got!r}"
          + ("" if ok else f"   expected {want!r}"))

for name, want in URLS:
    got = wiki.url_for(name)
    ok = got == want
    fails += not ok
    print(f"{'ok  ' if ok else 'FAIL'} url_for({name!r}) -> {got!r}"
          + ("" if ok else f"   expected {want!r}"))

print()
print("ALL PASS" if not fails else f"{fails} FAILURE(S)")
sys.exit(1 if fails else 0)
