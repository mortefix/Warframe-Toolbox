"""
registry.py - the catalogue of tools that WF Market Helper can launch.

Adding a new tool is a single entry in TOOLS below. The host reads this list
to build the landing page and to know how to run each tool, so no GUI code has
to change when the toolbox grows.

Each Tool points at a standalone Python script that the host runs as a
subprocess. Flags become checkboxes and args become text fields in the runner
view; whatever the user turns on is passed on the command line.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from core import theme

# Everything is anchored to this file's folder so the app works no matter what
# directory it is launched from.
ROOT = Path(__file__).resolve().parent
TOOLS_DIR = ROOT / "tools"


@dataclass
class ToolFlag:
    """A boolean command-line switch, shown as a checkbox."""
    flag: str                       # e.g. "--live"
    label: str                      # shown next to the checkbox
    help: str = ""                  # tooltip / caption
    default: bool = False


@dataclass
class ToolArg:
    """A value passed on the command line, shown as a labelled text field.

    If `flag` is set the value is passed as `flag VALUE`; otherwise it is
    passed positionally. Empty fields are omitted entirely."""
    key: str                        # internal id
    label: str                      # shown next to the field
    flag: str = ""                  # e.g. "--config"; "" for positional
    placeholder: str = ""
    help: str = ""
    default: str = ""


@dataclass
class Tool:
    id: str
    name: str
    tagline: str                    # one-line summary on the card
    description: str                # longer blurb on the runner page
    script: Path                    # the .py to run
    workdir: Path                   # cwd for the subprocess (config lives here)
    flags: list[ToolFlag] = field(default_factory=list)
    args: list[ToolArg] = field(default_factory=list)
    accent: str = theme.WEB_ACCENT  # card accent - slate by default. NOT the
                                    # app's gold: filled gold is reserved for
                                    # money actions, and a tool's Home card
                                    # renders its accent as a filled button.
    icon: str = "tool"              # core.theme.ICONS key for the sidebar
                                    # and Home card (default: puzzle piece)
    available: bool = True          # False renders a "coming soon" card
    requires_session: bool = False  # True: host refuses to launch it unless an
                                    # account is linked (all tools reach the API
                                    # only through the host's gateway)

    @property
    def exists(self) -> bool:
        return self.script.exists()


# --------------------------------------------------------------------------
# The toolbox. Add new tools here.
# --------------------------------------------------------------------------

# The original Repricer tool was retired 2026-07 - repricing is now a feature
# of the host's My Listings view (per-card Reprice + Reprice all), which the
# host runs natively because it owns the account.

TOOLS: list[Tool] = [
    Tool(
        id="api_check",
        name="API Status",
        tagline="Verify the warframe.market API is up and shaped as expected.",
        description=(
            "Read-only health check of every endpoint the tools depend on: the "
            "v2 item index, the v2 order book (and its v1 fallback), the signin "
            "surface, and - when an account is linked - an authenticated read "
            "of your own orders. Run this before trusting any tool after a WFM "
            "update, and before letting My Listings reprice anything.\n\n"
            "Never writes anything. Exit code 0 means all checks passed."
        ),
        script=TOOLS_DIR / "api_check" / "api_check.py",
        workdir=TOOLS_DIR / "api_check",
        accent=theme.OK,            # jade, the app's OK status colour
        icon="network",             # a tower: this tool talks to the API
        requires_session=False,   # runs unauthenticated; uses session if present
    ),
    # Future tools go here, e.g.:
    # Tool(id="relic_planner", name="Relic Planner", tagline="...", ...)
]
