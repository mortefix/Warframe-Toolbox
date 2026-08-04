"""The metrics token section: every reused dimension has one definition."""
import sys
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
from core import theme as t

fails = []
def check(name, got, want=True):
    ok = got == want
    if not ok:
        fails.append(f"{name}: got {got!r}, want {want!r}")
    print(f"  {'ok  ' if ok else 'FAIL'} {name}")

print("metrics tokens exist with expected types/values")
check("BORDER_W", t.BORDER_W, 2)
check("CTRL_BORDER_W", t.CTRL_BORDER_W, 1)
check("SP_XXS", t.SP_XXS, 2)
check("SCROLLBAR_THICK", t.SCROLLBAR_THICK, 12)
check("SCROLLBAR_HANDLE_MIN", t.SCROLLBAR_HANDLE_MIN, 30)
check("RADIUS_HANDLE", t.RADIUS_HANDLE, 3)
check("ICON_BTN", t.ICON_BTN, 28)
check("REMOVE_BTN", t.REMOVE_BTN, (24, 22))
check("DISCLOSURE_W", t.DISCLOSURE_W, 20)
check("TABLE_ROW_H", t.TABLE_ROW_H, 26)
check("DIALOG_MIN_W", t.DIALOG_MIN_W, 460)
check("WEIGHT_BOLD", t.WEIGHT_BOLD, "bold")
check("WEIGHT_SEMI", t.WEIGHT_SEMI, 600)
check("CONTROL_H", t.CONTROL_H, 26)

print("\nlive theme switching (set_theme) applies and RESETS cleanly")
_orig = t.active_theme()
t.set_theme("Orokin Light")
check("Light overlay applies its palette", t.BG, "#d7c9a8")
check("Light keeps the Marcellus title face", t.FONT_FACE["app_title"],
      "Marcellus")
t.set_theme("Dev-Fonts")
check("Dev-Fonts overlay applies", t.BG, "#d0d0d0")
check("Dev-Fonts re-faces the title", t.FONT_FACE["app_title"],
      "Mountains of Christmas")
t.set_theme("Orokin Dark")
check("switching back RESETS to the dark default (not left on Dev-Fonts)",
      t.BG, "#1b1915")
check("and restores the base font faces", t.FONT_FACE["app_title"], "Marcellus")
t.set_theme("Nope, not a theme")
check("an unknown name falls back to Orokin Dark", t.BG, "#1b1915")
check("always-offered themes: Orokin + Christmas Dark/Light",
      list(t.BASE_THEME_NAMES),
      ["Orokin Dark", "Orokin Light", "Christmas Dark", "Christmas Light"])
t.set_theme("Christmas Dark")
check("Christmas Dark applies its evergreen ground", t.BG, "#0f2417")
check("Christmas Dark faces the title in Mountains of Christmas",
      t.FONT_FACE["app_title"], "Mountains of Christmas")
check("Christmas keeps readable Spectral item names (from _OROKIN_FACES)",
      t.FONT_FACE["card_title"], "Spectral")
t.set_theme("Christmas Light")
check("Christmas Light applies its holly-mint ground", t.BG, "#dcecd8")
check("Christmas Light also faces titles in Mountains of Christmas",
      t.FONT_FACE["app_title"], "Mountains of Christmas")
check("dev themes are the three diagnostics", list(t.DEV_THEME_NAMES),
      ["Dev-Boxes", "Dev-Boundaries", "Dev-Fonts"])
t.set_theme(_orig)                      # leave the module as we found it

if fails:
    print("\n" + "\n".join(fails)); raise SystemExit(1)
print("\nall metrics checks passed")
