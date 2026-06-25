"""Unit tests for the strategy-synthesis graph split (EXP-049b, design B).

Covers the new graph topology (build_context → tool_agent ⇄ tool_execution →
strategy_synthesis → parse_action) and the STRATEGY_SYSTEM_PROMPT that forces
my_plan to be a long-term win path.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from pokechamp.agents.react_agent import (
    STRATEGY_SYSTEM_PROMPT,
    create_react_agent,
)


def test_graph_topology_has_strategy_split():
    """EXP-049b splits the legacy agent node into tool_agent + strategy_synthesis."""
    graph = create_react_agent(MagicMock())
    nodes = set(graph.nodes) - {"__start__", "__end__"}
    assert "tool_agent" in nodes
    assert "strategy_synthesis" in nodes
    assert "tool_execution" in nodes
    assert "build_context" in nodes
    assert "parse_action" in nodes
    # legacy monolithic agent node must be gone
    assert "agent" not in nodes


def test_strategy_prompt_forces_longterm_plan():
    """STRATEGY_SYSTEM_PROMPT must steer my_plan away from single-turn restatement."""
    assert "LONG-TERM" in STRATEGY_SYSTEM_PROMPT
    assert "my_plan" in STRATEGY_SYSTEM_PROMPT
    assert "NOT this turn" in STRATEGY_SYSTEM_PROMPT
    # concrete GOOD/BAD contrast so the model has an anchor
    assert "GOOD my_plan" in STRATEGY_SYSTEM_PROMPT
    assert "BAD my_plan" in STRATEGY_SYSTEM_PROMPT


def test_strategy_node_signature():
    """strategy_synthesis node must be constructable and bound to an llm."""
    from pokechamp.agents.react_agent import _make_strategy_synthesis

    node_fn = _make_strategy_synthesis(max_tool_calls=5)
    assert callable(node_fn)
