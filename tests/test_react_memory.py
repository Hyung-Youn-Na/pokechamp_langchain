"""Unit tests for battle-scoped memory (EXP-049a, design D).

Covers ``pokechamp/battle_memory.py`` (BattleMemory + refresh/update helpers),
``pokechamp/agents/common.py:parse_action_json`` strategy-key passthrough, and
``pokechamp/agents/react_agent.py:_format_memory_brief``.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from pokechamp.agents.common import parse_action_json
from pokechamp.agents.react_agent import _format_memory_brief
from pokechamp.battle_memory import (
    BattleMemory,
    plan_is_stale,
    refresh_team_roles,
    to_species_key,
    update_opp_revealed,
)


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


def _mock_pokemon(species, moves=None, item=None, tera_type=None):
    return SimpleNamespace(
        species=species,
        moves=moves or {},
        item=item,
        _terastallized_type=tera_type,
    )


def _mock_battle(opp_team=None, opp_active=None, turn=1):
    return SimpleNamespace(
        opponent_team=opp_team or {},
        opponent_active_pokemon=opp_active,
        turn=turn,
    )


# ---------------------------------------------------------------------------
# to_species_key
# ---------------------------------------------------------------------------


def test_to_species_key_basic():
    assert to_species_key("Gholdengo") == "gholdengo"
    assert to_species_key("Ogerpon-Wellspring") == "ogerponwellspring"
    assert to_species_key("Ting-Lu") == "tinglu"
    assert to_species_key("Iron Valiant") == "ironvaliant"
    assert to_species_key("  GREAT-Tusk  ") == "greattusk"
    assert to_species_key("") == ""


def test_species_key_consistent_with_strategies():
    """Every strategies species_key equals the normalised display_name.

    Guards the join contract with ``sets_*.json`` (smogon-meta-design §5.3).
    """
    from pokechamp.data_cache import get_cached_smogon_strategies

    strategies = get_cached_smogon_strategies()
    assert strategies, "Smogon strategies JSON must be loadable"
    for key, entry in strategies.items():
        display = entry.get("display_name", "") or ""
        assert to_species_key(display) == key, (
            f"display_name {display!r} -> {to_species_key(display)!r} != key {key!r}"
        )


# ---------------------------------------------------------------------------
# BattleMemory defaults
# ---------------------------------------------------------------------------


def test_battle_memory_defaults():
    mem = BattleMemory()
    assert mem.opp_role_balance == {}
    assert mem.opp_team_roles == {}
    assert mem.opp_revealed == {}
    assert mem.opp_win_condition == ""
    assert mem.my_plan == ""
    assert mem.plan_turn == 0


# ---------------------------------------------------------------------------
# refresh_team_roles
# ---------------------------------------------------------------------------


def test_refresh_team_roles_real_species():
    gholdengo = _mock_pokemon("Gholdengo")
    tinglu = _mock_pokemon("Ting-Lu")
    battle = _mock_battle(opp_team={"p1": gholdengo, "p2": tinglu})

    mem = BattleMemory()
    refresh_team_roles(mem, battle)

    assert "gholdengo" in mem.opp_team_roles
    assert "tinglu" in mem.opp_team_roles
    # gholdengo is a Special Wallbreaker per the compendium
    ghold_cats = {r["category"] for r in mem.opp_team_roles["gholdengo"]}
    assert "Wallbreakers" in ghold_cats
    # role balance aggregates categories across both mons
    assert len(mem.opp_role_balance) > 0
    assert sum(mem.opp_role_balance.values()) >= 2


def test_refresh_team_roles_unknown_species_skipped():
    mon = _mock_pokemon("DefinitelyNotAPokemon")
    battle = _mock_battle(opp_team={"p1": mon})

    mem = BattleMemory()
    refresh_team_roles(mem, battle)

    assert mem.opp_team_roles == {}
    assert mem.opp_role_balance == {}


def test_refresh_team_roles_idempotent():
    gholdengo = _mock_pokemon("Gholdengo")
    battle = _mock_battle(opp_team={"p1": gholdengo})

    mem = BattleMemory()
    refresh_team_roles(mem, battle)
    first = dict(mem.opp_team_roles)
    refresh_team_roles(mem, battle)  # calling again must not double-count
    assert mem.opp_team_roles == first


# ---------------------------------------------------------------------------
# update_opp_revealed
# ---------------------------------------------------------------------------


def test_update_opp_revealed_accumulates():
    mon = _mock_pokemon(
        "Gholdengo",
        moves={"shadowball": None, "makeitrain": None},
        item="Leftovers",
        tera_type=None,
    )
    battle = _mock_battle(opp_active=mon, turn=3)

    mem = BattleMemory()
    update_opp_revealed(mem, battle)

    entry = mem.opp_revealed["gholdengo"]
    assert set(entry["moves"]) == {"shadowball", "makeitrain"}
    assert entry["item"] == "Leftovers"
    assert entry["first_seen_turn"] == 3
    assert entry["last_seen_turn"] == 3


def test_update_opp_revealed_growth_across_turns():
    mem = BattleMemory()

    # Turn 2: only one move revealed
    mon = _mock_pokemon("Ting-Lu", moves={"stealthrock": None}, item=None)
    update_opp_revealed(mem, _mock_battle(opp_active=mon, turn=2))
    assert mem.opp_revealed["tinglu"]["moves"] == ["stealthrock"]
    assert mem.opp_revealed["tinglu"]["first_seen_turn"] == 2

    # Turn 5: more moves + an item
    mon = _mock_pokemon(
        "Ting-Lu", moves={"stealthrock": None, "earthquake": None}, item="Leftovers"
    )
    update_opp_revealed(mem, _mock_battle(opp_active=mon, turn=5))
    entry = mem.opp_revealed["tinglu"]
    assert set(entry["moves"]) == {"stealthrock", "earthquake"}
    assert entry["item"] == "Leftovers"
    assert entry["first_seen_turn"] == 2  # unchanged
    assert entry["last_seen_turn"] == 5


def test_update_opp_revealed_no_active():
    mem = BattleMemory()
    update_opp_revealed(mem, _mock_battle(opp_active=None, turn=1))
    assert mem.opp_revealed == {}


# ---------------------------------------------------------------------------
# plan_is_stale
# ---------------------------------------------------------------------------


def test_plan_is_stale_gate():
    mem = BattleMemory()
    assert plan_is_stale(mem, 1) is True  # no plan yet

    mem.my_plan = "set hazards then sweep"
    mem.plan_turn = 1
    assert plan_is_stale(mem, 3) is False  # 2 turns old
    assert plan_is_stale(mem, 10) is True  # 9 turns old > max_age 5


# ---------------------------------------------------------------------------
# _format_memory_brief
# ---------------------------------------------------------------------------


def test_format_memory_brief_empty():
    assert _format_memory_brief({}) == ""


def test_format_memory_brief_full():
    state = {
        "opp_role_balance": {"Wallbreakers": 2, "Walls": 1},
        "opp_revealed": {
            "gholdengo": {
                "moves": ["shadowball", "makeitrain"],
                "item": "Leftovers",
                "tera": None,
            }
        },
        "opp_win_condition": "Iron Valiant Agility sweep",
        "my_plan": "set hazards, then Gholdengo sweep",
        "plan_turn": 5,
    }
    brief = _format_memory_brief(state)
    assert "Battle Memory" in brief
    assert "Wallbreakers x2" in brief
    assert "Walls x1" in brief
    assert "gholdengo" in brief
    assert "shadowball" in brief
    assert "Iron Valiant Agility sweep" in brief
    assert "set hazards, then Gholdengo sweep" in brief


# ---------------------------------------------------------------------------
# parse_action_json strategy-key passthrough
# ---------------------------------------------------------------------------


def test_parse_action_json_passthrough_strategy_keys():
    out = parse_action_json(
        '{"move": "earthquake", '
        '"win_condition_opponent": "Dragonite DD sweep", '
        '"my_plan": "remove hazards, pressure with Gholdengo"}',
        None,
    )
    assert out is not None
    assert out["move"] == "earthquake"
    assert out["opp_win_condition"] == "Dragonite DD sweep"
    assert out["my_plan"] == "remove hazards, pressure with Gholdengo"


def test_parse_action_json_strategy_keys_optional():
    """Strategy keys are optional — plain actions still parse."""
    out = parse_action_json('{"move": "earthquake"}', None)
    assert out is not None
    assert out["move"] == "earthquake"
    assert "opp_win_condition" not in out
    assert "my_plan" not in out


def test_parse_action_json_strategy_keys_need_action():
    """Strategy keys without a valid action are dropped (no action = invalid)."""
    out = parse_action_json(
        '{"win_condition_opponent": "sweep", "my_plan": "something"}', None
    )
    assert out is None
