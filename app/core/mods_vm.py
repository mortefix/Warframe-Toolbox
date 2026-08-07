"""core/mods_vm.py - the player-facing collection lenses over mods_db.

The R&D Mods view (Settings > DevTools > Mods DB) exposes the database; the
player-facing Mods app speaks in COLLECTIONS: "how far along is my Shotgun
shelf, my Augur set, my Primed gallery?" This module owns every one of those
derivations so the view (ui/mods_shade) is pure placement:

  * ARSENAL     - weapon/gear buckets a player thinks in (Warframe, Primary,
                  Shotgun, Secondary, Melee, ...). Defined over compat and
                  mod_type; deliberately NO single-weapon/-frame compat
                  lenses (owner ruling: a 1-5 mod list is not a category).
  * COLLECTIONS - the named hunts (Primed, Galvanized, Corrupted, ...),
                  straight from mods.db set_defs.
  * mod SETS    - the bonus_* wearable sets (Augur, Gladiator, ...), the
                  headline request: small, completable, satisfying.
  * trophies    - owned-but-retired mods (and the unknown legacy ghosts):
                  the cabinet's back shelf.

All counts run over CANONICAL, OBTAINABLE mods (variants merge; retired
mods live only in the trophy lens), and every listing row carries what a
panel needs: name, image filename, ownership, rank, rarity, polarity,
wiki_url, of_id, tradable.

Price checks go through the host's MarketClient (one mod at a time - the
owner ruling is a per-mod button, never a 1600-mod sweep).
"""

from __future__ import annotations

import json
import re
from typing import NamedTuple

from core.mods_db import _mods_conn, _OBTAINABLE, _OWNED_CANON


class Lens(NamedTuple):
    key: str
    label: str
    where: str          # SQL fragment over alias m (constants only, no input)


#: weapon/gear buckets, in the order a player scans their arsenal
ARSENAL: tuple[Lens, ...] = (
    Lens("warframe",  "Warframe",   "m.compat = 'WARFRAME'"),
    Lens("aura",      "Auras",      "m.mod_type = 'aura'"),
    Lens("primary",   "Primary",
         "m.mod_type = 'primary' AND m.compat != 'Shotgun'"),
    Lens("shotgun",   "Shotgun",    "m.compat = 'Shotgun'"),
    Lens("sniper",    "Sniper",     "m.compat = 'Sniper'"),
    Lens("secondary", "Secondary",  "m.compat = 'Pistol'"),
    Lens("melee",     "Melee",      "m.mod_type = 'melee'"),
    Lens("stance",    "Stances",    "m.mod_type = 'stance'"),
    Lens("tennokai",  "Tennokai",
         "m.internal LIKE '%/EmpoweredHeavyMelee/%'"),
    Lens("companion", "Companions",
         "m.mod_type IN ('sentinel','kavat','kubrow','helminth charger')"),
    Lens("archwing",  "Archwing",
         "m.mod_type IN ('archwing','arch-gun','arch-melee')"),
    Lens("necramech", "Necramech",  "m.compat = 'Necramech'"),
    Lens("railjack",  "Railjack",
         "m.compat IN ('Plexus','Railjack Aura')"),
    Lens("kdrive",    "K-Drive",    "m.compat = 'K-Drive'"),
    Lens("parazon",   "Parazon",    "m.mod_type = 'parazon'"),
    Lens("exilus",    "Exilus",     "m.exilus = 1"),
    Lens("augments",  "Augments",
         "EXISTS (SELECT 1 FROM set_members sa WHERE sa.mod = m.internal "
         "AND sa.set_key = 'augments')"),
)

#: the named hunts, curated order (set_defs keys); syn_* appended dynamically
_COLLECTION_KEYS = (
    "primed", "corrupted", "acolyte", "nightmare", "arbitration",
    "nightwave", "antique", "flawed", "conclave",
)

#: named groups that read as SETS to the player (owner ruling 2026-08-07),
#: listed with the wearable bonus_* sets rather than in the collections
_SET_EXTRA_KEYS = ("galvanized", "amalgam", "archon", "bond", "requiem",
                   "lua_drift")

#: antivirus has no set_defs row; it is a path-classified group (see
#: parazon_class), so it gets its own lens fragment
_ANTIVIRUS_WHERE = ("(m.internal LIKE '%/Immortal/Antivirus%' OR "
                    "m.internal LIKE '%/DataSpike/Potency/GainAntivirus%')")

#: every mod ANY syndicate sells - the aggregate the collections ledger
#: shows (the per-syndicate syn_* sets stay in the data for tooling)
_SYNDICATE_WHERE = ("EXISTS (SELECT 1 FROM set_members sy "
                    "WHERE sy.mod = m.internal "
                    "AND sy.set_key LIKE 'syn\\_%' ESCAPE '\\')")

_CANON = "m.variant_of IS NULL"


def _rows(sql: str, params: tuple = ()) -> list[dict]:
    con = _mods_conn()
    try:
        return [dict(r) for r in con.execute(sql, params)]
    finally:
        con.close()


def _progress_where(where: str) -> tuple[int, int]:
    base = f"FROM mods m WHERE {_CANON} AND {_OBTAINABLE} AND ({where})"
    con = _mods_conn()
    try:
        total = con.execute(f"SELECT COUNT(*) {base}").fetchone()[0]
        owned = con.execute(
            f"SELECT COUNT(*) {base} AND {_OWNED_CANON}").fetchone()[0]
        return owned, total
    finally:
        con.close()


def arsenal_progress() -> list[dict]:
    """[{key, label, owned, total}] for every arsenal bucket."""
    return [{"key": c.key, "label": c.label,
             **dict(zip(("owned", "total"), _progress_where(c.where)))}
            for c in ARSENAL]


def _set_where(set_key: str) -> str:
    # set_key values come from set_defs (or the constants above), never from
    # user text; the shelf() search term IS parameterised.
    return ("EXISTS (SELECT 1 FROM set_members sx WHERE sx.mod = m.internal "
            f"AND sx.set_key = '{set_key}')")


def collections_progress() -> list[dict]:
    """The named hunts + syndicate shops, each with owned/total."""
    defs = {r["key"]: r["label"] for r in
            _rows("SELECT key, label FROM set_defs")}
    keys = [k for k in _COLLECTION_KEYS if k in defs]
    out = []
    for k in keys:
        owned, total = _progress_where(_set_where(k))
        if total:
            out.append({"key": f"set:{k}", "label": defs[k],
                        "owned": owned, "total": total})
    owned, total = _progress_where(_SYNDICATE_WHERE)
    if total:
        out.append({"key": "syndicate", "label": "Syndicate",
                    "owned": owned, "total": total})
    for k in sorted(k for k in defs if k.startswith("syn_")):
        owned, total = _progress_where(_set_where(k))
        if total:
            out.append({"key": f"set:{k}", "label": defs[k],
                        "owned": owned, "total": total})
    return out


def set_progress() -> list[dict]:
    """The mod sets: the wearable bonus_* sets (Augur, Gladiator, ...) plus
    the named groups that read as sets (_SET_EXTRA_KEYS) and the
    path-classified Antivirus group - each with owned/total, alphabetical
    by label."""
    defs = {r["key"]: r["label"] for r in
            _rows("SELECT key, label FROM set_defs")}
    out = []
    for k in ([k for k in defs if k.startswith("bonus_")]
              + [k for k in _SET_EXTRA_KEYS if k in defs]):
        owned, total = _progress_where(_set_where(k))
        if total:
            out.append({"key": f"set:{k}", "label": defs[k],
                        "owned": owned, "total": total})
    owned, total = _progress_where(_ANTIVIRUS_WHERE)
    if total:
        out.append({"key": "antivirus", "label": "Antivirus",
                    "owned": owned, "total": total})
    out.sort(key=lambda s: s["label"].lower())
    return out


def _lens_where(key: str) -> str:
    if key.startswith("set:"):
        return _set_where(key[4:])
    if key == "antivirus":
        return _ANTIVIRUS_WHERE
    if key == "syndicate":
        return _SYNDICATE_WHERE
    for c in ARSENAL:
        if c.key == key:
            return c.where
    raise KeyError(f"unknown lens {key!r}")


_ROW_COLS = ("m.internal, m.name, m.image, m.rarity, m.polarity, "
             "m.base_drain, m.max_rank, m.tradable, m.wiki_url, m.of_id, "
             "o.owned AS owned, o.current_rank AS current_rank")

_OWNED_JOIN = (
    "LEFT JOIN canon_map cm ON cm.mod = m.internal "
    "LEFT JOIN (SELECT c.canon AS canon, MAX(o.owned) AS owned, "
    "MAX(o.current_rank) AS current_rank FROM player.owned o "
    "JOIN canon_map c ON c.mod = o.mod GROUP BY c.canon) o "
    "ON o.canon = cm.canon")


def shelf(key: str, q: str = "", unowned_only: bool = False,
          limit: int = 400) -> list[dict]:
    """The mods on one lens's shelf, owned first then A-Z. `q` searches
    within the lens (the single-searchbar ruling: search narrows whatever
    is already open, no query language)."""
    where = [_CANON, _OBTAINABLE, f"({_lens_where(key)})"]
    params: list = []
    if q:
        where.append("m.name LIKE ? ESCAPE '\\'")
        params.append("%" + q.replace("\\", "\\\\").replace("%", "\\%")
                      .replace("_", "\\_") + "%")
    if unowned_only:
        where.append("(o.owned IS NULL OR o.owned = 0)")
    return _rows(
        f"SELECT {_ROW_COLS} FROM mods m {_OWNED_JOIN} "
        f"WHERE {' AND '.join(where)} "
        "ORDER BY (o.owned IS NOT NULL AND o.owned = 1) DESC, m.name "
        "LIMIT ?", tuple(params) + (limit,))


def search_all(q: str, limit: int = 400) -> list[dict]:
    """Search with no lens open - the whole obtainable catalogue."""
    esc = ("%" + q.replace("\\", "\\\\").replace("%", "\\%")
           .replace("_", "\\_") + "%")
    return _rows(
        f"SELECT {_ROW_COLS} FROM mods m {_OWNED_JOIN} "
        f"WHERE {_CANON} AND {_OBTAINABLE} AND m.name LIKE ? ESCAPE '\\' "
        "ORDER BY (o.owned IS NOT NULL AND o.owned = 1) DESC, m.name "
        "LIMIT ?", (esc, limit))


def trophies() -> list[dict]:
    """Owned-but-retired canonicals - the trophy shelf. Unknown legacy paths
    (the ability cards) are appended as name-only ghosts."""
    rows = _rows(
        f"SELECT {_ROW_COLS}, m.archived, m.legacy, m.unobtainable_reason "
        f"FROM mods m {_OWNED_JOIN} "
        f"WHERE {_CANON} AND NOT ({_OBTAINABLE}) "
        "AND o.owned = 1 ORDER BY m.name")
    ghosts = _rows("SELECT item_type FROM player.unknown_mods "
                   "ORDER BY item_type")
    for g in ghosts:
        raw = g["item_type"].rsplit("/", 1)[-1]
        stem = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", raw)   # OverloadAbilityCard

        rows.append({"internal": g["item_type"], "name": stem, "image": None,
                     "rarity": None, "polarity": None, "base_drain": None,
                     "max_rank": None, "tradable": 0, "wiki_url": "",
                     "of_id": None, "owned": 1, "current_rank": None,
                     "archived": 1, "legacy": 1, "unobtainable_reason":
                     "Not in any current game data (legacy item)."})
    return rows


def totals() -> dict:
    """The headline numbers (delegates to mods_db.counts, trimmed to what
    the player-facing headers show). `rivens` rides along from the live
    inventory; it counts toward NOTHING - it is display only."""
    from core import mods_db
    c = mods_db.counts()
    return {"owned": c["obtainable_owned"], "total": c["obtainable_total"],
            "extras": c["extras_owned"], "rivens": riven_count()}


# ---- rivens -----------------------------------------------------------------
# Rivens are NOT mods.db rows: each is a per-player roll living only in the
# inventory (mods_db excludes RIVEN_PREFIX from sync on purpose). This lens
# reads them straight from the provider, renders them as card rows, and
# counts them toward no completion metric (owner ruling).

#: ItemType tail -> riven family (the in-game card's weapon class)
RIVEN_FAMILY = {
    "LotusRifleRandomModRare":         "Rifle",
    "LotusShotgunRandomModRare":       "Shotgun",
    "LotusPistolRandomModRare":        "Pistol",
    "PlayerMeleeWeaponRandomModRare":  "Melee",
    "LotusModularPistolRandomModRare": "Kitgun",
    "LotusModularMeleeRandomModRare":  "Zaw",
    "LotusArchgunRandomModRare":       "Arch-Gun",
}

#: wiki art the riven cards borrow until the composed-card generator lands
#: (docs/THIRD_PARTY.md) - fetched through the normal mod_images pipeline
RIVEN_TEMPLATE_IMG = "RivenModTemplate.png"

_RIVEN_POLARITY = {"AP_ATTACK": "madurai", "AP_DEFENSE": "vazarin",
                   "AP_TACTIC": "naramon"}

#: fingerprint stat Tag -> (card abbreviation, tooltip words). The fallback
#: de-camels the tag, so an unmapped stat degrades to readable, not to blank.
_RIVEN_STAT = {
    "WeaponDamageAmountMod":          ("DMG",   "Damage"),
    "WeaponMeleeDamageMod":           ("DMG",   "Melee Damage"),
    "WeaponCritChanceMod":            ("CC",    "Critical Chance"),
    "WeaponCritDamageMod":            ("CD",    "Critical Damage"),
    "WeaponFireRateMod":              ("FR",    "Fire Rate"),
    "WeaponMultishotMod":             ("MS",    "Multishot"),
    "WeaponProcChanceMod":            ("SC",    "Status Chance"),
    "WeaponProcTimeMod":              ("SD",    "Status Duration"),
    "WeaponAmmoMaxMod":               ("AMMO",  "Ammo Maximum"),
    "WeaponClipMaxMod":               ("MAG",   "Magazine Capacity"),
    "WeaponReloadSpeedMod":           ("RLD",   "Reload Speed"),
    "WeaponRecoilReductionMod":       ("REC",   "Recoil"),
    "WeaponZoomFovMod":               ("ZOOM",  "Zoom"),
    "WeaponPunctureDepthMod":         ("PT",    "Punch Through"),
    "WeaponArmorPiercingDamageMod":   ("PUN",   "Puncture"),
    "WeaponImpactDamageMod":          ("IMP",   "Impact"),
    "WeaponSlashDamageMod":           ("SLA",   "Slash"),
    "WeaponElectricityDamageMod":     ("ELEC",  "Electricity"),
    "WeaponFreezeDamageMod":          ("COLD",  "Cold"),
    "WeaponFireDamageMod":            ("HEAT",  "Heat"),
    "WeaponToxinDamageMod":           ("TOX",   "Toxin"),
    "WeaponProjectileSpeedMod":       ("PFS",   "Projectile Flight Speed"),
    "WeaponRangeAmountMod":           ("RNG",   "Range"),
    "WeaponMeleeRangeIncMod":         ("RNG",   "Range"),
    "ComboDurationMod":               ("COMBO", "Combo Duration"),
    "SlideAttackCritChanceMod":       ("SLIDE", "Crit Chance on Slide"),
    "WeaponMeleeFinisherDamageMod":   ("FIN",   "Finisher Damage"),
    "WeaponMeleeComboEfficiencyMod":  ("EFF",   "Combo Efficiency"),
    "WeaponMeleeComboInitialBonusMod": ("IC",   "Initial Combo"),
    "WeaponMeleeComboPointsOnHitMod": ("CCC",   "Combo Count Chance"),
    "WeaponFactionDamageCorpus":      ("CORPUS",   "Damage to Corpus"),
    "WeaponFactionDamageGrineer":     ("GRINEER",  "Damage to Grineer"),
    "WeaponFactionDamageInfested":    ("INFESTED", "Damage to Infested"),
}

_riven_cache: dict = {"stamp": None, "rows": None}


def _decamel(raw: str) -> str:
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", raw)


def _stat_words(tag: str) -> tuple[str, str]:
    hit = _RIVEN_STAT.get(tag)
    if hit:
        return hit
    word = _decamel(re.sub(r"^Weapon|Mod$", "", tag))
    return word, word


def _weapon_name(compat: str) -> str:
    from core import public_export
    return (public_export.resolve_name(compat)
            or _decamel(compat.rsplit("/", 1)[-1]))


def rivens() -> list[dict]:
    """The player's UNVEILED rivens as card rows - stats compressed onto the
    card's second name line, the full story in `tooltip`. Veiled/raw rivens
    are excluded (owner ruling 2026-08-07: they carry no roll worth
    showing). Cached per provider mtime; blocking on a cache miss
    (AlecaFrame decrypt), so run via work."""
    from core import mods_db, wf_inventory
    provider = wf_inventory.active_provider()
    if provider is None:
        return []
    stamp = (provider.name, provider.source_mtime())
    if _riven_cache["stamp"] == stamp and _riven_cache["rows"] is not None:
        return _riven_cache["rows"]
    inv = provider.read_raw()
    if inv is None:
        return _riven_cache["rows"] or []
    rows: list[dict] = []

    def base(i: int, name: str, image: str) -> dict:
        return {"internal": f"riven:{i}", "name": name, "image": image,
                "rarity": "riven", "polarity": None, "base_drain": None,
                "max_rank": 8, "tradable": 0, "wiki_url": "", "of_id": None,
                "owned": 1, "current_rank": None}

    for x in inv.get("Upgrades", []) or []:
        if not isinstance(x, dict):
            continue
        p = str(x.get("ItemType", ""))
        if not p.startswith(mods_db.RIVEN_PREFIX):
            continue
        family = RIVEN_FAMILY.get(p.rsplit("/", 1)[-1],
                                  _decamel(p.rsplit("/", 1)[-1]))
        try:
            fp = json.loads(x.get("UpgradeFingerprint") or "{}")
        except (TypeError, ValueError):
            fp = {}
        weapon = _weapon_name(str(fp.get("compat", ""))) if fp.get("compat") \
            else family
        buffs = [_stat_words(str(b.get("Tag", ""))) for b in
                 fp.get("buffs", []) or [] if isinstance(b, dict)]
        curses = [_stat_words(str(c.get("Tag", ""))) for c in
                  fp.get("curses", []) or [] if isinstance(c, dict)]
        stat_line = " ".join(["+" + s for s, _w in buffs]
                             + ["−" + s for s, _w in curses])
        row = base(len(rows), f"{weapon} Riven\n{stat_line}",
                   RIVEN_TEMPLATE_IMG)
        row["current_rank"] = fp.get("lvl")
        pol = _RIVEN_POLARITY.get(str(fp.get("pol", "")))
        row["polarity"] = pol
        row["tooltip"] = (
            f"{weapon} {family} Riven"
            + (f" · {pol.capitalize()}" if pol else "")
            + f" · MR {fp.get('lvlReq', '?')}"
            + f" · {fp.get('rerolls', 0)} rerolls\n"
            + "\n".join("+ " + w for _s, w in buffs)
            + ("\n" if curses else "")
            + "\n".join("− " + w for _s, w in curses))
        rows.append(row)

    rows.sort(key=lambda r: r["name"])
    _riven_cache.update(stamp=stamp, rows=rows)
    return rows


def riven_count() -> int:
    """How many unveiled rivens the player holds."""
    try:
        return len(rivens())
    except Exception:                                   # noqa: BLE001
        return 0


def parazon_class(internal: str) -> str:
    """'antivirus' / 'requiem' / 'parazon', by export path (the only stable
    classifier: Antivirus* and GainAntivirus* grant antivirus, Immortal*
    are the requiem seals, everything else is a plain parazon mod)."""
    if ("/Immortal/Antivirus" in internal
            or "/DataSpike/Potency/GainAntivirus" in internal):
        return "antivirus"
    if "/Immortal/Immortal" in internal:
        return "requiem"
    return "parazon"


#: sort orders the view offers (core owns the ordering rules)
RARITY_ORDER = {"common": 0, "uncommon": 1, "rare": 2, "legendary": 3,
                "riven": 4}


def sort_rows(rows: list[dict], by: str, descending: bool) -> list[dict]:
    """Sort card rows by Name / Rank / Rarity / Polarity, name tie-broken."""
    def name(r):
        return (r.get("name") or "").lower()

    keys = {
        "Name": name,
        "Rank": lambda r: (r.get("current_rank")
                           if r.get("owned") == 1
                           and r.get("current_rank") is not None else -1,
                           name(r)),
        "Rarity": lambda r: (RARITY_ORDER.get(r.get("rarity") or "", -1),
                             name(r)),
        "Polarity": lambda r: (r.get("polarity") or "~", name(r)),
    }
    return sorted(rows, key=keys.get(by, name), reverse=descending)


def price_check(client, name: str) -> dict:
    """Lowest online sell price for ONE mod by display name.
    Returns {price, sellers} or {error}. Blocking - run via ui/work."""
    if client is None:
        return {"error": "market unavailable"}
    want = name.strip().lower()
    slug = next((s for n, s, _ in client.item_names()
                 if n.lower() == want), None)
    if slug is None:
        return {"error": "not traded on warframe.market"}
    try:
        price, sellers = client.lowest_online(slug)
    except Exception as exc:                      # MarketError, network
        return {"error": str(exc)}
    if price is None:
        return {"error": "no online sellers right now"}
    return {"price": price, "sellers": sellers}
