"""Price floors (sell side) and caps (buy side) - the rules only, no widgets.

These four things are ONE invariant and must not be split up again:

  * `app.listing_baseline`  - order_id -> the price a limit derives from
  * `prefs["floors"]`/`["caps"]` - slug -> a hand-set override
  * `prefs["floor_offset"]`/`["cap_offset"]` - the tab-wide +/- nudge
  * the "is this override still meaningful?" test

Only this module writes them. The rule is small but easy to get subtly wrong:
an override equal to the derived value is *not* an override, it is the default
spelled out, and storing it would freeze the limit against later baseline
movement. `Limits.commit()` is where that lives.

`Limits` holds live references to the caller's dicts rather than copies, so
the tab's prefs and the app's baseline stay the single source of truth and the
offset is read fresh on every call - exactly the behaviour this replaced.
"""

from __future__ import annotations

from typing import Literal, NamedTuple


class Commit(NamedTuple):
    """What committing a typed limit did. `rejected` means the text was not a
    number and the field should be repainted from the model, unchanged."""
    action: Literal["cleared", "set", "rejected"]
    value: int | None = None

    @property
    def changed(self) -> bool:
        return self.action != "rejected"


def parse_offset(text: str, current: int) -> int | None:
    """The tab-wide offset field: '+5', '-3', '5', or empty (meaning 0).
    None when it is not a number at all, so the caller can repaint from
    `current` rather than guess."""
    try:
        return int(text.replace("+", "").strip() or 0)
    except ValueError:
        return None


def parse_limit(text: str) -> int | None:
    """A per-item floor/cap field. None when unparseable. Empty string is NOT
    handled here - empty means "clear the override" and is a different
    outcome, so `Limits.commit` decides it."""
    try:
        return max(1, int(text))
    except ValueError:
        return None


class Limits:
    def __init__(self, baseline: dict[str, int], prefs: dict,
                 offset_key: str, override_key: str) -> None:
        self.baseline = baseline
        self.prefs = prefs
        self.offset_key = offset_key
        self.override_key = override_key

    @property
    def offset(self) -> int:
        return self.prefs[self.offset_key]

    @property
    def overrides(self) -> dict[str, int]:
        return self.prefs[self.override_key]

    def set_offset(self, value: int) -> bool:
        """True when the value actually changed and prefs need saving."""
        if value == self.offset:
            return False
        self.prefs[self.offset_key] = value
        return True

    def reference(self, order_id: str, posted: int) -> int:
        """The price this item's default limit derives from: its posted price
        at first sight this session, or the last price set by hand in Edit.
        First call for an order_id records it - that is the 'first sight'."""
        return self.baseline.setdefault(order_id, posted)

    def rebase(self, order_id: str, price: int) -> None:
        """A hand-set price becomes the new reference the default hangs off."""
        self.baseline[order_id] = price

    def auto(self, order_id: str, posted: int) -> int:
        return max(1, self.reference(order_id, posted) + self.offset)

    def limit(self, slug: str, order_id: str, posted: int) -> int:
        return self.overrides.get(slug, self.auto(order_id, posted))

    def is_overridden(self, slug: str) -> bool:
        return slug in self.overrides

    def commit(self, text: str, slug: str, order_id: str,
               posted: int) -> Commit:
        """Apply a typed limit. Empty clears the override; a value equal to
        the derived default also clears it (see the module docstring); a
        non-number is rejected and nothing is written."""
        text = text.strip()
        if not text:
            self.overrides.pop(slug, None)
            return Commit("cleared")
        val = parse_limit(text)
        if val is None:
            return Commit("rejected")
        if val == self.auto(order_id, posted):
            self.overrides.pop(slug, None)
            return Commit("cleared")
        self.overrides[slug] = val
        return Commit("set", val)

    def set_override(self, slug: str, value: int | None) -> None:
        """Edit dialog's road in: an explicit value or None to clear."""
        if value is None:
            self.overrides.pop(slug, None)
        else:
            self.overrides[slug] = value
