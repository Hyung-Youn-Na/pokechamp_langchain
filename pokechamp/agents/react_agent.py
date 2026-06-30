"""ReAct battle agent using LangGraph with tool calling.

This is the highest-value new agent: the LLM can call battle analysis
tools (damage calculator, type effectiveness, matchup analysis, etc.)
to gather quantitative data before making a decision.

Graph structure::

    build_context → agent_loop ⇄ tool_execution → parse_action

The agent loop continues until the LLM produces a final answer (no
tool calls) or the maximum number of tool calls is reached.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional, Sequence

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from pokechamp.agents.state import BattleAgentState
from pokechamp.battle_tools import ALL_BATTLE_TOOLS

# Default maximum tool calls per turn to enforce time limits
DEFAULT_MAX_TOOL_CALLS = 5


# ---------------------------------------------------------------------------
# System prompt for the ReAct agent
# ---------------------------------------------------------------------------

REACT_SYSTEM_PROMPT = """You are a competitive Pokémon battle AI. Your job is to choose the best move or switch for the current turn.

## Available Tools

You have access to battle analysis tools that provide quantitative data:
- `calculate_damage(move_name, target_species?)`: Estimate damage for a move. Only use with DAMAGING moves (physical/special), not status moves. Damage accounts for dynamic move types (Tera Blast, Weather Ball, Ivy Cudgel, etc.) via the Showdown engine when enabled.
- `check_type_effectiveness(attacking_type, defender_species?)`: Check type matchups (e.g. "water" vs "rock" → 2x).
- `analyze_matchup()`: Compare your active Pokemon vs opponent — speed, type advantages, best move.
- `get_team_analysis(side)`: Analyze team weaknesses/resistances. Use side="player" or "opponent".
- `predict_opponent_moves(species?)`: Predict opponent's moveset. Defaults to active opponent.
- `simulate_turn(player_move, estimated_opponent_move)`: Simulate a turn with specific moves. Player-move damage accounts for dynamic move types via the Showdown engine when enabled.
- `get_move_details(move_name)`: Get detailed move info including dynamic properties.
- `evaluate_position()`: Evaluate current battle position score (0-100).
- `get_strategy_insight(species, aspect?)`: Get Smogon community strategy (role / what it checks / weaknesses / win paths) for a Pokemon species. Use it to understand a species' long-term strategic role.

## Decision Process

1. Read the battle state carefully — note your available moves and switches
2. Use `calculate_damage` on your OWN available moves (only those listed in the prompt)
3. Optionally check type effectiveness or matchup for key moves
4. Compare damage results and choose the best action
5. Output your final JSON decision

## CRITICAL Rules

- You may call at most **{max_tools} tools** per turn. Plan your tool usage efficiently.
- **Only calculate damage for moves your Pokemon actually has** (listed in the prompt). Do NOT request damage for moves not in your moveset.
- Do NOT call `calculate_damage` for status moves like Protect, Recover, Toxic, etc.
- If a tool returns an error, do NOT retry the same call — move on to a different tool or make your decision.
- When you have enough data, stop calling tools and output your JSON decision.

## Output Format (MANDATORY)

Your final response MUST be ONLY a JSON object. No prose before or after.
DO NOT wrap in markdown code fences.

CORRECT: {{"move": "earthquake"}}
CORRECT: {{"switch": "toxapex"}}
WRONG: Based on my analysis, the best move is {{"move": "earthquake"}}
WRONG: I think Earthquake is the best because...

JSON keys:
- To use a move: {{"move": "<move_name>"}}
- To switch: {{"switch": "<pokemon_species>"}}
- To use Dynamax: {{"dynamax": "<move_name>"}}
- To Terastallize: {{"terastallize": "<move_name>"}}
- Optional, for long-term consistency: {{"win_condition_opponent": "<brief>"}} and {{"my_plan": "<your win path + next step>"}}. These carry to future turns (see the "Battle Memory" section in the state); update them when your read of the game changes.
"""


# ---------------------------------------------------------------------------
# Memory brief rendering (design D, EXP-049a)
# ---------------------------------------------------------------------------


def _format_memory_brief(state: BattleAgentState) -> str:
    """Render a compact memory brief from state for the user prompt.

    Surfaces the battle-scoped memory slices so the agent stays consistent
    with its long-term read of the game instead of optimising one turn in
    isolation. Returns "" when no memory is available (early turns).
    """
    parts: list[str] = []

    role_balance = state.get("opp_role_balance") or {}
    if role_balance:
        items = sorted(role_balance.items(), key=lambda kv: -kv[1])
        parts.append(
            "Opponent team roles: "
            + ", ".join(f"{cat} x{n}" for cat, n in items)
        )

    revealed = state.get("opp_revealed") or {}
    rev_lines: list[str] = []
    for species, info in revealed.items():
        bits: list[str] = []
        moves = info.get("moves") or []
        if moves:
            bits.append("moves: " + ", ".join(moves))
        if info.get("item"):
            bits.append(f"item: {info['item']}")
        if info.get("tera"):
            bits.append(f"tera: {info['tera']}")
        if bits:
            rev_lines.append(f"  - {species} ({'; '.join(bits)})")
    if rev_lines:
        parts.append("Opponent revealed so far:\n" + "\n".join(rev_lines))

    opp_wc = state.get("opp_win_condition") or ""
    if opp_wc:
        parts.append(f"Inferred opponent win condition: {opp_wc}")

    my_plan = state.get("my_plan") or ""
    plan_turn = state.get("plan_turn") or 0
    if my_plan:
        parts.append(f"My current plan (turn {plan_turn}): {my_plan}")

    # EXP-051 plan resilience: one-turn replan nudge when the own active mon
    # changed (KO/forced switch). _format_memory_brief is called by both
    # build_context and strategy_synthesis, so this surfaces in both prompts.
    if state.get("plan_invalidated"):
        parts.append(
            f"⚠️ PLAN DISRUPTED — {state.get('replan_reason', '')}. "
            f"Re-assess your win path; update my_plan only if it genuinely shifted."
        )

    if not parts:
        return ""
    return (
        "\n\n## Battle Memory (accumulated across turns)\n"
        + "\n".join(parts)
    )


# ---------------------------------------------------------------------------
# System prompt for the strategy synthesis node (EXP-049b, design B)
# ---------------------------------------------------------------------------

STRATEGY_SYSTEM_PROMPT = """You are the STRATEGY SYNTHESISER for a Pokémon battle. The tool-agent has already gathered quantitative data (damage estimates, type effectiveness, turn simulations). Your job is to synthesise that into a strategic decision AND a long-term plan.

## CRITICAL: my_plan is a LONG-TERM win path, NOT this turn's action

my_plan must describe how you win the WHOLE battle, not what you do this turn. The "Battle Memory" section shows your previous my_plan — keep it stable and only change it when your read of the win path genuinely shifts.

If the Battle Memory flags your plan as disrupted (your active Pokemon was KO'd or forced out), re-formulate my_plan only when your long-term win path actually changed — do not rewrite it for one-turn tactical events.

GOOD my_plan examples:
- "Set Stealth Rock with Ting-Lu early, then win by sweeping with Gholdengo once the opponent's special wall (Clodsire) is removed."
- "Opponent's only win condition is Dragonite Dragon Dance; keep Ceruledge (Shadow Sneak priority) alive as the revenge killer and win the long game by chipping."

BAD my_plan (this is just THIS turn's action — do NOT repeat it here):
- "KO Ogerpon with Thunderbolt this turn."
- "Switch to Jolteon."

Use the tool results and battle state to decide THIS turn's action (move/switch), but write my_plan as the multi-turn win path. win_condition_opponent is the opponent's analogous long-term path.

## Output (JSON only, no prose, no code fences)

{{"move": "<move_name>"}}  OR  {{"switch": "<species>"}}
plus (when your read changes):
{{"win_condition_opponent": "<their long-term win path>", "my_plan": "<your long-term win path>"}}
"""


# ---------------------------------------------------------------------------
# Graph nodes
# ---------------------------------------------------------------------------


def _make_build_context(max_tool_calls: int):
    """Create a ``build_context`` node bound to a specific tool-call limit."""

    def build_context(state: BattleAgentState) -> dict:
        """Build the initial prompt with battle state context.

        Uses ``state_translate()`` output (same as IO/CoT agents) so that
        all agents see identical battle state — ensuring experiment
        comparability.  The constraint prompt (output format + gimmick
        options) is appended to enforce consistent action parsing.
        """
        system_content = REACT_SYSTEM_PROMPT.format(max_tools=max_tool_calls)

        # Reuse the same battle state text that IO/CoT agents use
        user_content = (
            state.get("state_prompt", "")
            + state.get("state_action_prompt", "")
            + state.get("constraint_prompt", "")
        )
        # Inject the battle-scoped memory brief (design D, EXP-049a) so the
        # agent reasons over accumulated roles / revealed info / its own plan.
        memory_brief = _format_memory_brief(state)
        if memory_brief:
            user_content += memory_brief

        messages = [
            SystemMessage(content=system_content),
            HumanMessage(content=user_content),
        ]
        return {"messages": messages}

    return build_context


def _make_tool_agent(max_tool_calls: int):
    """Create a ``tool_agent`` node bound to a specific tool-call limit.

    Responsibilities (EXP-049b, design B): tool calling ONLY. Strategic
    synthesis is delegated to the ``strategy_synthesis`` node, which runs a
    clean rebuild after the tool loop ends — so this node never force-
    terminates or emits a final action.
    """

    def tool_agent(
        state: BattleAgentState,
        *,
        llm: BaseChatModel,
        tools: Sequence[BaseTool],
    ) -> dict:
        """LLM decides which (if any) tools to call."""
        from pokechamp.agents.common import extract_llm_usage

        tool_call_count = state.get("tool_call_count", 0)
        messages = list(state["messages"])

        # Budget hint nudges efficient, well-grounded termination without
        # adding new system instructions (EXP-002~004 prompt-bloat guard).
        remaining = max_tool_calls - tool_call_count
        if tool_call_count >= 2 and remaining <= 2:
            hint = (
                f"[BUDGET: {remaining} call(s) left. Before the next "
                f"tool, ask: will its result change my final decision? "
                f"If not, stop calling tools.]"
            )
        else:
            hint = (
                f"[BUDGET: You have {remaining} tool call(s) "
                f"remaining. Plan accordingly.]"
            )
        messages.append(HumanMessage(content=hint))

        llm_with_tools = llm.bind_tools(tools)
        response = llm_with_tools.invoke(messages)

        result: Dict[str, Any] = {"messages": [response]}
        result.update(extract_llm_usage(response))
        return result

    return tool_agent


def _make_strategy_synthesis(max_tool_calls: int):
    """Create a ``strategy_synthesis`` node (EXP-049b, design B).

    Runs a CLEAN rebuild after the tool loop ends (tools exhausted, budget
    reached, or the tool-agent produced no tool calls). It summarises the
    tool results + the tool-agent's reasoning + the battle memory brief,
    then asks the model for a strategic decision + long-term plan.

    The clean rebuild (vs. continuing the accumulated message history)
    avoids the per-turn prompt bloat seen in EXP-049a, and the dedicated
    STRATEGY_SYSTEM_PROMPT forces ``my_plan`` to be a long-term win path
    rather than a restatement of this turn's action (the 95.4% short-term
    restatement failure mode of EXP-049a).
    """

    def strategy_synthesis(
        state: BattleAgentState,
        *,
        llm: BaseChatModel,
    ) -> dict:
        from pokechamp.agents.common import extract_llm_usage, parse_action_json

        # Collect tool results + the tool-agent's last reasoning from the
        # accumulated message history, then discard the history itself.
        tool_results: list[str] = []
        last_ai_reasoning = ""
        for m in state["messages"]:
            if isinstance(m, ToolMessage):
                tool_results.append(m.content)
        for m in reversed(state["messages"]):
            if isinstance(m, AIMessage) and m.content:
                last_ai_reasoning = m.content
                break

        system_content = STRATEGY_SYSTEM_PROMPT
        user_content = (
            state.get("state_prompt", "")
            + state.get("state_action_prompt", "")
            + state.get("constraint_prompt", "")
        )
        memory_brief = _format_memory_brief(state)
        if memory_brief:
            user_content += memory_brief
        if tool_results:
            user_content += (
                "\n\n## Tool Results:\n"
                + "\n".join(f"- {r}" for r in tool_results)
            )
        if last_ai_reasoning:
            user_content += f"\n\n## Tool-Agent Reasoning:\n{last_ai_reasoning}"

        clean_messages = [
            SystemMessage(content=system_content),
            HumanMessage(content=user_content),
        ]
        json_llm = llm.bind(response_format={"type": "json_object"})
        response = json_llm.invoke(clean_messages)

        # Retry once if the response isn't parseable JSON.
        if response.content and parse_action_json(response.content, None) is None:
            retry_messages = [
                SystemMessage(
                    content=system_content
                    + "\n\nIMPORTANT: Output ONLY a raw JSON object, no other text."
                ),
                HumanMessage(content="Your JSON:"),
            ]
            try:
                response = json_llm.invoke(retry_messages)
            except Exception:
                pass  # keep original response

        result: Dict[str, Any] = {
            "messages": [response],
            "reasoning": response.content or "",
        }
        result.update(extract_llm_usage(response))
        return result

    return strategy_synthesis


def tool_execution(
    state: BattleAgentState,
    *,
    tools_by_name: Dict[str, BaseTool],
    max_tool_calls: int = DEFAULT_MAX_TOOL_CALLS,
) -> dict:
    """Execute any tool calls from the last AI message.

    Respects the tool-call budget: if the last AIMessage requests more
    tool calls than remaining budget allows, only the first *remaining*
    calls are executed.  Unexecuted calls receive a "budget exceeded"
    ToolMessage so that every ``tool_call_id`` has a matching response.

    Duplicate tool calls (same name + args) are intercepted and return
    a cached-style message instead of re-executing, preventing
    degenerate loops where small models repeat the same query.
    """
    last_message = state["messages"][-1]
    if not isinstance(last_message, AIMessage) or not last_message.tool_calls:
        return {"messages": []}

    tool_call_count = state.get("tool_call_count", 0)
    remaining = max(0, max_tool_calls - tool_call_count)

    # Collect signatures of previously executed tool calls for dedup.
    executed_signatures: set[tuple[str, str]] = set()
    msgs = state["messages"]
    for i, msg in enumerate(msgs):
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for tc in msg.tool_calls:
                tc_id = tc["id"]
                # Check if this tool_call has a matching ToolMessage
                has_response = any(
                    isinstance(m, ToolMessage) and m.tool_call_id == tc_id
                    for m in msgs[i + 1:]
                )
                if has_response:
                    sig = (tc["name"], json.dumps(tc["args"], sort_keys=True))
                    executed_signatures.add(sig)

    # Truncate to fit remaining budget
    pending = last_message.tool_calls
    calls_to_execute = pending[:remaining]
    calls_to_skip = pending[remaining:]

    tool_messages: list[ToolMessage] = []
    success_count = 0

    for tool_call in calls_to_execute:
        tool_name = tool_call["name"]

        # Dedup: skip tool calls with identical (name, args) signatures
        sig = (tool_name, json.dumps(tool_call["args"], sort_keys=True))
        if sig in executed_signatures:
            tool_messages.append(
                ToolMessage(
                    content=(
                        f"Tool {tool_name} was already called with these "
                        f"arguments.  Use a different approach or output "
                        f"your final JSON decision."
                    ),
                    tool_call_id=tool_call["id"],
                )
            )
            continue

        tool_fn = tools_by_name.get(tool_name)

        if tool_fn is None:
            tool_messages.append(
                ToolMessage(
                    content=f"Error: Tool '{tool_name}' not found.",
                    tool_call_id=tool_call["id"],
                )
            )
            continue

        try:
            result = tool_fn.invoke(tool_call["args"])
            # Ensure result is a string
            content = result if isinstance(result, str) else str(result)
            tool_messages.append(
                ToolMessage(content=content, tool_call_id=tool_call["id"])
            )
            # no_data 플래그: 유의미하지 않은 도구 결과(get_strategy_insight 빈 overview
            # 등)는 tool-call 예산에서 제외 — LLM이 대안 도구를 부를 예산 확보 (2026-06-25).
            budget_free = False
            try:
                parsed = json.loads(content)
                if isinstance(parsed, dict) and parsed.get("no_data"):
                    budget_free = True
            except (json.JSONDecodeError, TypeError, ValueError):
                pass
            if not budget_free:
                success_count += 1
        except Exception as e:
            tool_messages.append(
                ToolMessage(
                    content=(
                        f"Tool {tool_name} could not complete. "
                        f"Try a different approach or make your decision now. "
                        f"(Detail: {str(e)[:100]})"
                    ),
                    tool_call_id=tool_call["id"],
                )
            )

    # Generate "budget exceeded" responses for skipped calls so that
    # every tool_call_id has a matching ToolMessage (prevents dangling
    # tool_calls that cause API 400 errors).
    for tool_call in calls_to_skip:
        tool_messages.append(
            ToolMessage(
                content=(
                    f"Tool call skipped — tool-call budget of "
                    f"{max_tool_calls} has been reached. "
                    f"Output your final JSON decision now."
                ),
                tool_call_id=tool_call["id"],
            )
        )

    return {"messages": tool_messages, "tool_call_count": success_count}


def parse_action(state: BattleAgentState) -> dict:
    """Extract the final JSON action from the conversation.

    Falls back to prose extraction when JSON parsing fails, searching
    the last AI message for available move/switch names.

    Handles the force-termination edge case where the LLM may return
    ``tool_calls`` alongside content even when tools were not bound.
    In that scenario we still parse ``content`` for a valid JSON action.
    """
    from pokechamp.agents.common import (
        extract_action_from_prose,
        parse_action_json,
    )

    def _try_parse(msg: AIMessage) -> Optional[Dict[str, Any]]:
        """Attempt JSON then prose extraction on a single AIMessage."""
        content = msg.content
        if not content:
            return None

        # Primary: JSON parse
        action = parse_action_json(content, None)
        if action is not None:
            result: Dict[str, Any] = {"chosen_action": action}
            if action.get("dynamax"):
                result["chosen_dynamax"] = True
            if action.get("tera"):
                result["chosen_tera"] = True
            # Lift strategy-memory keys to the top level so LangGraph writes
            # them to state and the player persists them (design D, EXP-049a).
            if action.get("opp_win_condition"):
                result["opp_win_condition"] = action["opp_win_condition"]
            if action.get("my_plan"):
                result["my_plan"] = action["my_plan"]
            return result

        # Fallback: prose extraction for this message
        move_ids = [m["id"] for m in state.get("available_moves", [])]
        switch_species = [s["species"] for s in state.get("available_switches", [])]
        action = extract_action_from_prose(content, move_ids, switch_species)
        if action is not None:
            result = {"chosen_action": action}
            if action.get("dynamax"):
                result["chosen_dynamax"] = True
            if action.get("tera"):
                result["chosen_tera"] = True
            return result

        return None

    # Walk messages in reverse — prefer AIMessages without tool_calls,
    # but also try messages WITH tool_calls (force-termination scenario
    # where GLM-5.1 returns tool_calls alongside JSON content).
    for msg in reversed(state["messages"]):
        if isinstance(msg, AIMessage):
            # Fast path: no tool_calls → parse directly
            if not msg.tool_calls:
                parsed = _try_parse(msg)
                if parsed is not None:
                    return parsed
            else:
                # Force-termination fallback: tool_calls present but
                # content may still contain the JSON action we need.
                parsed = _try_parse(msg)
                if parsed is not None:
                    return parsed

    return {"chosen_action": None}


# ---------------------------------------------------------------------------
# Routing logic
# ---------------------------------------------------------------------------


def _make_should_continue(max_tool_calls: int):
    """Create a ``should_continue`` router bound to a specific tool-call limit."""

    def should_continue(state: BattleAgentState) -> str:
        """Route after tool_agent: call more tools, or synthesise strategy.

        Tool calls remain + budget available → "tools". Otherwise (no tool
        calls, or budget exhausted) → "strategy_synthesis" for the clean
        rebuild decision (EXP-049b, design B).
        """
        last_message = state["messages"][-1] if state["messages"] else None

        tool_call_count = state.get("tool_call_count", 0)
        if tool_call_count >= max_tool_calls:
            return "strategy_synthesis"

        if isinstance(last_message, AIMessage) and last_message.tool_calls:
            # Budget remaining → execute tools (tool_execution truncates to
            # fit); else synthesise.
            remaining = max_tool_calls - tool_call_count
            if remaining <= 0:
                return "strategy_synthesis"
            return "tools"

        return "strategy_synthesis"

    return should_continue


# ---------------------------------------------------------------------------
# Graph factory
# ---------------------------------------------------------------------------


def create_react_agent(
    llm: BaseChatModel,
    tools: Optional[Sequence[BaseTool]] = None,
    max_tool_calls: int = DEFAULT_MAX_TOOL_CALLS,
) -> CompiledStateGraph:
    """Create a compiled ReAct battle agent graph.

    Args:
        llm: A LangChain ``BaseChatModel`` instance that supports tool
            calling.
        tools: Battle tools to make available.  Defaults to all tools
            from ``battle_tools.ALL_BATTLE_TOOLS``.
        max_tool_calls: Maximum number of tool calls per turn.
            Defaults to ``DEFAULT_MAX_TOOL_CALLS`` (5).

    Returns:
        A compiled ``StateGraph`` ready for ``graph.invoke(state)``.
    """
    if tools is None:
        tools = ALL_BATTLE_TOOLS

    tools_by_name = {t.name: t for t in tools}

    # Create node functions bound to the given max_tool_calls limit
    _build_context = _make_build_context(max_tool_calls)
    _tool_agent = _make_tool_agent(max_tool_calls)
    _strategy_synthesis = _make_strategy_synthesis(max_tool_calls)
    _should_continue = _make_should_continue(max_tool_calls)

    graph = StateGraph(BattleAgentState)

    # Nodes
    graph.add_node("build_context", _build_context)
    graph.add_node(
        "tool_agent",
        _bind(_tool_agent, llm=llm, tools=tools),
    )
    graph.add_node(
        "tool_execution",
        _bind(
            tool_execution, tools_by_name=tools_by_name, max_tool_calls=max_tool_calls
        ),
    )
    graph.add_node(
        "strategy_synthesis",
        _bind(_strategy_synthesis, llm=llm),
    )
    graph.add_node("parse_action", parse_action)

    # Edges (EXP-049b): build_context → tool_agent ⇄ tool_execution →
    # strategy_synthesis → parse_action → END
    graph.set_entry_point("build_context")
    graph.add_edge("build_context", "tool_agent")
    graph.add_conditional_edges(
        "tool_agent",
        _should_continue,
        {"tools": "tool_execution", "strategy_synthesis": "strategy_synthesis"},
    )
    graph.add_edge("tool_execution", "tool_agent")
    graph.add_edge("strategy_synthesis", "parse_action")
    graph.add_edge("parse_action", END)

    return graph.compile()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bind(fn, **kwargs):
    """Bind keyword arguments to a graph node function."""

    def wrapped(state: BattleAgentState) -> dict:
        return fn(state, **kwargs)

    wrapped.__name__ = fn.__name__
    return wrapped
