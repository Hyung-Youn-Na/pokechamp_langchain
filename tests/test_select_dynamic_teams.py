"""select_dynamic_teams.py 단위 테스트 — score/정규화/선별 로직 검증.

metamon 풀(네트워크/캐시)에 의존하지 않고, 순수 로직만 검증한다:
- normalize_token 정규화
- score_team 카테고리별 점수(동적 타입/위력/priority/어빌리티/아이템/Tera)
- select_indices 상위 추출 + disjoint + 동점 tie-break
"""
import os
import sys
import types

import pytest

# scripts/exp 를 import path 에 추가
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "exp"))
import select_dynamic_teams as sdt  # noqa: E402


def _mon(moves=None, ability=None, item=None, tera=None):
    return types.SimpleNamespace(
        moves=moves or [], ability=ability, item=item, tera_type=tera
    )


# --- normalize_token ---


def test_normalize_strips_case_space_hyphen():
    assert sdt.normalize_token("Tera Blast") == "terablast"
    assert sdt.normalize_token("Heavy-Duty Boots") == "heavydutyboots"
    assert sdt.normalize_token("Ivy Cudgel") == "ivycudgel"
    assert sdt.normalize_token(None) == ""
    assert sdt.normalize_token("") == ""


def test_dynamic_keyword_sets_nonempty():
    # dynamic_move.py 디스패치 기반 — 비어있으면 스크립트가 무의미
    assert sdt.DYNAMIC_TYPE_MOVES
    assert sdt.DYNAMIC_POWER_MOVES
    assert "grassyglide" in sdt.DYNAMIC_PRIORITY_MOVES
    assert "protosynthesis" in sdt.DYNAMIC_ABILITIES


# --- score_team ---


def test_score_dynamic_type_moves():
    mons = [_mon(["Tera Blast"], tera="Fire"), _mon(["Ivy Cudgel"], tera="Water")]
    _, d = sdt.score_team(mons)
    assert d["type"] == 2  # terablast + ivycudgel
    assert d["tera"] == 2


def test_score_dynamic_power_moves():
    _, d = sdt.score_team([_mon(["Acrobatics", "Hex", "Knock Off"])])
    assert d["power"] == 3


def test_score_dynamic_power_extras():
    # sim/기타 동적 위력 (storedpower 등)
    _, d = sdt.score_team([_mon(["Stored Power", "Eruption"])])
    assert d["power"] == 2


def test_score_dynamic_priority():
    _, d = sdt.score_team([_mon(["Grassy Glide"])])
    assert d["priority"] == 1


def test_score_dynamic_ability():
    _, d = sdt.score_team([_mon([], ability="Protosynthesis"), _mon([], ability="Technician")])
    assert d["ability"] == 2


def test_score_dynamic_item_explicit_and_suffix():
    # 명시적 + 접미사(plate/memory/...)
    _, d = sdt.score_team([_mon([], item="Life Orb"), _mon([], item="Draco Plate")])
    assert d["item"] == 2


def test_score_team_formula_weights():
    # 1.5*tera + 2*type + 2*power + 1*pri + 1*abil + 0.5*item
    mons = [
        _mon(["Tera Blast", "Acrobatics"], ability="Protosynthesis",
             item="Booster Energy", tera="Fire"),
        _mon(["Grassy Glide"], tera="Water"),
    ]
    # tera=2, type=1(terablast), power=1(acrobatics), pri=1(grassyglide), abil=1, item=1
    score, d = sdt.score_team(mons)
    assert d == {"tera": 2, "type": 1, "power": 1, "priority": 1, "ability": 1, "item": 1}
    assert score == 1.5 * 2 + 2 * 1 + 2 * 1 + 1 * 1 + 1 * 1 + 0.5 * 1


def test_score_team_empty_team():
    score, d = sdt.score_team([])
    assert score == 0
    assert all(v == 0 for v in d.values())


# --- select_indices (가짜 team_set) ---


class _FakeTeamSet:
    """parse_showdown_team 이 파일 텍스트(= 단일 move명)를 그대로 1마리 moves 로."""

    def parse_showdown_team(self, text):
        return [_mon(moves=[text.strip()])]


def _write_teams(tmp_path, move_names):
    files = []
    for i, mv in enumerate(move_names):
        p = tmp_path / f"team_{i}.gen9ou_team"
        p.write_text(mv)
        files.append(str(p))
    return files


def test_select_indices_picks_dynamic_top(tmp_path):
    # 2점팀(Acrobatics/Tera Blast/Hex) vs 0점팀(Tackle/Growl)
    files = _write_teams(tmp_path, ["Tackle", "Acrobatics", "Tera Blast", "Growl", "Hex"])
    player, opponent, ranked = sdt.select_indices(_FakeTeamSet(), files, 2, 2, 4)
    assert len(player) == 2 and len(opponent) == 2
    # 상위 3개(2점) 중 player 2, opponent 1 + 0점 1개. 전부 dynamic 팀 우선.
    assert ranked[0][1] >= ranked[1][1] >= ranked[2][1]  # score desc


def test_select_indices_disjoint(tmp_path):
    files = _write_teams(tmp_path, [f"Acrobatics" for _ in range(10)])
    player, opponent, _ = sdt.select_indices(_FakeTeamSet(), files, 3, 3, 4)
    assert not (set(player) & set(opponent)), "player/opponent must be disjoint"


def test_select_indices_tiebreak_idx_ascending(tmp_path):
    # 전부 같은 move(동점) → numeric idx 오름차순
    files = _write_teams(tmp_path, ["Acrobatics"] * 5)
    player, opponent, ranked = sdt.select_indices(_FakeTeamSet(), files, 2, 2, 4)
    idxs_in_order = [r[0] for r in ranked]
    assert idxs_in_order == sorted(idxs_in_order)  # idx asc tie-break → 정렬 상태
    assert player == [0, 1]  # 가장 낮은 idx 먼저
    assert opponent == [2, 3]


def test_select_indices_handles_parse_error(tmp_path):
    # parse 실패(score -1) 팀은 최하위
    files = _write_teams(tmp_path, ["Tackle", "Acrobatics", "Growl"])
    # FakeTS 는 파싱 성공만. 에러 케이스는 _score_one 직접:
    _, _, detail = sdt._score_one(_FakeTeamSet(), (1, "/nonexistent/team.gen9ou_team"))
    assert detail.get("error")  # 예외 → error detail, score -1
