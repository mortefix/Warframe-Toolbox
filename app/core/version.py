"""The ONE place the app's version lives.

Everything that states a version derives it from here: the About page,
the warframe.market User-Agent (WFM's rules require identifying your
client), and any future packaged release. Bump __version__ and every
surface updates together.

The Overwolf companion (overwolf-companion/manifest.json) versions
independently - it ships through Overwolf's store on its own cadence.
"""

from pathlib import Path

APP_NAME = "WarframeToolbox"
__version__ = "1.1.0"

USER_AGENT = f"{APP_NAME}/{__version__} (by Mortefix)"


#: CHANGELOG.md lives at the repo root (one level above app/).
_CHANGELOG_PATH = Path(__file__).resolve().parents[2] / "CHANGELOG.md"


def changelog_text() -> str:
    """CHANGELOG.md entries, lightly prettified for the About page.

    Reads the repo-root CHANGELOG.md, drops its preamble, and returns the
    version sections as readable plain text. A section with no entries (an
    emptied [Unreleased] right after a release) is skipped. Falls back to a
    short note if the file cannot be read.
    """
    try:
        raw = _CHANGELOG_PATH.read_text(encoding="utf-8")
    except OSError:
        return f"v{__version__}\nChangelog unavailable."
    blocks = []                       # [(heading, [body lines]), ...]
    for line in raw.splitlines():
        if line.startswith("## "):
            core = line[3:].strip().replace("[", "").replace("]", "")
            name, _, date = core.partition(" - ")
            name = name.strip()
            if name != "Unreleased":
                name = "v" + name
            date = date.strip()
            blocks.append((name + (" — " + date if date else ""), []))
        elif blocks:
            body = blocks[-1][1]
            if line.startswith("### "):
                body.append(line[4:].strip())
            elif line.startswith("- "):
                body.append("  • " + line[2:].strip())
            elif line.strip():
                body.append("    " + line.strip())
    parts = [h + "\n" + "\n".join(b) for h, b in blocks if any(x.strip() for x in b)]
    return "\n\n".join(parts) or f"v{__version__}\nNo entries yet."
