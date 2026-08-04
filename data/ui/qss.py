"""The Orokin Treasury theme as a Qt style sheet, generated from core.theme.

This is the whole reason the Qt port is cheaper than it looks: the Tk app
carries roughly 638 per-widget `bg=`/`fg=` keyword arguments because Tk has no
cascade. Qt does, so nearly all of them become the rules below and the view
code stops mentioning colour at all.

Generated, never hand-written: every value here comes from core.theme, so a
token change repaints both front ends. If you find yourself typing a hex digit
in this file, put it in core.theme instead.

THE TRAP: a bare QWidget ignores `background` unless it has
`WA_StyledBackground` set. About 110 of the Tk app's 375 widget constructions
are bare `tk.Frame`s used purely as coloured panels, so this bites constantly
during the port. `panel()` in ui/widgets.py exists for exactly that.
"""

from __future__ import annotations

from PySide6.QtGui import QFontDatabase

from core import theme as t
from ui import icons


def _font_rule(role: str, available) -> str:
    fam = t.resolve_family(role, available)
    return f'font-family: "{fam}"; font-size: {t.size_of(role)}pt;'


def build(available_families=()) -> str:
    """Resolving the font chains needs the running toolkit, which is why this
    is a function rather than a constant.

    The shipped icon font is registered FIRST and the family list re-read
    afterwards. A caller that passed `QFontDatabase.families()` computed it
    before the font existed, so trusting that snapshot would silently resolve
    the icon role to the Segoe fallback - and the app would look correct on
    this machine and wrong on Linux, which is the worst possible failure for
    a portability fix.
    """
    icons.ensure_loaded()
    icons.ensure_text_fonts()      # register the bundled themeable faces too,
    # BEFORE snapshotting families - otherwise a theme's FONT_FACE would resolve
    # against a family list computed before the font existed (the same trap the
    # icon font hit) and silently fall back to the system chain.
    available_families = set(available_families) | set(QFontDatabase.families())
    body = _font_rule("body", available_families)
    h1 = _font_rule("h1", available_families)
    h2 = _font_rule("h2", available_families)
    small = _font_rule("small", available_families)
    badge = _font_rule("badge", available_families)
    price = _font_rule("price", available_families)
    mono = _font_rule("mono", available_families)
    icon = _font_rule("icon", available_families)
    nav_icon = _font_rule("nav_icon", available_families)
    msgbtn = _font_rule("msgbtn", available_families)
    # the five categories that gained their own role (the other two categories
    # are h1/h2 and body/small, already resolved above)
    app_title = _font_rule("app_title", available_families)
    nav_title = _font_rule("nav_title", available_families)
    card_title = _font_rule("card_title", available_families)
    field = _font_rule("input", available_families)
    button = _font_rule("button", available_families)
    terminal = _font_rule("terminal", available_families)

    return f"""
/* ---- base -------------------------------------------------------------
   NO universal background rule. In Qt the `QWidget` selector also matches
   QLabel, QCheckBox and friends, so `QWidget {{ background: ... }}` paints the
   page colour behind every piece of text - which shows as a dark box wherever
   a label sits on a lighter surface. Instead: only real surfaces declare a
   background, and everything else stays transparent and inherits what it
   sits on. That is the Tk `bg=PANEL`-on-every-label boilerplate replaced
   properly, rather than replaced with a bug. */
QWidget {{
    color: {t.TEXT};
    {body}
}}
QWidget[surface="app"] {{ background: {t.BG}; }}

/* text and controls never paint their own background */
QLabel, QCheckBox, QRadioButton, QGroupBox {{ background: transparent; }}

/* a QScrollArea and its viewport must not paint over the page either */
QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; }}

QToolTip {{
    background: {t.PANEL};
    color: {t.TEXT};
    border: {t.BORDER_W}px solid {t.BORDER};
    padding: 4px 6px;
}}

/* ---- text roles ------------------------------------------------------- */
/* the app/header title ("Warframe Toolbox - X") is its OWN font category, so a
   theme can face it apart from the in-app h1/h2 headers; defaults to the h2
   face, so the base themes are unchanged. */
/* the app/page/section titles are BOLD; on a single-weight face (Marcellus)
   Qt synthesises the weight, which is the intended heavier title presence. */
QLabel[role="app_title"] {{ {app_title} font-weight: {t.WEIGHT_BOLD};
                            color: {t.TEXT}; }}
QLabel[role="h1"]      {{ {h1}    font-weight: {t.WEIGHT_BOLD}; color: {t.TEXT}; }}
QLabel[role="h2"]      {{ {h2}    font-weight: {t.WEIGHT_BOLD}; color: {t.TEXT}; }}
/* item-card titles: their OWN face (a serif in the Orokin themes), and NOT the
   title's bold weight - they carry per-card colours (teal name, pink rank, ...)
   set inline, so this rule owns only the font. */
QLabel[role="card_title"] {{ {card_title} font-weight: {t.WEIGHT_SEMI};
                             color: {t.TEXT}; }}
QLabel[role="small"]   {{ {small} color: {t.MUTED}; }}
/* the listing side badge: bold + a touch larger; its bg/fg are set inline
   (WTS vs WTB colours), so this rule owns only the font */
QLabel[role="badge"]   {{ {badge} font-weight: {t.WEIGHT_BOLD}; }}
QLabel[role="caps"]    {{ {small} color: {t.MUTED}; }}
QLabel[role="price"]   {{ {price} color: {t.PLAT}; }}
/* item quantity on a listing card: the price face + weight so it reads as
   loud as the plat amount, but ivory (not plat blue) so it isn't a price */
QLabel[role="qty"]     {{ {price} color: {t.TEXT}; }}
QLabel[role="ducats"]  {{ {price} color: {t.ACCENT}; }}
QLabel[role="mono"]    {{ {mono}  color: {t.TEXT}; }}
QLabel[role="icon"]    {{ {icon}  color: {t.MUTED};
                          padding: 0; margin: 0; }}
QLabel[role="muted"]   {{ color: {t.MUTED}; }}
QLabel[level="ok"]     {{ color: {t.OK}; }}
QLabel[level="warn"]   {{ color: {t.WARN}; }}
QLabel[level="err"]    {{ color: {t.ERR}; }}

/* ---- surfaces --------------------------------------------------------- */
/* the tab well matches its card container (no dimmed "well"/shadow); it keeps
   the surface="tab" tag only to scope the input-field styling below. */
QWidget[surface="tab"]     {{ background: {t.WFM_CARD}; }}
QWidget[surface="panel"]   {{ background: {t.PANEL}; }}
/* Home tool cards: BG (the page colour, by request) inside the darker
   surface="card" section that holds them, so each card reads as a lighter tile
   in a darker tray, delineated by the same gold WFM_EDGE inlay the market and
   settings cards use. No hover state - the background must not change on
   mouseover (explicit user decision). */
QWidget[surface="tile"]    {{ background: {t.BG};
                              border: {t.BORDER_W}px solid {t.BORDER}; }}
QWidget[surface="card"]    {{ background: {t.WFM_CARD};
                              border: {t.BORDER_W}px solid {t.BORDER}; }}
/* the Home card's image placeholder (Element 5) - the deepest black in the
   app, the same backdrop item art sits on, so an empty band reads as a lit
   frame waiting for art rather than as a panel with a hole in it */
QWidget[surface="media"]   {{ background: {t.ICON_BG}; }}
QWidget[surface="header"]  {{ background: {t.HEADER_BG}; }}
/* The rail's edge is a SIBLING widget (widgets.vline), not a border on
   this rule: nav rows span the full width and paint straight over a
   parent border, so the edge vanished behind every button. */
QWidget[surface="sidebar"] {{ background: {t.SIDEBAR_BG}; }}
/* The three app containers on the rail are just a GOLD OUTLINE: the fill is
   SIDEBAR_BG, identical to the rail and to the rows inside, so nothing but the
   WFM_EDGE gold border (the body cards' exact trim) separates a group from the
   rail. */
QWidget[surface="nav_section"] {{ background: {t.SIDEBAR_BG};
                                  border: {t.BORDER_W}px solid {t.BORDER}; }}
QWidget[surface="console"] {{ background: {t.CONSOLE_BG};
                              color: {t.CONSOLE_FG}; }}
/* the API-check console is the "terminal" font category. The attribute
   selector outranks the plain-type input rule below, so this wins its font. */
QPlainTextEdit[surface="console"] {{ {terminal} }}
QFrame[surface="hairline"] {{ background: {t.BORDER};
                              border: none; max-height: {t.BORDER_W}px; }}
QFrame[surface="vline"] {{ background: {t.BORDER};
                           border: none; max-width: {t.BORDER_W}px; }}

/* ---- buttons ----------------------------------------------------------
   Gold discipline: the filled-gold button is for MONEY actions and the
   account link only. Everything else is [kind="secondary"], which is why
   that is also the default here. */
QPushButton {{
    background: {t.PANEL_HI};
    color: {t.TEXT};
    border: none;                      /* the Tk original is relief=flat, bd=0 */
    padding: 5px 10px;
    {button}
}}
QPushButton:hover   {{ background: {t.PANEL}; }}   /* darker, as in Tk */
QPushButton:pressed {{ background: {t.GOLD_FAINT}; }}
QPushButton:disabled {{ color: {t.MUTED}; background: {t.PANEL}; }}
/* wide=True in the Tk helper: a roomier primary-of-its-row button */
QPushButton[wide="true"] {{ padding: 5px 14px; }}
QPushButton[size="small"] {{ {small} }}
/* glyph buttons: the ✉ whisper-copy needs the Fluent icon face or the
   codepoint falls back to a blank box in Segoe UI */
QPushButton[role="glyph"] {{ {msgbtn} background: transparent; border: none;
                             color: {t.WFM_MUTED}; padding: 0; }}
QPushButton[role="glyph"]:hover {{ color: {t.WFM_TEAL}; }}

QPushButton[kind="money"] {{
    background: {t.ACCENT_SURFACE};
    color: {t.INK};
    border: {t.CTRL_BORDER_W}px solid {t.GOLD_DIM};
    font-weight: {t.WEIGHT_SEMI};
}}
QPushButton[kind="money"]:hover    {{ background: {t.GOLD_HI}; }}
QPushButton[kind="money"]:disabled {{ background: {t.GOLD_DIM};
                                      color: {t.PANEL}; }}
/* the listing card's Reprice button opts into tighter vertical padding
   (compact="true") so it fits the compact height shared by the flat buttons
   beside it - the base 5px padding otherwise makes it ~6px taller. NB: "size"
   is a reserved QWidget property, so a [size="small"] selector never matches -
   this uses a dedicated property instead. */
QPushButton[kind="money"][compact="true"] {{ padding: 2px 10px; }}
QPushButton[kind="danger"] {{
    background: {t.TITLEBAR_CLOSE};
    color: {t.TEXT};
    border: {t.CTRL_BORDER_W}px solid {t.WFM_RED_DIM};
}}
QPushButton[kind="flat"] {{
    background: transparent;
    border: none;
    color: {t.MUTED};
}}
QPushButton[kind="flat"]:hover {{ color: {t.TEXT}; }}

/* ---- inputs ----------------------------------------------------------- */
QLineEdit, QSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{
    background: {t.FIELD_BG_OUT};
    color: {t.TEXT};
    {field}
    border: {t.CTRL_BORDER_W}px solid {t.BORDER};
    selection-background-color: {t.GOLD_FAINT};
    selection-color: {t.TEXT};
    /* 2px, not 4: at 300% scaling a 4px pad is 12 real pixels top and
       bottom, which made every search field look inflated */
    padding: 2px 6px;
}}
/* height cap on text fields only - a QComboBox needs room for its arrow */
QLineEdit {{ max-height: 22px; }}
QWidget[surface="tab"] QLineEdit,
QWidget[surface="tab"] QComboBox,
QWidget[surface="tab"] QSpinBox {{ background: {t.FIELD_BG_IN}; }}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus {{
    border-color: {t.ACCENT};
}}
/* Qt draws no arrow once the drop-down is styled and no image is given, so
   the control stops looking like a dropdown at all. Carve out the well and
   let QComboBox.setEditText-free instances draw the ▾ as their own suffix
   (see ui/widgets.dropdown). */
QComboBox {{ padding-right: 20px; }}
QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: center right;
    border: none;
    width: 18px;
}}
QComboBox::down-arrow {{ image: none; width: 0; height: 0; }}
QLabel[role="combo-arrow"] {{ color: {t.MUTED}; background: transparent; }}
QComboBox QAbstractItemView {{
    background: {t.PANEL};
    color: {t.TEXT};
    border: {t.CTRL_BORDER_W}px solid {t.BORDER};
    selection-background-color: {t.GOLD_FAINT};
    outline: none;
}}
/* the autocomplete popup - a floating field, so it borrows the field's
   surface and inlay border, and takes the gold selection the Tk one had */
QListWidget[role="suggest"] {{
    background: {t.FIELD_BG_IN};
    color: {t.TEXT};
    border: {t.CTRL_BORDER_W}px solid {t.ACCENT};
    outline: none;
    {body}
}}
QListWidget[role="suggest"]::item {{
    padding: 3px 4px;
    border: none;
}}
QListWidget[role="suggest"]::item:hover {{
    background: {t.GOLD_FAINT};
}}
QListWidget[role="suggest"]::item:selected {{
    background: {t.ACCENT_SURFACE};
    color: {t.INK};
}}

QCheckBox, QRadioButton {{ background: transparent; color: {t.TEXT}; }}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 14px; height: 14px;
    background: {t.FIELD_BG_OUT};
    border: {t.CTRL_BORDER_W}px solid {t.BORDER};
}}
/* The checked fill is INSET rather than edge-to-edge: two adjacent filled
   boxes at 100% read as one blob, and leaving the frame visible keeps each
   one countable.

   THE SIZE MUST NOT CHANGE. In Qt style sheets `width`/`height` set the
   CONTENT box, with border and padding added on top - so the obvious
   spelling (keep width 14, add `padding: 2px` for the inset) made a checked
   box 20px against an unchecked 16px, and every checkbox in the app jumped
   4px the moment you ticked it. The content is shrunk by exactly twice the
   padding instead, so both states total 16px:

       unchecked   14 content           + 2 border = 16
       checked     12 content + 2 pad   + 2 border = 16

   12 of the 14px inner area is ~86% fill. 1px is the smallest inset that
   still reads as a frame, and integer padding is the only kind Qt lays out
   predictably - 80% exactly would need 1.4px. */
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    width: 12px; height: 12px;
    background: {t.ACCENT_SURFACE};
    background-clip: content;
    background-origin: content;
    padding: 1px;
    border-color: {t.GOLD_DIM};
}}

/* ---- scrollbars -------------------------------------------------------
   Flat, lacquer trough, bone thumb, gilded under the pointer - matching the
   ttk "clam" style the Tk app had to build by hand. */
QScrollBar:vertical {{
    background: {t.TAB_BG};
    width: {t.SCROLLBAR_THICK}px; margin: 0; border: none;
}}
QScrollBar::handle:vertical {{
    background: {t.PANEL_HI}; min-height: {t.SCROLLBAR_HANDLE_MIN}px; border-radius: {t.RADIUS_HANDLE}px;
}}
QScrollBar::handle:vertical:hover   {{ background: {t.GOLD_DIM}; }}
QScrollBar::handle:vertical:pressed {{ background: {t.ACCENT_SURFACE}; }}
QScrollBar:horizontal {{
    background: {t.TAB_BG}; height: {t.SCROLLBAR_THICK}px; margin: 0; border: none;
}}
QScrollBar::handle:horizontal {{
    background: {t.PANEL_HI}; min-width: {t.SCROLLBAR_HANDLE_MIN}px; border-radius: {t.RADIUS_HANDLE}px;
}}
QScrollBar::handle:horizontal:hover {{ background: {t.GOLD_DIM}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
QScrollArea {{ border: none; }}

/* ---- sidebar ----------------------------------------------------------
   The gold finial on the active row is painted, not styled - see
   ui/widgets.py Finial - because a spearpoint diamond is not a border. */
/* The ROW carries the highlight, not the button. Tk repaints rowf, the icon
   and the button together; putting the colour on the button alone leaves the
   finial and glyph sitting on the un-highlighted rail, which reads as a box
   drawn around the label. */
/* One tone: GOLD on the current row (highlight + lit text and glyph); every
   other row hovers to the neutral titlebar tint. Idle rows carry SIDEBAR_BG -
   the same colour as the rail AND the app containers, so a boxed app reads as a
   plain gold outline with no fill contrast; only active/hover paint over it. */
QWidget[nav="row"] {{ background: {t.SIDEBAR_BG}; }}
QWidget[nav="row"][active="true"] {{ background: {t.SIDEBAR_ACTIVE}; }}
QWidget[nav="row"][active="false"]:hover {{ background: {t.TITLEBAR_HOVER}; }}

QPushButton[nav="item"] {{
    background: transparent;           /* always - the row paints */
    border: none;
    color: {t.MUTED};
    text-align: left;
    /* 11px vertical keeps the row height; the tight 4px left closes the gap to
       the glyph beside it (was 8) so icon and label sit closer together */
    padding: 11px 4px;
    {nav_title}
}}
QWidget[nav="row"][active="true"] QPushButton[nav="item"] {{ color: {t.TEXT}; }}
QWidget[nav="row"][active="false"]:hover QPushButton[nav="item"] {{
    color: {t.TEXT};
}}
QLabel[nav="icon"] {{ {nav_icon} color: {t.MUTED};
                      background: transparent; padding: 0 1px; }}
QWidget[nav="row"][active="true"] QLabel[nav="icon"] {{ color: {t.ACCENT}; }}
QWidget[nav="row"][active="false"]:hover QLabel[nav="icon"] {{
    color: {t.TEXT};
}}

/* ---- badges (My Listings cards) --------------------------------------- */
QLabel[badge="sell"] {{ background: {t.WFM_BADGE_BG};
                        color: {t.WFM_BADGE_FG}; padding: 1px 4px; }}
QLabel[badge="buy"]  {{ background: {t.WFM_BUY_BG};
                        color: {t.WFM_BUY_FG};  padding: 1px 4px; }}
"""
