"""core/onboarding.py - the setup wizard's rules and copy.

The wizard view (ui/wizard.py) places widgets and nothing else: which pages
exist, everything they say, and what the data page detects all live here.
Detection reuses the same sources as Home's status lights (wf_local for the
game log, wf_inventory's provider seam for owned inventory), so the wizard
and Home can never disagree about what is connected.
"""

from __future__ import annotations

from typing import NamedTuple

from core import wf_inventory, wf_local


class DataStatus(NamedTuple):
    """What the AlecaFrame Data page reports. `source` is the active
    inventory provider's name ("" when none) - a label, never a path."""
    game_files: bool
    inventory: bool
    source: str


def detect() -> DataStatus:
    return DataStatus(
        game_files=wf_local.log_mtime() is not None,
        inventory=wf_inventory.available(),
        source=wf_inventory.source_name() or "",
    )


# ---- copy ------------------------------------------------------------------
# Every sentence the wizard shows. The view formats and places; it never
# writes its own words.

WELCOME_TITLE = "Welcome to Warframe Toolbox"
WELCOME_BODY = (
    "Let's set things up. The next steps connect your Warframe.com "
    "profile, link your warframe.market account, and check where your "
    "game data will come from.\n\n"
    "Every step is optional - you can skip any of them and come back "
    "later from Settings."
)

PROFILE_TITLE = "Connect your Warframe.com profile"
PROFILE_BODY = (
    "Sign in to Warframe.com below and your account ID is captured "
    "automatically - it lets the Toolbox read your public profile "
    "(mastery rank, loadout, progression) straight from Warframe's own "
    "servers. No password is shared with the Toolbox."
)
PROFILE_FALLBACK = (
    "Couldn't load warframe.com here - you can connect later from "
    "Settings > Data > Warframe."
)
#: The sign-in page's own states (ui/wf_connect.py shows them for the wizard
#: and for Settings alike). The page used to be a blank white rectangle until
#: the site answered, and a signed-in page that never produced an ID said
#: nothing at all, for ever.
PROFILE_LOADING = "Loading Warframe.com…"
PROFILE_UNREACHABLE = (
    "Couldn't reach Warframe.com. Check your connection, then try again."
)
PROFILE_RETRY = "Try again"
PROFILE_STUCK = (
    "You look signed in, but Warframe.com hasn't given the Toolbox your "
    "account ID. The site may have changed - skip this step for now and "
    "check for a Toolbox update."
)
PROFILE_DONE = "Account ID captured - you're connected."
#: The rail's success line (bottom left, beside Back): what worked, and what
#: to do now. The page's own note sits above a full-height web view and is
#: easy to miss, so the step used to end with no visible sign it had worked.
PROFILE_SUCCESS = "Profile connected. Press Next."
#: Shown in the same place until then, so the page never looks finished
#: before the account ID has actually been read.
PROFILE_WAITING = "Waiting for sign-in…"
MARKET_SUCCESS = "Linked as {name}. Press Next."

MARKET_TITLE = "Link your warframe.market account"
MARKET_BODY = (
    "Sign in to manage your orders from the Toolbox: repricing, "
    "visibility, sold flow and more. Credentials go only to "
    "api.warframe.market; your password is never saved."
)
MARKET_LINKED = "Linked as {name}."

DATA_TITLE = "AlecaFrame data"
DATA_BODY = (
    "The Toolbox reads your owned inventory (arcanes, mods) through "
    "AlecaFrame or the Warframe Toolbox companion. Here is what it can "
    "see right now:"
)
GAME_FILES_OK = "Game log found - Warframe has run on this machine."
GAME_FILES_MISSING = "No game log found yet - has Warframe run here?"
INVENTORY_OK = "Inventory source found ({source})."
INVENTORY_MISSING = "No inventory data yet."
ALECAFRAME_NOTICE = (
    "On a first launch this page usually can't confirm your data yet: "
    "AlecaFrame only fills in its data after it sees you complete a "
    "mission. Run Warframe with both AlecaFrame and Warframe Toolbox "
    "open in the background and finish one mission - from then on the "
    "Toolbox picks up your inventory automatically."
)
