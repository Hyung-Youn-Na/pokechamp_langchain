"""Unit tests for battle-scoped memory (EXP-049a, design D).

Covers ``pokechamp/battle_memory.py`` (BattleMemory + refresh/update helpers),
``pokechamp/agents/common.py:parse_action_json`` strategy-key passthrough, and
``pokechamp/agents/react_agent.py:_format_memory_brief``.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from pokechamp.agents.common import build_battle_state, parse_action_json
from pokechamp.agents.react_agent import _format_memory_brief
from pokechamp.battle_memory import (
    BattleMemory,
    detect_plan_disruption,
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


# ---------------------------------------------------------------------------
# detect_plan_disruption (EXP-051 plan resilience)
# ---------------------------------------------------------------------------


def _team_mon(species, fainted=False):
    """Own-team mon stub with a fainted flag (EXP-053 KO-only detection)."""
    m = _mock_pokemon(species)
    m.fainted = fainted
    return m


def _mock_battle_active(active_species, turn=1, team=None):
    """Battle with own active mon + optional team (for disruption tests)."""
    return SimpleNamespace(
        active_pokemon=_mock_pokemon(active_species),
        turn=turn,
        team=team or {},
    )


def test_detect_plan_disruption_first_turn():
    """No snapshot yet → never flag a disruption on the first observation."""
    mem = BattleMemory()
    battle = _mock_battle_active("Gholdengo", turn=1)
    disrupted, reason = detect_plan_disruption(mem, battle)
    assert disrupted is False
    assert reason is None
    # snapshot now seeded for the next turn's comparison
    assert mem.last_my_active_species == "gholdengo"


def test_detect_plan_disruption_no_change():
    """Same species on consecutive turns → no disruption, no nudge."""
    mem = BattleMemory()
    detect_plan_disruption(mem, _mock_battle_active("Gholdengo", turn=1))
    disrupted, reason = detect_plan_disruption(
        mem, _mock_battle_active("Gholdengo", turn=2)
    )
    assert disrupted is False
    assert reason is None


def test_detect_plan_disruption_my_ko():
    """Own active was KO'd and replaced → flag disruption (EXP-053 KO-only)."""
    mem = BattleMemory()
    detect_plan_disruption(
        mem,
        _mock_battle_active(
            "Gholdengo", turn=1, team={"g": _team_mon("Gholdengo", fainted=False)}
        ),
    )
    # turn 2: Kingambit active; Gholdengo now fainted (KO'd last turn)
    disrupted, reason = detect_plan_disruption(
        mem,
        _mock_battle_active(
            "Kingambit",
            turn=2,
            team={
                "g": _team_mon("Gholdengo", fainted=True),
                "k": _team_mon("Kingambit", fainted=False),
            },
        ),
    )
    assert disrupted is True
    assert reason is not None
    assert "gholdengo" in reason
    # snapshot updated to the new mon so the same KO is not re-flagged next turn
    assert mem.last_my_active_species == "kingambit"


def test_detect_plan_disruption_alive_switch_not_flagged():
    """Pivot / voluntary switch / forced switch (Roar): species changes but the
    previous active is still alive → NO disruption nudge (EXP-053). Covers
    U-turn, Volt Switch, Flip Turn, manual switch, and phazing (Roar/Whirlwind)."""
    mem = BattleMemory()
    detect_plan_disruption(
        mem,
        _mock_battle_active(
            "Gholdengo", turn=1, team={"g": _team_mon("Gholdengo", fainted=False)}
        ),
    )
    # turn 2: Kingambit active via pivot / switch / Roar — Gholdengo still alive,
    # just switched out. Must NOT flag a plan disruption.
    disrupted, reason = detect_plan_disruption(
        mem,
        _mock_battle_active(
            "Kingambit",
            turn=2,
            team={
                "g": _team_mon("Gholdengo", fainted=False),
                "k": _team_mon("Kingambit", fainted=False),
            },
        ),
    )
    assert disrupted is False
    assert reason is None
    assert mem.last_my_active_species == "kingambit"


def test_detect_plan_disruption_no_active():
    """active_pokemon=None → no exception, no disruption, snapshot untouched."""
    mem = BattleMemory()
    mem.last_my_active_species = "gholdengo"
    battle = SimpleNamespace(active_pokemon=None, turn=2)
    disrupted, reason = detect_plan_disruption(mem, battle)
    assert disrupted is False
    assert reason is None
    # snapshot must not be clobbered when there is no active mon
    assert mem.last_my_active_species == "gholdengo"


def test_format_memory_brief_replan_marker():
    """plan_invalidated state → brief carries the replan nudge; else absent."""
    base = {"my_plan": "set hazards then sweep", "plan_turn": 3}

    disrupted = dict(
        base,
        plan_invalidated=True,
        replan_reason="your gholdengo was removed (KO/forced switch)",
    )
    brief = _format_memory_brief(disrupted)
    assert "PLAN DISRUPTED" in brief
    assert "gholdengo was removed" in brief

    ok = dict(base, plan_invalidated=False, replan_reason="")
    brief_ok = _format_memory_brief(ok)
    assert "PLAN DISRUPTED" not in brief_ok


# ---------------------------------------------------------------------------
# build_battle_state plan_invalidated reset (EXP-051 frequency guard layer 2)
# ---------------------------------------------------------------------------


def _mock_battle_for_state(active_species=None, turn=1):
    """Minimal battle mock satisfying build_battle_state's reads."""
    mon = _mock_pokemon(active_species) if active_species else None
    return SimpleNamespace(
        battle_tag="b1",
        turn=turn,
        format="gen9ou",
        available_moves=[],
        available_switches=[],
        active_pokemon=mon,
        opponent_active_pokemon=None,
        team={},
        opponent_team={},
        weather=None,
        terrain=None,
        can_dynamax=False,
        can_tera=True,
    )


def _mock_sim():
    return SimpleNamespace(state_translate=lambda b: ("sys", "state", "state_action"))


def test_build_battle_state_resets_invalidated_flag():
    """The one-turn plan_invalidated nudge is copied into state then reset on
    memory (frequency guard layer 2) so it never persists across turns."""
    mem = BattleMemory()
    mem.plan_invalidated = True
    mem.replan_reason = "your gholdengo was removed (KO/forced switch)"
    state = build_battle_state(_mock_battle_for_state(), _mock_sim(), "", memory=mem)
    assert state["plan_invalidated"] is True  # surfaced this turn
    assert "gholdengo was removed" in state["replan_reason"]
    assert mem.plan_invalidated is False  # consumed — reset
    assert mem.replan_reason == ""
