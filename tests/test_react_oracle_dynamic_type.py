"""Tests for Showdown-oracle dynamic-type integration in ReAct battle tools.

This is the react-agent improvement path (LangChain/LangGraph): the damage
tools ``calculate_damage`` / ``simulate_turn`` override a dynamic-type move's
real type via the oracle before the LocalSim damage calc, so a single tool
call yields an accurate dynamic-type damage observation.

Covers:
- ``is_dynamic_type_move`` predicate (13 dynamic-type moves vs static)
- ``poke_env`` ``Move.type`` override (per-instance setter + clone) without
  mutating the shared ``GenData.moves`` entry
- ``OracleResultCache`` (hit/miss/None-cached/LRU eviction)
- ``get_shared_oracle`` singleton (lazy, shared, init-failure → None)
- ``_resolve_move_type_via_oracle`` (dynamic filter, fallback, caching)
- EXP-035 regression: only the *type* is overridden — never the base power
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from poke_env.environment.move import Move
from poke_env.environment.pokemon_type import PokemonType

from pokechamp.battle_tools import (
    BattleContext,
    _clone_move_with_type,
    _resolve_move_outcome_via_oracle,
)
from pokechamp.dynamic_move import (
    is_dynamic_move,
    is_dynamic_power_move,
    is_dynamic_type_move,
)
from pokechamp.showdown_oracle import (
    OracleResultCache,
    ShowdownOracle,
    _CACHE_MISS,
    get_oracle_cache,
    get_shared_oracle,
)


# ---------------------------------------------------------------------------
# is_dynamic_type_move
# ---------------------------------------------------------------------------


class TestIsDynamicTypeMove:
    DYNAMIC = [
        "weatherball",
        "terablast",
        "aurawheel",
        "hiddenpower",
        "ivycudgel",
        "ragingbull",
        "terastarstorm",
        "revelationdance",
        "terrainpulse",
        "judgment",
        "multiattack",
        "technoblast",
        "naturalgift",
    ]
    STATIC = ["tackle", "flamethrower", "surf", "earthquake", "protect", "swordsdance"]

    @pytest.mark.parametrize("mid", DYNAMIC)
    def test_dynamic_true(self, mid: str) -> None:
        assert is_dynamic_type_move(mid) is True

    @pytest.mark.parametrize("mid", STATIC)
    def test_static_false(self, mid: str) -> None:
        assert is_dynamic_type_move(mid) is False

    def test_accepts_move_object(self) -> None:
        assert is_dynamic_type_move(Move("weatherball", gen=9)) is True
        assert is_dynamic_type_move(Move("tackle", gen=9)) is False


class TestIsDynamicPowerMove:
    POWER = [
        "acrobatics",
        "facade",
        "knockoff",
        "weatherball",
        "lowkick",
        "grassknot",
        "heavyslam",
        "heatcrash",
        "hex",
        "naturalgift",
    ]
    NON_POWER = ["tackle", "flamethrower", "terablast", "ivycudgel", "surf"]

    @pytest.mark.parametrize("mid", POWER)
    def test_power_true(self, mid: str) -> None:
        assert is_dynamic_power_move(mid) is True

    @pytest.mark.parametrize("mid", NON_POWER)
    def test_power_false(self, mid: str) -> None:
        assert is_dynamic_power_move(mid) is False


class TestIsDynamicMove:
    def test_union_type_and_power(self) -> None:
        # type-only
        assert is_dynamic_move("terablast") is True
        # power-only
        assert is_dynamic_move("facade") is True
        # both (weatherball)
        assert is_dynamic_move("weatherball") is True

    def test_static_false(self) -> None:
        assert is_dynamic_move("tackle") is False
        assert is_dynamic_move("flamethrower") is False


# ---------------------------------------------------------------------------
# Move.type override + clone (poke_env/environment/move.py)
# ---------------------------------------------------------------------------


class TestMoveTypeOverride:
    def test_setter_str(self) -> None:
        m = Move("tackle", gen=9)
        assert m.type == PokemonType.NORMAL
        m.type = "water"
        assert m.type == PokemonType.WATER

    def test_setter_clear_returns_base(self) -> None:
        m = Move("tackle", gen=9)
        m.type = "fire"
        m.type = None
        assert m.type == PokemonType.NORMAL

    def test_setter_invalid_ignored(self) -> None:
        m = Move("tackle", gen=9)
        m.type = "notatype"
        assert m.type == PokemonType.NORMAL

    def test_clone_does_not_mutate_original(self) -> None:
        original = Move("tackle", gen=9)
        clone = _clone_move_with_type(original, "water")
        assert clone.type == PokemonType.WATER
        assert original.type == PokemonType.NORMAL

    def test_clone_preserves_id(self) -> None:
        clone = _clone_move_with_type(Move("weatherball", gen=9), "fire")
        assert str(clone.id) == "weatherball"
        assert clone.type == PokemonType.FIRE

    def test_clone_does_not_override_base_power(self) -> None:
        # EXP-035 regression guard: overriding the type must NOT also touch
        # base power (which sim.modify_base_power would then double-correct).
        original = Move("weatherball", gen=9)
        clone = _clone_move_with_type(original, "water")
        assert clone.base_power == original.base_power


# ---------------------------------------------------------------------------
# OracleResultCache
# ---------------------------------------------------------------------------


class TestOracleResultCache:
    def test_miss_then_hit(self) -> None:
        c = OracleResultCache(max_size=10)
        assert c.get("h", "weatherball", "a", "b") is _CACHE_MISS
        c.set("h", "weatherball", "a", "b", "water")
        assert c.get("h", "weatherball", "a", "b") == "water"

    def test_none_is_cached_not_miss(self) -> None:
        c = OracleResultCache(max_size=10)
        c.set("h", "m", "a", "b", None)
        assert c.get("h", "m", "a", "b") is None
        assert c.stats()["hits"] >= 1

    def test_lru_eviction_bounds_size(self) -> None:
        c = OracleResultCache(max_size=4)
        for i in range(4):
            c.set(f"h{i}", "m", "a", "b", "water")
        c.set("h4", "m", "a", "b", "fire")  # triggers 25% (1) eviction
        assert c.stats()["size"] <= 4

    def test_stats_counts(self) -> None:
        c = OracleResultCache(max_size=10)
        c.get("h", "m", "a", "b")  # miss
        c.set("h", "m", "a", "b", "water")
        c.get("h", "m", "a", "b")  # hit
        s = c.stats()
        assert s["hits"] == 1 and s["misses"] == 1


# ---------------------------------------------------------------------------
# get_shared_oracle singleton
# ---------------------------------------------------------------------------


class TestSharedOracleSingleton:
    def test_singleton_returns_same_instance(self) -> None:
        from pokechamp import showdown_oracle as mod

        with patch.object(ShowdownOracle, "_verify_dist"), patch.object(
            ShowdownOracle, "_spawn"
        ):
            mod._shared_oracle = None
            a = get_shared_oracle()
            b = get_shared_oracle()
            assert a is not None and a is b
            if a is not None:
                a.close()

    def test_returns_none_on_init_failure(self) -> None:
        from pokechamp import showdown_oracle as mod

        with patch.object(
            ShowdownOracle,
            "_verify_dist",
            side_effect=FileNotFoundError("no dist"),
        ):
            mod._shared_oracle = None
            assert get_shared_oracle() is None

    def test_get_oracle_cache_singleton(self) -> None:
        assert get_oracle_cache() is get_oracle_cache()


# ---------------------------------------------------------------------------
# _resolve_move_outcome_via_oracle
# ---------------------------------------------------------------------------


def _make_ctx(enable_oracle: bool = True) -> BattleContext:
    sim = MagicMock()
    sim.enable_showdown_oracle = enable_oracle
    sim.gen.gen = 9
    ctx = BattleContext(sim=sim, battle=MagicMock())
    ctx.active_pokemon = MagicMock()
    ctx.opponent_pokemon = MagicMock()
    ctx.active_pokemon.species = "charizard"
    ctx.opponent_pokemon.species = "blastoise"
    return ctx


def _payload(move_id: str, weather=None) -> dict:
    return {
        "move_id": move_id,
        "weather": weather,
        "terrain": None,
        "active_state": {"p1": [{}], "p2": [{}]},
    }


class TestResolveMoveOutcomeViaOracle:
    def test_static_move_skipped(self) -> None:
        ctx = _make_ctx()
        assert (
            _resolve_move_outcome_via_oracle(
                ctx, Move("tackle", gen=9), ctx.active_pokemon, ctx.opponent_pokemon
            )
            is None
        )

    def test_oracle_disabled_skipped(self) -> None:
        ctx = _make_ctx(enable_oracle=False)
        assert (
            _resolve_move_outcome_via_oracle(
                ctx, Move("weatherball", gen=9), ctx.active_pokemon, ctx.opponent_pokemon
            )
            is None
        )

    def test_dynamic_type_move_returns_outcome(self) -> None:
        ctx = _make_ctx()
        move = Move("weatherball", gen=9)
        with patch(
            "pokechamp.battle_state_mapper.battle_to_oracle_payload",
            return_value=_payload("weatherball", "raindance"),
        ), patch(
            "pokechamp.showdown_oracle.get_shared_oracle"
        ) as gso, patch(
            "pokechamp.showdown_oracle.get_oracle_cache"
        ) as gc:
            oracle = MagicMock()
            oracle.query.return_value = {
                "ok": True,
                "resolved": {"type": "water", "base_power": 50},
                "damage": {"min_pct": 33.0, "median_pct": 35.0, "max_pct": 37.0},
                "ko_estimate": {"ohko_chance": 0.0, "twohko_chance": 1.0},
            }
            gso.return_value = oracle
            cache = MagicMock()
            cache.get.return_value = _CACHE_MISS
            gc.return_value = cache
            outcome = _resolve_move_outcome_via_oracle(
                ctx, move, ctx.active_pokemon, ctx.opponent_pokemon
            )
        assert outcome == {
            "type": "water",
            "base_power": 50,
            "damage_pct_median": 35.0,
            "damage_pct_min": 33.0,
            "damage_pct_max": 37.0,
            "ko": {"ohko_chance": 0.0, "twohko_chance": 1.0},
        }
        oracle.query.assert_called_once()
        cache.set.assert_called_once()

    def test_dynamic_power_move_returns_outcome(self) -> None:
        # facade: sim can't resolve its power — outcome carries base_power
        # (140 under status) + damage so the tool can correct the estimate.
        ctx = _make_ctx()
        move = Move("facade", gen=9)
        with patch(
            "pokechamp.battle_state_mapper.battle_to_oracle_payload",
            return_value=_payload("facade"),
        ), patch(
            "pokechamp.showdown_oracle.get_shared_oracle"
        ) as gso, patch(
            "pokechamp.showdown_oracle.get_oracle_cache"
        ) as gc:
            oracle = MagicMock()
            oracle.query.return_value = {
                "ok": True,
                "resolved": {"type": "normal", "base_power": 140},
                "damage": {"max_pct": 80.0},
                "ko_estimate": {"ohko_chance": 0.1, "twohko_chance": 1.0},
            }
            gso.return_value = oracle
            cache = MagicMock()
            cache.get.return_value = _CACHE_MISS
            gc.return_value = cache
            outcome = _resolve_move_outcome_via_oracle(
                ctx, move, ctx.active_pokemon, ctx.opponent_pokemon
            )
        assert outcome is not None
        assert outcome["base_power"] == 140
        assert outcome["damage_pct_max"] == 80.0

    def test_generic_move_returns_outcome(self) -> None:
        # 게이트 제거 후 일반(비동적) 무브도 oracle 쿼리 → outcome 반환.
        # (이전엔 is_dynamic_move 게이트로 None.) 전 무브 동일 척도 보장.
        ctx = _make_ctx()
        move = Move("thunderbolt", gen=9)
        with patch(
            "pokechamp.battle_state_mapper.battle_to_oracle_payload",
            return_value=_payload("thunderbolt"),
        ), patch(
            "pokechamp.showdown_oracle.get_shared_oracle"
        ) as gso, patch(
            "pokechamp.showdown_oracle.get_oracle_cache"
        ) as gc:
            oracle = MagicMock()
            oracle.query.return_value = {
                "ok": True,
                "resolved": {"type": "electric", "base_power": 90},
                "damage": {"max_pct": 50.0},
                "ko_estimate": {"ohko_chance": 0.0, "twohko_chance": 1.0},
            }
            gso.return_value = oracle
            cache = MagicMock()
            cache.get.return_value = _CACHE_MISS
            gc.return_value = cache
            outcome = _resolve_move_outcome_via_oracle(
                ctx, move, ctx.active_pokemon, ctx.opponent_pokemon
            )
        assert outcome is not None
        assert outcome["type"] == "electric"
        assert outcome["damage_pct_max"] == 50.0
        oracle.query.assert_called_once()

    def test_oracle_unavailable_falls_back(self) -> None:
        ctx = _make_ctx()
        move = Move("weatherball", gen=9)
        with patch(
            "pokechamp.battle_state_mapper.battle_to_oracle_payload",
            return_value=_payload("weatherball"),
        ), patch(
            "pokechamp.showdown_oracle.get_shared_oracle", return_value=None
        ), patch(
            "pokechamp.showdown_oracle.get_oracle_cache"
        ) as gc:
            cache = MagicMock()
            cache.get.return_value = _CACHE_MISS
            gc.return_value = cache
            assert (
                _resolve_move_outcome_via_oracle(
                    ctx, move, ctx.active_pokemon, ctx.opponent_pokemon
                )
                is None
            )

    def test_cache_hit_skips_query(self) -> None:
        ctx = _make_ctx()
        move = Move("weatherball", gen=9)
        cached_outcome = {
            "type": "fire",
            "base_power": None,
            "damage_pct_max": None,
            "ko": None,
        }
        with patch(
            "pokechamp.battle_state_mapper.battle_to_oracle_payload",
            return_value=_payload("weatherball"),
        ), patch(
            "pokechamp.showdown_oracle.get_shared_oracle"
        ) as gso, patch(
            "pokechamp.showdown_oracle.get_oracle_cache"
        ) as gc:
            cache = MagicMock()
            cache.get.return_value = cached_outcome
            gc.return_value = cache
            outcome = _resolve_move_outcome_via_oracle(
                ctx, move, ctx.active_pokemon, ctx.opponent_pokemon
            )
        assert outcome == cached_outcome
        gso.assert_not_called()

    def test_never_raises_on_exception(self) -> None:
        ctx = _make_ctx()
        move = Move("weatherball", gen=9)
        with patch(
            "pokechamp.battle_state_mapper.battle_to_oracle_payload",
            side_effect=RuntimeError("boom"),
        ):
            assert (
                _resolve_move_outcome_via_oracle(
                    ctx, move, ctx.active_pokemon, ctx.opponent_pokemon
                )
                is None
            )
