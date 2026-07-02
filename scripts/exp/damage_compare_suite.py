#!/usr/bin/env python3
"""제어 데미지 비교 스위트 — calc(`@smogon/calc`) vs Showdown oracle.

고정된 카테고리별 케이스(일반/동적위력/동적타입/tera/OHKO/weather/status/screen/
ability)에 대해 양 백엔드에 **동일 payload**를 주고 데미지 차이를 표로 산출한다.
LLM 비개입 → temperature·명중률 무관, 완전 재현 가능. EXP-057 데미지 정확도 비교의
결정론적 데이터 소스.

배틀을 실행하지 않는다(§0-8) — oracle 워커에 payload JSON을 직접 보내는 비배틀 측정.

사용법::
    .venv/bin/python scripts/exp/damage_compare_suite.py [--json]
"""

from __future__ import annotations

import argparse
import json
from typing import Any, Dict, List, Optional, Tuple

from pokechamp.damage_calc_oracle import get_shared_damage_calc_oracle
from pokechamp.showdown_oracle import get_shared_oracle


# packed-string helper — nickname|species|item|ability|moves|nature|evs|gender|ivs|shiny|level|happiness
def P(  # noqa: E743 — short helper name
    species: str,
    *,
    item: str = "",
    ability: str = "",
    moves: str = "",
    nature: str = "serious",
    evs: str = "0,0,0,0,0,0",
    ivs: str = "31,31,31,31,31,31",
    gender: str = "",
    level: str = "100",
) -> str:
    return "|".join([species, species, item, ability, moves, nature, evs, gender, ivs, "", level, ""])


def ST(  # active_state helper
    species: str,
    *,
    hp_pct: float = 100.0,
    status: str = "",
    boosts: Optional[Dict[str, int]] = None,
    tera_type: str = "",
    is_terastallized: bool = False,
    ability: str = "",
    item: str = "",
) -> Dict[str, Any]:
    st: Dict[str, Any] = {"species_id": species, "hp_pct": hp_pct}
    if status:
        st["status"] = status
    if boosts:
        st["boosts"] = boosts
    if is_terastallized and tera_type:
        st["is_terastallized"] = True
        st["tera_type"] = tera_type
    if ability:
        st["ability"] = ability
    if item:
        st["item"] = item
    return st


# (label, category, move_id, attacker_packed, defender_packed, as1, as2, def_sc, weather, terrain)
# as1/as2: active_state dict (None → 풀피 기본). def_sc: target side_conditions.
CASES: List[Tuple[str, str, str, str, str, Optional[Dict], Optional[Dict], Dict, Optional[str], Optional[str]]] = [
    # --- 일반 (baseline) ---
    ("eq-cb", "normal", "earthquake",
     P("garchomp", item="choiceband", moves="earthquake", nature="jolly", evs="0,252,0,0,0,252", gender="M"),
     P("excadrill", moves="earthquake", nature="jolly", evs="4,252,0,0,0,252", gender="M"),
     None, None, {}, None, None),
    ("tb-lightball", "normal", "thunderbolt",
     P("pikachu", item="lightball", ability="static", moves="thunderbolt", nature="timid", evs="0,0,0,252,4,252"),
     P("gyarados", ability="intimidate", moves="waterfall", nature="adamant", evs="0,252,0,0,4,252"),
     None, None, {}, None, None),
    # --- 동적 위력 ---
    ("facade-burn", "dynamic-power", "facade",
     P("ursaring", item="toxicorb", ability="guts", moves="facade", nature="adamant", evs="0,252,0,0,4,252"),
     P("snorlax", item="leftovers", ability="thickfat", moves="bodyslam", nature="impish", evs="252,0,252,0,4,0"),
     ST("ursaring", status="brn"), None, {}, None, None),
    ("knockoff-item", "dynamic-power", "knockoff",
     P("crawdaunt", item="lifeorb", ability="adaptability", moves="knockoff", nature="adamant", evs="0,252,0,0,4,252"),
     P("snorlax", item="leftovers", ability="thickfat", moves="bodyslam", nature="impish", evs="252,0,252,0,4,0"),
     None, None, {}, None, None),
    ("hex-status", "dynamic-power", "hex",
     P("gengar", ability="cursedbody", moves="hex", nature="modest", evs="0,0,0,252,4,252"),
     P("moltres", item="leftovers", ability="flamebody", moves="roost", nature="bold", evs="252,0,0,0,252,0"),
     None, ST("moltres", status="brn"), {}, None, None),
    ("acrobatics-noitem", "dynamic-power", "acrobatics",
     P("dragapult", ability="clearbody", moves="acrobatics", nature="jolly", evs="0,252,0,0,4,252"),
     P("corsola", ability="weakarmor", moves="recover", nature="bold", evs="252,0,252,0,4,0"),
     None, None, {}, None, None),
    # --- 동적 타입 ---
    ("terablast-water", "dynamic-type", "terablast",
     P("arcanine", ability="intimidate", moves="terablast", nature="jolly", evs="0,252,0,0,4,252"),
     P("charizard", ability="blaze", moves="flamethrower", nature="timid", evs="0,0,0,252,4,252"),
     ST("arcanine", tera_type="water", is_terastallized=True), None, {}, None, None),
    ("weatherball-rain", "dynamic-type", "weatherball",
     P("pelipper", item="damprock", ability="drizzle", moves="weatherball", nature="modest", evs="0,0,0,252,4,252"),
     P("charizard", ability="blaze", moves="flamethrower", nature="timid", evs="0,0,0,252,4,252"),
     None, None, {}, "raindance", None),
    ("ivycudgel", "dynamic-type", "ivycudgel",
     P("ogerponwellspring", item="wellspringmask", ability="waterabsorb", moves="ivycudgel", nature="jolly", evs="0,252,0,0,4,252"),
     P("landorustherian", ability="intimidate", moves="earthquake", nature="adamant", evs="0,252,0,0,4,252"),
     None, None, {}, None, None),
    # --- tera (STAB boost) ---
    ("tera-stab-dragon", "tera", "outrage",
     P("garchomp", item="lifeorb", ability="roughskin", moves="outrage", nature="adamant", evs="0,252,0,0,4,252"),
     P("tyranitar", item="assaultvest", ability="sandstream", moves="stoneedge", nature="impish", evs="252,0,252,0,4,0"),
     ST("garchomp", tera_type="dragon", is_terastallized=True), None, {}, None, None),
    # --- OHKO ---
    ("fissure", "ohko", "fissure",
     P("garchomp", item="choiceband", moves="fissure", nature="jolly", evs="0,252,0,0,0,252", gender="M"),
     P("snorlax", item="leftovers", ability="thickfat", moves="bodyslam", nature="impish", evs="252,0,252,0,4,0"),
     None, None, {}, None, None),
    # --- weather 보정 ---
    ("rain-hydropump", "weather", "hydropump",
     P("pelipper", item="choicespecs", ability="drizzle", moves="hydropump", nature="modest", evs="0,0,0,252,4,252"),
     P("kingambit", item="leftovers", ability="defiant", moves="suckerpunch", nature="adamant", evs="252,0,0,0,4,252"),
     None, None, {}, "raindance", None),
    # --- status (burn physical halve) ---
    ("burn-eq-halve", "status", "earthquake",
     P("garchomp", item="choiceband", moves="earthquake", nature="jolly", evs="0,252,0,0,0,252", gender="M"),
     P("excadrill", moves="earthquake", nature="jolly", evs="4,252,0,0,0,252", gender="M"),
     ST("garchomp", status="brn"), None, {}, None, None),
    # --- screen (reflect physical halve) ---
    ("reflect-eq", "screen", "earthquake",
     P("garchomp", item="choiceband", moves="earthquake", nature="jolly", evs="0,252,0,0,0,252", gender="M"),
     P("excadrill", moves="earthquake", nature="jolly", evs="4,252,0,0,0,252", gender="M"),
     None, None, {"reflect": True}, None, None),
    ("lightscreen-shadowball", "screen", "shadowball",
     P("gengar", item="choicespecs", ability="cursedbody", moves="shadowball", nature="modest", evs="0,0,0,252,4,252"),
     P("dragapult", moves="shadowball", nature="modest", evs="0,0,0,252,4,252"),
     None, None, {"lightscreen": True}, None, None),
    # --- ability (technician ≤60 BP boost) ---
    ("technician-pursuit", "ability", "pursuit",
     P("scizor", item="lifeorb", ability="technician", moves="pursuit", nature="adamant", evs="0,252,0,0,4,252"),
     P("garchomp", ability="roughskin", moves="earthquake", nature="jolly", evs="0,252,0,0,4,252"),
     None, None, {}, None, None),
]


def make_payload(c: Tuple) -> Dict[str, Any]:
    label, cat, mid, atk, defn, as1, as2, def_sc, weather, terrain = c
    asp1 = as1 or ST(atk.split("|")[1])
    asp2 = as2 or ST(defn.split("|")[1])
    return {
        "id": label,
        "format": "gen9customgame",
        "seed": [42, 1337, 256, 999],
        "actor_side": "p1",
        "actor_slot": 0,
        "target_side": "p2",
        "target_slot": 0,
        "move_id": mid,
        "weather": weather,
        "terrain": terrain,
        "team_p1": atk,
        "team_p2": defn,
        "active_state": {"p1": [asp1], "p2": [asp2]},
        "side_conditions": {"p1": {}, "p2": dict(def_sc)},
    }


def summ(r: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not r or not r.get("ok"):
        return None
    dm = r.get("damage") or {}
    rs = r.get("resolved") or {}
    t = rs.get("type")
    ko = r.get("ko_estimate") or {}
    return {
        "median": dm.get("median_pct"),
        "mn": dm.get("min_pct"),
        "mx": dm.get("max_pct"),
        "type": (t.lower() if isinstance(t, str) and t else None),
        "bp": rs.get("base_power"),
        "ohko": ko.get("ohko_chance"),
    }


def run() -> List[Dict[str, Any]]:
    sd = get_shared_oracle()
    dc = get_shared_damage_calc_oracle()
    out: List[Dict[str, Any]] = []
    for c in CASES:
        p = make_payload(c)
        s = sd.query(p) if sd else None
        d = dc.query(p) if dc else None
        ss, ds = summ(s), summ(d)
        delta = None
        if ss and ds and ss["median"] is not None and ds["median"] is not None:
            delta = round(ss["median"] - ds["median"], 1)  # showdown − damagecalc
        out.append(
            {
                "label": c[0],
                "category": c[1],
                "move": c[2],
                "atk": c[3].split("|")[1],
                "defn": c[4].split("|")[1],
                "showdown": ss,
                "damagecalc": ds,
                "delta_median": delta,
                "type_match": (
                    ss["type"] == ds["type"]
                    if (ss and ds and ss["type"] and ds["type"])
                    else None
                ),
            }
        )
    return out


def print_table(rows: List[Dict[str, Any]]) -> None:
    hdr = f"{'label':22} {'cat':13} {'move':13} {'sd med':>7} {'dc med':>7} {'delta':>7} {'type':>11} {'tm':>4}"
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        s, d = r["showdown"], r["damagecalc"]
        sm = s["median"] if s else None
        dm = d["median"] if d else None
        st = s["type"] if s else "-"
        tm = {True: "✓", False: "✗", None: "-"}.get(r["type_match"], "-")
        delta = r["delta_median"]
        ds = f"{delta:+.1f}" if delta is not None else "  -"
        sm_s = f"{sm:.1f}" if isinstance(sm, (int, float)) else "-"
        dm_s = f"{dm:.1f}" if isinstance(dm, (int, float)) else "-"
        print(f"{r['label']:22} {r['category']:13} {r['move']:13} {sm_s:>7} {dm_s:>7} {ds:>7} {st:>11} {tm:>4}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true", help="표 대신 JSON 출력")
    args = ap.parse_args()
    rows = run()
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        print_table(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
