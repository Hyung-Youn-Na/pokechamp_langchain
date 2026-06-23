#!/usr/bin/env python3
"""Dynamic-resolve 팀 선별 → 고정 팀 manifest 생성.

metamon 풀의 각 팀을 ``parse_showdown_team`` 으로 파싱해 dynamic-resolve 점수를
산출하고, 상위 N팀(player/opponent disjoint)을 고정 팀 manifest 로 내보낸다.

왜 필요한가
-----------
EXP-035~038(sim dynamic resolve fix 시리즈) 재검증용. 랜덤 풀에선 dynamic resolve
(tera/ivycudgel/동적 무브)가 너무 드물어(EXP-038: tera 언급 0.7%, Ogerpon 3배틀)
fix1/2/3 효과 측정이 불가했다. dynamic-resolve 가 빈발하는 팀 매치업으로 baseline을
잡아야 fix 들의 진짜 효과가 드러난다.

재사용 (정합성)
---------------
``get_metamon_teams`` / ``_numeric_team_sort`` / ``TeamSet.parse_showdown_team`` 을
그대로 쓴다 → ``FixedTeamProvider`` 런타임과 **동일 파서·동일 정렬**이므로 manifest
인덱스가 런타임 팀과 정확히 일치한다.

행동 규칙 (§0-8): 본 스크립트는 메타 데이터 분석이지 배틀이 아니다. manifest 생성까지만.
"""
from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from poke_env.player.team_util import _numeric_team_sort, get_metamon_teams


# --- dynamic-resolve 키워드 세트 (dynamic_move.py 디스패치 + sim 분기 기반) ---

# resolve_dynamic_type (dynamic_move.py:248-273)
DYNAMIC_TYPE_MOVES = {
    "weatherball", "terablast", "aurawheel", "hiddenpower", "ivycudgel",
    "ragingbull", "terastarstorm", "revelationdance", "terrainpulse",
    "judgment", "multiattack", "technoblast", "naturalgift",
}
# resolve_dynamic_power (dynamic_move.py:767-782) + sim modify_base_power 조건부
DYNAMIC_POWER_MOVES = {
    "acrobatics", "facade", "knockoff", "weatherball", "lowkick", "grassknot",
    "heavyslam", "heatcrash", "hex", "naturalgift",
}
# sim/기타 동적 위력 (storedpower 등 상태/스택 기반; sim modify_base_power 영역)
DYNAMIC_POWER_EXTRA = {
    "storedpower", "powertrip", "flail", "reversal", "eruption", "waterspout",
    "magnitude", "punishment", "trumpcard", "spitup", "furycutter", "rage",
    "rollout", "echovedvoice", "gyroball", "electroball", "return", "frustration",
}
# resolve_dynamic_priority (dynamic_move.py:892-893)
DYNAMIC_PRIORITY_MOVES = {"grassyglide"}

# sim 별도 동적 어빌리티 (local_simulation.py modify_base_power/damage + 날씨/Terrain 셋업)
DYNAMIC_ABILITIES = {
    "protosynthesis", "quarkdrive",  # booster energy (fix1 priority/spe)
    "technician", "supremeoverlord", "guts",  # modify_base_power/damage
    "intimidate", "download", "defiant", "competitive", "weakarmor", "magicbounce",
    # 날씨/Terrain 셋업 → weatherball/terrainpulse/grassyglide 리졸브 트리거
    "drought", "drizzle", "sandstream", "snowwarning", "orichalcmpulse",
    "hadronengine", "grassysurge", "electricsurge", "psychicsurge", "mistysurge",
}
# 아이템: 접미사 매칭(plate/memory/drive/berry/gem) + 명시적
DYNAMIC_ITEM_SUFFIXES = ("plate", "memory", "drive", "berry", "gem")
DYNAMIC_ITEMS = {
    "boosterenergy", "lifeorb", "loadeddice", "choiceband", "choicespecs",
    "choicescarf", "heavydutyboots", "airballoon", "custapberry", "metronome",
    "thickclub", "lightball", "focussash", "expertbelt", "softsand",
}


def normalize_token(s):
    """소문자+공백/하이픈 제거 정규화 (dynamic_move.py ``_normalize_move_id`` 호환)."""
    if not s:
        return ""
    return s.lower().replace(" ", "").replace("-", "")


def score_team(mons):
    """``parse_showdown_team`` 결과(List[TeambuilderPokemon]) → (score, detail).

    전반 균형 가중치 — fix1/2/3 모든 dynamic 메커니즘을 골고루 반영:
      1.5*n_unique_tera + 2*n_dyn_type + 2*n_dyn_power + 1*n_dyn_priority
      + 1*n_dyn_ability + 0.5*n_dyn_item
    """
    n_unique_tera = len({m.tera_type for m in mons if getattr(m, "tera_type", None)})
    n_type = n_pow = n_pri = n_abil = n_item = 0
    for m in mons:
        for mv in getattr(m, "moves", []) or []:
            nmv = normalize_token(mv)
            if nmv in DYNAMIC_TYPE_MOVES:
                n_type += 1
            if nmv in DYNAMIC_POWER_MOVES or nmv in DYNAMIC_POWER_EXTRA:
                n_pow += 1
            if nmv in DYNAMIC_PRIORITY_MOVES:
                n_pri += 1
        if normalize_token(getattr(m, "ability", None)) in DYNAMIC_ABILITIES:
            n_abil += 1
        it = normalize_token(getattr(m, "item", None))
        if it and (it in DYNAMIC_ITEMS or any(it.endswith(suf) for suf in DYNAMIC_ITEM_SUFFIXES)):
            n_item += 1
    score = (
        1.5 * n_unique_tera
        + 2.0 * n_type
        + 2.0 * n_pow
        + 1.0 * n_pri
        + 1.0 * n_abil
        + 0.5 * n_item
    )
    detail = {"tera": n_unique_tera, "type": n_type, "power": n_pow,
              "priority": n_pri, "ability": n_abil, "item": n_item}
    return score, detail


def _score_one(team_set, idx_path):
    idx, path = idx_path
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        mons = team_set.parse_showdown_team(text)
        score, detail = score_team(mons)
    except Exception as e:  # 비표준 팀 파일 방어
        score, detail = -1.0, {"error": str(e)}
    return idx, score, detail


def select_indices(team_set, files, player_n, opponent_n, workers, seed=42):
    """풀 전수 score → player(dynamic 상위) + opponent(neutral) indices.

    §9 manifest 원칙: player 풀만 dynamic-resolve 기준으로 선별(실험변수),
    opponent 풀은 neutral 통제(dynamic 기준 미반영). 기존 dynamic-v1 은
    player/opponent 를 같은 dynamic score 상위에서 disjoint 로 뽑아 원칙 2를
    위반했다 — opponent 도 큐레이션되면 공격 신호가 섞여 fix 한계 효과의 인과
    해석이 불가능하다.

    - player = dynamic score 내림차순 상위 player_n (동점 시 idx 오름차순).
    - opponent = player 와 disjoint 한 풀에서 seed 고정 균등 랜덤 추출
      (dynamic 기준이 아닌 neutral 통제).
    """
    pairs = list(enumerate(files))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(lambda p: _score_one(team_set, p), pairs))
    # score desc, idx asc tie-break
    ranked = sorted(results, key=lambda r: (-r[1], r[0]))
    player = [r[0] for r in ranked[:player_n]]

    # opponent: neutral — player 와 disjoint 한 풀에서 균등 랜덤 (dynamic 미반영).
    import random

    player_set = set(player)
    remaining = [i for i in range(len(files)) if i not in player_set]
    rng = random.Random(seed)
    if len(remaining) >= opponent_n:
        opponent = rng.sample(remaining, opponent_n)
    else:
        opponent = list(remaining)
    return player, opponent, ranked


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--battle_format", default="gen9ou")
    ap.add_argument("--set", default="modern_replays",
                    help="metamon set (player/opponent 같은 풀)")
    ap.add_argument("--player_n", type=int, default=30)
    ap.add_argument("--opponent_n", type=int, default=30)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument(
        "--seed",
        type=int,
        default=42,
        help="opponent neutral 균등 추출 seed (player는 score 기준 고정)",
    )
    ap.add_argument("--out", required=True, help="출력 manifest JSON 경로")
    args = ap.parse_args()

    team_set = get_metamon_teams(args.battle_format, args.set)
    files = _numeric_team_sort(team_set.team_files)
    print(f"pool: {args.set}/{args.battle_format} = {len(files)} teams")

    player, opponent, ranked = select_indices(
        team_set, files, args.player_n, args.opponent_n, args.workers, args.seed
    )
    assert not (set(player) & set(opponent)), "player/opponent overlap!"

    manifest = {
        "version": 2,
        "mode": "fixed",
        "battle_format": args.battle_format,
        "description": (
            "Dynamic-resolve ablation 세트 (§9 원칙 준수, v2). player 풀만 dynamic-resolve "
            "score(Tera 다양성 + 동적 타입/위력/priority/어빌리티/아이템) 상위 팀(실험변수), "
            "opponent 풀은 player와 disjoint한 풀에서 seed 고정 균등 랜덤(neutral 통제, dynamic "
            "기준 미반영). v1은 player/opponent를 같은 dynamic 기준으로 선별해 §9 원칙 2를 "
            "위반 → 아카이빙. oracle 동적 타입/위력 통합(react 데미지 도구) 효과 측정용."
        ),
        "player": {
            "set": args.set,
            "indices": player,
            "selection": "dynamic_score_top",
        },
        "opponent": {
            "set": args.set,
            "indices": opponent,
            "selection": "neutral_random",
            "seed": args.seed,
        },
        "n_battles": args.player_n,
        "custom_purpose": "dynamic-resolve-ablation-v2",
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote manifest: {out}")

    # 상위 dynamic 팀(player) + neutral opponent 샘플 출력 (검증용)
    print(f"\nplayer rank 1 (idx={ranked[0][0]}, score={ranked[0][1]}): {ranked[0][2]}")
    print(f"player rank 2 (idx={ranked[1][0]}, score={ranked[1][1]}): {ranked[1][2]}")
    print(f"\nplayer indices[:10]:  {player[:10]}")
    print(f"opponent indices[:10]: {opponent[:10]}")
    print(
        f"\nopponent = neutral random (dynamic 기준 아님); "
        f"player/opponent disjoint: {len(set(player) & set(opponent)) == 0}"
    )


if __name__ == "__main__":
    main()
