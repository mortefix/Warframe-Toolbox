"""Offscreen checks for the Qt My Listings screen.

Two things drive what is tested here.

**The buy side is unreachable by hand.** This developer's account holds 24
sell orders and zero buy orders, so every WTB behaviour - the "cap" wording,
the `Bought` verb, and above all the INVERTED comparison that decides whether
a trader has been beaten - can only be exercised from a test. A screen
verified by looking at it would ship a broken WTB tab and nobody would notice
until the first buy order was posted.

**Card reuse is the architecture.** The Tk version destroyed and rebuilt every
card on each sort, filter or search change, and that churn is what made its
fourteen background paths fragile. The port keeps cards alive and re-orders
them, so several checks below assert widget IDENTITY across a view change -
not that the right thing is displayed, but that it is displayed by the same
object that displayed it before.

No network: a fake client stands in. `save_prefs` is stubbed, because the
screen writes real preferences to disk and a test must not clobber them.
"""
import base64
import os
import sys
# These tests print the glyphs the UI actually uses. A Windows console
# defaults to cp1252, which cannot encode them, so a PASSING test could
# still die in its own print statement.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtWidgets import QApplication, QMessageBox
except ImportError:
    print("PySide6 not installed - skipping Qt listings checks")
    raise SystemExit(0)

from core import listings_vm as lvm
from core import market as core_market
from core import theme as th
from ui import qss

fails = []


def check(name, got, want=True):
    ok = got == want
    if not ok:
        fails.append(f"{name}: got {got!r}, want {want!r}")
    print(f"  {'ok  ' if ok else 'FAIL'} {name}")


def settle(rounds=60):
    """Let worker threads land. The fake client returns instantly, so this is
    generous rather than tight."""
    for _ in range(rounds):
        app.processEvents()
        time.sleep(0.004)


# -- stand-ins ---------------------------------------------------------------

SAVED = []
core_market.save_prefs = lambda prefs: SAVED.append(dict(prefs))
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)


def listing(oid, name, plat, qty=1, visible=True, slug=None):
    return core_market.Listing(order_id=oid, slug=slug or name.lower(),
                               name=name, platinum=plat, quantity=qty,
                               visible=visible, updated="")


# a valid one-pixel PNG - the smallest thing QPixmap.loadFromData accepts
_PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
    "AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


class FakeClient:
    """Every call the screen makes, with no network and a call log."""

    def __init__(self):
        self.calls = []
        self.fail_next = None
        self.sell = [listing("a", "Ash Prime Set", 40, 2),
                     listing("b", "Banshee Prime Set", 15, 1),
                     listing("c", "Cernos Prime Set", 90, 3, visible=False)]
        self.buy = [listing("x", "Arcane Energize", 800, 1),
                    listing("y", "Arcane Grace", 400, 2)]
        #  slug -> what another trader is offering
        self.best = {"ash prime set": (35, 4), "banshee prime set": (18, 2),
                     "cernos prime set": (95, 1),
                     "arcane energize": (820, 3), "arcane grace": (380, 5)}
        # the user's OWN riven/lich contracts (My Listings > Contracts). One
        # visible riven and one hidden lich, so both the kind badge and the
        # warn-toned "hidden" tag get exercised.
        self.auctions = [
            {"id": "riv1", "kind": "riven", "visible": True,
             "name": "Visi-critacan", "weapon": "Kuva Bramma",
             "weapon_slug": "kuva_bramma", "mastery": 14,
             "rerolls": 3, "polarity": "madurai", "rank": 8,
             "attributes": ["+damage", "+critical chance", "-zoom"],
             "stats": [{"url_name": "melee_damage", "value": 126.4,
                        "positive": True},
                       {"url_name": "critical_damage", "value": 74.7,
                        "positive": True},
                       {"url_name": "zoom", "value": 50, "positive": False}],
             "element": "", "damage": None, "ephemera": False, "quirk": "",
             "starting": 200, "buyout": 1200, "top_bid": None,
             "owner": "Dzwsin", "status": "ingame"},
            {"id": "lic1", "kind": "lich", "visible": False, "name": "",
             "weapon": "Kuva Kohm", "weapon_slug": "kuva_kohm",
             "mastery": None, "rerolls": None,
             "polarity": "", "rank": None, "attributes": [], "stats": [],
             "element": "Toxin", "damage": 42, "ephemera": True, "quirk": "",
             "starting": 150, "buyout": None, "top_bid": 90,
             "owner": "Dzwsin", "status": "ingame"}]

    def my_listings(self):
        return {"sell": list(self.sell), "buy": list(self.buy)}

    def my_auctions(self):
        return list(self.auctions)

    def lowest_online(self, slug, exclude=""):
        return self.best.get(slug, (None, 0))

    highest_online = lowest_online

    def _maybe_fail(self, what):
        self.calls.append(what)
        if self.fail_next:
            msg, self.fail_next = self.fail_next, None
            raise core_market.MarketError(msg)

    def update_order(self, oid, plat, qty, visible, rank=None):
        self._maybe_fail(("update", oid, plat, qty, visible, rank))

    def max_rank(self, slug):
        """What /v2/item/<slug> reports. None for goods that do not rank."""
        return {"arcane_energize": 5, "arcane grace": 3}.get(slug)

    def close_order(self, oid, qty=1):
        self._maybe_fail(("close", oid, qty))

    def delete_order(self, oid):
        self._maybe_fail(("delete", oid))

    def set_auction_visibility(self, aid, visible):
        self._maybe_fail(("auction_visibility", aid, visible))
        for a in self.auctions:
            if a["id"] == aid:
                a["visible"] = visible

    def relist_auction(self, row, *, starting, buyout, mod_rank=None,
                       visible=True):
        # a real relist mints a fresh auction id; the fake keeps the old one
        # so the test can keep addressing cards["riv1"] across the re-fetch
        self._maybe_fail(("auction_relist", row["id"],
                          {"starting": starting, "buyout": buyout,
                           "mod_rank": mod_rank, "visible": visible}))
        for a in self.auctions:
            if a["id"] == row["id"]:
                a["starting"], a["buyout"] = starting, buyout
                a["visible"] = visible
                if mod_rank is not None:
                    a["rank"] = mod_rank
        return row["id"]

    def close_auction(self, aid):
        self._maybe_fail(("auction_close", aid))
        self.auctions = [a for a in self.auctions if a["id"] != aid]

    def weapon_thumbs(self):
        self.calls.append(("weapon_thumbs",))
        return {"kuva_bramma": "items/images/en/thumbs/kuva_bramma.png",
                "kuva_kohm": "lich_weapons/images/thumbs/kuva_kohm.png"}

    def fetch_thumb(self, path):
        # a real (1x1) PNG, so the contract cards' pixmap pipeline runs for
        # real; the WTS fakes carry no thumb path, so they never land here
        return _PNG_1PX if path else None


app = QApplication([])
app.setStyleSheet(qss.build(set(QFontDatabase.families())))

from ui.listings import EditListingDialog, ListingsView          # noqa: E402

client = FakeClient()


class FakeSession:
    username = "Dzwsin"


view = ListingsView(client, FakeSession(), {})
view.resize(1200, 800)
view.show()
settle()
wts, wtb = view.tabs["WTS"], view.tabs["WTB"]

print("the fetch feeds both sides from one call")
check("sell orders landed", len(wts.listings), 3)
check("buy orders landed", len(wtb.listings), 2)
check("one card per sell order", len(wts.cards), 3)
check("ledger counts price x quantity, not rows",
      view.ledger.text(), f"{40 * 2 + 15 * 1 + 90 * 3:,}")

print("\nthe two sides differ only through SIDES")
check("sell says floor", wts.spec.limit_word, "floor")
check("buy says cap", wtb.spec.limit_word, "cap")
check("sell verb", wts.spec.done_verb, "Sold")
check("buy verb", wtb.spec.done_verb, "Bought")
check("sell offset key is not the buy one",
      wts.limits.offset_key != wtb.limits.offset_key)
check("and neither are the override keys",
      wts.limits.override_key != wtb.limits.override_key)

print("\nTHE BUY SIDE'S INVERTED COMPARISON")
# The single rule no amount of clicking can reach on a sell-only account:
# a seller is beaten by a LOWER price, a buyer by a HIGHER one. Both cards
# below are "market 820 vs my 800" - the same numbers, opposite verdicts.
seller = wts.cards["a"]
seller.listing.market_low, seller.listing.online_count = 45, 4
seller.paint_market()
check("a HIGHER market price does not beat a seller",
      "⚠" in seller.market.text(), False)
seller.listing.market_low = 35
seller.paint_market()
check("a lower one does", "⚠" in seller.market.text())

buyer = wtb.cards["x"]
buyer.listing.market_low, buyer.listing.online_count = 780, 3
buyer.paint_market()
check("a LOWER market price does not beat a buyer",
      "⚠" in buyer.market.text(), False)
buyer.listing.market_low = 820
buyer.paint_market()
check("a higher one does", "⚠" in buyer.market.text())
check("the buy card says 'High =', not 'Low ='",
      "High =" in buyer.market.text() and "Low" not in buyer.market.text())

print("\n'no competition' is not 'still loading'")
# `market_low is None` means two different things and the card has to tell
# them apart, or an item nobody else lists looks permanently stuck at "low …"
fresh = wtb.cards["y"]
# the sweep already ran during startup, so put the card back to its
# pre-sweep state rather than asserting against a stale moment
fresh.market_known = False
fresh.listing.market_low = None
fresh.paint_market()
check("before the sweep it reads as pending",
      fresh.market.text().endswith("…"))
wtb._market_landed(("y", None, 0, False))
check("a sweep that found nobody says so",
      fresh.market.text(), "only listing")
check("and it does not claim to be beaten", "⚠" in fresh.market.text(), False)

# a sweep that ERRORED must not masquerade as "only listing" - that would
# tell the user they hold the sole listing when the book was never read
fresh.market_known = False
fresh.listing.market_low = None
fresh.paint_market()
wtb._market_landed(("y", None, 0, True))
check("a failed sweep reads as unknown", fresh.market.text(), "market unknown")
check("and does not claim to be the only listing",
      fresh.market.text() == "only listing", False)

print("\n-1 looks the same whatever the quantity")
# Pixel-level, because "these two buttons do not match" is invisible to logic.
# -1 stays live on a single unit: the refusal it gives when pressed explains
# itself, where a greyed-out control can only be silent about why.
one_unit = wts.cards["b"]       # quantity 1
many = wts.cards["a"]           # quantity 2


def ink(btn):
    """Every colour the button paints - text, border and fill."""
    img = btn.grab().toImage()
    return {img.pixelColor(x, y).name()
            for x in range(img.width()) for y in range(img.height())}


check("-1 is still pressable on a single unit", one_unit.down.isEnabled())
# They carry DIFFERENT icons now (add vs remove), so demanding identical
# pixels would forbid the icons themselves. What must match is the FRAMING -
# same border, colour and size - so the pair still reads as one control.
check("-1 and +1 share a style sheet",
      one_unit.down.styleSheet(), one_unit.up.styleSheet())
check("and the same size", one_unit.down.size(), one_unit.up.size())
check("and each carries its own icon",
      (one_unit.down.icon().isNull(), one_unit.up.icon().isNull()),
      (False, False))
check("-1 looks the same whatever the stock",
      ink(one_unit.down) == ink(many.down))
check("its tooltip is what explains the difference",
      "Delete" in one_unit.down.toolTip())

print("\nthe sort direction is NAMED, not drawn as an arrow")
# An up/down arrow is read both ways by different people. Naming the result
# means the control cannot be misread in either direction.
for sort_name, asc, desc in (("Name", "A → Z", "Z → A"),
                             ("Price", "low → high", "high → low"),
                             ("Quantity", "few → many", "many → few"),
                             ("Market best", "low → high", "high → low")):
    wts.sort.setCurrentText(sort_name)
    app.processEvents()
    check(f"{sort_name} ascending reads {asc!r}", wts.order_btn.text(), asc)
    wts._flip_order()
    check(f"{sort_name} descending reads {desc!r}", wts.order_btn.text(), desc)
    # and the DATA follows the label, in both directions
    first = wts._order[0]
    wts._flip_order()
    check(f"{sort_name} actually reverses", wts._order[0] != first
          or len(set(wts._order)) == 1)
wts.sort.setCurrentText("Name")
app.processEvents()

print("\nclearing the search returns to the top")
wts.area.verticalScrollBar().setValue(
    wts.area.verticalScrollBar().maximum())
wts.search.setText("cernos")
wts._search_typed()
app.processEvents()
wts.search.setText("")
wts._search_typed()
app.processEvents()
check("the scroll went home", wts.area.verticalScrollBar().value(), 0)

print("\ncards are RE-ORDERED, never rebuilt")
before = {oid: card for oid, card in wts.cards.items()}
wts.sort.setCurrentText("Price")
app.processEvents()
check("sorting by price reorders the display",
      wts._order, ["b", "a", "c"])
check("and every card is the SAME OBJECT it was",
      all(wts.cards[o] is before[o] for o in before))
wts._flip_order()
app.processEvents()
check("descending flips it", wts._order, ["c", "a", "b"])
check("still the same objects",
      all(wts.cards[o] is before[o] for o in before))
wts._flip_order()
wts.sort.setCurrentText("Name")
app.processEvents()

print("\nthe Show filter hides cards without destroying them")
wts.show_mode.setCurrentText("Visible")
app.processEvents()
check("the hidden order drops out of the order", wts._order, ["a", "b"])
check("but its card still exists", "c" in wts.cards)
check("it is merely not shown", wts.cards["c"].isVisible(), False)
wts.show_mode.setCurrentText("Hidden")
app.processEvents()
check("Hidden shows only the hidden one", wts._order, ["c"])
wts.show_mode.setCurrentText("All")
app.processEvents()
check("All brings everyone back", sorted(wts._order), ["a", "b", "c"])

print("\na hidden tab defers its relayout and catches up on show")
# WTB is behind WTS in the stack, so it is not visible
check("the buy tab is not visible", wtb.isVisible(), False)
wtb._dirty = False
wtb.apply_view()
check("applying a view while hidden only marks it dirty", wtb._dirty)
view.select("WTB")
app.processEvents()
check("showing it flushes the deferral", wtb._dirty, False)
check("and the cards are placed", sorted(wtb._order), ["x", "y"])
view.select("WTS")
app.processEvents()

print("\nquantity: zero is not a quantity")
check("Ash has 2, so -1 is allowed",
      lvm.adjust_quantity(wts.cards["a"].listing.quantity, -1), 1)
one = wts.cards["b"]
check("Banshee has 1, so -1 cannot be a decrement",
      lvm.adjust_quantity(one.listing.quantity, -1), None)
wts._adjust_qty("b", -1)
app.processEvents()
check("and asking anyway is refused, not obeyed",
      "Delete" in one.result.text())
check("with no call to the API", ("update", "b", 15, 0, True)
      not in client.calls)

print("\nquantity: a legal step goes through and repaints")
wts._adjust_qty("a", 1)
settle()
check("the API was called with the new quantity",
      ("update", "a", 40, 3, True, None) in client.calls)
check("the model moved", wts.cards["a"].listing.quantity, 3)
check("and the card shows it", wts.cards["a"].qty.text(), "3 ❒")

print("\nSold decrements; the last one closes the order")
wts._sold("a")
settle()
check("close was called", ("close", "a", 1) in client.calls)
check("quantity dropped", wts.cards["a"].listing.quantity, 2)
check("the card is still here", "a" in wts.cards)
one.listing.quantity = 1
wts._sold("b")                      # confirmed by the patched QMessageBox
settle()
check("the last unit closes the order outright", "b" in wts.cards, False)
check("and it leaves the model too",
      [l.order_id for l in wts.listings], ["a", "c"])

print("\nfailures land on the card that caused them")
client.fail_next = "rate limited"
wts._toggle_visible("a")
settle()
check("the message is shown on the card",
      wts.cards["a"].result.text(), "rate limited")
check("and the model did NOT move",
      wts.cards["a"].listing.visible, True)

print("\nbulk visibility: nothing to do is not a failure")
wts.set_status("")
for l in wts.listings:
    l.visible = True
mark = len(client.calls)          # count from HERE, not across the whole run
wts._bulk_visibility(True)
settle()
check("it says so rather than writing three no-ops",
      "already visible" in wts.status.text())
check("and calls nothing at all", client.calls[mark:], [])

print("\nbulk visibility: only the orders that need it")
wts.listings[0].visible = False
mark = len(client.calls)
wts._bulk_visibility(True)
settle()
check("exactly one order was written - the one that needed it",
      client.calls[mark:],
      [("update", "a", wts.listings[0].platinum,
        wts.listings[0].quantity, True, None)])
check("every order is visible now",
      all(l.visible for l in wts.listings))

print("\nthe limit field: a value equal to the default is a CLEAR")
# The rule that is easy to get wrong (core/floors.py): storing an override
# equal to the derived default freezes the limit against later baseline
# movement, so it must be recorded as an absence, not as a number.
card = wts.cards["a"]
slug = card.listing.slug
auto = wts.limits.auto("a", card.listing.platinum)
card.limit.setText(str(auto))
wts._commit_limit("a")
check("typing the default clears the override",
      wts.limits.is_overridden(slug), False)
check("and the tag says auto", card.limit_mode.text(), "auto")
card.limit.setText(str(auto + 7))
wts._commit_limit("a")
check("a different value IS an override", wts.limits.is_overridden(slug))
check("and the tag says set", card.limit_mode.text(), "set")
check("prefs were saved", len(SAVED) > 0)
card.limit.setText("")
wts._commit_limit("a")
check("blank clears it again", wts.limits.is_overridden(slug), False)
card.limit.setText("not a number")
wts._commit_limit("a")
check("a non-number writes nothing", wts.limits.is_overridden(slug), False)

print("\nthe tab offset repaints every card's limit")
wts.offset.setText("+5")
wts._commit_offset()
app.processEvents()
check("the offset took", wts.limits.offset, 5)
check("the field is repainted with its sign", wts.offset.text(), "+5")
check("and every auto limit followed",
      wts.cards["a"].limit.text(),
      str(wts.limits.auto("a", wts.cards["a"].listing.platinum)))
wts.offset.setText("banana")
wts._commit_offset()
check("a non-number is rejected and the field repainted",
      (wts.limits.offset, wts.offset.text()), (5, "+5"))
wts.offset.setText("+0")
wts._commit_offset()

print("\nthe market sweep lands by order_id")
wts._market_landed(("a", 33, 7, False))
check("the model took the price", wts.cards["a"].listing.market_low, 33)
check("and the online count", wts.cards["a"].listing.online_count, 7)
# the ONLY guard a late result needs now: cards outlive every worker, so
# widget liveness is not the question - staleness is
landed_before = wts.cards["a"].listing.market_low
wts._market_landed(("gone-order-id", 10, 1, False))
check("a result for a vanished order is dropped without raising",
      wts.cards["a"].listing.market_low, landed_before)

print("\na second sweep cancels the first")
wts.start_sweep()
first = wts._sweep
check("a sweep is running", first is not None)
wts.start_sweep()
check("starting another cancels it", first.cancelled)
check("and the new one is not cancelled", wts._sweep.cancelled, False)
settle()

print("\nsearch highlights the first match in DISPLAY order")
wts.search.setText("prime")
wts._search_typed()
app.processEvents()
def highlighted():
    return [o for o, c in wts.cards.items() if th.ACCENT in c.styleSheet()]


hits = highlighted()
check("exactly one card is highlighted", len(hits), 1)
check("and it is the first in display order", hits[0], wts._order[0])
wts.search.setText("")
wts._search_typed()
app.processEvents()
check("clearing the search clears the highlight", highlighted(), [])

print("\nrefetching reconciles cards instead of rebuilding them")
kept = wts.cards["a"]
client.sell = [listing("a", "Ash Prime Set", 40, 2),
               listing("d", "Dread Set", 22, 1)]
view.refresh()
settle()
check("the surviving order kept its widget", wts.cards["a"] is kept)
check("the new order got one", "d" in wts.cards)
check("and the departed ones are gone",
      sorted(wts.cards), ["a", "d"])

print("\nthe edit dialog writes price, quantity, limit and visibility")
dlg = EditListingDialog(wts, wts.cards["a"])
dlg.price.setText("55")
dlg.qty.setText("4")
dlg.limit.setText("50")
dlg.visible.setChecked(False)
dlg._save()
settle()
l = wts.cards["a"].listing
check("the model took all four",
      (l.platinum, l.quantity, l.visible), (55, 4, False))
check("the limit became an override", wts.limits.overrides.get(l.slug), 50)
# a hand-set price becomes the new reference the auto limit hangs off,
# otherwise later defaults would still derive from the price it replaced
check("and the baseline was rebased to it", view.baseline["a"], 55)

dlg2 = EditListingDialog(wts, wts.cards["a"])
dlg2.price.setText("oops")
dlg2._save()
check("a non-numeric price is refused",
      "whole numbers" in dlg2.status.text())
check("and nothing was written", wts.cards["a"].listing.platinum, 55)
dlg2.reject()

print("\nrank: two ranks of one item are two cards with two limits")
# Cards are keyed by order_id, so this already holds structurally - what was
# missing was any way to TELL them apart, and a floor that did not know the
# difference. A rank-0 Arcane Energize and a rank-5 one are different goods at
# very different prices; one limit cannot serve both.
r0 = listing("r0", "Arcane Energize", 40, 1, slug="arcane_energize")
r5 = listing("r5", "Arcane Energize", 900, 1, slug="arcane_energize")
r0.rank, r5.rank = 0, 5
client.sell = [r0, r5, listing("p", "Ash Prime Set", 40, 1)]
view.refresh()
settle()
check("both ranks got their own card", sorted(wts.cards), ["p", "r0", "r5"])
check("and the badge tells them apart",
      [wts.cards[o].rank.text() for o in ("r0", "r5")], ["R-0", "R-5"])
check("a good that does not rank shows no badge",
      wts.cards["p"].rank.isVisible(), False)
check("rankability is read off the ORDER, not a table in this repo",
      (lvm.is_rankable(r0), lvm.is_rankable(wts.cards["p"].listing)),
      (True, False))
check("their limit keys differ", lvm.limit_key(r0) != lvm.limit_key(r5))
check("an unranked good keeps the bare slug, so nothing stored has to move",
      lvm.limit_key(wts.cards["p"].listing), "ash prime set")

wts.cards["r0"].limit.setText("30")
wts._commit_limit("r0")
check("setting one rank's floor stores it under that rank",
      wts.limits.overrides.get("arcane_energize#r0"), 30)
check("and leaves the other rank on auto",
      wts.limits.is_overridden(lvm.limit_key(r5)), False)

print("\nthe edit dialog offers a rank only where there is one")
plain = EditListingDialog(wts, wts.cards["p"])
check("no picker for a good that does not rank", plain.rank, None)
plain.reject()

dlg = EditListingDialog(wts, wts.cards["r0"])
check("a rankable order gets one", dlg.rank is not None)
check("which opens holding the current rank", dlg.rank.currentText(), "R-0")
settle()
check("and widens to the item's full range once the API answers",
      [dlg.rank.itemText(i) for i in range(dlg.rank.count())],
      [f"R-{i}" for i in range(6)])
check("without moving the selection out from under you",
      dlg.rank.currentText(), "R-0")

dlg.rank.setCurrentText("R-3")
dlg.price.setText("100")
dlg.qty.setText("1")
dlg.limit.setText("")
mark = len(client.calls)
dlg._save()
settle()
check("the rank went to the API", client.calls[mark:],
      [("update", "r0", 100, 1, True, 3)])
check("the model moved", wts.cards["r0"].listing.rank, 3)
check("the badge followed", wts.cards["r0"].rank.text(), "R-3")
# changing rank changes the limit key, so the entry the OLD rank owned has to
# go - otherwise a future R-0 order silently inherits this one's floor
check("the floor left behind at the old rank is cleared",
      "arcane_energize#r0" in wts.limits.overrides, False)

print("\nContracts shows YOUR OWN riven/lich auctions")
# The third My Listings tab reads from my_auctions (a separate fetch). Two
# things matter: the view-level refresh reaches it even while another tab is on
# top - so a freshly posted contract is already there when you switch - and it
# stands on its own once shown. It sits behind WTS in the stack, so isVisible()
# is False for reasons of ancestry; isVisibleTo(tab) reads its own show state.
from PySide6.QtWidgets import QLabel                              # noqa: E402
contracts = view.tabs["Contracts"]


def contract_texts():
    """Every label the rendered contract cards paint (whitespace trimmed - the
    price tag carries a trailing space to breathe off the number)."""
    body = contracts.area.widget()
    return [w.text().strip() for w in body.findChildren(QLabel)] if body else []


# WTS is the visible tab here, yet the view-level refresh already populated
# Contracts behind it.
check("the view refresh reached the still-hidden Contracts tab",
      contracts.area.isVisibleTo(contracts))
check("the status counts them", "2 contracts" in contracts.status.text())

view.select("Contracts")
settle()
check("selecting it fires its own showEvent", contracts._loaded)
check("its scroll area is on screen", contracts.area.isVisible())
check("and the empty notice is not", contracts.notice.isVisible(), False)
texts = contract_texts()


def stat_label(sub):
    """The rendered stat label whose text contains `sub` (for colour checks)."""
    body = contracts.area.widget()
    return next((w for w in body.findChildren(QLabel) if sub in w.text()), None)


# the two-tone title: weapon (teal) and the riven's random name (gold) are now
# separate labels, exactly as AlecaFrame draws them
check("the weapon name is shown", "Kuva Bramma" in texts)
check("and the riven's name beside it", "Visi-critacan" in texts)
check("both kind badges are drawn (uppercased)",
      all(k in texts for k in ("RIVEN", "LICH")))
check("its buyout is labelled and priced",
      "buyout" in texts and "1200" in texts)
check("the lich prices off its opening bid (no buyout)",
      "start" in texts and "150" in texts)
# the rolled stats stack down the middle with their values
check("a positive stat is formatted with its value",
      any(x.startswith("+126.4%") and "Melee Damage" in x for x in texts))
check("a negative stat is shown too", any("Zoom" in x and "50%" in x
                                          for x in texts))
# and they are colour-coded: jade for a gain, coral for a loss
gain, loss = stat_label("Melee Damage"), stat_label("Zoom")
check("a gain reads jade", gain is not None and th.OK in gain.styleSheet())
check("a loss reads coral", loss is not None and th.ERR in loss.styleSheet())
check("the lich shows its element bonus as a stat",
      any("Toxin" in x for x in texts))
# the lich is hidden - it must wear the warn tag; the riven is visible and
# must NOT, or "hidden" would read as the account-wide state
check("only the hidden auction carries the hidden tag",
      texts.count("hidden"), 1)

print("\nthe contract card is live: picture, visibility toggle, remove")
# The picture pipeline is the WTS one with a different map: weapon_thumbs()
# (rivens are not tradeable items, so /v2/items cannot supply these) feeding
# fetch_thumb. The fake serves a real 1x1 PNG, so a null pixmap here means the
# pipeline broke, not that the asset was missing.
settle()
card = contracts.cards["riv1"]
check("the thumb worker asked for the weapon map",
      ("weapon_thumbs",) in client.calls)
check("the weapon picture landed on the card",
      not card.icon.pixmap().isNull())
# the polarity name carries its wiki symbol; an element (lich) has none
check("the riven's polarity symbol is drawn",
      card.pol_icon is not None and not card.pol_icon.pixmap().isNull())
check("the lich's element gets no polarity symbol",
      contracts.cards["lic1"].pol_icon is None)

client.calls.clear()
card.vis_btn.click()
settle()
check("the eye button hides the auction on the API",
      ("auction_visibility", "riv1", False) in client.calls)
check("and the re-fetched card now wears the hidden tag",
      contract_texts().count("hidden"), 2)

# remove is destructive, so it confirms first - declining must be a no-op
contracts._confirm = lambda *a: False
client.calls.clear()
contracts.cards["riv1"].rm_btn.click()
settle()
check("declining the confirm removes nothing", client.calls, [])

contracts._confirm = lambda *a: True
contracts.cards["lic1"].rm_btn.click()
settle()
check("the trash button closes the auction on the API",
      ("auction_close", "lic1") in client.calls)
check("and the re-fetch drops the card",
      "1 contract listed" in contracts.status.text())

client.fail_next = "auction house hiccup"
contracts.cards["riv1"].vis_btn.click()
settle()
check("a failed write reports in the status line",
      "auction house hiccup" in contracts.status.text())
check("and the card is usable again", contracts.cards["riv1"].isEnabled())

print("\nthe edit dialog: price/rank relist, visibility updates in place")
# built directly and driven via _save() - exec() would open a real modal loop,
# which is exactly the headless hang the suite guards against
from PySide6.QtWidgets import QDialog                             # noqa: E402
from ui.listings import EditContractDialog                        # noqa: E402
card = contracts.cards["riv1"]          # visible=False, buyout 1200, R-8 now
dlg = EditContractDialog(contracts, card)
check("the price field holds the shown price", dlg.price.text(), "1200")
check("the rank picker opens on the current rank",
      dlg.rank is not None and dlg.rank.currentText() == "R-8")
check("the visibility box mirrors the card", dlg.visible.isChecked(), False)
client.calls.clear()
dlg.price.setText("1500")
dlg.rank.setCurrentText("R-0")
dlg.visible.setChecked(True)
dlg._save()
settle()
# a price/rank change cannot be PUT (the API 403s it) - it must RELIST,
# carrying the untouched starting price and the visibility choice along
check("a price+rank change goes through relist, not update",
      ("auction_relist", "riv1",
       {"starting": 200, "buyout": 1500, "mod_rank": 0, "visible": True})
      in client.calls)
check("the dialog closed on success", dlg.result(), QDialog.Accepted)
check("and the re-fetched card shows the server's word",
      "1500" in contract_texts())
dlg.deleteLater()

# visibility ALONE is the one thing the API updates in place
dlg = EditContractDialog(contracts, contracts.cards["riv1"])
client.calls.clear()
dlg.visible.setChecked(False)
dlg._save()
settle()
check("a visibility-only change uses the in-place update",
      ("auction_visibility", "riv1", False) in client.calls)
check("and no relist happened",
      not any(c[0] == "auction_relist" for c in client.calls))
dlg.deleteLater()

dlg = EditContractDialog(contracts, contracts.cards["riv1"])
client.calls.clear()
dlg._save()
settle()
check("an untouched dialog sends nothing", client.calls, [])
check("but still closes", dlg.result(), QDialog.Accepted)
dlg.deleteLater()

print("\nan account with no contracts shows the notice, not an empty list")
client.auctions = []
contracts.refresh()
settle()
check("the scroll area is hidden", contracts.area.isVisible(), False)
check("the notice is shown instead", contracts.notice.isVisible())
check("and the status line is cleared", contracts.status.text(), "")
# restore, so a later manual capture sees a populated tab
client.auctions = list(FakeClient().auctions)
contracts.refresh()
settle()
view.select("WTS")

print()
if fails:
    print(f"{len(fails)} FAILURES:")
    for f in fails:
        print("   ", f)
    sys.exit(1)
print("ALL QT LISTINGS CHECKS PASSED")
