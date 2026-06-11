"""Shared utilities for battle agent graphs.

Provides helper functions for:
- Building ``BattleAgentState`` from live battle objects
- Parsing LLM JSON output into a ``BattleOrder``
- Action matching against available moves/switches
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from poke_env.environment.abstract_battle import AbstractBattle
from poke_env.environment.pokemon import Pokemon
from poke_env.player.battle_order import BattleOrder
from poke_env.player.local_simulation import LocalSim

from pokechamp.agents.state import BattleAgentState

# ---------------------------------------------------------------------------
# State construction
# ---------------------------------------------------------------------------


def build_battle_state(
    battle: AbstractBattle,
    sim: LocalSim,
    constraint_prompt: str = "",
) -> BattleAgentState:
    """Construct a ``BattleAgentState`` from live battle objects.

    Reuses ``sim.state_translate()`` to get prompt text, then populates
    the structured fields from the battle object.
    """
    system_prompt, state_prompt, state_action_prompt = sim.state_translate(battle)

    # Available moves
    available_moves = []
    for move in battle.available_moves:
        available_moves.append(
            {
                "id": str(move.id),
                "type": str(move.type) if move.type else None,
                "base_power": move.base_power,
                "accuracy": move.accuracy,
                "category": str(move.category) if move.category else None,
                "priority": move.priority,
            }
        )

    # Available switches
    available_switches = []
    for pokemon in battle.available_switches:
        available_switches.append(
            {
                "species": str(pokemon.species),
                "types": _get_types(pokemon),
                "hp_fraction": round(pokemon.current_hp_fraction, 3),
                "level": pokemon.level,
            }
        )

    # Active pokemon info
    active_info = (
        _pokemon_info(battle.active_pokemon) if battle.active_pokemon else None
    )
    opp_info = (
        _pokemon_info(battle.opponent_active_pokemon)
        if battle.opponent_active_pokemon
        else None
    )

    # Weather/terrain
    weather = str(battle.weather) if battle.weather else None
    terrain = (
        str(battle.terrain) if hasattr(battle, "terrain") and battle.terrain else None
    )

    # Team summaries
    team_summary = _summarize_team(battle.team)
    opponent_summary = _summarize_team(battle.opponent_team)

    return BattleAgentState(
        messages=[],
        battle_tag=battle.battle_tag,
        turn=battle.turn,
        battle_format=getattr(battle, "format", "gen9ou"),
        available_moves=available_moves,
        available_switches=available_switches,
        can_dynamax=battle.can_dynamax,
        can_tera=battle.can_tera,
        active_pokemon=active_info,
        opponent_pokemon=opp_info,
        team_summary=team_summary,
        opponent_summary=opponent_summary,
        weather=weather,
        terrain=terrain,
        system_prompt=system_prompt,
        state_prompt=state_prompt,
        state_action_prompt=state_action_prompt,
        constraint_prompt=constraint_prompt,
        reasoning="",
        evaluation_scores={},
        total_prompt_tokens=0,
        total_completion_tokens=0,
        llm_call_count=0,
        chosen_action=None,
        chosen_dynamax=False,
        chosen_tera=False,
    )


# ---------------------------------------------------------------------------
# Token tracking helpers
# ---------------------------------------------------------------------------


def extract_llm_usage(response) -> dict:
    """Extract token usage from an LLM response for state accumulation.

    Returns a dict with delta values that LangGraph's ``Annotated`` reducer
    will automatically sum across nodes.
    """
    prompt_tokens = 0
    completion_tokens = 0

    usage = getattr(response, "usage_metadata", None)
    if usage:
        prompt_tokens = usage.get("input_tokens", 0)
        completion_tokens = usage.get("output_tokens", 0)

    return {
        "total_prompt_tokens": prompt_tokens,
        "total_completion_tokens": completion_tokens,
        "llm_call_count": 1,
    }


# ---------------------------------------------------------------------------
# Action parsing
# ---------------------------------------------------------------------------


def extract_action_from_prose(
    llm_output: str,
    available_move_ids: List[str],
    available_switch_species: List[str],
) -> Optional[Dict[str, Any]]:
    """Extract a move or switch from prose text when JSON parsing fails.

    Searches the LLM output for mentions of available move IDs and switch
    species.  The **last** mention wins (LLM conclusions typically appear
    at the end).  Moves take priority over switches when both appear at
    the same position.

    If a "Recommendation" or "## Recommendation" section exists, it is
    searched first — the LLM's explicit conclusion is more reliable than
    passing mentions in the analysis body.

    Returns ``None`` if no match is found.
    """

    def _search_in_text(
        text: str,
        move_ids: List[str],
        switch_species: List[str],
    ) -> Optional[Dict[str, Any]]:
        """Find the last move/switch mention in *text*."""
        text_lower = text.lower().replace(" ", "")
        best_match: Optional[Dict[str, Any]] = None
        best_pos = -1

        for move_id in move_ids:
            normalized = move_id.lower().replace(" ", "")
            idx = text_lower.find(normalized)
            if idx >= 0 and idx > best_pos:
                best_pos = idx
                best_match = {"move": move_id}

        for species in switch_species:
            normalized = species.lower().replace(" ", "")
            idx = text_lower.find(normalized)
            if idx > best_pos:
                best_pos = idx
                best_match = {"switch": species}

        return best_match

    # 0. Try "Recommendation" section first (explicit conclusion)
    rec_match = re.search(
        r"(?:^|\n)\s*(?:##\s*)?Recommendation\s*:?\s*\n(.*?)(?:\n\s*\n|\n\s*##|\Z)",
        llm_output,
        re.IGNORECASE | re.DOTALL,
    )
    if rec_match:
        rec_section = rec_match.group(1)
        action = _search_in_text(rec_section, available_move_ids, available_switch_species)
        if action is not None:
            return action

    # 1. Fall back to searching the full text
    return _search_in_text(llm_output, available_move_ids, available_switch_species)


def parse_action_json(
    llm_output: str,
    battle: AbstractBattle,
) -> Optional[Dict[str, Any]]:
    """Parse LLM JSON output into a structured action dict.

    Returns ``None`` if parsing fails.  Handles markdown code fences,
    diverse key names, and extracts JSON embedded in prose text.
    """
    content = llm_output.strip()

    # --- Pre-processing: remove markdown code fences ---
    if content.startswith("```"):
        first_newline = content.find("\n")
        if first_newline >= 0:
            content = content[first_newline + 1:]
        if content.endswith("```"):
            content = content[:-3].rstrip()

    # --- 1st attempt: direct JSON parse ---
    action = None
    try:
        action = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        # --- 2nd attempt: extract first JSON object ---
        start = content.find("{")
        end = content.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                action = json.loads(content[start:end])
            except (json.JSONDecodeError, TypeError):
                pass

    if action is None:
        return None

    if not isinstance(action, dict):
        return None

    # --- Key normalisation ---
    # Normalise keys — handle diverse LLM response formats including:
    #   {"move": "x"}, {"action": "move", "move": "x"},
    #   {"switch": "x"}, {"action": "switch", "switch_target": "x"},
    #   {"dynamax": "x"}, {"terastallize": "x"},
    #   {"move_name": "x"}, {"chosen_move": "x"}, {"chosen_switch": "x"},
    #   {"decision": "switch"}
    result: Dict[str, Any] = {}

    # Determine action type
    action_type = (
        action.get("action", "").lower()
        if isinstance(action.get("action"), str)
        else ""
    )
    # "decision" as alias for "action"
    if not action_type and isinstance(action.get("decision"), str):
        action_type = action["decision"].lower()

    # Move aliases: move_name, chosen_move → move
    move_value = (
        action.get("move")
        or action.get("move_name")
        or action.get("chosen_move")
    )
    # Switch aliases: chosen_switch → switch
    switch_value = (
        action.get("switch")
        or action.get("chosen_switch")
    )

    # Move / Dynamax / Terastallize
    if "terastallize" in action and action["terastallize"] is not None:
        result["move"] = str(action["terastallize"]).strip()
        result["tera"] = True
    elif "dynamax" in action and action["dynamax"] is not None:
        result["move"] = str(action["dynamax"]).strip()
        result["dynamax"] = True
    elif move_value is not None:
        result["move"] = str(move_value).strip()

    # Switch — support "switch", "chosen_switch", and "switch_target" keys
    if switch_value is not None:
        result["switch"] = str(switch_value).strip()
    elif "switch_target" in action and action["switch_target"] is not None:
        result["switch"] = str(action["switch_target"]).strip()

    # If action type is explicitly "switch" but no switch found, try other keys
    if action_type == "switch" and "switch" not in result:
        for key in ("target", "pokemon", "species"):
            if key in action and action[key]:
                result["switch"] = str(action[key]).strip()
                break

    if "thought" in action:
        result["thought"] = action["thought"]

    # Must have at least one valid action key
    if "move" not in result and "switch" not in result:
        return None

    return result


def action_to_battle_order(
    action: Dict[str, Any],
    battle: AbstractBattle,
) -> Optional[BattleOrder]:
    """Convert a parsed action dict to a ``BattleOrder``.

    Mirrors the matching logic in ``LLMPlayer.io()`` without modifying
    any existing code.
    """
    next_action = None

    is_dynamax = action.get("dynamax", False)
    is_tera = action.get("tera", False)

    if "move" in action:
        llm_move_id = action["move"].lower().replace(" ", "")
        for move in battle.available_moves:
            if move.id.lower().replace(" ", "") == llm_move_id:
                next_action = BattleOrder(
                    move, dynamax=is_dynamax, terastallize=is_tera
                )
                break

    elif "switch" in action:
        llm_species = action["switch"].lower().replace(" ", "")
        for pokemon in battle.available_switches:
            if pokemon.species.lower().replace(" ", "") == llm_species:
                next_action = BattleOrder(pokemon)
                break

    return next_action


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_types(pokemon: Pokemon) -> List[str]:
    """Return clean uppercase type names (e.g. ``['WATER', 'FLYING']``)."""
    types = []
    if pokemon.type_1:
        types.append(pokemon.type_1.name)
    if pokemon.type_2:
        types.append(pokemon.type_2.name)
    return types


def _pokemon_info(pokemon: Pokemon) -> Dict[str, Any]:
    return {
        "species": str(pokemon.species),
        "types": _get_types(pokemon),
        "level": pokemon.level,
        "hp_fraction": round(pokemon.current_hp_fraction, 3),
        "status": str(pokemon.status) if pokemon.status else None,
        "boosts": dict(pokemon.boosts) if pokemon.boosts else {},
        "item": str(pokemon.item) if pokemon.item else None,
        "tera_type": str(getattr(pokemon, "_terastallized_type", None)) if getattr(pokemon, "_terastallized_type", None) else None,
    }


def _summarize_team(team: Dict[str, Pokemon]) -> str:
    parts = []
    for pokemon in team.values():
        hp = round(pokemon.current_hp_fraction * 100)
        status_str = f" [{pokemon.status}]" if pokemon.status else ""
        parts.append(f"{pokemon.species} ({hp}%{status_str})")
    return "; ".join(parts)
