"""고정 팀 모드 (FixedTeamProvider / load_fixed_manifest) 단위 테스트.

experiment-context.md §9 · docs/architecture/fixed-team-mode.md 검증:
- _numeric_team_sort: 사전순이 아닌 숫자순 정렬 (team_2 < team_10)
- FixedTeamProvider: 결정적(2회 로드 동일), 인덱스 범위 검증, 빈 indices 거부
- load_fixed_manifest: 스키마 검증(mode/version/set), manifest hash 계산
"""
import hashlib
import json
import os

import pytest

from poke_env.player.team_util import (
    FixedTeamProvider,
    _numeric_team_sort,
    load_fixed_manifest,
)


# --- _numeric_team_sort (전역 RNG·metamon 무관, 결정적 단위) ---


def test_numeric_team_sort_orders_numerically():
    paths = [
        "team_10.gen9ou_team",
        "team_2.gen9ou_team",
        "team_1.gen9ou_team",
        "team_20.gen9ou_team",
    ]
    nums = [
        int(os.path.basename(p).split("_")[1].split(".")[0])
        for p in _numeric_team_sort(paths)
    ]
    assert nums == sorted(nums), f"not numerically sorted: {nums}"


def test_numeric_team_sort_lexicographic_would_fail():
    # 정렬 전 raw sorted() 는 team_10 이 team_2 앞에 온다 (사전순).
    raw = sorted(["team_2.gen9ou_team", "team_10.gen9ou_team"])
    assert raw[0] == "team_10.gen9ou_team"  # 사전순의 잘못된 결과
    fixed = _numeric_team_sort(["team_2.gen9ou_team", "team_10.gen9ou_team"])
    assert fixed[0] == "team_2.gen9ou_team"  # 숫자순 보정


def test_numeric_team_sort_without_index_pattern():
    # team_N 패턴이 없으면 그냼 알파벳순 (안정적).
    paths = ["zzz.txt", "aaa.txt"]
    assert _numeric_team_sort(paths) == ["aaa.txt", "zzz.txt"]


# --- FixedTeamProvider (metamon 캐시 의존) ---


def _try_provider(*args, **kwargs):
    """metamon 캐시가 없으면 skip."""
    try:
        return FixedTeamProvider(*args, **kwargs)
    except Exception as e:  # 캐시/네트워크 미비
        pytest.skip(f"metamon cache unavailable: {e}")


@pytest.mark.teamloader
def test_fixed_provider_deterministic():
    p1 = _try_provider("gen9ou", "competitive", [0, 1, 2, 3, 4])
    p2 = _try_provider("gen9ou", "competitive", [0, 1, 2, 3, 4])
    for i in range(5):
        assert p1.at(i) == p2.at(i), f"nondeterministic at battle {i}"
        assert "|" in p1.at(i)  # packed Showdown teamstring


@pytest.mark.teamloader
def test_fixed_provider_no_global_rng_consumption():
    # 핵심 불변량: at(i) 호출은 random 모듈 상태를 소비하지 않는다.
    # 같은 provider 로 2회 연속 at 호출 → 동일 결과 (이미 caching). 더 중요:
    # provider 생성 자체가 random.choice 를 안 쓰는지는 코드 리뷰로 보장되며,
    # 여기선 결정성(2회 로드)으로 대리 검증.
    import random

    random.seed(123)
    p = _try_provider("gen9ou", "competitive", [0, 1, 2])
    random.seed(999)  # seed 를 바꿔도
    teams_a = [p.at(i) for i in range(3)]
    random.seed(0)  # 다시 바꿔도
    teams_b = [p.at(i) for i in range(3)]
    assert teams_a == teams_b  # provider 결과는 RNG state 와 무관


@pytest.mark.teamloader
def test_fixed_provider_index_out_of_range():
    _try_provider("gen9ou", "competitive", [0])  # 정상 로드 확인 (또는 skip)
    with pytest.raises(ValueError, match="out of range"):
        FixedTeamProvider("gen9ou", "competitive", [0, 999999])


@pytest.mark.teamloader
def test_fixed_provider_describe():
    p = _try_provider("gen9ou", "competitive", [0, 1, 2])
    desc = p.describe()
    assert desc["set"] == "competitive"
    assert desc["matchup_count"] == 3
    assert desc["indices"] == [0, 1, 2]
    assert desc["pool_size"] >= 3


def test_fixed_provider_empty_indices_rejected():
    with pytest.raises(ValueError, match="non-empty"):
        FixedTeamProvider("gen9ou", "competitive", [])


@pytest.mark.teamloader
def test_fixed_provider_modulo_wrap():
    p = _try_provider("gen9ou", "competitive", [0, 1])
    # indices 길이(2) 초과 position 은 modulo 순환
    assert p.at(0) == p.at(2) == p.at(4)
    assert p.at(1) == p.at(3) == p.at(5)


# --- load_fixed_manifest (스키마 검증) ---


def _write_manifest(tmp_path, data):
    m = tmp_path / "manifest.json"
    m.write_text(json.dumps(data))
    return m


def test_load_manifest_rejects_wrong_mode(tmp_path):
    m = _write_manifest(
        tmp_path,
        {"version": 1, "mode": "random", "battle_format": "gen9ou"},
    )
    with pytest.raises(ValueError, match="mode"):
        load_fixed_manifest(str(m))


def test_load_manifest_rejects_wrong_version(tmp_path):
    m = _write_manifest(
        tmp_path,
        {
            "version": 2,
            "mode": "fixed",
            "battle_format": "gen9ou",
            "player": {"set": "competitive", "indices": [0]},
            "opponent": {"set": "modern_replays", "indices": [0]},
        },
    )
    with pytest.raises(ValueError, match="version"):
        load_fixed_manifest(str(m))


def test_load_manifest_rejects_invalid_set(tmp_path):
    m = _write_manifest(
        tmp_path,
        {
            "version": 1,
            "mode": "fixed",
            "battle_format": "gen9ou",
            "player": {"set": "bogus_set", "indices": [0]},
            "opponent": {"set": "modern_replays", "indices": [0]},
        },
    )
    with pytest.raises(ValueError, match="invalid"):
        load_fixed_manifest(str(m))


def test_load_manifest_rejects_missing_battle_format(tmp_path):
    m = _write_manifest(
        tmp_path, {"version": 1, "mode": "fixed"}
    )
    with pytest.raises(ValueError, match="battle_format"):
        load_fixed_manifest(str(m))


def test_load_manifest_hash_matches_file(tmp_path):
    data = {
        "version": 1,
        "mode": "fixed",
        "battle_format": "gen9ou",
        "player": {"set": "competitive", "indices": [0, 1]},
        "opponent": {"set": "modern_replays", "indices": [0, 1]},
        "n_battles": 2,
    }
    m = _write_manifest(tmp_path, data)
    expected = "sha256:" + hashlib.sha256(m.read_bytes()).hexdigest()
    try:
        combo = load_fixed_manifest(str(m))
    except Exception as e:
        pytest.skip(f"metamon cache unavailable: {e}")
    assert combo.manifest_hash == expected
    assert combo.player.set_name == "competitive"
    assert combo.opponent.set_name == "modern_replays"
