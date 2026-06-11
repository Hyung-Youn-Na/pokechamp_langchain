"""Basic IO battle agent using LangGraph.

Equivalent to the existing ``prompt_algo="io"`` but built as a
LangGraph ``StateGraph``.  The graph is simple:

    build_prompt → call_llm → parse_action

This serves as the baseline LangGraph agent and validates that the
state schema and action-parsing pipeline work correctly.
"""

from __future__ import annotations

from typing import Any, Dict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph

from pokechamp.agents.state import BattleAgentState

# ---------------------------------------------------------------------------
# Graph nodes
# ---------------------------------------------------------------------------


def build_prompt(state: BattleAgentState) -> dict:
    """Construct system + user messages from battle state."""
    system = state["system_prompt"]

    # Reconstruct the same prompt that the original IO algorithm uses
    cot_prompt = "In fewer than 3 sentences, let's think step by step:"
    user = (
        state["state_prompt"]
        + state["state_action_prompt"]
        + state["constraint_prompt"]
        + cot_prompt
    )

    return {
        "messages": [
            SystemMessage(content=system),
            HumanMessage(content=user),
        ]
    }


def call_llm(state: BattleAgentState, *, llm: BaseChatModel) -> dict:
    """Invoke the LLM and store the raw response."""
    from pokechamp.agents.common import extract_llm_usage

    messages = state["messages"]
    response = llm.invoke(messages)
    result: Dict[str, Any] = {"messages": [response], "reasoning": response.content}
    result.update(extract_llm_usage(response))
    return result


def parse_action(state: BattleAgentState) -> dict:
    """Extract the chosen action from the LLM response.

    Falls back to prose extraction when JSON parsing fails.
    """
    from pokechamp.agents.common import (
        extract_action_from_prose,
        parse_action_json,
    )

    # Get last AI message
    last_msg = state["messages"][-1] if state["messages"] else None
    if not isinstance(last_msg, AIMessage):
        return {"chosen_action": None}

    content = last_msg.content
    action = parse_action_json(content, None)  # battle not needed here

    # Prose fallback: search for move/switch names in the text
    if action is None:
        move_ids = [m["id"] for m in state.get("available_moves", [])]
        switch_species = [s["species"] for s in state.get("available_switches", [])]
        action = extract_action_from_prose(content, move_ids, switch_species)

    if action is None:
        return {"chosen_action": None}

    result: Dict[str, Any] = {"chosen_action": action}
    if action.get("dynamax"):
        result["chosen_dynamax"] = True
    if action.get("tera"):
        result["chosen_tera"] = True

    return result


# ---------------------------------------------------------------------------
# Graph factory
# ---------------------------------------------------------------------------


def create_io_agent(llm: BaseChatModel) -> StateGraph:
    """Create a compiled IO battle agent graph.

    Args:
        llm: A LangChain ``BaseChatModel`` instance.

    Returns:
        A compiled ``StateGraph`` ready for ``graph.invoke(state)``.
    """
    graph = StateGraph(BattleAgentState)

    # Add nodes
    graph.add_node("build_prompt", build_prompt)
    graph.add_node("call_llm", _bind_llm(call_llm, llm))
    graph.add_node("parse_action", parse_action)

    # Edges
    graph.set_entry_point("build_prompt")
    graph.add_edge("build_prompt", "call_llm")
    graph.add_edge("call_llm", "parse_action")
    graph.add_edge("parse_action", END)

    return graph.compile()


def _bind_llm(node_fn, llm: BaseChatModel):
    """Wrap a node function to inject the LLM via keyword arg."""

    def wrapped(state: BattleAgentState) -> dict:
        return node_fn(state, llm=llm)

    wrapped.__name__ = node_fn.__name__
    return wrapped
