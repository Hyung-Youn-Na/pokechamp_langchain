"""Unit tests for the get_strategy_insight tool (EXP-049c, Smogon method 1)."""

from __future__ import annotations

import json

from pokechamp.battle_tools import ALL_BATTLE_TOOLS, get_strategy_insight


def test_overview_default_aspect():
    r = json.loads(get_strategy_insight.invoke({"species": "Gholdengo"}))
    assert r["species"] == "Gholdengo"
    assert "overview" in r and r["overview"]
    # cap enforces lean prompts (bloat guard)
    assert len(r["overview"]) <= 2000


def test_species_key_mapping_punctuation():
    # "Ogerpon-Wellspring" → "ogerponwellspring" must resolve
    r = json.loads(get_strategy_insight.invoke({"species": "Ogerpon-Wellspring"}))
    assert "overview" in r


def test_species_key_mapping_case_space():
    r = json.loads(get_strategy_insight.invoke({"species": "  Ting-Lu "}))
    assert "overview" in r


def test_not_found_fallback_never_raises():
    r = json.loads(get_strategy_insight.invoke({"species": "DefinitelyNotAPokemon"}))
    assert "note" in r
    assert "error" not in r
    # 빈 overview 원인 설명 (LLM 오판 방지)
    assert "data limitation" in r["note"].lower()
    # no_data 플래그: tool-call 예산에서 제외 (대안 도구용 예산 확보)
    assert r.get("no_data") is True


def test_empty_overview_explains_reason():
    """빈 overview 종은 이유(데이터 한계)를 설명해 LLM이 도구를 오판하지 않게 한다."""
    d = json.load(open("poke_env/data/static/gen9/ou/smogon_strategies_gen9ou.json"))
    empty_species = [k for k, v in d.items() if not (v.get("overview") or "").strip()]
    if not empty_species:
        return  # 빈 overview 종이 없으면 스킵
    r = json.loads(get_strategy_insight.invoke({"species": empty_species[0]}))
    if not r.get("overview"):
        assert "note" in r, "빈 overview일 때 note로 이유를 설명해야 함"
        assert "data limitation" in r["note"].lower()
        assert r.get("no_data") is True


def test_registered_in_all_battle_tools():
    names = [t.name for t in ALL_BATTLE_TOOLS]
    assert "get_strategy_insight" in names


def test_moveset_aspect_returns_build():
    r = json.loads(get_strategy_insight.invoke({"species": "gholdengo", "aspect": "moveset"}))
    # Either a moveset build or an overview fallback (when no movesets)
    assert ("moveset_name" in r) or ("overview" in r)
