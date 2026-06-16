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
- `calculate_damage(move_name, target_species?)`: Estimate damage for a move. Only use with DAMAGING moves (physical/special), not status moves.
- `check_type_effectiveness(attacking_type, defender_species?)`: Check type matchups (e.g. "water" vs "rock" → 2x).
- `analyze_matchup()`: Compare your active Pokemon vs opponent — speed, type advantages, best move.
- `get_team_analysis(side)`: Analyze team weaknesses/resistances. Use side="player" or "opponent".
- `predict_opponent_moves(species?)`: Predict opponent's moveset. Defaults to active opponent.
- `simulate_turn(player_move, estimated_opponent_move)`: Simulate a turn with specific moves.
- `get_move_details(move_name)`: Get detailed move info including dynamic properties.
- `evaluate_position()`: Evaluate current battle position score (0-100).

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

        messages = [
            SystemMessage(content=system_content),
            HumanMessage(content=user_content),
        ]
        return {"messages": messages}

    return build_context


def _make_agent_loop(max_tool_calls: int):
    """Create an ``agent_loop`` node bound to a specific tool-call limit."""

    def agent_loop(
        state: BattleAgentState,
        *,
        llm: BaseChatModel,
        tools: Sequence[BaseTool],
    ) -> dict:
        """LLM decides whether to call tools or produce a final answer."""
        from pokechamp.agents.common import extract_llm_usage

        # Count existing tool calls via state field (more robust than
        # scanning messages, and avoids cross-turn count bugs if messages
        # are ever persisted between turns).
        tool_call_count = state.get("tool_call_count", 0)

        messages = list(state["messages"])

        if tool_call_count >= max_tool_calls:
            # Force a final answer.  Instead of appending a second
            # SystemMessage to the (already malformed) multi-turn tool
            # history, rebuild a CLEAN 2-message conversation so the model
            # receives a well-formed request without orphaned tool results
            # or empty assistant turns.
            tool_results = []
            last_ai_reasoning = ""
            for m in state["messages"]:
                if isinstance(m, ToolMessage):
                    tool_results.append(m.content)

            # Preserve the LLM's intermediate reasoning so the final
            # decision benefits from the analysis context.
            for m in reversed(state["messages"]):
                if isinstance(m, AIMessage) and m.content:
                    last_ai_reasoning = m.content
                    break

            force_system = (
                REACT_SYSTEM_PROMPT.format(max_tools=max_tool_calls)
                + "\n\nSTOP. You have used all your tool calls. "
                "Output ONLY a JSON action now. No prose. No code fences. No explanation.\n"
                'Example: {"move": "earthquake"}\n'
                "Your JSON action:"
            )
            force_user = (
                state.get("state_prompt", "")
                + state.get("state_action_prompt", "")
                + state.get("constraint_prompt", "")
            )
            if tool_results:
                force_user += "\n\n## Tool Results Summary:\n" + "\n".join(
                    f"- {r}" for r in tool_results
                )
            if last_ai_reasoning:
                force_user += (
                    f"\n\n## Your Previous Reasoning:\n" f"{last_ai_reasoning}"
                )

            clean_messages = [
                SystemMessage(content=force_system),
                HumanMessage(content=force_user),
            ]
            # Use JSON mode to maximise structured output probability
            json_llm = llm.bind(response_format={"type": "json_object"})
            response = json_llm.invoke(clean_messages)

            # Verify the force-termination response is parseable.  If
            # not, retry once with an even more constrained prompt.
            if response.content:
                from pokechamp.agents.common import parse_action_json

                if parse_action_json(response.content, None) is None:
                    retry_system = (
                        force_system + "\n\nIMPORTANT: Your previous response was not "
                        "valid JSON.  Output ONLY a raw JSON object with "
                        "no other text, comments, or explanation.\n"
                        'Example: {"move": "earthquake"}\n'
                    )
                    retry_messages = [
                        SystemMessage(content=retry_system),
                        HumanMessage(content="Your JSON action:"),
                    ]
                    try:
                        response = json_llm.invoke(retry_messages)
                    except Exception:
                        pass  # Keep the original response
        else:
            # Inject remaining budget hint so the LLM can plan its tool
            # usage efficiently and avoid degenerate repeat calls.
            remaining = max_tool_calls - tool_call_count
            messages.append(
                HumanMessage(
                    content=(
                        f"[BUDGET: You have {remaining} tool call(s) "
                        f"remaining. Plan accordingly.]"
                    )
                )
            )
            # Bind tools to the model
            llm_with_tools = llm.bind_tools(tools)
            response = llm_with_tools.invoke(messages)

        result: Dict[str, Any] = {"messages": [response]}
        result.update(extract_llm_usage(response))
        return result

    return agent_loop


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
        """Route: if last AI message has tool calls, execute tools; else parse.

        Also enforces the tool call limit — if we've already reached
        ``max_tool_calls``, route to parse even if the LLM produced more
        tool calls (shouldn't happen with the unbind fix, but acts as
        a safety net).
        """
        last_message = state["messages"][-1] if state["messages"] else None

        # Safety: check tool call count via state field
        tool_call_count = state.get("tool_call_count", 0)
        if tool_call_count >= max_tool_calls:
            print(
                f"[ReAct] MAX_TOOL_CALLS reached: "
                f"{tool_call_count}/{max_tool_calls} "
                f"(turn {state.get('turn', '?')})"
            )
            return "parse"

        if isinstance(last_message, AIMessage) and last_message.tool_calls:
            # If executing these pending calls would exceed the limit,
            # but there is still remaining budget, route to "tools" so
            # that tool_execution can truncate and execute what fits.
            remaining = max_tool_calls - tool_call_count
            if remaining <= 0:
                return "parse"
            return "tools"

        return "parse"

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
    _agent_loop = _make_agent_loop(max_tool_calls)
    _should_continue = _make_should_continue(max_tool_calls)

    graph = StateGraph(BattleAgentState)

    # Nodes
    graph.add_node("build_context", _build_context)
    graph.add_node(
        "agent",
        _bind(_agent_loop, llm=llm, tools=tools),
    )
    graph.add_node(
        "tool_execution",
        _bind(
            tool_execution, tools_by_name=tools_by_name, max_tool_calls=max_tool_calls
        ),
    )
    graph.add_node("parse_action", parse_action)

    # Edges
    graph.set_entry_point("build_context")
    graph.add_edge("build_context", "agent")
    graph.add_conditional_edges(
        "agent",
        _should_continue,
        {"tools": "tool_execution", "parse": "parse_action"},
    )
    graph.add_edge("tool_execution", "agent")
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
