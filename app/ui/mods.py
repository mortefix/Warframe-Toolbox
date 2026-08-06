"""Mods (R&D test app): query the two-database mod model.

THROWAWAY by design - this view exists to exercise core.mods_db (immutable
mods.db + persistent player DB) and demonstrate set-based querying before
the real mods helper app is designed. Player data on top, query bar in the
middle, a results table, a live read-only SQL console, and placeholder
buttons for the features the real app will grow.

Removal = this file + one NavItem in core/nav.py + one branch in
ui/app.py._build (+ app/mods.db and the player DB).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QFrame, QGridLayout, QHBoxLayout,
                               QLineEdit, QPushButton, QScrollArea,
                               QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from core import mods_db
from core import theme as t
from ui import work
from ui.widgets import Dropdown, hairline, label, panel, polarity_icon

_COLUMNS = ("Owned", "Name", "Sets", "Compat", "Polarity", "Rarity",
            "Drain", "Rank")


class ModsView(QWidget):
    def __init__(self, open_wiki, open_overframe=None) -> None:
        super().__init__()
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._open_wiki = open_wiki
        self._open_overframe = open_overframe
        self._job = None
        self._serial = 0
        self._row_urls: list[str] = []
        self._row_of: list[int | None] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll, 1)

        frame = QWidget()
        frame.setAttribute(Qt.WA_StyledBackground, True)
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(t.SP_SCREEN, t.SP_XL, t.SP_SCREEN, t.SP_XL)
        lay.setSpacing(t.SP_LG)
        scroll.setWidget(frame)

        if not mods_db.available():
            box = panel("card")
            bl = QVBoxLayout(box)
            bl.setContentsMargins(t.SP_XL, t.SP_XL, t.SP_XL, t.SP_XL)
            bl.addWidget(label("Mod database not built", role="h2"))
            bl.addWidget(label("Run tools/modkit/fetch_wiki.py and "
                               "build_index.py, then reopen this app.",
                               role="muted"))
            lay.addWidget(box)
            lay.addStretch(1)
            return

        # -- player data cards ------------------------------------------------
        lay.addWidget(label("Player Data", role="h1"))
        cards = QGridLayout()
        cards.setSpacing(t.SP_MD)
        self._cards: dict[str, tuple] = {}
        for i, (key, title) in enumerate((
                ("owned", "Owned"), ("progress", "Progress"),
                ("lost", "Lost"), ("unknown", "Unknown"),
                ("coverage", "Coverage"), ("source", "Source"))):
            box = panel("card")
            bl = QVBoxLayout(box)
            bl.setContentsMargins(t.SP_LG, t.SP_MD, t.SP_LG, t.SP_MD)
            bl.setSpacing(t.SP_SM)
            bl.addWidget(label(title, role="h2"))
            body = label("—", role="small")
            body.setWordWrap(True)
            bl.addWidget(body)
            bl.addStretch(1)
            cards.addWidget(box, i // 3, i % 3)
            self._cards[key] = (box, body)
        lay.addLayout(cards)

        # -- query bar ---------------------------------------------------------
        lay.addWidget(label("Query", role="h1"))
        bar = panel("card")
        bar_l = QVBoxLayout(bar)
        bar_l.setContentsMargins(t.SP_LG, t.SP_MD, t.SP_LG, t.SP_MD)
        bar_l.setSpacing(t.SP_MD)

        row1 = QHBoxLayout()
        row1.setSpacing(t.SP_MD)
        self.search = QLineEdit()
        self.search.setPlaceholderText("search mods by name…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._requery)
        row1.addWidget(self.search, 1)
        self.hide_owned = QCheckBox("Hide owned")
        self.hide_owned.toggled.connect(self._requery)
        row1.addWidget(self.hide_owned)
        self.sort = Dropdown()
        for label_, key in (("Sort: name", "name"), ("Sort: drain", "drain"),
                            ("Sort: unowned first", "unowned")):
            self.sort.addItem(label_, key)
        self.sort.currentIndexChanged.connect(self._requery)
        row1.addWidget(self.sort)
        refresh = QPushButton("↻ Refresh data")
        refresh.clicked.connect(self._sync)
        row1.addWidget(refresh)
        bar_l.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(t.SP_MD)
        self.set_pick = Dropdown()
        self.set_pick.addItem("All sets", "")
        for key, label_ in mods_db.set_list():
            self.set_pick.addItem(label_, key)
        self.set_pick.currentIndexChanged.connect(self._requery)
        row2.addWidget(self.set_pick)
        facets = mods_db.facets()
        self.compat = Dropdown()
        self.compat.addItem("Any compat", "")
        for v in facets["compat"]:
            self.compat.addItem(str(v), v)
        self.compat.currentIndexChanged.connect(self._requery)
        row2.addWidget(self.compat)
        self.polarity = Dropdown()
        self.polarity.addItem("Any polarity", "")
        for v in facets["polarity"]:
            self.polarity.addItem(str(v), v)
        self.polarity.currentIndexChanged.connect(self._requery)
        row2.addWidget(self.polarity)
        self.rarity = Dropdown()
        self.rarity.addItem("Any rarity", "")
        for v in facets["rarity"]:
            self.rarity.addItem(str(v), v)
        self.rarity.currentIndexChanged.connect(self._requery)
        row2.addWidget(self.rarity)
        row2.addStretch(1)
        bar_l.addLayout(row2)
        lay.addWidget(bar)

        self.result_note = label("", role="muted")
        lay.addWidget(self.result_note)

        # -- results table -----------------------------------------------------
        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setMinimumHeight(t.SP_SCREEN * 14)
        self.table.itemDoubleClicked.connect(self._open_row_wiki)
        lay.addWidget(self.table)
        lay.addWidget(label("Double-click a row to open the mod's wiki page "
                            "(latest acquisition info lives there).",
                            role="small"))

        # -- SQL console (live demo of sets-as-queries) ------------------------
        lay.addWidget(hairline())
        lay.addWidget(label("Query Console (read-only SELECT — try: SELECT "
                            "name FROM set_arbitration)", role="h2"))
        con_row = QHBoxLayout()
        con_row.setSpacing(t.SP_MD)
        self.sql = QLineEdit()
        self.sql.setPlaceholderText("SELECT name FROM set_corrupted "
                                    "ORDER BY name")
        self.sql.returnPressed.connect(self._run_sql)
        con_row.addWidget(self.sql, 1)
        run = QPushButton("Run")
        run.clicked.connect(self._run_sql)
        con_row.addWidget(run)
        lay.addLayout(con_row)

        # -- feature buttons (one real: Overframe builds deep link) -----------
        btns = QHBoxLayout()
        btns.setSpacing(t.SP_MD)
        of_btn = QPushButton("Builds (Overframe)")
        of_btn.setToolTip("Open the selected mod's Overframe page in the "
                          "embedded Overframe tab")
        of_btn.clicked.connect(self._open_row_overframe)
        btns.addWidget(of_btn)
        for text in ("Complete this set", "Export list", "Price check",
                     "Set relations…"):
            b = QPushButton(text)
            b.clicked.connect(self._planned)
            btns.addWidget(b)
        btns.addStretch(1)
        lay.addLayout(btns)
        self.status = label("", role="muted")
        lay.addWidget(self.status)
        lay.addStretch(1)

        self._requery()
        self._refresh_cards()
        # The Qt shell has no on_show hook (pages persist in the stack), so
        # the inventory sync runs once at build + on the Refresh button.
        self._sync()

    # -- background sync + cards ---------------------------------------------

    def _sync(self) -> None:
        self.status.setText("syncing inventory…")
        self._job = work.run(mods_db.sync_owned, self._synced)

    def _synced(self, result: dict) -> None:
        if result.get("synced"):
            self.status.setText(
                f"synced from {result.get('provider', '?')}: "
                f"{result.get('new', 0)} newly owned, "
                f"{result.get('lost', 0)} lost")
        else:
            self.status.setText(f"sync skipped: {result.get('reason', '?')}")
        self._refresh_cards()
        self._requery()

    def _refresh_cards(self) -> None:
        self._cards_job = work.run(mods_db.counts, self._cards_done)

    def _cards_done(self, c: dict) -> None:
        owned, total = c["owned"], c["total_known"]
        self._set_card("owned", f"{owned} / {total} distinct mods\n"
                                f"{c['copies']} copies · {c['ranked']} ranked "
                                f"instances")
        self._set_card("progress", f"{c['unranked_owned']} owned but unranked"
                                   f"\n{c['not_maxed']} not at max rank")
        self._set_card("lost", f"{c['lost']} previously owned, now missing")
        self._set_card("unknown", f"{c['unknown']} inventory mods the "
                                  f"database doesn't know")
        cov = "\n".join(f"{k}: {a}/{b}"
                        for k, (a, b) in c.get("coverage", {}).items())
        self._set_card("coverage", cov or "—")
        meta = c.get("meta", {})
        self._set_card("source", f"provider: {meta.get('provider', '—')}\n"
                                 f"last sync: {meta.get('last_sync', '—')}")

    def _set_card(self, key: str, text: str) -> None:
        self._cards[key][1].setText(text)

    # -- querying --------------------------------------------------------------

    def _requery(self) -> None:
        self._serial += 1
        serial = self._serial
        args = dict(q=self.search.text().strip(),
                    set_key=self.set_pick.currentData() or "",
                    compat=self.compat.currentData() or "",
                    polarity=self.polarity.currentData() or "",
                    rarity=self.rarity.currentData() or "",
                    hide_owned=self.hide_owned.isChecked(),
                    sort=self.sort.currentData() or "name")
        self._query_job = work.run(lambda: (serial,
                                            mods_db.query_mods(**args)),
                                   self._queried)

    def _queried(self, payload) -> None:
        serial, (rows, total) = payload
        if serial != self._serial:
            return                        # a newer query superseded this one
        self._fill_table(rows)
        shown = len(rows)
        self.result_note.setText(
            f"{total} matches" + (f" — showing first {shown}"
                                  if shown < total else ""))

    def _fill_table(self, rows: list[dict]) -> None:
        # restore the standard columns (the SQL console reshapes the table)
        self.table.setColumnCount(len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setRowCount(len(rows))
        self._row_urls = []
        self._row_of = []
        for i, r in enumerate(rows):
            self._row_urls.append(r.get("wiki_url") or "")
            self._row_of.append(r.get("of_id"))
            owned = r.get("owned")
            mark = "✔" if owned == 1 else ("lost" if owned == 0 else "")
            rank = ""
            if r.get("max_rank") is not None:
                cur = r.get("current_rank")
                rank = (f"{cur}/{r['max_rank']}" if owned == 1
                        and cur is not None else f"—/{r['max_rank']}")
            values = (mark, r.get("name") or "", r.get("display_set") or "",
                      r.get("compat") or "", r.get("polarity") or "",
                      r.get("rarity") or "", str(r.get("base_drain") or ""),
                      rank)
            for col, val in enumerate(values):
                item = QTableWidgetItem(val)
                if col == 4 and val:
                    pm = polarity_icon(val)
                    if pm is not None:
                        item.setData(Qt.DecorationRole, pm)
                self.table.setItem(i, col, item)
        self.table.resizeColumnsToContents()

    def _open_row_wiki(self, item) -> None:
        row = item.row()
        if 0 <= row < len(self._row_urls) and self._row_urls[row]:
            self._open_wiki(self._row_urls[row])

    def _open_row_overframe(self) -> None:
        row = self.table.currentRow()
        if not (0 <= row < len(self._row_of)):
            self.status.setText("Select a mod row first.")
            return
        of_id = self._row_of[row]
        if of_id is None:
            self.status.setText("No Overframe page recorded for this mod "
                                "(added after the id snapshot).")
            return
        if self._open_overframe is None:
            self.status.setText("Overframe tab unavailable.")
            return
        self._open_overframe(f"https://overframe.gg/items/arsenal/{of_id}/")

    # -- console + placeholders ------------------------------------------------

    def _run_sql(self) -> None:
        sql = self.sql.text().strip()
        if not sql:
            return
        self._sql_job = work.run(lambda: mods_db.run_select(sql),
                                 self._sql_done)

    def _sql_done(self, result: dict) -> None:
        if result["error"]:
            self.result_note.setText(f"query error: {result['error']}")
            return
        cols = result["cols"] or ["(no columns)"]
        self.table.setColumnCount(len(cols))
        self.table.setHorizontalHeaderLabels([str(c) for c in cols])
        self.table.setRowCount(len(result["rows"]))
        self._row_urls = []
        for i, row in enumerate(result["rows"]):
            for j, val in enumerate(row):
                self.table.setItem(i, j, QTableWidgetItem(
                    "" if val is None else str(val)))
        self.table.resizeColumnsToContents()
        self.result_note.setText(f"console: {len(result['rows'])} rows "
                                 "(double-click disabled for console results)")

    def _planned(self) -> None:
        self.status.setText("Planned — not implemented in the test app.")
