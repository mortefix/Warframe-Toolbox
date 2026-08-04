"""The ONE place the app's version lives.

Everything that states a version derives it from here: the About page,
the warframe.market User-Agent (WFM's rules require identifying your
client), and any future packaged release. Bump __version__ and every
surface updates together.

The Overwolf companion (overwolf-companion/manifest.json) versions
independently - it ships through Overwolf's store on its own cadence.
"""

APP_NAME = "WarframeToolbox"
__version__ = "1.0.0"

USER_AGENT = f"{APP_NAME}/{__version__} (by Mortefix)"
