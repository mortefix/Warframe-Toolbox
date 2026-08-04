"""The "Orokin Treasury" design system, as data - no toolkit imports.

Every colour, spacing step and font role the app draws with lives here and
ONLY here. The Tk front end re-exports these names so its 638 per-widget
`bg=`/`fg=` kwargs keep working unchanged; the PySide6 front end generates a
QSS sheet from the same constants. One source of truth, two renderers.

Nothing in this module may import tkinter, PySide6, or anything else that
knows how a pixel gets drawn. Fonts are declared as (family-preference,
size) pairs and resolved against the running toolkit's font database by the
front end, because "is Bahnschrift installed" is a toolkit question.

---- STYLE GUIDE ------------------------------------------------------------
Reference this whenever a design element is added or changed.

The app is a Tenno's treasury ledger: a void-black lacquered cabinet whose
panels are warm near-blacks (umber, never blue), trimmed with ONE metal -
aged gold - reserved for hairlines, the active-nav finial, focus edges and
money actions. Ivory porcelain text carries the data; platinum prices get
their own cool silver (PLAT) so the metal being counted never reads as
decoration. Gold is inlay, never plating.

Controls sit LEFT of their descriptive text (checkboxes, spinboxes, etc.).
Dropdowns show a "▾" arrow; cyclic pickers wrap so
scrolling loops.

Gold discipline: filled-gold (ACCENT background) is for MONEY actions and the
account link only - Reprice, Sold, Sign in. Everything else is the secondary
button, built from one shared surface/hover/padding rule, never by hand. WARN
is pushed to orange so it can never be mistaken for the gold accent.
Sanctioned exception: the Vosfor collection progress bar fills with gold
("the treasury fills"), turning jade when a collection is complete.

Glyphs: nav/status marks use Segoe Fluent Icons (the "icon" role). Button
labels carry a leading monochrome dingbat by convention, and the two refresh
arrows are deliberately different: ⟳ marks a MONEY action (Reprice),
↻ marks a plain data refresh. Never a colour emoji.

Hierarchy example (the Settings tree): "SETTINGS" = small caps muted title,
"Display"/"Data" = h2 headings, "Warframe"/"Market"/... = body leaf items.
"""

from __future__ import annotations

from typing import NamedTuple

# ---- spacing scale (golden-ratio rhythm) - use these, never ad-hoc numbers --
SP_SCREEN = 24  # left/right gutter of a screen's content (the widest step)
SP_XL = 16      # between major blocks
SP_LG = 10      # section padding / heading -> content
SP_MD = 6       # between related rows
SP_SM = 4       # control -> its label / adjacent buttons

# ---- palette (all contrast ratios verified >= 4.5:1 for text on its bg) ----
BG = "#1b1915"             # content background - warm void-black lacquer
TAB_BG = "#141210"         # dimmed well inside tabbed containers
ICON_BG = "#0c0b08"        # item-image backdrop, deepest black in the app
ROW_ALT = "#211d16"        # zebra stripe - a whisper lighter and warmer
FIELD_BG_IN = "#262117"    # input fields inside dark tab containers
FIELD_BG_OUT = "#1f1b14"   # input fields elsewhere (panels, dialogs)
FIELD_EDGE = "#55482c"     # 1px dim-gold inlay border on every input
PANEL = "#26221a"          # raised panel surface
PANEL_HI = "#322c20"       # highlighted panel / secondary button / hover
TITLEBAR_BG = "#0f0e0b"    # cabinet lid - darkest chrome
TITLEBAR_HOVER = "#2a251b"
TITLEBAR_CLOSE = "#8c3125"  # deep lacquered red (also the danger-button bg)
HEADER_BG = "#201c16"
SIDEBAR_BG = "#141210"
# The nav highlight is kept LOW-CONTRAST on purpose - just a step above
# SIDEBAR_BG, so the gold finial does the marking and the fill only supports it.
SIDEBAR_ACTIVE = "#231e15"  # active nav bg (paired with the gold finial)
TEXT = "#e9e3d3"           # ivory porcelain
MUTED = "#a89f8c"          # aged bone - secondary text and CAPS labels
ACCENT = "#c9a860"         # aged gold - money buttons, focus, active marks
CONSOLE_BG = "#121008"     # black-lacquer glass
CONSOLE_FG = "#d8d0b8"     # parchment
OK = "#7cc98c"             # jade
WARN = "#e5943d"           # orange-amber (never reads as the gold ACCENT)
ERR = "#e2695c"            # warm coral

# ---- gold inlay + platinum (Orokin Treasury additions) ---------------------
GOLD_HI = "#e4c882"        # bright gold: finial tip, primary-btn hover, caret
GOLD_DIM = "#7a693e"       # filigree hairlines / inlay strokes - NEVER text
GOLD_FAINT = "#2a2413"     # faint gold wash: selection bg on black surfaces
PLAT = "#cdd5da"           # platinum numerals - cool silver, matches the gem
HAIRLINE = "#2e2818"       # 1px neutral separators between shell regions
SCRIM = "rgba(0, 0, 0, 110)"   # dimming behind a slide-over drawer
INK = "#191512"            # dark text ON gold/teal filled buttons

# ---- warframe.market-inspired palette (My Listings cards) ------------------
# Deepened ~8% onto the lacquer, semantics preserved; the site pink stays
# EXACT so cards echo the embedded warframe.market web view.
WFM_CARD = "#16140f"
WFM_EDGE = "#37301f"       # 1px gold-tinted card border
WFM_TEAL = "#63c7c9"       # void-energy teal - bridge to the site palette
WFM_TEAL_DIM = "#2e5150"
WFM_PINK = "#dd58a5"       # site-exact pink (5.6:1 on WFM_CARD)
WFM_MUTED = "#a39a88"
WFM_BADGE_BG = "#43293a"   # wts tag (plum, like the site)
WFM_BADGE_FG = "#d9a3c5"
WFM_BUY_BG = "#22404e"     # wtb tag (blue)
WFM_BUY_FG = "#8ac6dc"
WFM_RED = "#cf5f4f"
WFM_RED_DIM = "#55302a"

# ---- named accents (were bare hex literals) --------------------------------
RARITY_BRONZE = "#b08a63"  # Common arcanes; also the Vosfor app's card accent
RARITY_SILVER = "#9fb8c4"  # Uncommon arcanes
WEB_ACCENT = "#8f9aa6"     # embedded web apps - slate, deliberately NOT PLAT
                           # (PLAT is reserved for platinum numerals) and not
                           # gold (they are not money actions)

# ---- reputation ------------------------------------------------------------
# Deliberately desaturated versions of OK and ERR. A trader's reputation is
# context, not a verdict - it should be readable at a glance and then recede,
# so it must never compete with the jade/coral used for actual outcomes.
REP_UP = "#6b9c74"         # muted jade - positive standing
REP_DOWN = "#a2685f"       # muted coral - negative standing

# ---- rarity ----------------------------------------------------------------
# Rarity reads as a metal ladder: bronze -> silver -> gold -> platinum. Rare
# uses ACCENT (the palette's gold) rather than GOLD_HI, which is scoped to
# finial tips, hover and the caret.
RARITY_COLOR = {"Common": RARITY_BRONZE, "Uncommon": RARITY_SILVER,
                "Rare": ACCENT, "Legendary": PLAT}

# ---- disclosure arrows -----------------------------------------------------
# Sized to the TITLE they belong to (the h2 role), not to body text - the same
# pairing the Settings tree uses.
ARROW_OPEN = "▾"       # down
ARROW_CLOSED = "▸"     # right

# ---- icons -----------------------------------------------------------------
# Every mark in the app, named by what it MEANS rather than by a codepoint.
#
# The app ships Material Symbols (Apache 2.0, see assets/licenses/) instead of
# leaning on Segoe Fluent Icons, and that is a licensing and portability fix as
# much as a visual one: the Segoe fonts are Windows-only and cannot be
# redistributed, so the previous set could not have survived the move to Linux
# that [[linux-portability-goal]] anticipates. It also ends a whole class of
# bug this codebase kept hitting - a Private Use Area codepoint is a number
# nobody can read, and picking the wrong one is invisible until it renders. Two
# separate icons shipped broken that way: U+E82D fell through to a CJK glyph in
# the Wiki button, and Segoe has no ribbon bookmark at all.
#
# Material Symbols is addressed by LIGATURE: the text "storefront" renders the
# shop icon. A typo therefore renders as the word "storefornt" rather than as
# a blank box, which is a louder failure and a much easier fix.
#
# Both codes live in one row so the two front ends cannot drift while the Tk
# app is still shipping. Qt reads `.material`; Tk reads `.fluent` and keeps the
# Windows glyphs it can actually render.


class Icon(NamedTuple):
    material: str      # Material Symbols ligature name - the Qt front end
    fluent: str        # Segoe Fluent Icons codepoint - the Tk front end


ICONS: dict[str, Icon] = {
    "home":      Icon("home", "\uE80F"),
    "listings":  Icon("sell", "\uE8EC"),
    "market":    Icon("storefront", "\uE7BF"),
    "vosfor":    Icon("calculate", "\uE8EF"),
    "settings":  Icon("settings", "\uE713"),
    "live":      Icon("live_tv", "\uE787"),
    "wiki":      Icon("menu_book", "\uE82D"),
    "builds":    Icon("construction", "\uE90F"),
    "mail":      Icon("mail", "\uE715"),
    "delete":    Icon("delete", "\uE74D"),
    "bookmarks": Icon("list", "\uE8A4"),
    # the ribbon. Material draws it with a FILL axis, so saved and unsaved are
    # one glyph at two axis values and cannot drift apart
    "bookmark":  Icon("bookmark", "\uE7C1"),
    "tool":      Icon("extension", "\uEA86"),
    "network":   Icon("cell_tower", "\uEC05"),
    "refresh":   Icon("refresh", "\uE72C"),
    # web-tab chrome
    "back":      Icon("arrow_back", "\uE72B"),
    "forward":   Icon("arrow_forward", "\uE72A"),
    "home_page": Icon("home", "\uE80F"),
    "close":     Icon("close", "\uE711"),
    # Vosfor arcane status. The Tk marks are plain dingbats rather than Segoe
    # codepoints - they render in any font, which is why they were chosen -
    # so this column is not all Private Use Area.
    "maxed":     Icon("check_circle", "\u2714"),
    "owned":     Icon("contrast", "\u25D0"),
    "missing":   Icon("radio_button_unchecked", "\u2717"),
    "complete":  Icon("task_alt", "\u2714"),
    # disclosure triangles on the collection cards
    "expand":    Icon("expand_more", "\u25BE"),
    "collapse":  Icon("chevron_right", "\u25B8"),
    # listing card actions
    "sold":      Icon("check", "\u2714"),
    "edit":      Icon("edit", "\u270E"),
    "add_one":   Icon("add", "+"),
    "less_one":  Icon("remove", "\u2212"),
    "visible":   Icon("visibility", "\u25C9"),
    "hidden":    Icon("visibility_off", "\u25CC"),
    "reprice":   Icon("sync", "\u27F3"),
    # the watchlist star: one glyph, filled when watched
    "watch":     Icon("star", "\u2606"),
    # Dev data-explorer apps + their group
    "world":     Icon("public", "\ue774"),
    "profile":   Icon("person", "\ue77b"),
    "log":       Icon("description", "\ue7c3"),
    "dev":       Icon("code", "\ue943"),
    "inventory": Icon("inventory_2", "\ue7b8"),
}


def glyph(key: str, fluent: bool = False) -> str:
    """The mark for `key`, in the form the calling front end can render.

    Unknown keys come back as the key itself, which renders as a readable
    word rather than as an exception or a blank - a missing icon should never
    be the thing that takes a screen down.
    """
    icon = ICONS.get(key)
    if icon is None:
        return key
    return icon.fluent if fluent else icon.material


HOME_ICON = "home"
LISTINGS_ICON = "listings"
WIKI_ICON = "wiki"          # deliberately the SAME key the Wiki tab carries in
                            # WEB_APPS, so a wiki link anywhere in the app
                            # names the tab it opens

# ---- typography ------------------------------------------------------------
# (preferred families in order, point size). The front end probes the font
# database and takes the first family present, so a machine without
# Bahnschrift degrades to a Segoe weight rather than to Tk's default.
FONTS: dict[str, tuple[tuple[str, ...], int]] = {
    # page titles - one per screen
    "h1":    (("Bahnschrift SemiBold", "Bahnschrift", "Segoe UI Semibold"), 18),
    # headings: sections, tabs, tree categories
    "h2":    (("Bahnschrift SemiBold", "Bahnschrift", "Segoe UI Semibold"), 13),
    # THE standard text: rows, values, search fields, dropdown items
    "body":  (("Segoe UI",), 11),
    # captions, hints, TITLES-IN-CAPS labels
    "small": (("Segoe UI",), 10),
    # the WTS/WTB side badge on a listing card - bold + a touch bigger than
    # small so it reads as a label, sized to match the +/-1 buttons beside it
    "badge": (("Segoe UI",), 12),
    # plat/ducat/Vosfor numerals - DIN tabular digits keep money columns
    # aligned; platinum is coloured PLAT, ducats ACCENT
    "price": (("Bahnschrift SemiBold", "Bahnschrift", "Segoe UI Semibold"), 11),
    # console output + fixed-width data columns (e.g. Vosfor's 05/21 counter)
    "mono":  (("Cascadia Mono", "Consolas"), 10),
    # nav/action glyphs (NEVER colour emoji). Material Symbols ships WITH the
    # app, so unlike every other role this one does not degrade - the Segoe
    # fallbacks are there only for the Tk front end, which cannot load a font
    # from a file without a Windows-only API call.
    "icon":   (("Material Symbols Sharp", "Segoe Fluent Icons",
                "Segoe MDL2 Assets"), 12),
    # the mail-copy button in the Market order book - the one place a glyph is
    # a click target rather than a label, so it gets its own larger size
    "msgbtn": (("Material Symbols Sharp", "Segoe Fluent Icons",
                "Segoe MDL2 Assets"), 15),
}


def resolve_family(role: str, available: set[str] | frozenset[str]) -> str:
    """First preferred family for `role` that `available` contains, else the
    last preference as a final fallback. `available` is whatever the toolkit
    reports - tkinter.font.families() or QFontDatabase.families()."""
    prefs, _size = FONTS[role]
    return next((f for f in prefs if f in available), prefs[-1])


def size_of(role: str) -> int:
    return FONTS[role][1]
