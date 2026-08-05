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

UI = Path(__file__).resolve().parent.parent / "app" / "ui"
fails = []


def check(name, got, want=True):
    ok = got == want
    if not ok:
        fails.append(f"{name}: got {got!r}, want {want!r}")
    print(f"  {'ok  ' if ok else 'FAIL'} {name}")


py = sorted(UI.glob("*.py"))
text = {f.name: f.read_text(encoding="utf-8") for f in py}

print("colour discipline")
# EVERY colour is addressable in the stylesheet: no literal colour form may
# appear in any source file EXCEPT core/theme.py (the palette itself). This is
# what makes theming possible - a colour hardcoded anywhere would not switch
# with the theme. Covers hex (#rgb and #rrggbb), rgb()/rgba(), and CSS colour
# NAMES used as a style value. Scans app/ui/ AND app/core/ (minus theme.py).
CORE = Path(__file__).resolve().parent.parent / "app" / "core"
colour_src = dict(text)                       # the ui/*.py already loaded
for f in sorted(CORE.glob("*.py")):
    if f.name != "theme.py":
        colour_src[f"core/{f.name}"] = f.read_text(encoding="utf-8")
# A CSS colour NAME only counts as an offender when it is a style VALUE - i.e.
# followed by ; or a closing quote - so prose like "# a money action: gold" in a
# comment does not trip it, but a literal `color: gold;` would.
colour_re = re.compile(
    r"#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b|\brgba?\("
    r"|:\s*(?:white|black|red|green|blue|gray|grey|yellow|orange|silver|gold)"
    r"\s*[;\"']")
# Scan LINE by line (not the whole file): the value-delimiter `\s*[;"']` must not
# be allowed to span a newline into the next line's quote.
colour_offenders = {}
for name, src in colour_src.items():
    hits = [i for i, ln in enumerate(src.splitlines(), 1) if colour_re.search(ln)]
    if hits:
        colour_offenders[name] = hits
check("every colour is a theme token (no literal colour outside theme.py)",
      colour_offenders, {})

print("\ncorners")
# 0 radius everywhere except the sanctioned 3px scrollbar handles in qss.py.
br_files = {name for name, src in text.items() if "border-radius" in src}
check("border-radius appears only in qss.py", br_files <= {"qss.py"})
if "qss.py" in text:
    radii = set(re.findall(r"border-radius:\s*(\d+)px", text["qss.py"]))
    # The one radius (scrollbar handle) now comes from t.RADIUS_HANDLE, so no
    # raw radius literal should remain in qss.py.
    check("no raw corner-radius px literal (use t.RADIUS_HANDLE)", radii, set())

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

print("\ndimension discipline (metrics tokens)")
qss = text.get("qss.py", "")
# Border WIDTHS are UNIVERSAL tokens - BORDER_W (bodies/frames) and CTRL_BORDER_W
# (controls/inputs). No literal "border: Npx" may appear ANYWHERE in ui: the app
# hardcodes which ROLE each widget is, and the pixel value lives only in
# core.theme, so it applies identically to every theme (Orokin Dark / Light).
bw_re = re.compile(r"border(?:-\w+)?:\s*\d+px")
raw_bw = {name: [i for i, ln in enumerate(src.splitlines(), 1) if bw_re.search(ln)]
          for name, src in text.items() if bw_re.search(src)}
check("no literal border-width px in ui (use BORDER_W / CTRL_BORDER_W)", raw_bw, {})
# Scrollbar metrics + handle radius + weights come from tokens. POSITIVE checks
# (the token is referenced) are used because a bare "12px" also legitimately
# appears in the one-off checkbox-indicator size, so absence-of-"12px" would be a
# false trip. The handle-min (30) and radius are scrollbar-only, so absence of
# the raw literal there is a safe extra guard.
for tok in ("t.BORDER_W", "t.SCROLLBAR_THICK", "t.SCROLLBAR_HANDLE_MIN",
            "t.RADIUS_HANDLE", "t.WEIGHT_BOLD", "t.WEIGHT_SEMI"):
    check(f"qss references {tok}", tok in qss)
check("qss scrollbar handle-min is a token",
      "min-height: 30px" not in qss and "min-width: 30px" not in qss)
check("qss handle radius is a token", "border-radius: 3px" not in qss)
check("qss font-weight uses tokens",
      "font-weight: bold" not in qss and "font-weight: 600" not in qss)

print("\ncross-file duplicates are tokenized")
# The values that used to be defined independently in multiple ui files now
# reference one token. Assert the raw forms are gone.
ui_no_qss = {n: s for n, s in text.items() if n != "qss.py"}


def none_contain(substr):
    return {n for n, s in ui_no_qss.items() if substr in s}


check("no raw setFixedSize(24, 22) (use t.REMOVE_BTN)",
      none_contain("setFixedSize(24, 22)"), set())
check("no raw setMinimumWidth(430) (use t.DIALOG_MIN_W)",
      none_contain("setMinimumWidth(430)"), set())
check("no raw disclosure setFixedWidth(20) (use t.DISCLOSURE_W)",
      none_contain("setFixedWidth(20)"), set())
check("no raw icon-button setFixedWidth(28) (use t.ICON_BTN)",
      none_contain("setFixedWidth(28)"), set())
check("SCROLLBAR_H references the token",
      any("SCROLLBAR_H = t.SCROLLBAR_THICK" in s for s in ui_no_qss.values()))

print()
if fails:
    print(f"{len(fails)} STYLE-GUIDE VIOLATIONS:")
    for f in fails:
        print("   ", f)
    sys.exit(1)
print("ALL STYLE-GUIDE INVARIANTS HOLD")
