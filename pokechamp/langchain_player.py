"""LangChain-powered battle player using LangGraph agent workflows.

This module provides ``LangChainPlayer``, which inherits from the
existing ``LLMPlayer`` and overrides ``choose_move()`` to route new
prompt algorithms (``react``, ``cot_langchain``, ``io_langchain``)
through LangGraph agent graphs.

**Key principle:** Existing prompt algorithms (io, sc, cot, tot, minimax,
heuristic, etc.) are delegated to ``super().choose_move()`` with zero
changes to the existing code.

Usage::

    from pokechamp.langchain_backend import LangChainBackend
    from pokechamp.langchain_player import LangChainPlayer

    player = LangChainPlayer(
        backend="gpt-4o",
        llm_backend=LangChainBackend("openai:gpt-4o"),
        prompt_algo="react",
    )
"""

from __future__ import annotations

import traceback
from typing import Optional

from langchain_core.language_models import BaseChatModel
from poke_env.environment.abstract_battle import AbstractBattle
from poke_env.player.battle_order import BattleOrder
from poke_env.player.local_simulation import LocalSim

from pokechamp.agents.common import (
    action_to_battle_order,
    build_battle_state,
)
from pokechamp.agents.cot_agent import create_cot_agent
from pokechamp.agents.io_agent import create_io_agent
from pokechamp.agents.llm_logging import LLMLoggingCallback
from pokechamp.agents.react_agent import create_react_agent
from pokechamp.battle_tools import BattleContext, set_battle_context
from pokechamp.llm_player import LLMPlayer


class LangChainPlayer(LLMPlayer):
    """Battle player that uses LangGraph agent workflows.

    Inherits all functionality from ``LLMPlayer``.  New prompt
    algorithms are handled by LangGraph graphs; existing algorithms
    fall through to the parent class unchanged.

    Supported new prompt_algo values:

    - ``"react"`` — ReAct agent with battle tool calling
    - ``"io_langchain"`` — Basic IO via LangGraph (baseline)
    - ``"cot_langchain"`` — Chain-of-thought via LangGraph

    Any other prompt_algo value is delegated to ``super().choose_move()``.
    """

    def __init__(self, *args, **kwargs):
        self._max_tokens = kwargs.pop("max_tokens", 8192)
        self._max_tool_calls = kwargs.pop("max_tool_calls", 5)
        super().__init__(*args, **kwargs)
        self._agent_graphs = {}
        self._chat_model: Optional[BaseChatModel] = None
        self.json_parse_failures = 0
        # Track decision counts per (battle_tag, turn) to assign
        # unique decision_index values when choose_move() is called
        # multiple times in the same turn.
        self._decision_counts: dict[str, int] = {}
        self._last_decision_turn: dict[str, int] = {}

    def _get_chat_model(self) -> BaseChatModel:
        """Get or create the LangChain chat model from the backend."""
        if self._chat_model is not None:
            return self._chat_model

        # If the backend is already a LangChainBackend, extract the model
        from pokechamp.langchain_backend import LangChainBackend

        if isinstance(self.llm, LangChainBackend):
            self._chat_model = self.llm.chat_model
        else:
            # Lazy import to avoid hard dependency
            from langchain.chat_models import init_chat_model

            # Map common backend strings to LangChain provider specs
            backend = self.backend
            if "gpt" in backend and not backend.startswith("openai/"):
                model_spec = f"openai:{backend}"
            elif "gemini" in backend:
                model_spec = f"google_genai:{backend}"
            elif backend.startswith("ollama/"):
                model_spec = f"ollama:{backend.replace('ollama/', '')}"
            else:
                model_spec = f"openai:{backend}"

            self._chat_model = init_chat_model(
                model_spec,
                temperature=self.temperature,
                max_tokens=self._max_tokens,
            )

        return self._chat_model

    def _get_graph(self, algo: str):
        """Get or create a compiled agent graph for the given algorithm."""
        if algo in self._agent_graphs:
            return self._agent_graphs[algo]

        llm = self._get_chat_model()

        if algo == "react":
            graph = create_react_agent(llm, max_tool_calls=self._max_tool_calls)
        elif algo == "io_langchain":
            graph = create_io_agent(llm)
        elif algo == "cot_langchain":
            graph = create_cot_agent(llm)
        else:
            raise ValueError(f"Unknown LangGraph algorithm: {algo}")

        self._agent_graphs[algo] = graph
        return graph

    def choose_move(self, battle: AbstractBattle):
        """Route to LangGraph agent or fall back to existing logic."""
        # Reset LLM call counter at the start of each new battle
        if battle.battle_tag != self._last_battle_tag:
            self.llm_call_count = 0
            self.json_parse_failures = 0
            self._last_battle_tag = battle.battle_tag

        algo = self.prompt_algo

        # Route new algorithms through LangGraph
        if algo in ("react", "io_langchain", "cot_langchain"):
            return self._run_langgraph_agent(battle, algo)

        # All existing algorithms go through the original code path
        return super().choose_move(battle)

    def _run_langgraph_agent(self, battle: AbstractBattle, algo: str) -> BattleOrder:
        """Run a LangGraph agent and return a BattleOrder."""
        # Create LocalSim (same as parent choose_move)
        sim = LocalSim(
            battle,
            self.move_effect,
            self.pokemon_move_dict,
            self.ability_effect,
            self.pokemon_ability_dict,
            self.item_effect,
            self.pokemon_item_dict,
            self.gen,
            self._dynamax_disable,
            self.strategy_prompt,
            format=self.format,
            prompt_translate=self.prompt_translate,
            enable_dynamic_flags=self.enable_dynamic_flags,
            enable_dynamic_calcs=self.enable_dynamic_calcs,
            enable_showdown_oracle=self.enable_showdown_oracle,
        )

        # Early exit: fainted active pokemon with only 1 switch
        if battle.active_pokemon:
            if battle.active_pokemon.fainted and len(battle.available_switches) == 1:
                return BattleOrder(battle.available_switches[0])
            elif (
                not battle.active_pokemon.fainted
                and len(battle.available_moves) == 1
                and len(battle.available_switches) == 0
            ):
                return self.choose_max_damage_move(battle)
        elif len(battle.available_moves) <= 1 and len(battle.available_switches) == 0:
            return self.choose_max_damage_move(battle)

        # Update strategy prompt on turn 1
        if battle.turn <= 1 and self.use_strat_prompt:
            self.strategy_prompt = sim.get_llm_system_prompt(
                self.format,
                self.llm,
                team_str=self.team_str,
                model="gpt-4o-2024-05-13",
            )

        # Build constraint prompt
        gimmick_output_format = ""
        if "pokellmon" not in self.ps_client.account_configuration.username:
            dynamax_option = (
                ' or {"dynamax":"<move_name>"}' if battle.can_dynamax else ""
            )
            tera_option = (
                ' or {"terastallize":"<move_name>"}' if battle.can_tera else ""
            )
            gimmick_output_format = f"{dynamax_option}{tera_option}"

        if battle.active_pokemon.fainted or len(battle.available_moves) == 0:
            constraint = 'Choose the most suitable pokemon to switch. Your output MUST be a JSON like: {"switch":"<switch_pokemon_name>"}\n'
        elif len(battle.available_switches) == 0:
            constraint = f'Choose the best action and your output MUST be a JSON like: {{"move":"<move_name>"}}{gimmick_output_format}\n'
        else:
            constraint = f'Choose the best action and your output MUST be a JSON like: {{"move":"<move_name>"}}{gimmick_output_format} or {{"switch":"<switch_pokemon_name>"}}\n'

        # Set battle context for tools
        weather = str(battle.weather) if battle.weather else None
        terrain = (
            str(battle.terrain)
            if hasattr(battle, "terrain") and battle.terrain
            else None
        )
        ctx = BattleContext(
            sim=sim,
            battle=battle,
            active_pokemon=battle.active_pokemon,
            opponent_pokemon=battle.opponent_active_pokemon,
            weather=weather,
            terrain=terrain,
        )
        set_battle_context(ctx)

        # Build state
        state = build_battle_state(battle, sim, constraint)

        # Set up LLM logging callback if log_dir is configured
        callbacks = []
        if self.log_dir:
            # Track decision_index: how many choose_move calls for
            # this (battle, turn).  Resets when the turn number changes.
            btag = battle.battle_tag
            current_turn = battle.turn
            last_turn = self._last_decision_turn.get(btag, -1)
            if current_turn != last_turn:
                # New turn — reset decision counter
                self._decision_counts[btag] = 0
                self._last_decision_turn[btag] = current_turn
            else:
                # Same turn — another decision (e.g. after Volt Switch)
                self._decision_counts[btag] = (
                    self._decision_counts.get(btag, 0) + 1
                )

            decision_index = self._decision_counts.get(btag, 0)

            log_callback = LLMLoggingCallback(
                log_dir=self.log_dir,
                battle_tag=btag,
                turn=current_turn,
                decision_index=decision_index,
            )
            callbacks.append(log_callback)

        # Run the graph
        graph = self._get_graph(algo)
        config = {"callbacks": callbacks} if callbacks else {}
        try:
            result = graph.invoke(state, config=config)
        except Exception as e:
            print(f"LangGraph agent error: {e}. Falling back to max damage.")
            traceback.print_exc()
            self.json_parse_failures += 1
            return self.choose_max_damage_move(battle)

        # Accumulate LLM usage metrics from the graph result
        graph_prompt_tokens = result.get("total_prompt_tokens", 0)
        graph_completion_tokens = result.get("total_completion_tokens", 0)
        graph_llm_calls = result.get("llm_call_count", 0)

        # Update player-level counters so the experiment script can read them
        self.llm_call_count += graph_llm_calls
        if hasattr(self.llm, "prompt_tokens"):
            self.llm.prompt_tokens += graph_prompt_tokens
        if hasattr(self.llm, "completion_tokens"):
            self.llm.completion_tokens += graph_completion_tokens

        # Parse result
        action = result.get("chosen_action")
        if action is not None:
            order = action_to_battle_order(action, battle)
            if order is not None:
                # Log the reasoning
                reasoning = result.get("reasoning", "")
                if reasoning:
                    self._send_thinking_message(battle, reasoning)
                return order

        # Fallback to max damage
        self.json_parse_failures += 1
        print("LangGraph agent returned no valid action. Using max damage.")
        return self.choose_max_damage_move(battle)
