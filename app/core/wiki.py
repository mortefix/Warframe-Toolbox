"""Warframe wiki page URLs for the names the app already has on screen -
warframe.market item names, and the arcane names the Vosfor planner reads
out of AlecaFrame.

The wiki is one of the Toolbox's own tabs, so these URLs are handed to the
embedded browser (App.open_wiki -> WebAppView -> webhost.open_site), never
to webbrowser.open(). The only place a wiki URL reaches an external browser
is the "can't be embedded" fallback, and only when the user clicks it.

Market names are not wiki titles. "Rhino Prime Set" and "Braton Prime
Barrel" are listings; the articles are "Rhino Prime" (which the wiki itself
redirects to Rhino/Prime) and "Braton Prime". normalize() peels those
listing suffixes off. It is deliberately conservative: a name it does not
recognise is passed through untouched, and a miss lands on MediaWiki's
"page does not exist" screen, which carries its own search box - visible
and recoverable, unlike a silently wrong article.
"""

from __future__ import annotations

from urllib.parse import quote

BASE = "https://wiki.warframe.com/w/"

# Peeled first, in this order. All are listing wrappers, never part of an
# article title: "Rhino Prime Set" -> "Rhino Prime", "Forma Blueprint" ->
# "Forma", "Chesa Kubrow Imprint" -> "Chesa Kubrow" (the wiki documents the
# companion breed, not the imprint listing).
_WRAPPERS = (" Set", " Blueprint", " Imprint")

# Component listings. A part is sold per-piece but documented on the parent
# item's page - "Braton Prime Barrel" -> "Braton Prime", and equally the
# non-Prime "Braton Vandal Barrel" -> "Braton Vandal" and "Agkuza Guard" ->
# "Agkuza"; component pages don't exist, so an unstripped part name always
# missed. "Helmet" is deliberately absent: every " Helmet" listing on the
# market is an arcane helmet (its own article), not a warframe part.
_COMPONENTS = (
    # warframe parts
    "Neuroptics", "Chassis", "Systems", "Harness", "Wings",
    # weapon parts
    "Barrel", "Receiver", "Stock", "Blade", "Handle", "Hilt", "Link",
    "Ornament", "Grip", "String", "Lower Limb", "Upper Limb", "Pouch",
    "Disc", "Boot", "Head", "Gauntlet", "Guard", "Star", "Chain",
    # companion parts
    "Carapace", "Cerebrum", "Cortex", "Collar",
    # archwing parts
    "Fuselage", "Engine",
    # kavasa collar set pieces
    "Band", "Buckle",
)

# Names that END in a component word but ARE the article - stripping would
# turn a working link into a miss. Generated from the /v2/items catalogue
# (2026-08-02) by keeping every name that ends in a _COMPONENTS word yet is
# NOT tagged "component" - almost all mods, plus a skin and the Ayatan
# stars. Regenerate the same way if a future mod collides.
_KEEP = frozenset({
    "abating link", "ammo chain", "ammo stock", "ayatan amber star",
    "ayatan cyan star", "carnis carapace", "catalyzer link",
    "chromatic blade", "conductive blade", "electrified barrel",
    "hydraulic barrel", "jugulus carapace", "kavasa prime band",
    "kavasa prime buckle", "narrow barrel", "neutron star",
    "ostron chest guard", "primed ammo chain", "primed ammo stock",
    "primed rubedo-lined barrel", "prism guard", "reflex guard",
    "rhythm guard", "rolling guard", "rubedo-lined barrel",
    "saxum carapace", "sharpened blade", "shock collar",
    "spring-loaded blade", "tempered blade",
})

# Whole-name rewrites for listings that describe a mechanic rather than an
# item. Keyed on the lowercased name.
_ALIASES = {
    "riven mod": "Riven Mods",
}


def normalize(name: str) -> str:
    """A wiki article title for a market/arcane item name.

    Peels listing wrappers, then a component word off ANY listing - Prime or
    not, since a component page never exists and the parent article always
    does. The protection for real articles that merely END in a component
    word ("Rolling Guard", "Tempered Blade") is _KEEP, generated from the
    market catalogue's own item tags rather than guessed.
    """
    out = " ".join(name.split())          # collapse stray whitespace
    if not out:
        return out

    for _ in range(len(_WRAPPERS)):       # "X Prime Chassis Blueprint"
        for suffix in _WRAPPERS:
            if out.lower().endswith(suffix.lower()) and len(out) > len(suffix):
                out = out[:-len(suffix)].rstrip()
                break
        else:
            break

    lower = out.lower()
    if lower.endswith(" riven mod"):
        return _ALIASES["riven mod"]
    if lower in _ALIASES:
        return _ALIASES[lower]
    if lower in _KEEP:
        return out

    for part in _COMPONENTS:
        if not lower.endswith(" " + part.lower()):
            continue
        base = out[:-len(part)].rstrip()
        if base:
            out = base
        break
    return out


def url_for(name: str) -> str:
    """The wiki page URL for an item name ("" for an empty name).

    Spaces become underscores the way MediaWiki titles do; everything else
    is percent-encoded, so apostrophes and parentheses survive.

    Idempotent on already-formed wiki URLs: mods.db stores each mod's
    wiki_url pre-built from the wiki entry's Link (which is not always the
    display name, e.g. Flawed Chilling Grasp -> "Chilling Grasp"), so the
    mods view hands a URL here, not a title. Only BASE-prefixed URLs pass
    through - this is not a general open-any-URL door.
    """
    if name.startswith(BASE):
        return name
    title = normalize(name)
    if not title:
        return ""
    return BASE + quote(title.replace(" ", "_"), safe="_/")
