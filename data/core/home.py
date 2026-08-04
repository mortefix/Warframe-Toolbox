"""What the Home gallery contains: one card per app, with its copy.

Cards mirror the sidebar and open the same views. Everything here is content
and rules - which cards exist, in what order, what each says, and what its
button should read - so both front ends render the same gallery.

Settings deliberately has NO card: it is chrome, not a tool, and is opened
from the sidebar. API Status has none either - it lives inside
Settings > Data > Market.
"""

from __future__ import annotations

from typing import Iterable, NamedTuple

from . import theme, wf_inventory, wf_local, wf_profile
from .webapps import WEB_APPS, WEB_KEYS

# Accents identify a card; they ride on the stripe and icon, never on the
# button. A filled accent per card would put six saturated surfaces - one of
# them gold - on the first screen of the app.
ACCENTS = {
    "listings": theme.ACCENT,          # My Listings IS the treasury: gold
    "market": theme.WFM_TEAL,
    "vosfor": theme.RARITY_BRONZE,     # bronze: dissolved dust
    "web": theme.WEB_ACCENT,           # slate: "the webview is a lit pane" -
}                                      # not gold (not money), not PLAT


class Card(NamedTuple):
    key: str
    name: str
    icon: str
    accent: str
    requires_session: bool
    exists: bool            # False for a tool whose script is missing
    blurb: str


NATIVE = (
    Card("listings", "My Listings", theme.LISTINGS_ICON, ACCENTS["listings"],
         True, True,
         "Your buy & sell orders, warframe.market style: Sold, Edit, "
         "quantity, visibility and delete on every card - plus one-click "
         "repricing that matches the best online price, never past your "
         "floor/cap."),
    Card("market", "Market", "market", ACCENTS["market"], False, True,
         "Browse warframe.market live: the order book for any item, riven & "
         "lich contracts, and a watchlist so you can bookmark items instead "
         "of searching them again."),
    Card("vosfor", "Vosfor", "vosfor", ACCENTS["vosfor"], False, True,
         "The Arcane Dissolution planner: ranks every collection by expected "
         "value per 200-Vosfor pack, reads your arcanes from AlecaFrame (or "
         "tick them off by hand), and splits your Vosfor into the best "
         "purchase plan."),
)

WEB_BLURBS = {
    "web_wiki": "The official Warframe wiki, embedded - look up anything "
                "without leaving the app.",
    "web_builds": "Overframe's builds and tier lists, embedded - with the "
                  "Toolbox ad blocker on duty.",
}

HIDDEN = frozenset({"api_check"})      # reached from Settings > Data > Market


def cards(tools: Iterable = ()) -> list[Card]:
    """Native apps lead, then the embedded web apps, then the registry's
    tools. Add a site to WEB_APPS or a tool to the registry and it appears
    here - no edit to this function."""
    out = list(NATIVE)
    out += [Card(a.key, a.label, a.icon, ACCENTS["web"], False, True,
                 WEB_BLURBS.get(a.key, "Embedded web app."))
            for a in WEB_APPS]
    out += [Card(t.id, t.name, t.icon, t.accent, t.requires_session,
                 t.exists, t.tagline)
            for t in tools if t.id not in HIDDEN]
    return out


class Action(NamedTuple):
    """What the card's button says and does. `kind` is one of:
      "open"    - navigate to `card.key`
      "link"    - the account isn't linked yet and this card needs one
      "missing" - the tool's script is absent; the button is dead
    """
    label: str
    kind: str
    enabled: bool


def action_for(card: Card, linked: bool) -> Action:
    """A web tab is a site we host, not an app we run - "Visit" says so."""
    if not card.exists:
        return Action("Script missing", "missing", False)
    if card.requires_session and not linked:
        return Action("Link account first", "link", True)
    verb = "Visit" if card.key in WEB_KEYS else "Open"
    return Action(f"{verb}  →", "open", True)


class PlayerStatus(NamedTuple):
    """What the Home status panel shows as identity + connection lights.

    Mastery rank is deliberately NOT here: it now comes from the Warframe.com
    profile API (wf_profile), falling back to AlecaFrame's blob, and either read
    can touch disk or the network, so Home fills the rank in off-thread after
    this cheap snapshot is drawn.
    """
    name: str            # warframe.market display name, "" when not linked
    market: bool         # linked to warframe.market
    game_files: bool     # the app can see the game's local files (EE.log)
    profile: bool        # Warframe.com account linked (public profile API)
    inventory: bool      # an owned-inventory source is available (our Overwolf
                         # companion, or AlecaFrame as the fallback)


def player_status(name: str, market_linked: bool) -> PlayerStatus:
    """A snapshot of the connections Home shows as lights. Cheap by design - a
    session flag the caller already has, a settings read, and a couple of
    stat() calls - so it can be recomputed on every rebuild without a worker."""
    return PlayerStatus(
        name=name,
        market=market_linked,
        game_files=wf_local.log_mtime() is not None,
        profile=wf_profile.configured(),
        inventory=wf_inventory.available(),
    )
