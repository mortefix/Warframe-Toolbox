"""Enforce the MECHANICAL invariants of docs/STYLE_GUIDE.md.

The style guide is a guardrail, not a suggestion. Prose rules (proportion,
whitespace balance) are audited by eye; the mechanical ones live here, so a
future change cannot silently regress the token/dimensional discipline that the
Tk->Qt migration established. All of these pass today - this test LOCKS that in.
"""
import re
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path

UI = Path(__file__).resolve().parent.parent / "data" / "ui"
fails = []


def check(name, got, want=True):
    ok = got == want
    if not ok:
        fails.append(f"{name}: got {got!r}, want {want!r}")
    print(f"  {'ok  ' if ok else 'FAIL'} {name}")


py = sorted(UI.glob("*.py"))
text = {f.name: f.read_text(encoding="utf-8") for f in py}

print("colour discipline")
# Every colour is a theme token; qss.py builds the sheet from t.* and nothing in
# ui/ writes a raw #rrggbb. (A colour that must vary belongs in core/theme.py.)
hex_re = re.compile(r"#[0-9a-fA-F]{6}\b")
hex_offenders = {name: [i for i, ln in enumerate(src.splitlines(), 1)
                        if hex_re.search(ln)]
                 for name, src in text.items() if hex_re.search(src)}
check("no raw #hex colour anywhere in data/ui/", hex_offenders, {})

print("\ncorners")
# 0 radius everywhere except the sanctioned 3px scrollbar handles in qss.py.
br_files = {name for name, src in text.items() if "border-radius" in src}
check("border-radius appears only in qss.py", br_files <= {"qss.py"})
if "qss.py" in text:
    radii = set(re.findall(r"border-radius:\s*(\d+)px", text["qss.py"]))
    check("the only corner radius is 3px (scrollbar handles)", radii, {"3"})

print("\ntypography")
# Sizes come from theme.FONTS via size_of(); qss.py emits generated
# "font-size: {n}pt" rules, which is fine. The ONLY hand-written font-size in
# ui/ is the 30pt item-icon placeholder glyph.
raw_fs = [(name, i, ln.strip())
          for name, src in text.items() if name != "qss.py"
          for i, ln in enumerate(src.splitlines(), 1) if "font-size" in ln]
check("exactly one hand-written font-size outside qss.py", len(raw_fs), 1)
check("and it is the sanctioned 30pt placeholder",
      bool(raw_fs) and "30pt" in raw_fs[0][2])

print("\nspacing scale (§4)")
# Layout margins/spacing come from the SP_* scale, not raw pixels. Raw 0-3 is
# allowed: 0 = no margin, and 1/2/3 are tight in-grid detail paddings (the
# Fibonacci detail range, §6b). Anything >= 4 is either a token value
# (4/6/10/16/24) or off-scale drift written by hand - it must be a t.SP_* token.
SPACE_CALLS = ("setContentsMargins", "setSpacing", "setHorizontalSpacing",
               "setVerticalSpacing", "addSpacing")
call_re = re.compile(r"\b(" + "|".join(SPACE_CALLS) + r")\(([^)]*)\)")
lit_re = re.compile(r"(?<![\w.])(\d+)")
space_offenders = []
for name, src in text.items():
    for i, ln in enumerate(src.splitlines(), 1):
        for m in call_re.finditer(ln):
            if any(int(n.group(1)) >= 4 for n in lit_re.finditer(m.group(2))):
                space_offenders.append(f"{name}:{i}  {m.group(0)}")
check("layout spacing uses SP_* tokens, not raw px >= 4", space_offenders, [])

print()
if fails:
    print(f"{len(fails)} STYLE-GUIDE VIOLATIONS:")
    for f in fails:
        print("   ", f)
    sys.exit(1)
print("ALL STYLE-GUIDE INVARIANTS HOLD")
