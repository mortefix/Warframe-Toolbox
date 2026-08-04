"""ui/dev_inventory.py - a read-only inspector for the OWNED-inventory overview
(core.arcane_inv): platinum, credits, endo, and the SIZES of the big libraries
(mods, arcanes, misc). This is the one dev app whose data is owned inventory, so
it is sourced from AlecaFrame's cache today; Phase 3 swaps the source behind the
same 'inventory' store namespace. Large libraries show a COUNT, not every item."""

from __future__ import annotations

from core import store, wf_inventory
from ui.dev_common import Card, DevView

#: How each provider names its source in the "From" row.
_SOURCE_LABELS = {
    "overwolf-companion": "Warframe Toolbox Overwolf companion",
    "alecaframe": "AlecaFrame lastData.dat (fallback)",
    "linux-gep": "Linux game-events reader",
}


class InventoryDevView(DevView):
    TITLE = "Inventory"
    NAMESPACE = wf_inventory.INVENTORY_NS
    ICON = "inventory"

    def refresh_source(self):
        return wf_inventory.refresh_overview(force=True)

    def build_cards(self) -> list:
        ov = store.read(self.NAMESPACE)
        if not isinstance(ov, dict):
            hint = ("Click Refresh." if wf_inventory.available()
                    else "No inventory source — install the Overwolf companion "
                         "or run AlecaFrame, then Refresh.")
            return [Card("No data", [("status", f"Not collected yet. {hint}")])]

        def n(key):
            return f"{ov.get(key, 0):,}"

        cards = [Card("Currencies", [
            ("Platinum", ov.get("platinum")),
            ("Credits", n("credits")),
            ("Endo", n("endo")),
            ("Regal Aya", ov.get("regal_aya")),
            ("Trades remaining", ov.get("trades_remaining")),
        ])]

        cards.append(Card("Mods & arcanes (counts)", [
            ("Ranked mod/arcane instances", ov.get("ranked_mod_arcane_instances")),
            ("Unranked stacks", ov.get("unranked_stacks")),
            ("Distinct arcanes", ov.get("distinct_arcanes")),
        ]))

        cards.append(Card("Other items (counts)", [
            ("Misc items", ov.get("misc_items")),
            ("Recipes / blueprints", ov.get("recipes")),
            ("Consumables", ov.get("consumables")),
            ("Inventory keys (total)", ov.get("top_level_keys")),
        ]))

        source = ov.get("_source")
        cards.append(Card("Source", [
            ("From", _SOURCE_LABELS.get(source, source or "unknown")),
            ("Active provider", wf_inventory.source_name() or "none"),
        ]))
        return cards
