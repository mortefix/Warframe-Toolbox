"""ui/dev_profile.py - a read-only inspector for the cached getProfileViewingData
document (core.wf_profile). Identity, equipped loadout, and COUNTS for the large
progression libraries (mastery-XP records, intrinsics, syndicates, nodes)."""

from __future__ import annotations

from core import wf_profile
from ui.dev_common import Card, DevView, fmt_epoch


#: Standing thresholds to REACH each positive syndicate rank (standard across
#: the main syndicates); negative ranks mirror the first two. Used only to label
#: a standing with its rank for the dev panel.
_RANK_TITLES = {
    -2: "rank -2 (opposed)", -1: "rank -1 (opposed)", 0: "rank 0 (neutral)",
    1: "rank 1", 2: "rank 2", 3: "rank 3", 4: "rank 4", 5: "rank 5 (max)",
}


def _rank_label(title) -> str:
    return _RANK_TITLES.get(title, f"rank {title}")


class ProfileDevView(DevView):
    TITLE = "Profile"
    NAMESPACE = wf_profile.NAMESPACE
    ICON = "profile"

    def refresh_source(self):
        return wf_profile.refresh()

    def build_cards(self) -> list:
        p = wf_profile.stored()
        if p is None:
            hint = ("Set your account ID in Settings → Warframe, then Refresh."
                    if not wf_profile.configured()
                    else "Configured — click Refresh.")
            return [Card("No data", [("status", f"Not collected yet. {hint}")])]

        cards = [Card("Identity", [
            ("Display name", wf_profile.display_name() or "—"),
            ("Mastery rank", wf_profile.mastery_rank()),
            ("Account created", fmt_epoch(wf_profile.created_at())),
            ("Account ID", wf_profile.account_id() or "—"),
        ])]

        lp = wf_profile.loadout() or {}
        cards.append(Card("Equipped loadout", [
            ("Preset name", lp.get("n", "—")),
            ("Focus school", lp.get("FocusSchool", "—")),
        ]))

        # Large libraries: enumerate counts, not every row (dev panel, not
        # inventory UI).
        cards.append(Card("Progression (counts)", [
            ("Mastery-XP records", len(wf_profile.item_xp() or [])),
            ("Intrinsics tracked", len(wf_profile.intrinsics() or {})),
            ("Syndicate standings", len(wf_profile.syndicate_standings() or [])),
            ("Node completions", len(wf_profile.node_completion() or [])),
            ("Wishlist items", len(p.get("Wishlist", []) or [])),
            ("Challenge progress", len(p.get("ChallengeProgress", []) or [])),
        ]))

        intrinsics = wf_profile.intrinsics() or {}
        if intrinsics:
            rows = [(k, v) for k, v in sorted(intrinsics.items())]
            cards.append(Card("Intrinsics", rows))

        standings = wf_profile.syndicate_standings() or []
        if standings:
            # show the RANK (the Affiliations "Title" field) next to the raw
            # standing, so the number has meaning
            rows = [(s.get("Tag", "?"),
                     f"{_rank_label(s.get('Title'))} · {s.get('Standing')}")
                    for s in standings[:16]]
            cards.append(Card(
                f"Syndicate ranks (first {len(rows)} of {len(standings)})",
                rows))

        return cards
