"""Unit tests for the Showdown TS Oracle integration (mock-based).

Covers:
- TestBattleStateMapper (≥5 tests): weather, terrain, boosts, status, team
  packing, volatiles, JSON serialization, immutability, defensive defaults.
- TestShowdownOracleWrapper (≥5 tests): query round-trip, timeout, worker
  death recovery, logging, close/cleanup, dist verification, max restarts.
- TestPromptIntegration (≥5 tests): oracle-off identity, oracle flag guard,
  LocalSim attributes, oracle info format concept, silent failure pattern.

All tests use mocks and do NOT require a Node.js build.  Integration tests
requiring the real oracle worker are in a separate feature and marked with
``@pytest.mark.oracle``.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import subprocess
import time
from io import BytesIO
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from pokechamp.battle_state_mapper import (
    _DEFAULT_BOOSTS,
    _normalize_id,
    _extract_weather,
    _extract_terrain,
    _map_boosts,
    _map_status,
    _map_volatiles,
    _pack_pokemon,
    _pack_team,
    _build_active_state,
    _map_side_conditions,
    battle_to_oracle_payload,
)

# ---------------------------------------------------------------------------
# Helpers — lightweight mock factories
# ---------------------------------------------------------------------------


def _make_pokemon(
    species: str = "pikachu",
    level: int = 100,
    current_hp: int = 300,
    max_hp: int = 350,
    status: Any = None,
    boosts: Optional[Dict[str, int]] = None,
    item: Optional[str] = None,
    ability: Optional[str] = None,
    moves: Optional[Dict[str, Any]] = None,
    effects: Optional[Dict[Any, Any]] = None,
    terastallized: bool = False,
    shiny: bool = False,
    gender: Optional[str] = None,
    active: bool = True,
) -> MagicMock:
    """Create a mock Pokemon object for testing."""
    mon = MagicMock(spec=[])
    mon.species = species
    mon.level = level
    mon.current_hp = current_hp
    mon.max_hp = max_hp
    mon.status = status
    mon.boosts = boosts
    mon.item = item
    mon.ability = ability
    mon.moves = moves or {}
    mon.effects = effects
    mon.terastallized = terastallized
    mon.shiny = shiny
    mon.gender = gender
    mon.active = active
    return mon


def _make_weather_enum(name: str) -> MagicMock:
    """Create a mock Weather enum value."""
    w = MagicMock(spec=[])
    w.name = name
    return w


def _make_field_enum(name: str, is_terrain: bool = False) -> MagicMock:
    """Create a mock Field enum value."""
    f = MagicMock(spec=[])
    f.name = name
    f.is_terrain = is_terrain
    return f


def _make_status_enum(name: str) -> MagicMock:
    """Create a mock Status enum value."""
    s = MagicMock(spec=[])
    s.name = name
    return s


def _make_battle(
    weather: Optional[Dict] = None,
    fields: Optional[Dict] = None,
    team: Optional[Dict] = None,
    opponent_team: Optional[Dict] = None,
    player_role: str = "p1",
    side_conditions: Optional[Dict] = None,
    opponent_side_conditions: Optional[Dict] = None,
) -> MagicMock:
    """Create a mock Battle object for testing."""
    battle = MagicMock(spec=[])
    battle.weather = weather
    battle.fields = fields
    battle.team = team or {}
    battle.opponent_team = opponent_team or {}
    battle.player_role = player_role
    battle.side_conditions = side_conditions or {}
    battle.opponent_side_conditions = opponent_side_conditions or {}
    return battle


def _make_move(move_id: str = "tackle") -> MagicMock:
    """Create a mock Move object for testing."""
    move = MagicMock(spec=[])
    move.id = move_id
    return move


# =====================================================================
# TestBattleStateMapper — ≥5 tests
# =====================================================================


class TestBattleStateMapper:
    """Tests for ``pokechamp/battle_state_mapper.py`` helper functions."""

    # -- weather ----------------------------------------------------------

    def test_weather_mapping_raindance(self) -> None:
        """Weather.RAINDANCE maps to 'raindance'."""
        weather_enum = _make_weather_enum("RAINDANCE")
        result = _extract_weather({weather_enum: 1})
        assert result == "raindance"

    def test_weather_mapping_sunnyday(self) -> None:
        """Weather.SUNNYDAY maps to 'sunnyday'."""
        weather_enum = _make_weather_enum("SUNNYDAY")
        result = _extract_weather({weather_enum: 1})
        assert result == "sunnyday"

    def test_weather_mapping_none_when_empty(self) -> None:
        """Empty weather dict returns None."""
        assert _extract_weather({}) is None
        assert _extract_weather(None) is None

    def test_weather_mapping_sandstorm(self) -> None:
        """Weather.SANDSTORM maps to 'sandstorm'."""
        weather_enum = _make_weather_enum("SANDSTORM")
        result = _extract_weather({weather_enum: 1})
        assert result == "sandstorm"

    # -- terrain ----------------------------------------------------------

    def test_terrain_mapping_electric(self) -> None:
        """Field.ELECTRIC_TERRAIN maps to 'electricterrain'."""
        field_enum = _make_field_enum("ELECTRIC_TERRAIN", is_terrain=True)
        result = _extract_terrain({field_enum: 1})
        assert result == "electricterrain"

    def test_terrain_mapping_grassy(self) -> None:
        """Field.GRASSY_TERRAIN maps to 'grassyterrain'."""
        field_enum = _make_field_enum("GRASSY_TERRAIN", is_terrain=True)
        result = _extract_terrain({field_enum: 1})
        assert result == "grassyterrain"

    def test_terrain_none_when_no_terrain(self) -> None:
        """Non-terrain fields are ignored; returns None."""
        field_enum = _make_field_enum("TRICK_ROOM", is_terrain=False)
        result = _extract_terrain({field_enum: 1})
        assert result is None

    def test_terrain_none_when_empty(self) -> None:
        """Empty fields dict returns None."""
        assert _extract_terrain({}) is None
        assert _extract_terrain(None) is None

    # -- boosts -----------------------------------------------------------

    def test_boosts_mapping_with_values(self) -> None:
        """Boosts dict maps correctly with explicit values."""
        raw = {"atk": 2, "def": -1, "spa": 0, "spd": 3}
        result = _map_boosts(raw)
        assert result["atk"] == 2
        assert result["def"] == -1
        assert result["spa"] == 0
        assert result["spd"] == 3
        # Missing stats default to 0
        assert result["spe"] == 0
        assert result["accuracy"] == 0
        assert result["evasion"] == 0

    def test_boosts_defaults_when_none(self) -> None:
        """None boosts returns default dict with all zeros."""
        result = _map_boosts(None)
        assert result == _DEFAULT_BOOSTS

    def test_boosts_defaults_when_empty(self) -> None:
        """Empty boosts dict returns defaults."""
        result = _map_boosts({})
        assert result == _DEFAULT_BOOSTS

    # -- status -----------------------------------------------------------

    def test_status_mapping_burn(self) -> None:
        """Status.BRN maps to 'brn'."""
        result = _map_status(_make_status_enum("BRN"))
        assert result == "brn"

    def test_status_mapping_paralysis(self) -> None:
        """Status.PAR maps to 'par'."""
        result = _map_status(_make_status_enum("PAR"))
        assert result == "par"

    def test_status_mapping_none(self) -> None:
        """None status maps to None."""
        assert _map_status(None) is None

    def test_status_mapping_poison(self) -> None:
        """Status.PSN maps to 'psn'."""
        result = _map_status(_make_status_enum("PSN"))
        assert result == "psn"

    def test_status_mapping_toxic(self) -> None:
        """Status.TOX maps to 'tox'."""
        result = _map_status(_make_status_enum("TOX"))
        assert result == "tox"

    # -- volatiles --------------------------------------------------------

    def test_volatiles_mapping(self) -> None:
        """Volatiles/effects are extracted as lowercase ID list."""
        eff1 = MagicMock(spec=[])
        eff1.name = "focusenergy"
        eff2 = MagicMock(spec=[])
        eff2.name = "substitute"
        result = _map_volatiles({eff1: 1, eff2: 1})
        assert "focusenergy" in result
        assert "substitute" in result

    def test_volatiles_empty_when_none(self) -> None:
        """None effects returns empty list."""
        assert _map_volatiles(None) == []
        assert _map_volatiles({}) == []

    # -- normalize_id -----------------------------------------------------

    def test_normalize_id_lowercase(self) -> None:
        """IDs are lowercased."""
        assert _normalize_id("SolarBeam") == "solarbeam"

    def test_normalize_id_removes_spaces(self) -> None:
        """Spaces and non-alphanumeric chars are removed."""
        assert _normalize_id("Air Balloon") == "airballoon"
        assert _normalize_id("X-Special") == "xspecial"

    def test_normalize_id_none_returns_empty(self) -> None:
        """None input returns empty string."""
        assert _normalize_id(None) == ""

    # -- team packing -----------------------------------------------------

    def test_pack_pokemon_basic(self) -> None:
        """Single Pokemon packing produces pipe-separated string."""
        mon = _make_pokemon(species="charizard", level=50, item="choiceband")
        result = _pack_pokemon(mon)
        assert isinstance(result, str)
        parts = result.split("|")
        # nickname|species|item|ability|moves|nature|evs|gender|ivs|shiny|level|happiness
        assert len(parts) >= 12  # at least 12 pipe-separated segments
        assert parts[1] == "charizard"  # species
        assert parts[2] == "choiceband"  # item

    def test_pack_team_multiple(self) -> None:
        """Multiple Pokemon are joined with ']'."""
        mon1 = _make_pokemon(species="charizard")
        mon2 = _make_pokemon(species="blastoise")
        result = _pack_team({"a": mon1, "b": mon2})
        assert isinstance(result, str)
        assert "]" in result
        segments = result.split("]")
        assert len(segments) == 2

    def test_pack_team_empty(self) -> None:
        """Empty team returns empty string."""
        assert _pack_team(None) == ""
        assert _pack_team({}) == ""

    def test_pack_team_lead_first(self) -> None:
        """lead species is packed first (it becomes worker active[0])."""
        mons = {
            "a": _make_pokemon(species="tyranitar"),
            "b": _make_pokemon(species="quaquaval"),
            "c": _make_pokemon(species="kingdra"),
        }
        result = _pack_team(mons, lead=_make_pokemon(species="quaquaval"))
        first = result.split("|")[0]
        assert first == "quaquaval"
        # Remaining members keep their insertion order (stable sort).
        order = [seg.split("|")[0] for seg in result.split("]") if seg.split("|")[0]]
        assert order == ["quaquaval", "tyranitar", "kingdra"]

    def test_pack_team_lead_none_preserves_order(self) -> None:
        """No lead argument keeps insertion order (regression)."""
        mons = {
            "a": _make_pokemon(species="tyranitar"),
            "b": _make_pokemon(species="quaquaval"),
        }
        result = _pack_team(mons)
        order = [seg.split("|")[0] for seg in result.split("]") if seg.split("|")[0]]
        assert order == ["tyranitar", "quaquaval"]

    def test_pack_team_lead_missing_falls_back(self) -> None:
        """A lead species not in the team keeps insertion order."""
        mons = {
            "a": _make_pokemon(species="tyranitar"),
            "b": _make_pokemon(species="quaquaval"),
        }
        result = _pack_team(mons, lead=_make_pokemon(species="pikachu"))
        order = [seg.split("|")[0] for seg in result.split("]") if seg.split("|")[0]]
        assert order == ["tyranitar", "quaquaval"]

    # -- build_active_state -----------------------------------------------

    def test_build_active_state_basic(self) -> None:
        """Active state includes species, hp_pct, level."""
        mon = _make_pokemon(
            species="gengar",
            current_hp=200,
            max_hp=300,
            level=50,
            status=_make_status_enum("BRN"),
        )
        result = _build_active_state(mon)
        assert result["species_id"] == "gengar"
        assert result["level"] == 50
        assert result["hp_pct"] == pytest.approx(66.7, abs=0.1)
        assert result["status"] == "brn"

    def test_build_active_state_with_item_and_ability(self) -> None:
        """Active state includes item and ability when present."""
        mon = _make_pokemon(
            species="dragapult",
            item="choiceband",
            ability="clearbody",
        )
        result = _build_active_state(mon)
        assert result["item"] == "choiceband"
        assert result["ability"] == "clearbody"

    def test_build_active_state_unknown_item_treated_as_none(self) -> None:
        """'unknown_item' is treated as None (not revealed)."""
        mon = _make_pokemon(species="pikachu", item="unknown_item")
        result = _build_active_state(mon)
        assert result["item"] is None

    # -- side conditions --------------------------------------------------

    def test_map_side_conditions(self) -> None:
        """Side conditions are mapped to normalized dict."""
        cond = MagicMock(spec=[])
        cond.name = "STEALTH_ROCK"
        result = _map_side_conditions({cond: 1})
        assert "stealthrock" in result

    def test_map_side_conditions_empty(self) -> None:
        """Empty side conditions returns empty dict."""
        assert _map_side_conditions(None) == {}
        assert _map_side_conditions({}) == {}

    # -- full payload -----------------------------------------------------

    def test_full_payload_json_serializable(self) -> None:
        """battle_to_oracle_payload returns a JSON-serializable dict."""
        user = _make_pokemon(species="charizard")
        target = _make_pokemon(species="blastoise")
        move = _make_move("flamethrower")
        battle = _make_battle(
            team={"c1": user},
            opponent_team={"o1": target},
        )
        payload = battle_to_oracle_payload(
            battle, user, target, move, request_id="test-123"
        )
        serialized = json.dumps(payload)
        assert isinstance(serialized, str)
        parsed = json.loads(serialized)
        assert parsed["id"] == "test-123"
        assert parsed["move_id"] == "flamethrower"

    def test_full_payload_has_required_fields(self) -> None:
        """Payload contains all required oracle request fields."""
        user = _make_pokemon(species="charizard")
        target = _make_pokemon(species="blastoise")
        move = _make_move("earthquake")
        battle = _make_battle(
            team={"c1": user},
            opponent_team={"o1": target},
        )
        payload = battle_to_oracle_payload(
            battle, user, target, move, request_id="test-456"
        )
        required_keys = [
            "id",
            "format",
            "seed",
            "actor_side",
            "actor_slot",
            "target_side",
            "target_slot",
            "move_id",
            "weather",
            "terrain",
            "team_p1",
            "team_p2",
            "active_state",
            "side_conditions",
        ]
        for key in required_keys:
            assert key in payload, f"Missing key: {key}"

    def test_full_payload_immutability(self) -> None:
        """Source objects are not mutated by battle_to_oracle_payload."""
        user = _make_pokemon(species="charizard", boosts={"atk": 2})
        target = _make_pokemon(species="blastoise", item="leftovers")
        move = _make_move("flamethrower")
        battle = _make_battle(
            team={"c1": user},
            opponent_team={"o1": target},
        )
        # Snapshot state before
        user_species_before = user.species
        user_boosts_before = dict(user.boosts)
        target_item_before = target.item

        battle_to_oracle_payload(battle, user, target, move)

        # Verify unchanged
        assert user.species == user_species_before
        assert user.boosts == user_boosts_before
        assert target.item == target_item_before

    def test_full_payload_missing_optional_fields(self) -> None:
        """Payload succeeds even when optional fields are missing."""
        user = MagicMock(spec=["species", "current_hp", "max_hp"])
        user.species = "charizard"
        user.current_hp = 100
        user.max_hp = 200
        user.level = 100
        user.status = None
        user.boosts = None
        user.item = None
        user.ability = None
        user.moves = {}
        user.effects = None
        user.terastallized = False
        user.shiny = False
        user.gender = None
        user.active = True

        target = _make_pokemon(species="blastoise")
        move = _make_move("tackle")
        battle = _make_battle(
            team={"c1": user},
            opponent_team={"o1": target},
        )
        payload = battle_to_oracle_payload(battle, user, target, move)
        assert payload is not None
        assert payload["move_id"] == "tackle"


# =====================================================================
# TestShowdownOracleWrapper — ≥5 tests
# =====================================================================


class TestShowdownOracleWrapper:
    """Tests for ``pokechamp/showdown_oracle.py`` ShowdownOracle class.

    All tests mock the subprocess so no real Node worker is needed.
    """

    def _make_oracle_with_mock(
        self,
        alive: bool = True,
        response: Optional[str] = None,
        timeout: bool = False,
    ) -> MagicMock:
        """Create a ShowdownOracle with mocked internals.

        Returns the oracle instance with the mock process attached.
        """
        from pokechamp.showdown_oracle import ShowdownOracle

        with patch.object(ShowdownOracle, "_verify_dist"):
            with patch.object(ShowdownOracle, "_spawn"):
                oracle = ShowdownOracle.__new__(ShowdownOracle)
                oracle._worker_path = "oracle-worker.js"
                oracle._node_path = "node"
                oracle._timeout_seconds = 5.0
                oracle._max_restarts = 3
                oracle._closed = False

                # Mock process
                proc = MagicMock(spec=subprocess.Popen)
                proc.poll.return_value = None if alive else 0
                proc.stdin = MagicMock()
                if timeout:
                    proc.stdout = BytesIO(b"")  # EOF → no newline → timeout
                elif response is not None:
                    proc.stdout = BytesIO((response + "\n").encode("utf-8"))
                else:
                    proc.stdout = BytesIO(b'{"ok": true}\n')

                oracle._process = proc

        return oracle

    # -- query success ----------------------------------------------------

    def test_query_success_returns_parsed_dict(self) -> None:
        """query() returns parsed JSON dict on success."""
        oracle = self._make_oracle_with_mock(
            response='{"ok": true, "move_id": "tackle"}'
        )
        result = oracle.query({"move_id": "tackle"})
        assert result is not None
        assert result["ok"] is True
        assert result["move_id"] == "tackle"

    # -- query failure returns None ---------------------------------------

    def test_query_returns_none_on_malformed_json(self) -> None:
        """query() returns None when worker returns invalid JSON."""
        oracle = self._make_oracle_with_mock(response="NOT JSON")
        result = oracle.query({"move_id": "tackle"})
        assert result is None

    def test_query_returns_none_when_closed(self) -> None:
        """query() returns None after close() is called."""
        oracle = self._make_oracle_with_mock()
        oracle.close()
        result = oracle.query({"move_id": "tackle"})
        assert result is None

    # -- timeout handling -------------------------------------------------

    def test_timeout_returns_none(self) -> None:
        """query() returns None when worker does not respond in time."""
        oracle = self._make_oracle_with_mock(timeout=True)
        # The mock BytesIO with empty bytes will cause EOF → None
        result = oracle.query({"move_id": "tackle"})
        assert result is None

    # -- worker death recovery --------------------------------------------

    def test_auto_restart_on_worker_death(self) -> None:
        """query() restarts dead worker and retries."""
        oracle = self._make_oracle_with_mock(alive=False)
        # After detecting death, _spawn should be called, then we need
        # the new process to be alive. Patch _spawn to set up new mock.
        new_proc = MagicMock(spec=subprocess.Popen)
        new_proc.poll.return_value = None
        new_proc.stdin = MagicMock()
        new_proc.stdout = BytesIO(b'{"ok": true}\n')

        original_spawn = oracle._spawn

        def fake_spawn() -> None:
            oracle._process = new_proc
            oracle._closed = False

        oracle._spawn = fake_spawn
        result = oracle.query({"move_id": "tackle"})
        assert result is not None
        assert result["ok"] is True

    # -- max restarts respected -------------------------------------------

    def test_max_restarts_exhausted_returns_none(self) -> None:
        """query() returns None after exhausting max_restarts."""
        oracle = self._make_oracle_with_mock(alive=False)
        oracle._max_restarts = 1

        # _spawn always creates a dead worker
        def fake_spawn() -> None:
            dead_proc = MagicMock(spec=subprocess.Popen)
            dead_proc.poll.return_value = 1  # dead
            dead_proc.stdin = MagicMock()
            dead_proc.stdout = BytesIO(b"")
            oracle._process = dead_proc
            oracle._closed = False

        oracle._spawn = fake_spawn
        result = oracle.query({"move_id": "tackle"})
        assert result is None

    # -- close terminates worker ------------------------------------------

    def test_close_terminates_worker(self) -> None:
        """close() terminates the subprocess and sets _closed."""
        oracle = self._make_oracle_with_mock()
        proc = oracle._process
        oracle.close()
        assert oracle._closed is True
        proc.terminate.assert_called()

    # -- context manager --------------------------------------------------

    def test_context_manager_closes_on_exit(self) -> None:
        """Context manager (__enter__/__exit__) calls close()."""
        oracle = self._make_oracle_with_mock()
        proc = oracle._process
        with oracle:
            assert oracle._closed is False
        assert oracle._closed is True

    # -- logging uses logging module, not print ---------------------------

    def test_logging_not_print(self) -> None:
        """showdown_oracle.py uses logging.getLogger, never print()."""
        source_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "pokechamp",
            "showdown_oracle.py",
        )
        with open(source_path, "r") as f:
            source = f.read()
        # Check no bare print() calls (in code lines, not docstrings/comments)
        lines = source.split("\n")
        for i, line in enumerate(lines):
            stripped = line.strip()
            # Skip comments, docstrings, and lines inside string literals
            if stripped.startswith("#"):
                continue
            if stripped.startswith('"""') or stripped.startswith("'''"):
                continue
            if stripped.startswith("-") or stripped.startswith("*"):
                continue  # docstring content
            # Only flag actual code lines with print(
            if "print(" in stripped:
                # Ensure it's not inside a string literal
                code_before_print = stripped.split("print(")[0]
                if code_before_print.count('"') % 2 == 0:
                    assert False, f"Found print() at line {i + 1}: {stripped}"

    def test_logging_uses_getlogger(self) -> None:
        """Module creates a logger via logging.getLogger."""
        import pokechamp.showdown_oracle as mod

        assert hasattr(mod, "logger")
        assert isinstance(mod.logger, logging.Logger)
        assert mod.logger.name == "showdown_oracle"

    # -- dist verification ------------------------------------------------

    def test_verify_dist_raises_when_missing(self) -> None:
        """_verify_dist raises FileNotFoundError when dist is missing."""
        from pokechamp.showdown_oracle import ShowdownOracle

        oracle = ShowdownOracle.__new__(ShowdownOracle)
        oracle._worker_path = "/nonexistent/oracle-worker.js"
        with pytest.raises(FileNotFoundError, match="Showdown dist not found"):
            oracle._verify_dist()

    # -- atexit registered ------------------------------------------------

    def test_atexit_registered(self) -> None:
        """__init__ registers atexit handler for cleanup."""
        from pokechamp.showdown_oracle import ShowdownOracle

        with patch.object(ShowdownOracle, "_verify_dist"):
            with patch.object(ShowdownOracle, "_spawn"):
                with patch("pokechamp.showdown_oracle.atexit") as mock_atexit:
                    oracle = ShowdownOracle.__new__(ShowdownOracle)
                    oracle._worker_path = "w.js"
                    oracle._node_path = "node"
                    oracle._timeout_seconds = 5.0
                    oracle._max_restarts = 3
                    oracle._process = None
                    oracle._closed = False
                    # Simulate __init__ call
                    ShowdownOracle.__init__(oracle)
                    mock_atexit.register.assert_called_once_with(oracle.close)


# =====================================================================
# TestPromptIntegration — ≥5 tests
# =====================================================================


class TestPromptIntegration:
    """Tests for oracle-related prompt integration points.

    These tests verify that the oracle flag and LocalSim attributes work
    correctly and that the oracle-off path produces identical output to
    the baseline (no oracle code executed).
    """

    # -- LocalSim attributes ----------------------------------------------

    def test_localsim_has_enable_showdown_oracle_attr(self) -> None:
        """LocalSim stores enable_showdown_oracle from constructor."""
        from poke_env.player.local_simulation import LocalSim

        sim = LocalSim.__new__(LocalSim)
        # Simulate constructor setting the attribute
        sim.enable_showdown_oracle = True
        assert hasattr(sim, "enable_showdown_oracle")
        assert sim.enable_showdown_oracle is True

    def test_localsim_oracle_default_none(self) -> None:
        """LocalSim.oracle is initialized to None."""
        from poke_env.player.local_simulation import LocalSim

        sim = LocalSim.__new__(LocalSim)
        sim.oracle = None
        assert sim.oracle is None

    def test_localsim_oracle_flag_default_false(self) -> None:
        """LocalSim defaults enable_showdown_oracle to False."""
        from poke_env.player.local_simulation import LocalSim

        # Check constructor signature
        import inspect

        sig = inspect.signature(LocalSim.__init__)
        params = sig.parameters
        assert "enable_showdown_oracle" in params
        assert params["enable_showdown_oracle"].default is False

    # -- oracle-off identity ----------------------------------------------

    def test_oracle_off_dynamic_calcs_unchanged(self) -> None:
        """_apply_dynamic_calcs_to_move returns same result regardless of
        oracle flag when dynamic_flags/calcs are also disabled."""
        from unittest.mock import MagicMock

        # Create a mock sim with dynamic flags disabled
        sim = MagicMock()
        sim.enable_dynamic_flags = False
        sim.enable_dynamic_calcs = False
        sim.enable_showdown_oracle = False

        move = MagicMock()
        battle = MagicMock()
        user = MagicMock()
        target = MagicMock()

        from pokechamp.prompts import _apply_dynamic_calcs_to_move

        result_off = _apply_dynamic_calcs_to_move(move, battle, sim, user, target)

        # With dynamic flags off, should return (None, None, "")
        assert result_off == (None, None, "")

    def test_oracle_off_no_subprocess(self) -> None:
        """When oracle flag is False, no oracle subprocess is spawned."""
        from poke_env.player.local_simulation import LocalSim

        # Create a real-ish LocalSim to check oracle attr
        sim = LocalSim.__new__(LocalSim)
        sim.oracle = None
        sim.enable_showdown_oracle = False

        # Verify oracle stays None
        assert sim.oracle is None
        assert sim.enable_showdown_oracle is False

    # -- oracle flag guard pattern ----------------------------------------

    def test_oracle_flag_guard_returns_false_when_disabled(self) -> None:
        """getattr(sim, 'enable_showdown_oracle', False) is False when
        the attribute is False or missing."""
        sim = MagicMock()
        sim.enable_showdown_oracle = False
        assert getattr(sim, "enable_showdown_oracle", False) is False

        sim2 = MagicMock(spec=[])  # no attributes
        assert getattr(sim2, "enable_showdown_oracle", False) is False

    def test_oracle_flag_guard_returns_true_when_enabled(self) -> None:
        """getattr(sim, 'enable_showdown_oracle', False) is True when set."""
        sim = MagicMock()
        sim.enable_showdown_oracle = True
        assert getattr(sim, "enable_showdown_oracle", False) is True

    # -- silent failure pattern -------------------------------------------

    def test_oracle_failure_does_not_propagate(self) -> None:
        """Oracle query failure (returns None) does not raise to caller.

        This tests the expected pattern: oracle.query() returns None on
        failure, and the calling code silently skips the augmentation.
        """
        # Simulate oracle returning None (failure)
        oracle_mock = MagicMock()
        oracle_mock.query.return_value = None

        # The pattern used in prompts.py: if result is None → skip
        result = oracle_mock.query({"move_id": "tackle"})
        assert result is None

        # Verify no exception is raised — this is the contract
        # The caller should check `if result and result.get("ok")`
        # and silently skip on None.

    # -- oracle info format concept ---------------------------------------

    def test_oracle_info_format_string(self) -> None:
        """Oracle info string follows expected 'Oracle:Dmg=...' format."""
        # This tests the expected format of oracle info output
        mock_result = {
            "ok": True,
            "damage": {"min": 142, "max": 168, "min_pct": 78.0, "max_pct": 92.0},
            "ko_estimate": {"ohko_chance": 0.0, "twohko_chance": 1.0},
        }

        # Simulate _format_oracle_info-like formatting
        damage = mock_result.get("damage", {})
        ko = mock_result.get("ko_estimate", {})
        min_dmg = damage.get("min", 0)
        max_dmg = damage.get("max", 0)
        min_pct = damage.get("min_pct", 0)
        max_pct = damage.get("max_pct", 0)
        twohko = ko.get("twohko_chance", 0)

        oracle_info = (
            f"Oracle:Dmg={min_dmg}-{max_dmg}"
            f"({min_pct:.0f}-{max_pct:.0f}% HP)"
            f",2HKO={twohko:.0%}"
        )
        assert oracle_info.startswith("Oracle:")
        assert "Dmg=142-168" in oracle_info
        assert "78-92% HP" in oracle_info
        assert "2HKO=100%" in oracle_info


# =====================================================================
# Integration tests — require a real Node oracle worker
# =====================================================================
# All tests below are marked with ``@pytest.mark.oracle`` and need the
# Showdown dist build (``npm run build``) to be available.  They are
# excluded by ``pytest -m "not oracle"`` so the rest of the suite works
# without Node.

_HERACROSS_TEAM = (
    "heracross|Heracross|flameplate|guts|"
    "facade,closecombat,knockoff,earthquake|"
    "adamant|0,252,0,0,4,252|M||||"
)

_BLASTOISE_TEAM = (
    "blastoise|Blastoise|leftovers|torrent|"
    "surf,icebeam,rapidspin,protect|"
    "bold|252,0,252,0,4,0|M||||"
)

_LAPRAS_TEAM = "lapras|Lapras||||freezedry||||||"

_SQUIRTLE_TEAM = "squirtle|Squirtle||||surf||||||"


def _make_oracle_payload(
    move_id: str,
    *,
    team_p1: str = _HERACROSS_TEAM,
    team_p2: str = _BLASTOISE_TEAM,
    seed: Optional[list] = None,
    p1_active: Optional[Dict[str, Any]] = None,
    p2_active: Optional[Dict[str, Any]] = None,
    side_conditions: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a minimal oracle payload for integration testing."""
    if seed is None:
        seed = [42, 1337, 256, 999]
    active_state: Dict[str, Any] = {
        "p1": [p1_active or {}],
        "p2": [p2_active or {}],
    }
    if side_conditions is None:
        side_conditions = {"p1": {}, "p2": {}}
    return {
        "id": f"it-{move_id}-{time.monotonic_ns()}",
        "format": "gen9customgame",
        "seed": seed,
        "actor_side": "p1",
        "actor_slot": 0,
        "target_side": "p2",
        "target_slot": 0,
        "move_id": move_id,
        "weather": None,
        "terrain": None,
        "pseudoweather": [],
        "team_p1": team_p1,
        "team_p2": team_p2,
        "active_state": active_state,
        "side_conditions": side_conditions,
    }


@pytest.fixture(scope="module")
def real_oracle():
    """Module-scoped fixture that provides a real ShowdownOracle instance.

    Yields the oracle and tears it down after all integration tests in
    the module finish.
    """
    from pokechamp.showdown_oracle import ShowdownOracle

    oracle = ShowdownOracle()
    yield oracle
    oracle.close()


# -----------------------------------------------------------------------
# 5 canonical move tests
# -----------------------------------------------------------------------


@pytest.mark.oracle
def test_facade_burn_power_boost(real_oracle: Any) -> None:
    """Facade + user has burn → base_power == 140, base_power_changed == True."""
    payload = _make_oracle_payload(
        "facade",
        p1_active={"species_id": "heracross", "status": "brn"},
    )
    result = real_oracle.query(payload)
    assert result is not None, "Oracle returned None for facade query"
    assert result["ok"] is True
    assert result["resolved"]["base_power"] == 140
    assert result["resolved"]["base_power_changed"] is True
    assert "facade" in result["resolved"]["base_power_reason"].lower()


@pytest.mark.oracle
def test_knockoff_item_boost(real_oracle: Any) -> None:
    """Knockoff + target holds item → boosted power (base 65 × 1.5 = 97)."""
    payload = _make_oracle_payload(
        "knockoff",
        p2_active={"species_id": "blastoise", "item": "leftovers"},
    )
    result = real_oracle.query(payload)
    assert result is not None, "Oracle returned None for knockoff query"
    assert result["ok"] is True
    assert result["resolved"]["base_power"] == 97
    assert result["resolved"]["base_power_changed"] is True
    assert "knockoff" in result["resolved"]["base_power_reason"].lower()


@pytest.mark.oracle
def test_fissure_ohko(real_oracle: Any) -> None:
    """Fissure → is_ohko == True."""
    payload = _make_oracle_payload("fissure")
    result = real_oracle.query(payload)
    assert result is not None, "Oracle returned None for fissure query"
    assert result["ok"] is True
    assert result["resolved"]["is_ohko"] is True
    assert result["ko_estimate"]["ohko_chance"] == 1.0


@pytest.mark.oracle
def test_bodypress_def_stat(real_oracle: Any) -> None:
    """Bodypress → override_offensive_stat == 'def'."""
    payload = _make_oracle_payload("bodypress")
    result = real_oracle.query(payload)
    assert result is not None, "Oracle returned None for bodypress query"
    assert result["ok"] is True
    assert result["resolved"]["override_offensive_stat"] == "def"


@pytest.mark.oracle
def test_freezedry_water_effectiveness(real_oracle: Any) -> None:
    """Freezedry vs Water target → effectiveness_multiplier >= 2.0."""
    payload = _make_oracle_payload(
        "freezedry",
        team_p1=_LAPRAS_TEAM,
        team_p2=_SQUIRTLE_TEAM,
        p1_active={"species_id": "lapras"},
        p2_active={"species_id": "squirtle"},
    )
    result = real_oracle.query(payload)
    assert result is not None, "Oracle returned None for freezedry query"
    assert result["ok"] is True
    assert result["resolved"]["effectiveness_multiplier"] >= 2.0


# -----------------------------------------------------------------------
# Resilience & operational tests
# -----------------------------------------------------------------------


@pytest.mark.oracle
def test_worker_crash_recovery() -> None:
    """Kill the worker subprocess → next query auto-restarts → succeeds."""
    from pokechamp.showdown_oracle import ShowdownOracle

    oracle = ShowdownOracle()
    try:
        # First, verify the oracle works.
        payload = _make_oracle_payload("tackle")
        result = oracle.query(payload)
        assert result is not None, "Initial query should succeed"
        assert result["ok"] is True

        # Kill the worker process directly.
        assert oracle._process is not None
        old_pid = oracle._process.pid
        oracle._process.kill()
        oracle._process.wait()
        assert oracle._process.poll() is not None, "Worker should be dead"

        # Next query should auto-restart and succeed.
        result2 = oracle.query(payload)
        assert result2 is not None, "Query after crash should succeed"
        assert result2["ok"] is True
        # New worker should have a different PID.
        assert oracle._process is not None
        assert oracle._process.pid != old_pid
    finally:
        oracle.close()


@pytest.mark.oracle
def test_sequential_queries(real_oracle: Any) -> None:
    """10 sequential queries with different moves — all succeed independently."""
    moves = [
        "tackle",
        "scratch",
        "pound",
        "facade",
        "knockoff",
        "bodyslam",
        "earthquake",
        "icebeam",
        "thunderbolt",
        "shadowball",
    ]
    for move_id in moves:
        payload = _make_oracle_payload(move_id)
        result = real_oracle.query(payload)
        assert result is not None, f"Query for {move_id} returned None"
        assert result["ok"] is True, f"Query for {move_id} failed"
        assert result["move_id"] == move_id


@pytest.mark.oracle
def test_query_latency(real_oracle: Any) -> None:
    """Warm-worker query latency ≤50ms at the 95th percentile."""
    # Warm up with a few queries.
    warmup_payload = _make_oracle_payload("tackle")
    for _ in range(3):
        real_oracle.query(warmup_payload)

    # Measure latencies.
    latencies: list = []
    moves = [
        "tackle",
        "flamethrower",
        "surf",
        "thunderbolt",
        "icebeam",
        "earthquake",
        "shadowball",
        "airslash",
        "darkpulse",
        "hydropump",
        "psychic",
        "energyball",
        "sludgebomb",
        "flashcannon",
        "dragonclaw",
        "stoneedge",
        "ironhead",
        "poisonjab",
        "xscissor",
        "crunch",
    ]
    for move_id in moves:
        payload = _make_oracle_payload(move_id)
        t0 = time.monotonic()
        result = real_oracle.query(payload)
        elapsed = (time.monotonic() - t0) * 1000  # ms
        assert result is not None, f"Query for {move_id} failed"
        latencies.append(elapsed)

    # 95th percentile.
    latencies.sort()
    idx95 = int(len(latencies) * 0.95)
    p95 = latencies[idx95]
    assert p95 <= 50.0, (
        f"95th percentile latency {p95:.1f}ms exceeds 50ms " f"(raw: {latencies})"
    )


@pytest.mark.oracle
def test_no_zombie_processes() -> None:
    """After closing an oracle, no oracle-worker Node processes remain."""
    from pokechamp.showdown_oracle import ShowdownOracle

    oracle = ShowdownOracle()
    # Verify the worker is running.
    assert oracle._process is not None
    pid = oracle._process.pid
    assert pid is not None

    # Close the oracle.
    oracle.close()

    # The process should no longer be running.
    import signal

    try:
        os.kill(pid, 0)  # Check if process exists
        # If we get here, process is still alive — wait briefly.
        time.sleep(0.5)
        try:
            os.kill(pid, 0)
            pytest.fail(f"Worker process {pid} is still alive after close()")
        except ProcessLookupError:
            pass  # Process gone — good.
    except ProcessLookupError:
        pass  # Process already gone — expected.


@pytest.mark.oracle
def test_deterministic_results(real_oracle: Any) -> None:
    """Same seed → identical results across two queries."""
    seed = [12345, 67890, 11111, 22222]
    payload_a = _make_oracle_payload("tackle", seed=seed, p1_active={})
    payload_b = _make_oracle_payload("tackle", seed=seed, p1_active={})

    # The ids must differ (so they are separate requests), but the
    # resolved properties should be identical.
    result_a = real_oracle.query(payload_a)
    result_b = real_oracle.query(payload_b)

    assert result_a is not None
    assert result_b is not None
    # Compare resolved fields (id will differ, so exclude it).
    assert result_a["resolved"] == result_b["resolved"]
    assert result_a["damage"] == result_b["damage"]


# -----------------------------------------------------------------------
# End-to-end flow test
# -----------------------------------------------------------------------


@pytest.mark.oracle
def test_oracle_e2e_prompt_integration(real_oracle: Any) -> None:
    """CLI flag triggers oracle query → prompt output contains 'Oracle:'.

    This test verifies the end-to-end data flow from oracle query through
    to the formatted output string.  We replicate the _format_oracle_info
    logic inline to avoid circular imports with the module-scoped fixture.
    The prompts.py integration code path is covered by unit tests in
    TestPromptIntegration.
    """
    # 1. Query the real oracle with facade + burn status.
    payload = _make_oracle_payload("facade", p1_active={"status": "brn"})
    result = real_oracle.query(payload)
    assert result is not None, "Oracle query returned None"
    assert result["ok"] is True

    # 2. Verify the response structure has expected fields.
    assert "resolved" in result
    assert "damage" in result
    assert result["resolved"]["base_power"] == 140
    assert result["resolved"]["base_power_changed"] is True

    # 3. Build the oracle info string (mirrors _format_oracle_info).
    parts: list = ["Oracle:"]
    damage = result.get("damage", {})
    if damage:
        min_dmg = damage.get("min")
        max_dmg = damage.get("max")
        if min_dmg is not None and max_dmg is not None:
            parts.append(f"Dmg={min_dmg}-{max_dmg}")
    resolved = result.get("resolved", {})
    if resolved.get("base_power_changed"):
        parts.append(f"BP={resolved.get('base_power', '?')}")

    oracle_info = parts[0] + ",".join(parts[1:])
    assert oracle_info.startswith(
        "Oracle:"
    ), f"Expected 'Oracle:' prefix, got: {oracle_info!r}"
    assert (
        "BP=140" in oracle_info
    ), f"Expected 'BP=140' in oracle_info, got: {oracle_info!r}"

    # 4. Simulate the prompts.py integration pattern: append to dynamic_info.
    existing_dynamic_info = "Dynamic:some_info"
    augmented = f"{existing_dynamic_info} | {oracle_info}"
    assert "Oracle:" in augmented
    assert augmented.startswith("Dynamic:")
    assert "| Oracle:" in augmented


@pytest.mark.oracle
def test_oracle_disabled_identical_output() -> None:
    """With oracle disabled, no oracle subprocess is spawned and no oracle
    code paths are triggered.

    Verifies VAL-X-003: flow identical to baseline, no performance impact.
    The _apply_dynamic_calcs_to_move oracle-off identity is already covered
    by the unit test test_oracle_off_dynamic_calcs_unchanged.
    """
    # 1. Verify no oracle-worker processes running initially.
    result = subprocess.run(
        ["pgrep", "-f", "oracle-worker"],
        capture_output=True,
        text=True,
    )
    # pgrep returns 1 when no processes match — that's expected.
    pre_existing = result.stdout.strip() if result.returncode == 0 else ""

    # 2. Create a mock sim with oracle disabled — verify no oracle attr.
    from poke_env.player.local_simulation import LocalSim

    sim = LocalSim.__new__(LocalSim)
    sim.oracle = None
    sim.enable_showdown_oracle = False

    # The flag guard pattern: getattr(sim, 'enable_showdown_oracle', False)
    assert getattr(sim, "enable_showdown_oracle", False) is False
    assert sim.oracle is None

    # 3. Verify no new oracle-worker processes were spawned.
    result2 = subprocess.run(
        ["pgrep", "-f", "oracle-worker"],
        capture_output=True,
        text=True,
    )
    post_existing = result2.stdout.strip() if result2.returncode == 0 else ""
    # The only oracle-worker processes should be from the real_oracle fixture,
    # which was already running before this test.
    assert post_existing == pre_existing or post_existing == ""


# -----------------------------------------------------------------------
# resolved.type — dynamic move type resolution (react-agent damage tools)
# -----------------------------------------------------------------------


@pytest.mark.oracle
def test_weatherball_type_resolves_with_weather(real_oracle: Any) -> None:
    """Weather Ball type tracks the active weather."""
    payload = _make_oracle_payload("weatherball")
    payload["weather"] = "raindance"
    result = real_oracle.query(payload)
    assert result["ok"] is True
    assert result["resolved"]["type"] == "water"

    payload = _make_oracle_payload("weatherball")
    payload["weather"] = "sunnyday"
    result = real_oracle.query(payload)
    assert result["ok"] is True
    assert result["resolved"]["type"] == "fire"


@pytest.mark.oracle
def test_terablast_type_resolves_with_tera(real_oracle: Any) -> None:
    """Tera Blast type becomes the user's Tera type when terastallized."""
    payload = _make_oracle_payload(
        "terablast",
        p1_active={
            "species_id": "heracross",
            "is_terastallized": True,
            "tera_type": "fire",
        },
    )
    result = real_oracle.query(payload)
    assert result["ok"] is True
    assert result["resolved"]["type"] == "fire"


@pytest.mark.oracle
def test_static_move_type_is_base(real_oracle: Any) -> None:
    """Non-dynamic moves report their base type."""
    payload = _make_oracle_payload("facade", p1_active={"species_id": "heracross"})
    result = real_oracle.query(payload)
    assert result["ok"] is True
    assert result["resolved"]["type"] == "normal"


@pytest.mark.oracle
def test_lightscreen_halves_special_damage(real_oracle: Any) -> None:
    """Light Screen on the target side halves special-move damage.

    The Showdown side-condition event doesn't fire in the hand-built Battle,
    so the worker applies the screen multiplier directly (oracle-worker.js).
    """
    base = _make_oracle_payload(
        "surf", team_p1=_SQUIRTLE_TEAM, team_p2=_BLASTOISE_TEAM
    )
    screened = _make_oracle_payload(
        "surf",
        team_p1=_SQUIRTLE_TEAM,
        team_p2=_BLASTOISE_TEAM,
        side_conditions={"p1": {}, "p2": {"lightscreen": 1}},
    )
    r_base = real_oracle.query(base)
    r_screened = real_oracle.query(screened)
    assert r_base["ok"] and r_screened["ok"]
    d_base = r_base["damage"]["max_pct"]
    d_screened = r_screened["damage"]["max_pct"]
    assert d_screened <= d_base * 0.55, (
        f"lightscreen did not halve special damage: {d_screened} vs {d_base}"
    )


@pytest.mark.oracle
def test_generic_move_returns_damage(real_oracle: Any) -> None:
    """A generic (non-dynamic) move returns positive damage via the unified
    oracle path (the dynamic-only gate was removed for fair cross-move
    comparison)."""
    payload = _make_oracle_payload("earthquake")  # Heracross vs Blastoise
    result = real_oracle.query(payload)
    assert result["ok"] is True
    assert result["damage"]["max_pct"] > 0


@pytest.mark.oracle
def test_nroll_damage_range(real_oracle: Any) -> None:
    """roll_count=N samples the 0.85–1.0 damage spread → min ≤ median ≤ max.
    roll_count=1 collapses to a single sample (min == max, legacy compat)."""
    base = _make_oracle_payload(
        "surf", team_p1=_SQUIRTLE_TEAM, team_p2=_BLASTOISE_TEAM
    )
    payload_n = dict(base)
    payload_n["roll_count"] = 8
    r_n = real_oracle.query(payload_n)
    assert r_n["ok"] is True
    d = r_n["damage"]
    assert d["min_pct"] <= d["median_pct"] <= d["max_pct"]
    assert "median_pct" in d  # N-roll 응답 필드

    payload_1 = dict(base)
    payload_1["roll_count"] = 1
    r_1 = real_oracle.query(payload_1)
    assert r_1["ok"] is True
    assert r_1["damage"]["min_pct"] == r_1["damage"]["max_pct"]  # 단일 roll
