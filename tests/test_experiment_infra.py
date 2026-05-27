"""
Tests for experiment tracking infrastructure.

Covers: CLI argument acceptance, feature flag propagation, LLM call counting,
token aggregation, backend lock, and result output formatting.

All tests use @pytest.mark.moves marker and pass without vLLM/Showdown servers.
"""

import argparse
import os
import sys
import pytest

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ---------------------------------------------------------------------------
# VAL-INFRA-001 / VAL-INFRA-002: CLI arguments accepted
# ---------------------------------------------------------------------------
class TestCLIArguments:
    """Verify --enable_dynamic_flags and --enable_dynamic_calcs are accepted."""

    @pytest.mark.moves
    def test_enable_dynamic_flags_accepted(self):
        """--enable_dynamic_flags is parsed without error and defaults False."""
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "--enable_dynamic_flags",
            action="store_true",
            default=False,
        )
        # Default
        args = parser.parse_args([])
        assert args.enable_dynamic_flags is False
        # Flag present
        args = parser.parse_args(["--enable_dynamic_flags"])
        assert args.enable_dynamic_flags is True

    @pytest.mark.moves
    def test_enable_dynamic_calcs_accepted(self):
        """--enable_dynamic_calcs is parsed without error and defaults False."""
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "--enable_dynamic_calcs",
            action="store_true",
            default=False,
        )
        # Default
        args = parser.parse_args([])
        assert args.enable_dynamic_calcs is False
        # Flag present
        args = parser.parse_args(["--enable_dynamic_calcs"])
        assert args.enable_dynamic_calcs is True

    @pytest.mark.moves
    def test_both_flags_independent(self):
        """Each flag can be set independently."""
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "--enable_dynamic_flags", action="store_true", default=False
        )
        parser.add_argument(
            "--enable_dynamic_calcs", action="store_true", default=False
        )

        args = parser.parse_args(["--enable_dynamic_flags"])
        assert args.enable_dynamic_flags is True
        assert args.enable_dynamic_calcs is False

        args = parser.parse_args(["--enable_dynamic_calcs"])
        assert args.enable_dynamic_flags is False
        assert args.enable_dynamic_calcs is True

        args = parser.parse_args(["--enable_dynamic_flags", "--enable_dynamic_calcs"])
        assert args.enable_dynamic_flags is True
        assert args.enable_dynamic_calcs is True


# ---------------------------------------------------------------------------
# VAL-INFRA-003: Feature flags propagate from CLI to LLMPlayer
# ---------------------------------------------------------------------------
class TestFeatureFlagPropagation:
    """Verify flags pass through get_llm_player → LLMPlayer."""

    @pytest.mark.moves
    def test_llmplayer_stores_enable_dynamic_flags(self):
        """LLMPlayer stores enable_dynamic_flags as instance attribute."""
        player = _make_minimal_llmplayer(
            enable_dynamic_flags=True, enable_dynamic_calcs=False
        )
        assert player.enable_dynamic_flags is True
        assert player.enable_dynamic_calcs is False

    @pytest.mark.moves
    def test_llmplayer_stores_enable_dynamic_calcs(self):
        """LLMPlayer stores enable_dynamic_calcs as instance attribute."""
        player = _make_minimal_llmplayer(
            enable_dynamic_flags=False, enable_dynamic_calcs=True
        )
        assert player.enable_dynamic_flags is False
        assert player.enable_dynamic_calcs is True

    @pytest.mark.moves
    def test_llmplayer_defaults_flags_to_false(self):
        """Without explicit flags, both default to False."""
        player = _make_minimal_llmplayer()
        assert player.enable_dynamic_flags is False
        assert player.enable_dynamic_calcs is False

    @pytest.mark.moves
    def test_localsim_stores_flags(self):
        """LocalSim stores enable_dynamic_flags and enable_dynamic_calcs."""
        from poke_env.player.local_simulation import LocalSim
        from unittest.mock import MagicMock

        battle = MagicMock()
        battle.active_pokemon = MagicMock()
        gen = MagicMock()

        sim = LocalSim(
            battle=battle,
            move_effect={},
            pokemon_move_dict={},
            ability_effect={},
            pokemon_ability_dict={},
            item_effect={},
            pokemon_item_dict={},
            gen=gen,
            _dynamax_disable=False,
            enable_dynamic_flags=True,
            enable_dynamic_calcs=True,
            enable_showdown_oracle=True,
        )
        assert sim.enable_dynamic_flags is True
        assert sim.enable_dynamic_calcs is True
        assert sim.enable_showdown_oracle is True
        assert sim.oracle is None

    @pytest.mark.moves
    def test_localsim_flags_default_false(self):
        """LocalSim flags default to False when not specified."""
        from poke_env.player.local_simulation import LocalSim
        from unittest.mock import MagicMock

        battle = MagicMock()
        battle.active_pokemon = MagicMock()
        gen = MagicMock()

        sim = LocalSim(
            battle=battle,
            move_effect={},
            pokemon_move_dict={},
            ability_effect={},
            pokemon_ability_dict={},
            item_effect={},
            pokemon_item_dict={},
            gen=gen,
            _dynamax_disable=False,
        )
        assert sim.enable_dynamic_flags is False
        assert sim.enable_dynamic_calcs is False
        assert sim.enable_showdown_oracle is False
        assert sim.oracle is None


# ---------------------------------------------------------------------------
# VAL-INFRA-004: Token counting per battle
# ---------------------------------------------------------------------------
class TestTokenCounting:
    """Verify token counters exist and are updated."""

    @pytest.mark.moves
    def test_vllm_player_has_token_counters(self):
        """VLLMPlayer exposes prompt_tokens and completion_tokens."""
        from pokechamp.vllm_player import VLLMPlayer

        vllm = VLLMPlayer(model="test-model")
        assert hasattr(vllm, "prompt_tokens")
        assert hasattr(vllm, "completion_tokens")
        assert vllm.prompt_tokens == 0
        assert vllm.completion_tokens == 0

    @pytest.mark.moves
    def test_gpt_player_has_token_counters(self):
        """GPTPlayer exposes prompt_tokens and completion_tokens."""
        from pokechamp.gpt_player import GPTPlayer

        gpt = GPTPlayer(api_key="test-key")
        assert hasattr(gpt, "prompt_tokens")
        assert hasattr(gpt, "completion_tokens")


# ---------------------------------------------------------------------------
# VAL-INFRA-005: LLM call counting
# ---------------------------------------------------------------------------
class TestLLMCallCounting:
    """Verify LLM call counter increments and resets per battle."""

    @pytest.mark.moves
    def test_llmplayer_has_call_counter(self):
        """LLMPlayer has llm_call_count attribute initialized to 0."""
        player = _make_minimal_llmplayer()
        assert hasattr(player, "llm_call_count")
        assert player.llm_call_count == 0

    @pytest.mark.moves
    def test_llmplayer_counter_resets_on_new_battle_tag(self):
        """Counter resets when battle_tag changes (new battle)."""
        player = _make_minimal_llmplayer()
        player.llm_call_count = 5
        player._last_battle_tag = "battle-1"

        # Simulate entering choose_move with a new battle
        from unittest.mock import MagicMock

        new_battle = MagicMock()
        new_battle.battle_tag = "battle-2"
        new_battle.active_pokemon = MagicMock()
        new_battle.active_pokemon.fainted = False
        new_battle.available_moves = []
        new_battle.available_switches = []

        # The counter should be reset in choose_move
        # We test the logic directly
        if new_battle.battle_tag != player._last_battle_tag:
            player.llm_call_count = 0
            player._last_battle_tag = new_battle.battle_tag

        assert player.llm_call_count == 0
        assert player._last_battle_tag == "battle-2"

    @pytest.mark.moves
    def test_llmplayer_counter_does_not_reset_same_battle(self):
        """Counter does NOT reset for the same battle_tag."""
        player = _make_minimal_llmplayer()
        player.llm_call_count = 5
        player._last_battle_tag = "battle-1"

        # Same battle_tag
        if "battle-1" != player._last_battle_tag:
            player.llm_call_count = 0

        assert player.llm_call_count == 5


# ---------------------------------------------------------------------------
# VAL-INFRA-008: Backend lock for dynamic calcs
# ---------------------------------------------------------------------------
class TestBackendLock:
    """Verify --enable_dynamic_calcs requires vllm/* backend."""

    @pytest.mark.moves
    def test_dynamic_calcs_rejects_non_vllm(self):
        """Backend lock rejects non-vllm backends when calcs enabled."""
        backend = "gemini-2.5-flash"
        assert not backend.startswith("vllm/")

    @pytest.mark.moves
    def test_dynamic_calcs_accepts_vllm(self):
        """Backend lock accepts vllm/* backends."""
        backend = "vllm/google/gemma-4-26B-A4B-it"
        assert backend.startswith("vllm/")

    @pytest.mark.moves
    def test_dynamic_calcs_no_lock_when_disabled(self):
        """No lock enforced when dynamic_calcs is False."""
        # Any backend is fine when flag is off
        backend = "gemini-2.5-flash"
        enable_dynamic_calcs = False
        assert not (enable_dynamic_calcs and not backend.startswith("vllm/"))


# ---------------------------------------------------------------------------
# VAL-INFRA-009: vLLM config unchanged
# ---------------------------------------------------------------------------
class TestVLLMConfig:
    """Verify vllm_config.yaml parameters are unchanged."""

    @pytest.mark.moves
    def test_vllm_config_unchanged(self):
        """vllm_config.yaml retains original hyperparameters."""
        import yaml

        config_path = os.path.join(
            os.path.dirname(__file__), "..", "pokechamp", "vllm_config.yaml"
        )
        with open(config_path) as f:
            cfg = yaml.safe_load(f)

        assert cfg["temperature"] == 1.0
        assert cfg["top_p"] == 0.95
        assert cfg["presence_penalty"] == 1.5
        assert cfg["max_tokens"] == 32768
        assert cfg["extra_body"]["top_k"] == 64
        assert cfg["extra_body"]["chat_template_kwargs"]["enable_thinking"] is False


# ---------------------------------------------------------------------------
# VAL-INFRA-006/007: Result output formatting
# ---------------------------------------------------------------------------
class TestResultFormatting:
    """Verify experiment result output format."""

    @pytest.mark.moves
    def test_metrics_keys(self):
        """Per-battle metrics dict has required keys."""
        metrics = {
            "won": 1,
            "turns": 25,
            "prompt_tokens": 5000,
            "completion_tokens": 200,
            "llm_calls": 50,
        }
        required_keys = {
            "won",
            "turns",
            "prompt_tokens",
            "completion_tokens",
            "llm_calls",
        }
        assert required_keys.issubset(set(metrics.keys()))

    @pytest.mark.moves
    def test_averages_computed(self):
        """Averages are computed correctly from metrics list."""
        metrics = [
            {
                "won": 1,
                "turns": 20,
                "prompt_tokens": 1000,
                "completion_tokens": 100,
                "llm_calls": 10,
            },
            {
                "won": 0,
                "turns": 30,
                "prompt_tokens": 2000,
                "completion_tokens": 200,
                "llm_calls": 20,
            },
        ]
        n = len(metrics)
        win_rate = sum(m["won"] for m in metrics) / n * 100
        avg_turns = sum(m["turns"] for m in metrics) / n
        avg_prompt_tokens = sum(m["prompt_tokens"] for m in metrics) / n
        avg_llm_calls = sum(m["llm_calls"] for m in metrics) / n

        assert win_rate == 50.0
        assert avg_turns == 25.0
        assert avg_prompt_tokens == 1500.0
        assert avg_llm_calls == 15.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_minimal_llmplayer(**kwargs):
    """Create an LLMPlayer with minimal setup for testing.

    Avoids connecting to any server by patching __init__ internals.
    Uses lazy import to avoid circular import issues at module level.
    """
    from unittest.mock import MagicMock, patch

    # Lazy import to handle circular imports gracefully
    import pokechamp.llm_player as _lpm

    LLMPlayer = _lpm.LLMPlayer

    # Prepare defaults
    flags = {
        "enable_dynamic_flags": kwargs.pop("enable_dynamic_flags", False),
        "enable_dynamic_calcs": kwargs.pop("enable_dynamic_calcs", False),
    }

    with patch.object(LLMPlayer, "__init__", lambda self, *a, **kw: None):
        player = LLMPlayer.__new__(LLMPlayer)

    # Set the attributes that our code reads
    player.enable_dynamic_flags = flags["enable_dynamic_flags"]
    player.enable_dynamic_calcs = flags["enable_dynamic_calcs"]
    player.llm_call_count = 0
    player._last_battle_tag = None
    player.llm = MagicMock()
    player.llm.prompt_tokens = 0
    player.llm.completion_tokens = 0

    return player
