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

import json
import re
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
from pokechamp.battle_memory import (
    BattleMemory,
    gather_preview_strategy,
    predict_opp_leads,
    refresh_own_team_roles,
    refresh_team_roles,
    update_opp_revealed,
)
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
        # Battle-scoped memory (design D, EXP-049a): one BattleMemory per
        # battle_tag, persisted across turns so the agent accumulates
        # opponent team roles, revealed moves/items/tera, and its own plan.
        self._battle_memory: dict[str, BattleMemory] = {}

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

    # ------------------------------------------------------------------
    # Team preview: strategic lead + win-plan seed (EXP-050a, human-thought point 1)
    # ------------------------------------------------------------------

    # Reuses the parent ``_LEAD_SELECTION_SYSTEM_PROMPT``'s 6 lead-selection
    # considerations verbatim (no new instructional prose — EXP-002~004 / 049a
    # bloat guard), then extends the OUTPUT to also produce a battle-long win
    # plan. my_plan definition mirrors STRATEGY_SYSTEM_PROMPT (react_agent) so
    # the first turn's strategy node follows an already-formed long-term plan
    # instead of restating this turn's action (the 049a failure mode).
    _PREVIEW_SYSTEM_PROMPT = (
        "You are an expert competitive Pokemon gen9ou (OverUsed singles 6v6) "
        "team analyst. Your task is to choose the optimal lead Pokemon and "
        "team order, AND to formulate the win plan for the WHOLE battle.\n\n"
        "Key considerations for lead selection in gen9ou singles:\n"
        "1. Type matchup advantage against the opponent's likely leads\n"
        "2. Speed tier - outspeeding the opponent's likely lead is critical\n"
        "3. Entry hazard setting (Stealth Rock, Spikes) vs anti-lead "
        "(Defog, Rapid Spin, Taunt)\n"
        "4. Lead momentum - can your lead force a favorable switch or get "
        "an early KO?\n"
        "5. Team order after the lead - order remaining Pokemon by how soon "
        "you might need them as switch-ins\n"
        "6. Synergy - your lead should set up the rest of your team for success\n\n"
        "Opponent data is limited during team preview: you can see their "
        "species, types, base stats, and possible abilities, but NOT their "
        "exact moves, items, or abilities.\n\n"
        "my_plan must describe how you win the WHOLE battle, NOT the first "
        "turn. GOOD: \"Set Stealth Rock with Ting-Lu early, then sweep with "
        "Gholdengo once the opponent's special wall is removed.\" "
        "BAD (this is one turn, not a plan): \"Lead with Ting-Lu and use "
        "Stealth Rock.\"\n\n"
        "Respond with ONLY a JSON object, no prose, no code fences:\n"
        '{"team_order": "<6-digit order, FIRST digit is your lead>", '
        '"my_plan": "<your long-term win path>", '
        '"opp_win_condition": "<their long-term win path>"}'
    )

    def teampreview(self, battle: AbstractBattle) -> str:
        """Team preview: LLM oneshot -> /team order + BattleMemory win-plan seed.

        EXP-050a (human-thought point 1). Seeds ``my_plan`` /
        ``opp_win_condition`` so the first turn's strategy node follows an
        already-formed plan instead of formulating one from scratch (the
        EXP-049a short-term-restatement failure mode). Falls back to
        ``random_teampreview`` on any error or when disabled.
        """
        if not self.enable_llm_lead_selection:
            return self.random_teampreview(battle)

        try:
            own_team = list(battle.team.values())
            opp_team = list(battle._teampreview_opponent_team)
            if not own_team:
                return self.random_teampreview(battle)

            # teampreview() runs before the first choose_move(), so create +
            # seed the memory here. choose_move() keeps an existing memory
            # for this battle_tag (see the guard there), so the seed survives.
            memory = self._battle_memory.get(battle.battle_tag)
            if memory is None:
                memory = BattleMemory()
                self._battle_memory[battle.battle_tag] = memory
            refresh_own_team_roles(memory, battle)
            refresh_team_roles(memory, battle)

            # EXP-050a v2: full-info analysis (bloat limit lifted per user
            # policy) — opponent likely-lead prediction, Smogon strategy
            # overviews for all 12 mons, per-pokemon role labels. Surfaced as
            # structured context so the LLM grounds a rich long-term win plan.
            opp_leads = predict_opp_leads(battle, memory, top_n=6)
            own_species = [getattr(m, "species", "") or "" for m in own_team]
            opp_species = [getattr(m, "species", "") or "" for m in opp_team]
            strategy = gather_preview_strategy(
                [s for s in own_species + opp_species if s], cap=0
            )

            team_data = self._format_lead_selection_data(own_team, opp_team)
            user_prompt = self._create_lead_selection_prompt(team_data)
            # Replace the parent prompt's trailing "Respond with ONLY a
            # 6-digit number" instruction (it conflicts with JSON output)
            # and append the role-balance brief + JSON instruction.
            marker = "Respond with ONLY a 6-digit number"
            idx = user_prompt.find(marker)
            if idx > 0:
                user_prompt = user_prompt[:idx].rstrip()
            user_prompt += "\n\n" + self._render_role_balance_brief(memory)
            user_prompt += "\n\n" + self._render_preview_analysis(
                memory, opp_leads, strategy
            )
            user_prompt += (
                "\n\nRespond with ONLY a JSON object (no prose, no code "
                'fences): {"team_order":"<6-digit, first is lead>",'
                '"my_plan":"<long-term win path>",'
                '"opp_win_condition":"<their long-term win path>"}'
            )

            response = self.get_LLM_action(
                system_prompt=self._PREVIEW_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                model=self.backend,
                temperature=0.3,
                max_tokens=min(self._max_tokens, 8192),
            )

            order, seed = self._parse_preview_response(response, len(own_team))
            self._log_preview(
                battle,
                status="llm_ok" if order else "parse_fail_fallback",
                order=order,
                seed=seed,
                response=response,
                user_prompt=user_prompt,
            )
            if order:
                if seed.get("my_plan"):
                    memory.my_plan = seed["my_plan"]
                if seed.get("opp_win_condition"):
                    memory.opp_win_condition = seed["opp_win_condition"]
                memory.preview_seed_turn = 0
                print(
                    f"[teampreview 050a] order={order} "
                    f"plan_seed={bool(seed.get('my_plan'))}"
                )
                return f"/team {order}"
        except Exception as e:
            print(f"[teampreview 050a] Error: {e}")
            self._log_preview(battle, status="exception_fallback", error=str(e))

        return self.random_teampreview(battle)

    def _log_preview(
        self,
        battle: AbstractBattle,
        status: str,
        order: Optional[str] = None,
        seed: Optional[dict] = None,
        response: Optional[str] = None,
        user_prompt: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        """Append a team-preview decision record to ``preview_llm_log.jsonl``.

        teampreview() runs OUTSIDE the LangGraph (it is a player method), so
        its oneshot LLM call is not captured by ``LLMLoggingCallback`` /
        ``langgraph_llm_log.jsonl``. This writes a separate per-battle record so
        the lead-selection + win-plan reasoning is inspectable (EXP-050a).
        No-op when ``log_dir`` is unset or writing fails — logging must never
        break a battle. ``status`` is one of: ``llm_ok`` (order parsed),
        ``parse_fail_fallback`` (LLM ran but order unparseable → random),
        ``exception_fallback`` (error → random).
        """
        log_dir = getattr(self, "log_dir", None)
        if not log_dir:
            return
        import os
        from datetime import datetime

        entry = {
            "timestamp": datetime.now().isoformat(),
            "battle_tag": getattr(battle, "battle_tag", None),
            "status": status,
            "order": order,
        }
        if seed is not None:
            entry["seed"] = seed
        if response is not None:
            entry["response"] = (response or "")[:2000]
        if user_prompt is not None:
            entry["user_prompt"] = (user_prompt or "")[:4000]
        if error:
            entry["error"] = error[:300]
        try:
            path = os.path.join(log_dir, "preview_llm_log.jsonl")
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass

    @staticmethod
    def _render_role_balance_brief(memory: BattleMemory) -> str:
        """One-line role balance for both teams (EXP-050a).

        Aggregates only (category counts) — per-role listing would bloat the
        prompt (EXP-049a lesson). Used at team preview to ground the win-plan.
        """

        def _fmt(bal: dict) -> str:
            if not bal:
                return "unknown"
            items = sorted(bal.items(), key=lambda kv: (-kv[1], kv[0]))
            return ", ".join(f"{cat} x{n}" for cat, n in items)

        return (
            f"Your team roles: {_fmt(memory.my_role_balance)}\n"
            f"Opponent team roles: {_fmt(memory.opp_role_balance)}"
        )

    @staticmethod
    def _render_preview_analysis(
        memory: BattleMemory,
        opp_leads: list,
        strategy: dict,
    ) -> str:
        """Structured preview analysis for the full-info win-plan prompt (EXP-050a v2).

        Bloat limit lifted per user policy: surfaces likely opponent leads,
        per-pokemon role labels (own + opp), and Smogon strategy overviews for
        all species so the LLM grounds a rich long-term win plan.
        """
        lines = ["## Preview Analysis (structured — ground your win plan here)"]

        if opp_leads:
            lines.append(
                "\nLikely opponent leads (speed tier + role + type threat):"
            )
            for d in opp_leads:
                roles = ", ".join(d.get("roles") or []) or "n/a"
                lines.append(
                    f"  - {d['species']} (Spe {d['speed']}, roles: {roles}, "
                    f"type-threat {d['type_threat']})"
                )

        def _role_line(key: str, rlist: list) -> str:
            labels = ", ".join(
                f"{r.get('category', '')}/{r.get('role', '')}" for r in rlist
            )
            return f"  - {key}: {labels or 'n/a'}"

        if memory.my_team_roles:
            lines.append("\nYour team roles (per species):")
            for key, rlist in memory.my_team_roles.items():
                lines.append(_role_line(key, rlist))

        if memory.opp_team_roles:
            lines.append("\nOpponent team roles (per species):")
            for key, rlist in memory.opp_team_roles.items():
                lines.append(_role_line(key, rlist))

        if strategy:
            lines.append(
                "\nSmogon strategy overviews (checks / weaknesses / win paths):"
            )
            for key, ov in strategy.items():
                lines.append(f"  [{key}]\n  {ov}")

        return "\n".join(lines)

    @staticmethod
    def _parse_preview_response(text: str, team_size: int) -> tuple:
        """Parse the preview LLM JSON into ``(team_order, seed)``.

        ``team_order`` is validated as a permutation of 1..team_size (reuses
        the parent's digit-extraction fallback for robustness). ``seed``
        holds ``my_plan`` / ``opp_win_condition`` (may be empty). Returns
        ``(None, {})`` on parse failure so the caller falls back to
        ``random_teampreview``.
        """
        if not text:
            return None, {}
        raw = text.strip()
        # Strip markdown code fences if present.
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw[:4].lower() == "json":
                raw = raw[4:]

        plan = ""
        win = ""
        order = None
        try:
            obj = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            obj = None

        if isinstance(obj, dict):
            order_val = obj.get("team_order") or obj.get("order")
            if isinstance(order_val, str):
                digits = "".join(ch for ch in order_val if ch.isdigit())
                if LangChainPlayer._is_valid_team_order(digits, team_size):
                    order = digits
            plan = str(obj.get("my_plan") or "").strip()
            win = str(obj.get("opp_win_condition") or "").strip()

        # Fallback: JSON failed — try a plain N-digit permutation scan for
        # the order only (mirrors the parent _parse_teampreview_response).
        if order is None:
            match = re.search(r"\b(\d{" + str(team_size) + r"})\b", raw)
            if match and LangChainPlayer._is_valid_team_order(
                match.group(1), team_size
            ):
                order = match.group(1)

        return order, {"my_plan": plan, "opp_win_condition": win}

    def choose_move(self, battle: AbstractBattle):
        """Route to LangGraph agent or fall back to existing logic."""
        # Reset LLM call counter at the start of each new battle
        if battle.battle_tag != self._last_battle_tag:
            self.llm_call_count = 0
            self.json_parse_failures = 0
            self._last_battle_tag = battle.battle_tag
            # New battle → fresh memory (design D, EXP-049a). teampreview()
            # (EXP-050a) may have already created + seeded memory for this
            # battle with a win plan; keep it if present so the preview plan
            # carries into turn 1 instead of being overwritten.
            if battle.battle_tag not in self._battle_memory:
                self._battle_memory[battle.battle_tag] = BattleMemory()

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

        # Battle-scoped memory (design D, EXP-049a): refresh role analysis
        # and revealed observations each turn, then inject into state so
        # graph nodes (build_context) can reason over them.
        memory = self._battle_memory.get(battle.battle_tag)
        if memory is None:
            memory = BattleMemory()
            self._battle_memory[battle.battle_tag] = memory
        refresh_team_roles(memory, battle)
        update_opp_revealed(memory, battle)

        # Build state
        state = build_battle_state(battle, sim, constraint, memory=memory)

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

        # Persist LLM-authored strategy state to battle memory (design D).
        # parse_action writes these from the agent JSON output; keep the
        # latest non-empty value so it carries across turns.
        new_win_condition = result.get("opp_win_condition")
        new_plan = result.get("my_plan")
        if new_win_condition:
            memory.opp_win_condition = new_win_condition
        if new_plan:
            memory.my_plan = new_plan
            memory.plan_turn = battle.turn

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
