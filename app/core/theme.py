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

Gold discipline: filled-gold (ACCENT_SURFACE background) is for MONEY actions and
the account link only - Reprice, Sign in. The same gold as INK (ACCENT) marks the
active nav, focus edges and the Sold outline - one hue, two roles, two tokens.
Everything else is the secondary button, built from one shared surface/hover/
padding rule, never by hand. WARN is pushed to orange so it can never be mistaken
for the gold accent. Sanctioned exception: the Vosfor collection progress bar
fills with gold (ACCENT_SURFACE, "the treasury fills") in its BAR_TRACK groove,
turning jade (OK_SURFACE) when a collection is complete.

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

# ---- metrics (dimensions; theme-INVARIANT - a light theme keeps these) -----
# Unlike the palette, these do not change between themes. They are the reused
# sizes the app draws with; put a dimension here the moment a second widget
# needs the same value.
BORDER_W = 2                 # universal frame border thickness
CTRL_BORDER_W = 1            # controls & inputs (buttons, text fields, dropdowns,
                             # checkboxes) - the THINNER border class. Bodies,
                             # cards and containers use the thicker BORDER_W.
SP_XXS = 2                   # micro-gap below SP_SM (extends the spacing scale)
SCROLLBAR_THICK = 12         # scrollbar track thickness (v width / h height)
SCROLLBAR_HANDLE_MIN = 30    # scrollbar handle min extent
RADIUS_HANDLE = 3            # the ONLY non-zero corner radius (scrollbar handle)
ICON_BTN = 28                # standard icon-button width: the contract-card,
                             # market-row and web-tab chrome buttons. (The My
                             # Listings item card has its OWN icon size, below.)
CONTROL_H = 26               # shared control/button HEIGHT - the base every item-
                             # card button inherits, and the reference height for
                             # buttons elsewhere. Logical px, DPI-invariant.
REMOVE_BTN = (24, 22)        # small remove/close button (w, h)
DISCLOSURE_W = 20            # disclosure-arrow column width
TABLE_ROW_H = 26             # market table row height
DIALOG_MIN_W = 460           # every dialog's minimum width
WEIGHT_BOLD = "bold"         # qss font-weight: the listing badge label
WEIGHT_SEMI = 600            # qss font-weight: the money button

# ---- layout patterns (reused margin tuples; splat into setContentsMargins) ---
# Composed of the SP_* scale; centralised so a page's rhythm has ONE definition
# rather than the same tuple retyped in every view.
PAGE_HEADER_MARGINS = (SP_SCREEN, SP_LG, SP_SCREEN, SP_LG)  # a screen's header row
PAGE_HOLDER_MARGINS = (SP_SCREEN, 0, SP_SCREEN, SP_XL)      # scroll-holder gutters
TOP_GAP_MARGINS = (0, SP_LG, 0, 0)                          # gap under a tab bar

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
# The muted colour used as a SURFACE (the offline status chip's fill), split
# out from MUTED-the-text-colour. In dark they coincide (a muted tan works as
# both faint text AND a subtle chip), which is why the overload was invisible;
# a light theme needs them apart - dark text vs a light neutral chip.
MUTED_SURFACE = "#a89f8c"  # == MUTED here so Orokin Dark is unchanged
ACCENT = "#c9a860"         # aged gold as INK - focus edge, active marks, gold text
# The accent as a SURFACE (the money-button / checkbox-tick / suggest-selection
# fill), split from ACCENT-the-ink. In Orokin they coincide (the same gold works
# as both the mark AND the filled button), which is why the overload was
# invisible; a diagnostic or future theme needs them apart - a fill colour vs a
# foreground colour. == ACCENT here so Orokin Dark is unchanged.
ACCENT_SURFACE = "#c9a860"  # == ACCENT here so Orokin Dark is unchanged
CONSOLE_BG = "#121008"     # black-lacquer glass
CONSOLE_FG = "#d8d0b8"     # parchment
OK = "#7cc98c"             # jade - status text/marks (ink)
# jade as a SURFACE: the Vosfor "collection complete" progress-bar fill, split
# from OK-the-status-ink. == OK here so Orokin Dark is unchanged.
OK_SURFACE = "#7cc98c"     # == OK here so Orokin Dark is unchanged
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
WFM_EDGE = "#37301f"       # (legacy) card border - now folded into BORDER
# ONE border colour for every frame in the app - cards, containers, inputs,
# separators. All of them reference this; changing it moves every border at once.
BORDER = "#37301f"
# The Vosfor progress-bar TRACK (the unfilled groove the gold/jade bar sits in) -
# a true SURFACE, split out of WFM_EDGE, which is a border/ink token that was
# doing fill duty here. == the old WFM_EDGE value so the bar looks unchanged.
BAR_TRACK = "#37301f"
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
    # the sidebar nav glyphs - a touch larger (~20%) than the 12pt "icon" role
    # so the rail's app icons read at a glance; still the icon FACE, never
    # re-faced by a theme (not in _FACEABLE_ROLES). Its row height is unchanged:
    # the nav button's own line box is taller than this glyph.
    "nav_icon": (("Material Symbols Sharp", "Segoe Fluent Icons",
                  "Segoe MDL2 Assets"), 15),
    # ---- the seven UI font CATEGORIES ------------------------------------
    # A theme may re-FACE each of these independently (see FONT_FACE). Three of
    # the seven already exist above: in-app titles/headers = h1 + h2, body text
    # = body + small. The five below are the categories that did not have their
    # own role yet. Each DEFAULTS to the exact face the app already drew it with,
    # so Orokin Dark/Light are unchanged; only the FAMILY is theme-overridable,
    # never the size.
    "app_title": (("Bahnschrift SemiBold", "Bahnschrift",
                   "Segoe UI Semibold"), 13),   # main title "Warframe Toolbox - X" (was h2)
    "nav_title": (("Bahnschrift SemiBold", "Bahnschrift",
                   "Segoe UI Semibold"), 13),   # sidebar app names (was h2)
    "input":    (("Segoe UI",), 11),   # text typed into fields (was body)
    "button":   (("Segoe UI",), 11),   # push-button labels (was body)
    "terminal": (("Segoe UI",), 11),   # the API-check console output (was body)
    # item-card TITLES (the item name on each My Listings / Contract / riven
    # card, and the rank/suffix/stat that share its size) - split out of h2 so a
    # card name can wear a different face from the page/section headings. Same
    # default size as h2 so the base look is unchanged until a theme re-faces it.
    "card_title": (("Bahnschrift SemiBold", "Bahnschrift",
                    "Segoe UI Semibold"), 13),
}


# ---- themeable font faces --------------------------------------------------
# FONTS above is the FALLBACK face chain per role (system Segoe/Bahnschrift/
# Cascadia). A theme selects the actual FAMILY of any role through FONT_FACE;
# the SIZE always stays with the role. This is what makes "a font per UI
# category" a theme dimension, exactly like the colours. The icon roles (icon,
# msgbtn) are deliberately NEVER overridden - they must stay on the Material
# Symbols face or their ligatures render as plain words instead of glyphs.
#
# The Orokin base themes (Dark AND Light) draw the UI in bundled COMMERCIAL
# faces, chosen for the Orokin's ancient-yet-advanced feel without drama:
#   Marcellus - an elegant, light Roman-capitals face: the ancient/ceremonial
#               "gold inscription" voice, for the app title and in-app headers.
#   Exo 2     - a restrained sci-fi sans: the "advanced" voice, for every
#               interactive and body role (nav, body, inputs, buttons, prices).
#   VT323     - the DEC-terminal pixel face, for the API console and the mono
#               counters (it IS monospaced, so columns still line up).
# One face is reused across several categories on purpose - per-category-unique
# was a DIAGNOSTIC-only exercise (Dev-Fonts). The FONTS chains stay as the
# graceful fallback if a bundled file is ever missing.
_OROKIN_FACES = {
    # titles wear Marcellus - the elegant Roman-capitals face (user's pick). It is
    # single-weight, so the qss title bold weight renders SYNTHETIC (a gentle
    # thickening, not a drawn bold).
    "app_title": "Marcellus", "h1": "Marcellus", "h2": "Marcellus",
    # item-card titles wear Spectral - a serif DRAWN for screen-text readability,
    # so item names stay legible at their small size (Cormorant's hairlines were
    # not). Still a serif "ledger entry" voice, just an easier-reading one.
    "card_title": "Spectral",
    "nav_title": "Exo 2", "body": "Exo 2", "small": "Exo 2",
    "input": "Exo 2", "button": "Exo 2", "badge": "Exo 2", "price": "Exo 2",
    "mono": "VT323", "terminal": "VT323",
}
# Orokin Dark is the module baseline (it is NOT a _PALETTES overlay), so setting
# the module-level FONT_FACE here is what puts Dark on the commercial faces;
# Orokin Light inherits it (its overlay carries no FONT_FACE, so globals().update
# leaves this in place). Each dev theme REPLACES it through its own overlay.
FONT_FACE: dict[str, str] = dict(_OROKIN_FACES)


def resolve_family(role: str, available: set[str] | frozenset[str]) -> str:
    """The family to draw `role` with. A theme's FONT_FACE override wins when
    the forced family is actually registered; otherwise the first preferred
    family in FONTS that `available` contains, else the last preference as a
    final fallback. `available` is whatever the toolkit reports -
    tkinter.font.families() or QFontDatabase.families()."""
    forced = FONT_FACE.get(role)
    if forced and forced in available:
        return forced
    prefs, _size = FONTS[role]
    return next((f for f in prefs if f in available), prefs[-1])


def size_of(role: str) -> int:
    return FONTS[role][1]


# ---- theme selection --------------------------------------------------------
# Orokin Light is a SECOND palette: the colour values below are overlaid over the
# Orokin Dark defaults defined above. Metrics, spacing, fonts and icons are
# theme-INVARIANT and are not repeated here. This is the proof that the token
# layer is a real stylesheet - a whole theme is a dict of colours and nothing
# else; no view code changes.
#
# Concept: the Orokin towers in white porcelain and gold rather than void-black
# lacquer. Warm parchment surfaces, dark umber text, a DEEPER gold (a pale gold
# vanishes on a light ground), and the warframe.market teal/pink/blue pushed
# darker so they still read on cream.
# The always-offered themes: the base Orokin pair plus the seasonal Christmas.
# The diagnostic "Dev-*" themes are a DEVELOPER FEATURE - the theme picker offers
# them only when developer features are enabled (config `dev_panels`; see
# ui/settings.py). A dev theme already saved in config still LOADS (active_theme
# validates against THEME_NAMES), so nothing breaks if one is selected; the gate
# only controls which OPTIONS show.
BASE_THEME_NAMES = ("Orokin Dark", "Orokin Light",
                    "Christmas Dark", "Christmas Light")
DEV_THEME_NAMES = ("Dev-Boxes", "Dev-Boundaries", "Dev-Fonts")
THEME_NAMES = BASE_THEME_NAMES + DEV_THEME_NAMES


def theme_choices(dev: bool) -> list[str]:
    """Theme names to OFFER in the picker: the base themes always, plus the dev
    themes only when developer features are on."""
    return list(BASE_THEME_NAMES) + (list(DEV_THEME_NAMES) if dev else [])

_LIGHT = dict(
    # Aged Orokin derelict: DEEP, shadowed background layers with a LIGHTER lit
    # cream in the foreground (cards / fields / panels) for depth, and every gold
    # border the SAME louder bronze so the frame reads as one continuous inlay.
    # -- background layers (deeper, aged, shadowed) --
    BG="#d7c9a8", TAB_BG="#cabb98", ICON_BG="#b3a57f", ROW_ALT="#d1c3a2",
    SIDEBAR_BG="#cfc09d", HEADER_BG="#cdbf9c", TITLEBAR_BG="#ccbe9a",
    TITLEBAR_HOVER="#c0b28d", TITLEBAR_CLOSE="#a63d2b", SIDEBAR_ACTIVE="#dccfad",
    CONSOLE_BG="#cdc1a1",
    # -- foreground surfaces (lighter, lit cream) --
    WFM_CARD="#e9e0c6", PANEL="#e6dcc0", PANEL_HI="#dcd1b3",
    FIELD_BG_IN="#f1e9d4", FIELD_BG_OUT="#ede4ce",
    # -- ink --
    TEXT="#2c2518", MUTED="#695e46", MUTED_SURFACE="#bdae86",
    CONSOLE_FG="#38301e", OK="#4e8a53", OK_SURFACE="#4e8a53",
    WARN="#b0701e", ERR="#b4443a",
    # -- bronze: fills/marks, and ONE louder border for every gold edge --
    ACCENT="#9a7638", ACCENT_SURFACE="#9a7638", GOLD_HI="#b08a45",
    GOLD_FAINT="#e2d3a4", INK="#231c10",
    BORDER="#9e7724", BAR_TRACK="#9e7724", GOLD_DIM="#9e7724", WFM_EDGE="#9e7724",
    FIELD_EDGE="#9e7724", HAIRLINE="#9e7724", PLAT="#4d5a61",
    # -- warframe.market accents (kept muted so they sit under the bronze) --
    WFM_TEAL="#2d8284", WFM_TEAL_DIM="#77a9a7", WFM_PINK="#b6447d",
    WFM_MUTED="#716544",
    WFM_BADGE_BG="#dabfce", WFM_BADGE_FG="#7c3a5f", WFM_BUY_BG="#c0d4da",
    WFM_BUY_FG="#2b5462", WFM_RED="#b4443a", WFM_RED_DIM="#cb9e91",
    RARITY_BRONZE="#926537", RARITY_SILVER="#697f87", WEB_ACCENT="#656f79",
    REP_UP="#59845f", REP_DOWN="#9d5a4e",
)

# Christmas Dark: the Orokin treasury dressed for the holidays. The gold-on-dark-
# lacquer system barely changes shape - the void-black surfaces become deep
# EVERGREEN, the gold inlay/borders/money-buttons stay (now reading as ornaments
# and ribbon), ivory text becomes SNOW, platinum becomes ICY silver, and
# holly-RED is the THIRD festive colour with its own job - the WTS tags (bright
# red, pairing with the green WTB tags) and the active-nav highlight (a red row
# under the gold finial, so red shows on every page via the rail), plus the
# usual danger/errors. Green = surfaces, gold = metal, red = tags + selection.
# The titles wear
# Mountains of Christmas; everything else keeps the readable Orokin faces (the
# FONT_FACE is built FROM _OROKIN_FACES so no role falls back to a system font).
_CHRISTMAS_DARK = dict(
    # -- background layers: deep evergreen lacquer, warm --
    BG="#0f2417", TAB_BG="#0b1b11", ICON_BG="#060f09", ROW_ALT="#13291b",
    SIDEBAR_BG="#0b1a11", HEADER_BG="#0d1e13", TITLEBAR_BG="#081409",
    TITLEBAR_HOVER="#3a1c1a", TITLEBAR_CLOSE="#a5342a", SIDEBAR_ACTIVE="#4a1a17",
    CONSOLE_BG="#07130b",
    # -- foreground surfaces (lit evergreen) --
    WFM_CARD="#0e2115", PANEL="#163218", PANEL_HI="#20401f",
    FIELD_BG_IN="#173320", FIELD_BG_OUT="#122a18",
    # -- ink: snow ivory + frost sage --
    TEXT="#f2ece0", MUTED="#a6b19d", MUTED_SURFACE="#88a084",
    CONSOLE_FG="#d9e2cc", OK="#5ec26c", OK_SURFACE="#5ec26c",
    WARN="#e2a63f", ERR="#ec6a5f",
    # -- Christmas gold: inlay, marks, money (INK sits on gold buttons) --
    ACCENT="#d9b45c", ACCENT_SURFACE="#c99a3f", GOLD_HI="#f0cd76",
    GOLD_DIM="#8a6f38", GOLD_FAINT="#243016", INK="#1b2410",
    BORDER="#8a6d33", BAR_TRACK="#0b1b11", FIELD_EDGE="#8a6d33",
    HAIRLINE="#233420", PLAT="#cdd9e2",
    # -- warframe.market accents, re-tinted festive (holly + frost + pine) --
    WFM_EDGE="#8a6d33", WFM_TEAL="#7fcbbb", WFM_TEAL_DIM="#2f5249",
    WFM_PINK="#e58aa8", WFM_MUTED="#9aa693",
    WFM_BADGE_BG="#a8352b", WFM_BADGE_FG="#f6e2d4",
    WFM_BUY_BG="#1d3a2a", WFM_BUY_FG="#9ed7b2",
    WFM_RED="#d15a4a", WFM_RED_DIM="#4a2620",
    RARITY_BRONZE="#c08a5a", RARITY_SILVER="#b6c2ca", WEB_ACCENT="#9aa89e",
    REP_UP="#66a870", REP_DOWN="#b06a5e",
    FONT_FACE={**_OROKIN_FACES, "app_title": "Mountains of Christmas",
               "h1": "Mountains of Christmas"},
)

# Christmas Light: candy cane. NOT a light-mode parity of the dark theme - it
# stands on its own and leans HARD into red + green. The whiteness is gone: the
# whole ground is holly-mint, table rows stripe green<->rose, and the STRUCTURE
# carries the colour - BORDER is a real green (every panel + the rail's app
# containers are framed green) and WFM_EDGE is candy red (every market/listing
# card is framed red), so red and green literally stripe the layout. Cards stay
# peppermint-WHITE as the stripe between them, and all ink stays dark evergreen
# so it reads on the tinted ground. Green is the accent metal (money buttons,
# marks, finial, item names, WTB, positives); red owns attention (WTS tags, the
# active row, danger). Gold + silver recede to hairlines, platinum, and the thin
# money-button edge. The two contrast ceilings: SIDEBAR_ACTIVE and TITLEBAR_HOVER
# paint UNDER dark nav text (qss lines 344-357), so they stay light-enough reds.
# Festive titles (Mountains of Christmas) over the readable Orokin faces.
_CHRISTMAS_LIGHT = dict(
    # -- surfaces: holly-mint ground, no more snow (dark ink still reads) --
    BG="#dcecd8", TAB_BG="#cee4c9", ICON_BG="#c6dfc1", ROW_ALT="#f6e1de",
    SIDEBAR_BG="#cfe4ca", HEADER_BG="#cbe1c6", TITLEBAR_BG="#c4ddbe",
    TITLEBAR_HOVER="#f3c7c0", TITLEBAR_CLOSE="#c0392b", SIDEBAR_ACTIVE="#ee9f95",
    CONSOLE_BG="#cfe4ca",
    WFM_CARD="#ffffff", PANEL="#d6e9d1", PANEL_HI="#c4ddbe",
    FIELD_BG_IN="#ffffff", FIELD_BG_OUT="#f2f8ef",
    # -- ink: dark evergreen charcoal --
    TEXT="#1e2a1f", MUTED="#566855", MUTED_SURFACE="#a9bda6",
    CONSOLE_FG="#233f28", WARN="#c9821f", ERR="#cf2f2a",
    OK="#188a42", OK_SURFACE="#2fb35f",
    # -- GREEN accent metal + green-edged FIELDS; the FRAMES go RED (below) --
    ACCENT="#1f9d4e", ACCENT_SURFACE="#34b35f", GOLD_HI="#57c67e",
    GOLD_DIM="#b89a4a", GOLD_FAINT="#dfeacb", INK="#0b3318",
    # BORDER = every frame in the app (sidebar sections, panels, cards, tables,
    # the header divider). Red here is what stripes the whole layout red against
    # the green content it wraps - the candy cane. FIELD_EDGE stays green so
    # inputs/dropdowns keep green trim inside the red-framed panels.
    BORDER="#cf3a2f", BAR_TRACK="#d4e6cf", FIELD_EDGE="#4aa869",
    HAIRLINE="#c2d8bd", PLAT="#6b7883",
    # -- warframe.market accents: LOUD candy red/green (WFM_EDGE = muted sage,
    #    it's disabled/placeholder ink, NOT a frame - must not shout) --
    WFM_EDGE="#93ac90", WFM_TEAL="#1c8a52", WFM_TEAL_DIM="#a7d3ba",
    WFM_PINK="#cc3f7a", WFM_MUTED="#63745f",
    WFM_BADGE_BG="#d02b22", WFM_BADGE_FG="#fff2ef",
    WFM_BUY_BG="#2fb35f", WFM_BUY_FG="#08340f",
    WFM_RED="#cf2f2a", WFM_RED_DIM="#eab6b1",
    RARITY_BRONZE="#b07a45", RARITY_SILVER="#8a97a0", WEB_ACCENT="#4f6a57",
    REP_UP="#2f9a50", REP_DOWN="#c0463a",
    FONT_FACE={**_OROKIN_FACES, "app_title": "Mountains of Christmas",
               "h1": "Mountains of Christmas"},
)


def active_theme() -> str:
    """The selected palette name from settings (defaults to Orokin Dark). Read at
    import for the INITIAL theme; live theme changes go through set_theme()."""
    try:
        from . import config
        name = config.load_settings().get("theme", "Orokin Dark")
    except Exception:
        name = "Orokin Dark"
    return name if name in THEME_NAMES else "Orokin Dark"


# ---- diagnostic themes ------------------------------------------------------
# Two throwaway "see the stylesheet matrix" palettes. They are the PROOF the
# theme engine is complete: every token gets a UNIQUE colour with no view-code
# change, so you can see exactly where each token renders.
#   Dev-Boxes:      every FILL token a unique light colour (black text stays
#                   readable), every INK token (text/symbol/border) solid black.
#                   -> read the LAYERING: where each filled region begins/ends.
#   Dev-Boundaries: inverse - every FILL a flat 20% grey, every INK a unique loud
#                   colour. -> read the BOUNDARIES: every border/text/mark.
# A token that shows the "wrong" way (a coloured "text", a grey that should read
# as a border) is a token doing DOUBLE duty - the diagnostic's whole point.
#
# The re-faceable roles (icon/msgbtn are absent on purpose - they stay Material
# Symbols). Dev-Boxes and Dev-Boundaries put the ENTIRE UI on one commercial
# face, Be Vietnam Pro - the first step of moving the app off the system fonts;
# Dev-Fonts (below) instead gives each category its own face.
_FACEABLE_ROLES = ("app_title", "nav_title", "h1", "h2", "card_title", "body",
                   "small", "input", "button", "terminal", "badge", "price",
                   "mono")
_BE_VIETNAM = {r: "Be Vietnam Pro" for r in _FACEABLE_ROLES}
_DEV_BOXES = dict(
    BG="#de7c7c", TAB_BG="#95ace4", ICON_BG="#b6de7c", ROW_ALT="#e495db",
    SIDEBAR_BG="#7cdece", HEADER_BG="#e4c095", TITLEBAR_BG="#957cde",
    TITLEBAR_HOVER="#98e495", TITLEBAR_CLOSE="#de7c9d",
    SIDEBAR_ACTIVE="#95c7e4", CONSOLE_BG="#d6de7c", WFM_CARD="#d495e4",
    PANEL="#7cdead", PANEL_HI="#e4a595", FIELD_BG_IN="#7c85de",
    FIELD_BG_OUT="#b3e495", MUTED_SURFACE="#de7cbe", ACCENT_SURFACE="#95e1e4",
    OK_SURFACE="#c79ee4", BAR_TRACK="#e4d27c",
    GOLD_HI="#dec67c", GOLD_FAINT="#b995e4", WFM_TEAL_DIM="#7cde8d",
    WFM_BADGE_BG="#e4959f", WFM_BUY_BG="#7ca6de", WFM_RED_DIM="#cee495",
    TEXT="#000000", MUTED="#000000", CONSOLE_FG="#000000", OK="#000000",
    ACCENT="#000000",
    WARN="#000000", ERR="#000000", INK="#000000", GOLD_DIM="#000000",
    BORDER="#000000", WFM_EDGE="#000000", FIELD_EDGE="#000000",
    HAIRLINE="#000000", PLAT="#000000", WFM_TEAL="#000000",
    WFM_PINK="#000000", WFM_MUTED="#000000", WFM_BADGE_FG="#000000",
    WFM_BUY_FG="#000000", WFM_RED="#000000", RARITY_BRONZE="#000000",
    RARITY_SILVER="#000000", WEB_ACCENT="#000000", REP_UP="#000000",
    REP_DOWN="#000000",
    FONT_FACE=_BE_VIETNAM,
)
_DEV_BOUNDARIES = dict(
    BG="#333333", TAB_BG="#333333", ICON_BG="#333333", ROW_ALT="#333333",
    SIDEBAR_BG="#333333", HEADER_BG="#333333", TITLEBAR_BG="#333333",
    TITLEBAR_HOVER="#333333", TITLEBAR_CLOSE="#333333",
    SIDEBAR_ACTIVE="#333333", CONSOLE_BG="#333333", WFM_CARD="#333333",
    PANEL="#333333", PANEL_HI="#333333", FIELD_BG_IN="#333333",
    FIELD_BG_OUT="#333333", MUTED_SURFACE="#333333", ACCENT_SURFACE="#333333",
    OK_SURFACE="#333333", BAR_TRACK="#333333",
    GOLD_HI="#333333", GOLD_FAINT="#333333", WFM_TEAL_DIM="#333333",
    WFM_BADGE_BG="#333333", WFM_BUY_BG="#333333", WFM_RED_DIM="#333333",
    TEXT="#f65a5a", MUTED="#3d73f5", CONSOLE_FG="#b5f65a", OK="#f53dde",
    ACCENT="#f5d23d",
    WARN="#5af6dc", ERR="#f5a13d", INK="#815af6", GOLD_DIM="#45f53d",
    BORDER="#f65a8e", WFM_EDGE="#3db0f5", FIELD_EDGE="#eaf65a",
    HAIRLINE="#ce3df5", PLAT="#5af6a8", WFM_TEAL="#f5633d",
    WFM_PINK="#5a68f6", WFM_MUTED="#82f53d", WFM_BADGE_FG="#f65ac3",
    WFM_BUY_FG="#3deef5", WFM_RED="#f6cf5a", RARITY_BRONZE="#913df5",
    RARITY_SILVER="#5af674", WEB_ACCENT="#f53d55", REP_UP="#5a9cf6",
    REP_DOWN="#c0f53d",
    FONT_FACE=_BE_VIETNAM,
)

# Dev-Fonts: a NEUTRAL grey canvas - every fill one light grey, every ink and
# border black - so colour gets out of the way and the seven font CATEGORIES
# stand out, each drawn in a different bundled commercial face. (User spec:
# borders black, boxes light grey.) The four extra roles fold into the nearest
# category so nothing renders in the system font: badge/price ride body's Exo 2,
# mono rides the terminal's VT323. icon/msgbtn stay Material Symbols (absent).
_DEV_FONTS_FACES = {
    "app_title": "Mountains of Christmas",   # the Christmas face - main title
    "nav_title": "Orbitron",                 # wide geometric sci-fi - sidebar
    "h1": "Rajdhani", "h2": "Rajdhani",      # narrow game-HUD - in-app headers
    "card_title": "Cinzel Decorative",       # loud ornate display - item cards
    "input": "Chakra Petch",                 # Warframe-tech - input fields
    "button": "Be Vietnam Pro",              # the keeper - button text
    "body": "Exo 2", "small": "Exo 2",       # readable sci-fi - body text
    "terminal": "VT323",                     # DEC-terminal pixel - the console
    "badge": "Exo 2", "price": "Exo 2", "mono": "VT323",
}
# The canonical FILL vs INK token split (the same one Dev-Boxes encodes by
# colour). Dev-Fonts paints every fill one light grey and every ink black.
_FILL_TOKENS = ("BG", "TAB_BG", "ICON_BG", "ROW_ALT", "SIDEBAR_BG", "HEADER_BG",
                "TITLEBAR_BG", "TITLEBAR_HOVER", "TITLEBAR_CLOSE",
                "SIDEBAR_ACTIVE", "CONSOLE_BG", "WFM_CARD", "PANEL", "PANEL_HI",
                "FIELD_BG_IN", "FIELD_BG_OUT", "MUTED_SURFACE", "ACCENT_SURFACE",
                "OK_SURFACE", "BAR_TRACK", "GOLD_HI", "GOLD_FAINT",
                "WFM_TEAL_DIM", "WFM_BADGE_BG", "WFM_BUY_BG", "WFM_RED_DIM")
_INK_TOKENS = ("TEXT", "MUTED", "CONSOLE_FG", "OK", "ACCENT", "WARN", "ERR",
               "INK", "GOLD_DIM", "BORDER", "WFM_EDGE", "FIELD_EDGE",
               "HAIRLINE", "PLAT", "WFM_TEAL", "WFM_PINK", "WFM_MUTED",
               "WFM_BADGE_FG", "WFM_BUY_FG", "WFM_RED", "RARITY_BRONZE",
               "RARITY_SILVER", "WEB_ACCENT", "REP_UP", "REP_DOWN")
_DEV_FONTS = {**{k: "#d0d0d0" for k in _FILL_TOKENS},
              **{k: "#000000" for k in _INK_TOKENS},
              "FONT_FACE": _DEV_FONTS_FACES}

# Every non-dark theme is a palette OVERLAY over the Orokin Dark defaults.
_PALETTES = {"Orokin Light": _LIGHT,
             "Christmas Dark": _CHRISTMAS_DARK,
             "Christmas Light": _CHRISTMAS_LIGHT,
             "Dev-Boxes": _DEV_BOXES,
             "Dev-Boundaries": _DEV_BOUNDARIES,
             "Dev-Fonts": _DEV_FONTS}

# Snapshot the Orokin Dark defaults for EVERY token any overlay touches, captured
# NOW while the module globals still hold the dark literals defined at the top.
# A live theme switch resets to these before applying another overlay - without
# it, switching Light -> Dark would leave Light's values behind, since an overlay
# only writes the keys it changes.
_OVERLAY_KEYS = {k for pal in _PALETTES.values() for k in pal} - {"FONT_FACE"}
_DARK_DEFAULTS = {k: globals()[k] for k in _OVERLAY_KEYS}


def set_theme(name: str) -> None:
    """Apply a theme's palette + font faces to this module's globals, IN PLACE.
    Resets to the Orokin Dark defaults first so switching between overlays is
    clean, then overlays the named theme. Idempotent and repeatable - this is
    what makes live (no-restart) theme switching possible: the caller re-runs it,
    regenerates the QSS from the new globals, and repaints. Unknown names fall
    back to Orokin Dark (same rule as active_theme)."""
    if name not in THEME_NAMES:
        name = "Orokin Dark"
    globals().update(_DARK_DEFAULTS)
    globals()["FONT_FACE"] = dict(_OROKIN_FACES)
    overlay = _PALETTES.get(name)
    if overlay:
        globals().update(overlay)
    # RARITY_COLOR is the only colour-DERIVED table; rebuild it for the live palette.
    global RARITY_COLOR
    RARITY_COLOR = {"Common": RARITY_BRONZE, "Uncommon": RARITY_SILVER,
                    "Rare": ACCENT, "Legendary": PLAT}


set_theme(active_theme())          # initial application at import
