"""Battle agent state schema for LangGraph graphs.

Defines ``BattleAgentState`` — the TypedDict shared by all battle agent
graphs.  Each field represents a slice of the battle state that one or
more graph nodes may read or write.
"""

from __future__ import annotations

from typing import Annotated, Any, Dict, List, Optional

from langchain_core.messages import AnyMessage
from langgraph.graph import add_messages
from typing import TypedDict


def _add_int(a: int, b: int) -> int:
    """Reducer that sums integer values across graph nodes."""
    return a + b


class BattleAgentState(TypedDict):
    """State schema shared by all battle agent graphs.

    Populated once per ``choose_move()`` call from the ``AbstractBattle``
    and ``LocalSim`` objects, then passed through the graph nodes.
    """

    # -- LangChain message channel --
    messages: Annotated[list[AnyMessage], add_messages]

    # -- Battle context (set once per turn) --
    battle_tag: str
    turn: int
    battle_format: str

    # -- Available actions --
    available_moves: List[Dict[str, Any]]
    available_switches: List[Dict[str, Any]]
    can_dynamax: bool
    can_tera: bool

    # -- Battle state summary --
    active_pokemon: Optional[Dict[str, Any]]
    opponent_pokemon: Optional[Dict[str, Any]]
    team_summary: str
    opponent_summary: str
    weather: Optional[str]
    terrain: Optional[str]

    # -- Prompts from state_translate --
    system_prompt: str
    state_prompt: str
    state_action_prompt: str
    constraint_prompt: str

    # -- Reasoning state --
    reasoning: str
    evaluation_scores: Dict[str, float]

    # -- LLM usage tracking (accumulated via reducer) --
    total_prompt_tokens: Annotated[int, _add_int]
    total_completion_tokens: Annotated[int, _add_int]
    llm_call_count: Annotated[int, _add_int]

    # -- Final output --
    chosen_action: Optional[Dict[str, Any]]
    chosen_dynamax: bool
    chosen_tera: bool
