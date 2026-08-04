"""ui/dev_eelog.py - a read-only inspector for the EE.log event tail
(core.ee_events). Total events, a breakdown by type, and the most recent lines.
Refresh re-tails the log (read-only); it needs the game to have run at least
once for there to be anything to see."""

from __future__ import annotations

from collections import Counter

from core import ee_events
from ui.dev_common import Card, DevView


class EELogDevView(DevView):
    TITLE = "EE.log"
    NAMESPACE = ee_events.NAMESPACE
    ICON = "log"

    def refresh_source(self):
        return ee_events.tail()

    def build_cards(self) -> list:
        evs = ee_events.events()
        if not evs:
            return [Card("No data", [
                ("status", "No events tailed yet — click Refresh "
                           "(needs the game to have run).")])]

        counts = Counter(e.get("type") for e in evs)
        cards = [Card("Summary", [
            ("Total events", len(evs)),
            ("Latest login", ee_events.latest_login() or "—"),
            ("Event types", len(counts)),
        ])]

        cards.append(Card("By type", [(k, counts[k]) for k in sorted(counts)]))

        recent = evs[-12:]
        rows = [(f"{e.get('t')}s",
                 f"[{e.get('type')}] {e.get('msg', '')[:80]}") for e in recent]
        cards.append(Card(f"Recent events (last {len(recent)})", rows))

        return cards
