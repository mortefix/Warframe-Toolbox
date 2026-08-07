"""
core/mods_db.py - the two-database mods model (R&D test app).

  * app/mods.db        IMMUTABLE truth about mods (shipped, opened read-only;
                       regenerated only by tools/modkit). Sets are SQL views.
  * <data root>/mods_player.db   PERSISTENT player state: owned/lost flags,
                       copies, current rank, timestamps, and the unknown-mod
                       catch-all. The app remembers ownership across sessions
                       and across inventory-source hiccups.

Obtain-info is deliberately absent everywhere: each mod carries a wiki_url
and the wiki owns "how do I get this" - this module never will.

Threading: NO shared connections. Every function opens its own connection
inside the calling thread and closes it in the same frame, so sqlite3's
default same-thread rule is never violated and no locking is needed. The
files are small; open cost is negligible.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from core import paths
from core import wf_inventory

MODS_DB = Path(__file__).resolve().parent.parent / "mods.db"
PLAYER_DB = paths.USERDATA / "mods_player.db"

MOD_PREFIX = "/Lotus/Upgrades/Mods/"
RIVEN_PREFIX = MOD_PREFIX + "Randomized/"

_PLAYER_SCHEMA = """
CREATE TABLE IF NOT EXISTS owned(
  mod TEXT PRIMARY KEY, owned INTEGER NOT NULL,
  copies INTEGER, ranked_instances INTEGER,
  current_rank INTEGER, max_rank_seen INTEGER,
  first_seen TEXT, last_seen TEXT, lost_at TEXT);
CREATE TABLE IF NOT EXISTS unknown_mods(
  item_type TEXT PRIMARY KEY, copies INTEGER, first_seen TEXT);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
"""


def available() -> bool:
    return MODS_DB.is_file()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _mods_conn() -> sqlite3.Connection:
    """Read-only mods.db, with the player DB attached when it exists."""
    con = sqlite3.connect(f"file:{MODS_DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    if PLAYER_DB.is_file():
        con.execute("ATTACH DATABASE ? AS player", (str(PLAYER_DB),))
    else:
        # an empty in-memory stand-in keeps every query shape identical
        con.execute("ATTACH DATABASE ':memory:' AS player")
        con.executescript(_PLAYER_SCHEMA.replace(
            "CREATE TABLE IF NOT EXISTS ",
            "CREATE TABLE IF NOT EXISTS player."))
    return con


def _player_conn() -> sqlite3.Connection:
    """Writable player DB (created with schema on first use)."""
    PLAYER_DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(PLAYER_DB))
    con.row_factory = sqlite3.Row
    con.executescript(_PLAYER_SCHEMA)
    return con


# ---- owned-state extraction + sync -------------------------------------------

def mods_from_inv(inv: dict, known: set[str] | None = None) -> dict[str, dict]:
    """{item_type: {copies, ranked_instances, best_rank}} for MODS only.
    Pure - same tolerant shape as arcane_inv's extractor; rivens excluded.

    Mods do NOT all live under /Lotus/Upgrades/Mods/: augment cards are
    /Lotus/Powersuits/..., stances /Lotus/Weapons/..., companion precepts
    /Lotus/Types/... (measured 2026-08-05: ~400 owned mods were invisible
    to a prefix filter). So membership in `known` (the mods.db universe) is
    the primary test; the prefix only admits not-yet-known mods so they can
    reach the unknown_mods catch-all."""
    out: dict[str, dict] = {}
    known = known or set()

    _NEVER = ("/Lotus/Upgrades/CosmeticEnhancers/",   # arcanes, not mods
              "/Lotus/Upgrades/Stickers/")
    _MODLIKE = (MOD_PREFIX, "/Lotus/Powersuits/", "/Lotus/Weapons/",
                "/Lotus/Types/")

    def wanted(p) -> bool:
        if not isinstance(p, str) or p.startswith(RIVEN_PREFIX):
            return False
        if p in known:
            return True     # the DB's word beats any path heuristic - e.g.
                            # Peculiar mods live under CosmeticEnhancers
        if p.startswith(_NEVER):
            return False
        return p.startswith(_MODLIKE)

    def slot(p: str) -> dict:
        return out.setdefault(p, {"copies": 0, "ranked_instances": 0,
                                  "best_rank": 0})

    for x in inv.get("RawUpgrades", []) or []:
        if not isinstance(x, dict):
            continue
        p = x.get("ItemType", "")
        if wanted(p):
            try:
                count = int(x.get("ItemCount", 1))
            except (TypeError, ValueError):
                count = 1
            slot(p)["copies"] += max(count, 0)
    for x in inv.get("Upgrades", []) or []:
        if not isinstance(x, dict):
            continue
        p = x.get("ItemType", "")
        if wanted(p):
            rank = 0
            fp = x.get("UpgradeFingerprint")
            if isinstance(fp, str):
                try:
                    rank = int(json.loads(fp).get("lvl", 0))
                except (ValueError, TypeError):
                    rank = 0
            s = slot(p)
            s["copies"] += 1
            s["ranked_instances"] += 1
            s["best_rank"] = max(s["best_rank"], rank)
    return out


def prune_known_unknowns() -> int:
    """Drop unknown_mods rows that mods.db has since learned (a DB upgrade
    can teach it a path - the Striker/BoomStick errata). Without this the
    row lingers forever: the unknown counter overstates and the obtainable
    metric's extras double-count the mod. Returns rows dropped."""
    if not PLAYER_DB.is_file():
        return 0
    known = [r["internal"] for r in _known_internals()]
    con = _player_conn()
    try:
        dropped = 0
        for i in range(0, len(known), 500):
            chunk = known[i:i + 500]
            dropped += con.execute(
                "DELETE FROM unknown_mods WHERE item_type IN (%s)"
                % ",".join("?" * len(chunk)), chunk).rowcount
        con.commit()
        return dropped
    finally:
        con.close()


def sync_owned(force: bool = False) -> dict:
    """Diff the live inventory into the player DB. Loss is only ever inferred
    from a SUCCESSFUL read - provider absence changes nothing. Returns a
    small status dict for the UI."""
    prune_known_unknowns()      # DB-vs-DB; needs no inventory read
    provider = wf_inventory.active_provider()
    if provider is None:
        return {"synced": False, "reason": "no inventory source"}
    mtime = provider.source_mtime()
    con = _player_conn()
    try:
        prev = con.execute("SELECT value FROM meta WHERE key='source_mtime'"
                           ).fetchone()
        if (not force and prev is not None and mtime is not None
                and float(prev["value"]) == float(mtime)):
            return {"synced": False, "reason": "unchanged"}
        inv = provider.read_raw()
        if not isinstance(inv, dict):
            return {"synced": False, "reason": "inventory read failed"}
        known = {r["internal"] for r in _known_internals()}
        snapshot = mods_from_inv(inv, known)
        now = _now()
        new = lost = 0
        for item, s in snapshot.items():
            row = con.execute("SELECT owned, first_seen, max_rank_seen "
                              "FROM owned WHERE mod=?", (item,)).fetchone()
            if row is None:
                new += 1
                con.execute(
                    "INSERT INTO owned VALUES (?,?,?,?,?,?,?,?,NULL)",
                    (item, 1, s["copies"], s["ranked_instances"],
                     s["best_rank"], s["best_rank"], now, now))
            else:
                if not row["owned"]:
                    new += 1
                con.execute(
                    "UPDATE owned SET owned=1, copies=?, ranked_instances=?, "
                    "current_rank=?, max_rank_seen=MAX(max_rank_seen,?), "
                    "last_seen=?, lost_at=NULL WHERE mod=?",
                    (s["copies"], s["ranked_instances"], s["best_rank"],
                     s["best_rank"], now, item))
            if item not in known:
                con.execute(
                    "INSERT INTO unknown_mods VALUES (?,?,?) "
                    "ON CONFLICT(item_type) DO UPDATE SET copies=excluded"
                    ".copies", (item, s["copies"], now))
        gone = con.execute(
            "SELECT mod FROM owned WHERE owned=1").fetchall()
        for row in gone:
            if row["mod"] not in snapshot:
                lost += 1
                con.execute("UPDATE owned SET owned=0, lost_at=? WHERE mod=?",
                            (now, row["mod"]))
        for k, v in (("schema_version", "1"), ("last_sync", now),
                     ("provider", provider.name),
                     ("source_mtime", str(mtime if mtime is not None else 0))):
            con.execute("INSERT INTO meta VALUES (?,?) ON CONFLICT(key) "
                        "DO UPDATE SET value=excluded.value", (k, v))
        con.commit()
        return {"synced": True, "new": new, "lost": lost,
                "provider": provider.name}
    finally:
        con.close()


def _known_internals():
    con = sqlite3.connect(f"file:{MODS_DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        return con.execute("SELECT internal FROM mods").fetchall()
    finally:
        con.close()


# ---- queries ------------------------------------------------------------------

def set_list() -> list[tuple[str, str]]:
    con = _mods_conn()
    try:
        rows = con.execute("SELECT key, label FROM set_defs").fetchall()
        return [(r["key"], r["label"]) for r in rows]
    finally:
        con.close()


def facets() -> dict:
    con = _mods_conn()
    try:
        def col(name):
            return [r[0] for r in con.execute(
                f"SELECT DISTINCT {name} FROM mods WHERE {name} IS NOT NULL "
                f"ORDER BY 1")]
        return {"compat": col("compat"), "polarity": col("polarity"),
                "rarity": col("rarity")}
    finally:
        con.close()


_SORTS = {
    "name": "m.name",
    "drain": "m.base_drain DESC, m.name",
    "unowned": "(o.owned IS NOT NULL AND o.owned = 1), m.name",
}


def query_mods(q: str = "", set_key: str = "", compat: str = "",
               polarity: str = "", rarity: str = "", hide_owned: bool = False,
               sort: str = "name", limit: int = 300) -> tuple[list[dict], int]:
    """(rows, total_matches). Overlap-aware set filter via set_members;
    owned columns joined from the player DB.

    Ownership is resolved per canon GROUP, not per exact path (the owner
    ruling: DE data twins merge - see build_index.py and _OWNED_CANON).
    The inventory holds whichever twin path DE ships; both rows must show
    that ownership, or the canonical twin renders as unowned."""
    where, params = [], []
    joins = [
        "LEFT JOIN canon_map cm ON cm.mod = m.internal",
        "LEFT JOIN (SELECT c.canon AS canon, MAX(o.owned) AS owned, "
        "MAX(o.current_rank) AS current_rank, SUM(o.copies) AS copies, "
        "MAX(o.lost_at) AS lost_at FROM player.owned o "
        "JOIN canon_map c ON c.mod = o.mod GROUP BY c.canon) o "
        "ON o.canon = cm.canon",
    ]
    if set_key:
        joins.append("JOIN set_members sm ON sm.mod = m.internal "
                     "AND sm.set_key = ?")
        params.append(set_key)
    if q:
        where.append("m.name LIKE ? ESCAPE '\\'")
        params.append("%" + q.replace("\\", "\\\\").replace("%", "\\%")
                      .replace("_", "\\_") + "%")
    for colname, val in (("compat", compat), ("polarity", polarity),
                         ("rarity", rarity)):
        if val:
            where.append(f"m.{colname} = ?")
            params.append(val)
    if hide_owned:
        where.append("(o.owned IS NULL OR o.owned = 0)")
    sql_where = (" WHERE " + " AND ".join(where)) if where else ""
    order = _SORTS.get(sort, _SORTS["name"])
    body = f"FROM mods m {' '.join(joins)}{sql_where}"
    con = _mods_conn()
    try:
        total = con.execute(f"SELECT COUNT(*) {body}", params).fetchone()[0]
        rows = con.execute(
            f"SELECT m.*, o.owned AS owned, o.current_rank AS current_rank, "
            f"o.copies AS owned_copies, o.lost_at AS lost_at "
            f"{body} ORDER BY {order} LIMIT ?", params + [limit]).fetchall()
        return [dict(r) for r in rows], total
    finally:
        con.close()


#: headline sets for the Coverage card (syndicate shops are appended
#: dynamically - Daniel tracks his 4/6 augment-shop clears)
_COVERAGE_SETS = ("corrupted", "primed", "galvanized", "arbitration",
                  "conclave")

#: a canonical mod-group counts as owned when ANY of its variants is owned
_OWNED_CANON = ("EXISTS (SELECT 1 FROM canon_map c JOIN player.owned o "
                "ON o.mod = c.mod WHERE c.canon = m.internal AND o.owned = 1)")

#: obtainable in game TODAY (owner ruling 2026-08-07): not archived, not a
#: legacy fusion core, no curated unobtainable_reason. The single source for
#: the headline "x / total obtainable +N retired" stat.
_OBTAINABLE = ("m.archived = 0 AND m.legacy = 0 "
               "AND m.unobtainable_reason IS NULL")


def counts() -> dict:
    """Completion metrics per the owner's rulings: variants merge into their
    canonical mod, archived mods are excluded from completion entirely, and
    charge-based 'ranks' (requiem/antique) never count as rank progress."""
    con = _mods_conn()
    try:
        one = lambda sql: con.execute(sql).fetchone()[0]  # noqa: E731
        canon = "FROM mods m WHERE m.variant_of IS NULL AND m.archived=0"
        out = {
            "total_known": one(f"SELECT COUNT(*) {canon}"),
            "owned": one(f"SELECT COUNT(*) {canon} AND {_OWNED_CANON}"),
            "lost": one(
                f"SELECT COUNT(*) {canon} AND NOT {_OWNED_CANON} AND EXISTS "
                "(SELECT 1 FROM canon_map c JOIN player.owned o "
                "ON o.mod = c.mod WHERE c.canon = m.internal)"),
            "copies": one("SELECT COALESCE(SUM(copies),0) FROM player.owned "
                          "WHERE owned=1"),
            "ranked": one("SELECT COALESCE(SUM(ranked_instances),0) "
                          "FROM player.owned WHERE owned=1"),
            # flat-rank mods (max_rank=0) can never rank up, and charge-based
            # mods (requiem/antique) 'rank' by depleting charges - neither
            # counts as unranked/not-maxed
            "unranked_owned": one(
                "SELECT COUNT(*) FROM player.owned o JOIN mods m "
                "ON m.internal=o.mod WHERE o.owned=1 AND o.current_rank=0 "
                "AND m.max_rank > 0 AND m.charge_based=0 AND m.archived=0"),
            "not_maxed": one(
                "SELECT COUNT(*) FROM player.owned o JOIN mods m "
                "ON m.internal=o.mod WHERE o.owned=1 AND m.max_rank "
                "IS NOT NULL AND o.current_rank < m.max_rank "
                "AND m.charge_based=0 AND m.archived=0"),
            "unknown": one("SELECT COUNT(*) FROM player.unknown_mods"),
            # the headline stat: completion over what the game still offers,
            # plus the retired extras the player holds anyway. Unknown paths
            # count as extras: everything mods.db knows IS in mods.db, so an
            # unknown is either a retired ghost (Volt ability cards) or a
            # brand-new mod awaiting a DB regen - visible via "unknown".
            "obtainable_total": one(
                "SELECT COUNT(*) FROM mods m WHERE m.variant_of IS NULL "
                f"AND {_OBTAINABLE}"),
            "obtainable_owned": one(
                "SELECT COUNT(*) FROM mods m WHERE m.variant_of IS NULL "
                f"AND {_OBTAINABLE} AND {_OWNED_CANON}"),
            "extras_owned": one(
                "SELECT COUNT(*) FROM mods m WHERE m.variant_of IS NULL "
                f"AND NOT ({_OBTAINABLE}) AND {_OWNED_CANON}")
                + one("SELECT COUNT(*) FROM player.unknown_mods"),
        }
        cov = {}
        syn_keys = [r["key"] for r in con.execute(
            "SELECT key FROM set_defs WHERE key LIKE 'syn_%' ORDER BY key")]
        for key in list(_COVERAGE_SETS) + syn_keys:
            row = con.execute(
                f"SELECT COUNT(*), SUM(CASE WHEN {_OWNED_CANON} THEN 1 "
                f"ELSE 0 END) FROM set_members sm JOIN mods m "
                f"ON m.internal = sm.mod WHERE sm.set_key = ? "
                f"AND m.variant_of IS NULL AND m.archived = 0",
                (key,)).fetchone()
            cov[key] = (row[1] or 0, row[0])
        out["coverage"] = cov
        meta = {}
        for r in con.execute("SELECT key, value FROM player.meta"):
            meta[r["key"]] = r["value"]
        out["meta"] = meta
        return out
    finally:
        con.close()


def run_select(sql: str, limit: int = 200) -> dict:
    """The demo query console: a single read-only SELECT/WITH statement.
    The read-only connection is the real enforcement; this guard just gives
    friendlier errors."""
    stripped = sql.strip().rstrip(";")
    if ";" in stripped:
        return {"error": "one statement at a time", "cols": [], "rows": []}
    if not stripped.lower().startswith(("select", "with")):
        return {"error": "SELECT/WITH queries only", "cols": [], "rows": []}
    con = _mods_conn()
    try:
        cur = con.execute(stripped)
        cols = [d[0] for d in cur.description or []]
        rows = [list(r) for r in cur.fetchmany(limit)]
        return {"error": None, "cols": cols, "rows": rows}
    except sqlite3.Error as exc:
        return {"error": str(exc), "cols": [], "rows": []}
    finally:
        con.close()
