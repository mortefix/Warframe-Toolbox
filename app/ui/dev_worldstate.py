"""ui/dev_worldstate.py - a read-only inspector for the cached worldState.php
document (core.worldstate). Counts of every live section, plus a small sample of
fissures and the current Baro / Nightwave, so we can see the feed at a glance."""

from __future__ import annotations

from core import worldstate
from ui.dev_common import Card, DevView, fmt_epoch


class WorldStateDevView(DevView):
    TITLE = "WorldState"
    NAMESPACE = worldstate.NAMESPACE
    ICON = "world"

    def refresh_source(self):
        return worldstate.refresh()

    def build_cards(self) -> list:
        doc = worldstate.stored()
        if doc is None:
            return [Card("No data", [
                ("status", "Not collected yet — click Refresh.")])]

        cards = [Card("Overview", [
            ("Server time", fmt_epoch(worldstate.server_time())),
            ("Top-level sections", len(doc)),
        ])]

        cards.append(Card("Live activity (counts)", [
            ("Void fissures", len(worldstate.fissures())),
            ("Railjack storms", len(worldstate.void_storms())),
            ("Sorties", len(worldstate.sorties())),
            ("Archon hunt", len(worldstate.archon_hunt())),
            ("Invasions", len(worldstate.invasions())),
            ("Events", len(worldstate.events())),
            ("Alerts", len(worldstate.alerts())),
            ("Syndicate missions", len(worldstate.syndicate_missions())),
            ("Daily deals", len(worldstate.daily_deals())),
        ]))

        baro = worldstate.baro()
        if baro:
            b = baro[0]
            cards.append(Card("Void Trader (Baro)", [
                ("Character", b.get("Character", "?")),
                ("Node", b.get("Node", "?")),
                ("Manifest items", len(b.get("Manifest", []) or [])),
            ]))

        nw = worldstate.nightwave()
        if nw:
            cards.append(Card("Nightwave", [
                ("Season", nw.get("Season")),
                ("Phase", nw.get("Phase")),
                ("Active challenges",
                 len(nw.get("ActiveChallenges", []) or [])),
            ]))

        fissures = worldstate.fissures()
        if fissures:
            shown = fissures[:6]
            rows = [(f.get("Node", "?"),
                     f.get("Modifier") or f.get("MissionType", "")) for f in shown]
            cards.append(Card(
                f"Fissures (first {len(shown)} of {len(fissures)})", rows))

        return cards
