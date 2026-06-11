"""Chain-of-thought battle agent using LangGraph.

Equivalent to the existing ``prompt_algo="cot"`` but built as a
LangGraph ``StateGraph``.  The graph separates reasoning from decision:

    build_prompt → think → decide

The LLM first reasons step-by-step (max 4 sentences), then makes a
final decision based on its reasoning.
"""

from __future__ import annotations

from typing import Any, Dict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from pokechamp.agents.state import BattleAgentState

# ---------------------------------------------------------------------------
# Graph nodes
# ---------------------------------------------------------------------------


def build_prompt(state: BattleAgentState) -> dict:
    """Construct the CoT prompt from battle state."""
    system = state["system_prompt"]

    # CoT constraint prompt (matches existing LLMPlayer format)
    user = (
        state["state_prompt"]
        + state["state_action_prompt"]
        + state["constraint_prompt"]
    )

    return {
        "messages": [
            SystemMessage(content=system),
            HumanMessage(content=user),
        ]
    }


def think(state: BattleAgentState, *, llm: BaseChatModel) -> dict:
    """LLM thinks step-by-step about the battle situation."""
    from pokechamp.agents.common import extract_llm_usage

    cot_instruction = (
        "In fewer than 4 sentences, let's think step by step about "
        "the best action for this turn. Consider type matchups, HP "
        "advantage, and strategic implications. After reasoning, "
        "provide your final decision as a JSON object."
    )

    messages = list(state["messages"])
    messages.append(HumanMessage(content=cot_instruction))

    response = llm.invoke(messages)
    result: Dict[str, Any] = {"messages": [response], "reasoning": response.content}
    result.update(extract_llm_usage(response))
    return result


def decide(state: BattleAgentState) -> dict:
    """Parse the final decision from the LLM's reasoning.

    Falls back to prose extraction when JSON parsing fails.
    """
    from pokechamp.agents.common import (
        extract_action_from_prose,
        parse_action_json,
    )

    # Look for the JSON action in the last AI message
    last_ai_content = None
    for msg in reversed(state["messages"]):
        if isinstance(msg, AIMessage):
            action = parse_action_json(msg.content, None)
            if action is not None:
                result: Dict[str, Any] = {"chosen_action": action}
                if action.get("dynamax"):
                    result["chosen_dynamax"] = True
                if action.get("tera"):
                    result["chosen_tera"] = True
                return result
            # Remember last AI content for prose fallback
            if last_ai_content is None:
                last_ai_content = msg.content

    # Prose fallback: search for move/switch names in the text
    if last_ai_content is not None:
        move_ids = [m["id"] for m in state.get("available_moves", [])]
        switch_species = [s["species"] for s in state.get("available_switches", [])]
        action = extract_action_from_prose(last_ai_content, move_ids, switch_species)
        if action is not None:
            result: Dict[str, Any] = {"chosen_action": action}
            if action.get("dynamax"):
                result["chosen_dynamax"] = True
            if action.get("tera"):
                result["chosen_tera"] = True
            return result

    return {"chosen_action": None}


# ---------------------------------------------------------------------------
# Graph factory
# ---------------------------------------------------------------------------


def create_cot_agent(llm: BaseChatModel) -> CompiledStateGraph:
    """Create a compiled chain-of-thought battle agent graph.

    Args:
        llm: A LangChain ``BaseChatModel`` instance.

    Returns:
        A compiled ``StateGraph`` ready for ``graph.invoke(state)``.
    """
    graph = StateGraph(BattleAgentState)

    # Nodes
    graph.add_node("build_prompt", build_prompt)
    graph.add_node("think", _bind_llm(think, llm))
    graph.add_node("decide", decide)

    # Edges
    graph.set_entry_point("build_prompt")
    graph.add_edge("build_prompt", "think")
    graph.add_edge("think", "decide")
    graph.add_edge("decide", END)

    return graph.compile()


def _bind_llm(node_fn, llm: BaseChatModel):
    """Wrap a node function to inject the LLM."""

    def wrapped(state: BattleAgentState) -> dict:
        return node_fn(state, llm=llm)

    wrapped.__name__ = node_fn.__name__
    return wrapped
