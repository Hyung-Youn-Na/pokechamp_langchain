from typing import Any, Callable, List, Optional, TypedDict


class BattleDecisionState(TypedDict):
    # --- Input (from backend) ---
    system_prompt: str
    user_prompt: str
    model: str
    temperature: float
    json_format: bool
    max_tokens: int
    actions: Optional[Any]

    # --- Node 1: Battlefield analysis ---
    battlefield_report: Optional[str]

    # --- Node 2: Role analysis ---
    role_analysis: Optional[str]

    # --- Node 3: Matchup assessment ---
    matchup_assessment: Optional[str]

    # --- Node 4: Damage evaluation ---
    damage_evaluation: Optional[str]

    # --- Node 5: Tactical plans ---
    tactical_plans: Optional[list]

    # --- Node 6: Opponent prediction ---
    opponent_prediction: Optional[str]

    # --- Node 7: Plan evaluation ---
    plan_evaluation: Optional[str]

    # --- Node 8: Final action ---
    final_action: Optional[str]

    # --- Legacy fields (backward compat) ---
    battle_analysis: Optional[str]
    candidate_moves: Optional[list]
    evaluation_notes: Optional[str]

    raw_outputs: List[str]

    # --- Control ---
    retry_count: int
    needs_revision: bool

    # --- Injected by backend ---
    llm: Optional[Any]
    _track_tokens_fn: Optional[Callable]
    node_llms: Optional[Any]
