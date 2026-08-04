"""Render a single ListingCard in isolation (no wf.market session needed) and
grab it, for the item-card cascade before/after proof. Also prints the current
sizeHint-derived sizes. Scale via QT_SCALE_FACTOR = target/3 (see tools/shot.py).
Usage: QT_SCALE_FACTOR=1.0 python tools/card_shot.py out.png
"""
import os, sys
os.environ.pop("QT_QPA_PLATFORM", None)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

out = sys.argv[1] if len(sys.argv) > 1 else "card.png"
from PySide6.QtGui import QFontDatabase
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QVBoxLayout
app = QApplication(sys.argv[:1])
from core import theme as t
from core.market import Listing
from core import listings_vm as vm
from ui import qss
app.setStyleSheet(qss.build(set(QFontDatabase.families())))
from ui.listings import ListingCard
from ui.widgets import panel

listing = Listing(order_id="o1", slug="ash_prime_set", name="Ash Prime Set",
                  platinum=45, quantity=3, visible=True, updated="just now",
                  rank=None, market_low=40, online_count=7)
card = ListingCard(listing, vm.SIDES["sell"])
card.setFixedWidth(520)
host = panel("app")
lay = QVBoxLayout(host)
lay.setContentsMargins(24, 24, 24, 24)
lay.addWidget(card)
lay.addStretch(1)
host.show(); host.setWindowState(Qt.WindowNoState); host.resize(568, 300)
for _ in range(30):
    app.processEvents()
img = host.grab(); img.save(out)
print(f"saved {out}  dpr={host.devicePixelRatioF():.2f} grab={img.width()}x{img.height()}")
print(f"MEASURE  H(up.height)={card.up.sizeHint().height()}  "
      f"wide(up.width)={card.up.sizeHint().width()}  icon_w(H+6)={card.up.sizeHint().height()+6}")
