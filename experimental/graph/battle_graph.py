from langgraph.graph import END, START, StateGraph

from experimental.graph.battle_state import BattleDecisionState
from experimental.graph import nodes


def create_battle_graph(max_retries: int = 3) -> StateGraph:
    graph = StateGraph(BattleDecisionState)

    # Analysis phase
    graph.add_node("analyze_battlefield", nodes.analyze_battlefield)
    graph.add_node("analyze_roles", nodes.analyze_roles)
    graph.add_node("assess_matchups", nodes.assess_matchups)
    graph.add_node("evaluate_damage", nodes.evaluate_damage)

    # Planning phase
    graph.add_node("generate_tactical_plans", nodes.generate_tactical_plans)
    graph.add_node("predict_opponent", nodes.predict_opponent)

    # Decision phase
    graph.add_node("evaluate_plans", nodes.evaluate_plans)
    graph.add_node("select_action", nodes.select_action)
    graph.add_node("revise_decision", nodes.revise_decision)

    # Linear pipeline: analysis → planning → decision
    graph.add_edge(START, "analyze_battlefield")
    graph.add_edge("analyze_battlefield", "analyze_roles")
    graph.add_edge("analyze_roles", "assess_matchups")
    graph.add_edge("assess_matchups", "evaluate_damage")
    graph.add_edge("evaluate_damage", "generate_tactical_plans")
    graph.add_edge("generate_tactical_plans", "predict_opponent")
    graph.add_edge("predict_opponent", "evaluate_plans")
    graph.add_edge("evaluate_plans", "select_action")

    # Revision loop
    def after_select(state: BattleDecisionState) -> str:
        if state.get("needs_revision") and state.get("retry_count", 0) < max_retries:
            return "revise_decision"
        return END

    graph.add_conditional_edges("select_action", after_select)
    graph.add_edge("revise_decision", "analyze_battlefield")

    return graph.compile()
