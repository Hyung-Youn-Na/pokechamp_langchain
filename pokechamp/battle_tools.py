"""
LangChain battle tools for PokéChamp agents.

This module defines LangChain ``@tool``-decorated functions that expose
battle analysis capabilities.  Each tool wraps existing PokéChamp logic
from ``prompts.py``, ``local_simulation.py``, ``dynamic_move.py``, etc.

Tools are stateless functions — they receive a ``BattleContext`` dataclass
holding the current battle state (LocalSim, battle object, teams, etc.)
and return human-readable strings that an LLM agent can reason over.

**No existing files are modified.** This is a purely additive module.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any, Optional

from langchain_core.tools import tool
from poke_env.data import to_id_str
from poke_env.environment.move import Move
from poke_env.environment.pokemon import Pokemon

from pokechamp.data_cache import (
    get_cached_move_effect,
    get_cached_pokemon_move_dict,
)
from pokechamp.dynamic_move import (
    resolve_dynamic_power,
    resolve_dynamic_priority,
    resolve_dynamic_type,
)

_logger = logging.getLogger("battle_tools")

# ---------------------------------------------------------------------------
# Battle context — injected into tools at call time
# ---------------------------------------------------------------------------


@dataclass
class BattleContext:
    """Holds live battle state that tools need.

    Instantiated once per ``choose_move()`` call and passed to each tool
    so the tools themselves remain pure functions.
    """

    sim: Any  # LocalSim instance
    battle: Any  # AbstractBattle instance
    active_pokemon: Optional[Pokemon] = None
    opponent_pokemon: Optional[Pokemon] = None
    weather: Optional[str] = None
    terrain: Optional[str] = None


# Module-level holder for the current turn's context.
# Set by LangChainPlayer before invoking the agent graph.
_current_context: Optional[BattleContext] = None


def set_battle_context(ctx: BattleContext) -> None:
    """Store the current battle context for tool access."""
    global _current_context
    _current_context = ctx


def get_battle_context() -> BattleContext:
    """Retrieve the current battle context.

    Raises RuntimeError if no context has been set.
    """
    if _current_context is None:
        raise RuntimeError(
            "BattleContext not set. Call set_battle_context() before "
            "invoking agent tools."
        )
    return _current_context


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------


def _get_pokemon_types(pokemon: Pokemon) -> list[str]:
    """Return clean uppercase type name list for a Pokemon.

    Uses ``.name`` on the type enum to get clean identifiers like
    ``"WATER"`` instead of ``"water (pokemon type) object"``.
    """
    types = []
    if pokemon.type_1:
        types.append(pokemon.type_1.name)
    if pokemon.type_2:
        types.append(pokemon.type_2.name)
    return types


def _get_type_multiplier(
    attacking_type: str, defender: Pokemon, type_chart: Any
) -> float:
    """Compute the damage multiplier for an attacking type vs a defender.

    Uses ``calculate_move_type_damage_multipier`` with the correct
    signature ``(type_1, type_2, type_chart, constraint_type_list)``
    and maps the categorised result back to a numeric multiplier.
    """
    from poke_env.player.local_simulation import calculate_move_type_damage_multipier

    # Extract defender types as .name strings
    def_type_1 = defender.type_1.name if defender.type_1 else None
    def_type_2 = defender.type_2.name if defender.type_2 else None

    if not def_type_1:
        return 1.0

    atk_upper = attacking_type.upper()
    try:
        (
            extreme,
            effective,
            resistant,
            extreme_res,
            immune,
        ) = calculate_move_type_damage_multipier(
            def_type_1,
            def_type_2,
            type_chart,
            [atk_upper],  # constraint: only interested in this one type
        )
    except Exception:
        return 1.0

    # The function capitalises returned type names (e.g. "Water")
    atk_cap = atk_upper.capitalize()
    if atk_cap in extreme:
        return 4.0
    if atk_cap in effective:
        return 2.0
    if atk_cap in resistant:
        return 0.5
    if atk_cap in extreme_res:
        return 0.25
    if atk_cap in immune:
        return 0.0
    return 1.0


def _find_move(move_name: str, ctx: BattleContext) -> Move:
    """Find or create a Move object from a name string.

    Normalises the name via ``to_id_str`` and first tries to match
    against the active Pokemon's known moves (which carry PP, boosts,
    and other runtime state).  Falls back to creating a fresh Move.
    """
    move_id = to_id_str(move_name)
    mon = ctx.active_pokemon
    if mon:
        for m in mon.moves.values():
            if str(m.id) == move_id:
                return m
    return Move(move_id, gen=ctx.sim.gen.gen)


def _find_opponent_pokemon(
    species: Optional[str], ctx: BattleContext
) -> Optional[Pokemon]:
    """Find an opponent Pokemon by species name.

    If *species* is ``None`` or matches the current active opponent,
    returns ``ctx.opponent_pokemon``.  Otherwise searches the full
    opponent team (revealed members only).
    """
    if not species:
        return ctx.opponent_pokemon

    species_id = to_id_str(species)

    # Check current opponent first
    if ctx.opponent_pokemon and to_id_str(str(ctx.opponent_pokemon.species)) == species_id:
        return ctx.opponent_pokemon

    # Search opponent team
    if ctx.battle:
        for mon in ctx.battle.opponent_team.values():
            if to_id_str(str(mon.species)) == species_id:
                return mon

    # Fallback: can't find the species, use active opponent
    return ctx.opponent_pokemon


def _pokemon_to_dict(pokemon: Pokemon) -> dict:
    """Serialise key Pokemon fields for tool output."""
    return {
        "species": str(pokemon.species),
        "types": _get_pokemon_types(pokemon),
        "level": pokemon.level,
        "hp_fraction": round(pokemon.current_hp_fraction, 3),
        "status": str(pokemon.status) if pokemon.status else None,
        "boosts": dict(pokemon.boosts) if pokemon.boosts else {},
        "item": str(pokemon.item) if pokemon.item else None,
        "tera_type": (
            str(getattr(pokemon, "_terastallized_type", None))
            if getattr(pokemon, "_terastallized_type", None)
            else None
        ),
    }


def _active_state_hash(payload: dict) -> str:
    """Stable hash of the type-affecting fields in an oracle payload."""
    key_data = json.dumps(
        {
            "weather": payload.get("weather"),
            "terrain": payload.get("terrain"),
            "active_p1": payload.get("active_state", {}).get("p1"),
            "active_p2": payload.get("active_state", {}).get("p2"),
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.md5(key_data.encode("utf-8")).hexdigest()


def _clone_move_with_type(move: Move, resolved_type: str) -> Move:
    """Return a copy of ``move`` with its type overridden.

    The original Move (shared via ``active_pokemon.moves`` / move caches) is
    left untouched. Uses the per-instance ``type`` setter so the shared
    ``GenData.moves`` entry is never mutated.
    """
    gen = getattr(move, "_gen", None) or 9
    clone = Move(str(move.id), gen=gen)
    clone.type = resolved_type
    return clone


def _resolve_move_outcome_via_oracle(
    ctx: BattleContext,
    move: Move,
    mon: Optional[Pokemon],
    mon_opp: Optional[Pokemon],
) -> Optional[dict]:
    """Resolve a damaging move's type + power + damage via the Showdown oracle.

    **All** damaging moves are queried (not just dynamic ones) so the agent
    compares every move on the same Showdown-accurate yardstick. The previous
    dynamic-only gate left generic moves on the LocalSim path, whose category
    bias (special moves under-stated, physical over-stated) distorted
    cross-move comparisons (EXP-046). Every failure path returns ``None``
    (never raises) so callers fall back to the base move + LocalSim.

    Returns a dict ``{"type", "base_power", "damage_pct_max", "ko"}`` where
    ``type`` is a lowercase name or None, ``base_power``/``damage_pct_max``
    are numbers or None, and ``ko`` is
    ``{"ohko_chance", "twohko_chance"}`` or None. Returns ``None`` if the
    oracle is disabled / unavailable / fails.
    """
    try:
        if not getattr(ctx.sim, "enable_showdown_oracle", False):
            return None
        if mon is None or mon_opp is None:
            return None
        from pokechamp.battle_state_mapper import battle_to_oracle_payload
        from pokechamp.showdown_oracle import (
            _CACHE_MISS,
            get_oracle_cache,
            get_shared_oracle,
        )

        payload = battle_to_oracle_payload(ctx.battle, mon, mon_opp, move)
        if not payload:
            return None

        move_id = str(payload.get("move_id") or move.id).lower()
        atk = str(getattr(mon, "species", "")).lower()
        defn = str(getattr(mon_opp, "species", "")).lower()
        ash = _active_state_hash(payload)

        cache = get_oracle_cache()
        cached = cache.get(ash, move_id, atk, defn)
        if cached is not _CACHE_MISS:
            return cached  # outcome dict or None — both cached

        oracle = get_shared_oracle()
        if oracle is None:
            cache.set(ash, move_id, atk, defn, None)
            return None

        result = oracle.query(payload)
        outcome: Optional[dict] = None
        if result and result.get("ok"):
            resolved = result.get("resolved", {}) or {}
            damage = result.get("damage", {}) or {}
            ko = result.get("ko_estimate", {}) or {}
            rtype = resolved.get("type")
            rtype = rtype.lower() if isinstance(rtype, str) and rtype else None
            outcome = {
                "type": rtype,
                "base_power": resolved.get("base_power"),
                "damage_pct_median": damage.get("median_pct")
                if damage.get("median_pct") is not None
                else damage.get("max_pct"),
                "damage_pct_min": damage.get("min_pct"),
                "damage_pct_max": damage.get("max_pct"),
                "ko": {
                    "ohko_chance": ko.get("ohko_chance"),
                    "twohko_chance": ko.get("twohko_chance"),
                },
            }
        cache.set(ash, move_id, atk, defn, outcome)
        _logger.debug("oracle outcome move=%s outcome=%s", move_id, outcome)
        return outcome
    except Exception as exc:  # noqa: BLE001 — never raise to tool callers
        _logger.debug("oracle outcome resolve failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@tool(parse_docstring=True)
def calculate_damage(
    move_name: str,
    target_species: Optional[str] = None,
) -> str:
    """Calculate estimated damage for a move against the opponent.

    Uses the battle engine's damage formula to estimate how much HP
    the target will lose, how many turns to KO, and KO probability.

    Args:
        move_name: The move to evaluate (e.g. "thunderbolt").
            Only damaging moves (physical/special category) produce
            meaningful results — status moves will be rejected.
        target_species: Opponent species name. Defaults to current
            opponent active Pokemon.  When specified, the tool will
            look up the matching opponent team member.

    Returns:
        JSON string with min/max HP loss, turns to KO, and details.
    """
    ctx = get_battle_context()
    mon = ctx.active_pokemon
    mon_opp = _find_opponent_pokemon(target_species, ctx)

    if mon is None or mon_opp is None:
        return json.dumps({"error": "No active Pokemon in context"})

    # Find the move
    try:
        move = _find_move(move_name, ctx)
    except Exception:
        return json.dumps({"error": f"Move '{move_name}' not found"})

    # Dynamic moves (weather ball / tera blast / ivy cudgel / facade /
    # knockoff / hex etc.): resolve the real type AND power via the Showdown
    # oracle. The type is overridden on the move so the sim's effectiveness /
    # STAB calc is accurate; the power is NOT overridden on the move (that
    # would double-correct with sim.modify_base_power — the EXP-035 trap),
    # instead the oracle's accurate damage reflects the power directly below.
    outcome = _resolve_move_outcome_via_oracle(ctx, move, mon, mon_opp)
    resolved_type = outcome["type"] if outcome else None
    if resolved_type:
        move = _clone_move_with_type(move, resolved_type)

    # Reject status / non-damaging moves — they don't produce meaningful
    # damage numbers and would return absurd turns_to_ko values.
    move_cat = str(move.category).upper() if move.category else ""
    if "STATUS" in move_cat or move.base_power == 0:
        return json.dumps({
            "error": (
                f"'{move_name}' is a status move (category: {move_cat}), "
                "not a damaging move. Use get_move_details for status move info."
            ),
        })

    try:
        # Use LocalSim for damage calculation via calculate_remaining_hp
        hp1, hp2, m1_ok, m2_ok = ctx.sim.calculate_remaining_hp(
            p1=mon,
            p2=mon_opp,
            m1=move,
            m2=Move("splash", gen=ctx.sim.gen.gen),  # placeholder for opponent
        )

        # Estimate turns to faint
        from pokechamp.prompts import get_number_turns_faint

        turns, remaining_hp = get_number_turns_faint(
            mon, move, mon_opp, ctx.sim, return_hp=True
        )

        # Oracle damage correction: replace the LocalSim HP/turns estimate with
        # the oracle's Showdown-accurate damage. Every damaging move is now
        # resolved by the oracle (not just dynamic ones) so all moves share one
        # yardstick — the LocalSim path's category bias (special under-stated,
        # physical over-stated) used to distort cross-move comparisons (EXP-046).
        # The power is NOT overridden on the move — the damage observation
        # (hp_lost) already reflects the resolved power, avoiding both the
        # EXP-035 double-correction with sim.modify_base_power and the need for
        # a separate base_power provenance field.
        # Only overwrite the sim estimate when the oracle produced a real
        # damage number. A zero (|cant|nopp| / invalid matchup) must NOT
        # replace the sim value — it would report hp_lost 0% while leaving the
        # sim-derived turns_to_ko, yielding a self-contradictory observation.
        dmg_median = outcome.get("damage_pct_median") if outcome else None
        if outcome and (dmg_median or 0) > 0:
            hp2 = max(0, round(100 - dmg_median))
            ko = outcome.get("ko") or {}
            if ko.get("ohko_chance") is not None and ko["ohko_chance"] >= 0.5:
                turns = 1
            elif ko.get("twohko_chance") is not None and ko["twohko_chance"] >= 0.5:
                turns = 2

        result = {
            "move": move_name,
            "attacker": str(mon.species),
            "defender": str(mon_opp.species),
            "defender_hp_after": f"{hp2}%",
            "hp_lost": f"{100 - hp2}%",
            "turns_to_ko": turns,
            "estimated_remaining_hp": round(remaining_hp, 3) if remaining_hp else None,
        }
        # N-roll damage range (난수 분산 반영). median 단일 값에 min/max 부가.
        if outcome:
            dmin = outcome.get("damage_pct_min")
            dmax = outcome.get("damage_pct_max")
            if (
                dmin is not None
                and dmax is not None
                and not (dmin == dmax == dmg_median)
            ):
                result["hp_lost_min"] = f"{round(dmin)}%"
                result["hp_lost_max"] = f"{round(dmax)}%"
        if resolved_type:
            result["effective_type"] = resolved_type.capitalize()
            result["type_source"] = "showdown_oracle"
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool(parse_docstring=True)
def check_type_effectiveness(
    attacking_type: str,
    defender_species: Optional[str] = None,
) -> str:
    """Check type effectiveness of an attacking type against a Pokemon.

    Args:
        attacking_type: The attacking type (e.g. "fire", "water").
        defender_species: Target species. Defaults to current opponent.

    Returns:
        Damage multiplier and description (e.g. "2x super effective").
    """
    ctx = get_battle_context()
    mon_opp = _find_opponent_pokemon(defender_species, ctx)

    if mon_opp is None:
        return json.dumps({"error": "No opponent Pokemon in context"})

    try:
        type_chart = ctx.sim.gen.type_chart
        multiplier = _get_type_multiplier(attacking_type, mon_opp, type_chart)

        if multiplier == 0:
            desc = "immune (no effect)"
        elif multiplier < 1:
            desc = f"not very effective ({multiplier}x)"
        elif multiplier == 1:
            desc = "neutral (1x)"
        else:
            desc = f"super effective ({multiplier}x)"

        result = {
            "attacking_type": attacking_type.capitalize(),
            "defender": str(mon_opp.species),
            "defender_types": _get_pokemon_types(mon_opp),
            "multiplier": multiplier,
            "description": desc,
        }
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool(parse_docstring=True)
def analyze_matchup(
    attacker_species: Optional[str] = None,
    defender_species: Optional[str] = None,
) -> str:
    """Analyze the matchup between two Pokemon.

    Compares speed tiers, best attacking moves, and type advantages.

    Args:
        attacker_species: Attacker species. Defaults to active Pokemon.
        defender_species: Defender species. Defaults to opponent.

    Returns:
        JSON with speed comparison, best move, and matchup score.
    """
    ctx = get_battle_context()
    mon = ctx.active_pokemon
    mon_opp = ctx.opponent_pokemon

    if mon is None or mon_opp is None:
        return json.dumps({"error": "No active Pokemon in context"})

    try:
        type_chart = ctx.sim.gen.type_chart

        # Speed comparison
        my_speed = mon.base_stats.get("spe", 0)
        opp_speed = mon_opp.base_stats.get("spe", 0)
        speed_ratio = my_speed / max(opp_speed, 1)

        # Type advantage analysis using the corrected helper
        my_types = _get_pokemon_types(mon)
        opp_types = _get_pokemon_types(mon_opp)

        my_type_adv = []
        for t in my_types:
            mult = _get_type_multiplier(t, mon_opp, type_chart)
            my_type_adv.append({"type": t.capitalize(), "multiplier": mult})

        opp_type_adv = []
        for t in opp_types:
            mult = _get_type_multiplier(t, mon, type_chart)
            opp_type_adv.append({"type": t.capitalize(), "multiplier": mult})

        # Best move estimate
        best_move = None
        best_turns = 999
        from pokechamp.prompts import get_number_turns_faint

        for m in mon.moves.values():
            # Skip status moves
            m_cat = str(m.category).upper() if m.category else ""
            if "STATUS" in m_cat or m.base_power == 0:
                continue
            try:
                turns = get_number_turns_faint(mon, m, mon_opp, ctx.sim)
                if turns < best_turns:
                    best_turns = turns
                    best_move = str(m.id)
            except Exception:
                continue

        result = {
            "attacker": str(mon.species),
            "defender": str(mon_opp.species),
            "speed": {
                "attacker_base": my_speed,
                "defender_base": opp_speed,
                "ratio": round(speed_ratio, 2),
                "outspeed": speed_ratio > 1,
            },
            "type_advantage": {
                "my_offense_vs_opp": my_type_adv,
                "opp_offense_vs_me": opp_type_adv,
            },
            "best_move": best_move,
            "best_move_turns_to_ko": best_turns if best_move else None,
            "hp": {
                "attacker": round(mon.current_hp_fraction, 3),
                "defender": round(mon_opp.current_hp_fraction, 3),
            },
        }
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool(parse_docstring=True)
def get_team_analysis(side: str = "player") -> str:
    """Analyze a team's type coverage and weaknesses.

    Args:
        side: Which team to analyze — "player" or "opponent".
            Defaults to "player".

    Returns:
        JSON with team members, type coverage, and weakness summary.
    """
    ctx = get_battle_context()
    battle = ctx.battle

    if side == "player":
        team = battle.team
    else:
        team = battle.opponent_team

    if not team:
        return json.dumps({"error": f"No {side} team data available"})

    type_chart = ctx.sim.gen.type_chart

    members = []
    all_weaknesses: dict[str, list[str]] = {}
    all_resistances: dict[str, list[str]] = {}

    ALL_TYPES = [
        "NORMAL", "FIRE", "WATER", "ELECTRIC", "GRASS", "ICE",
        "FIGHTING", "POISON", "GROUND", "FLYING", "PSYCHIC", "BUG",
        "ROCK", "GHOST", "DRAGON", "DARK", "STEEL", "FAIRY",
    ]

    for pokemon in team.values():
        if pokemon.fainted:
            continue
        info = _pokemon_to_dict(pokemon)
        members.append(info)

        # Check all attacking types against this Pokemon
        for atk_type in ALL_TYPES:
            try:
                mult = _get_type_multiplier(atk_type, pokemon, type_chart)
                if mult >= 2:
                    all_weaknesses.setdefault(atk_type.capitalize(), []).append(
                        str(pokemon.species)
                    )
                elif mult <= 0.5:
                    all_resistances.setdefault(atk_type.capitalize(), []).append(
                        str(pokemon.species)
                    )
            except Exception:
                continue

    alive_count = sum(1 for p in team.values() if not p.fainted)
    fainted_count = sum(1 for p in team.values() if p.fainted)

    result = {
        "side": side,
        "alive": alive_count,
        "fainted": fainted_count,
        "members": members,
        "shared_weaknesses": {
            k: v for k, v in all_weaknesses.items() if len(v) >= 2
        },
        "shared_resistances": {
            k: v for k, v in all_resistances.items() if len(v) >= 2
        },
    }
    return json.dumps(result, ensure_ascii=False)


@tool(parse_docstring=True)
def predict_opponent_moves(species: Optional[str] = None) -> str:
    """Predict the opponent's likely moveset for a Pokemon.

    Combines confirmed (revealed) moves with statistical predictions
    from the Bayesian move predictor or species data.

    Args:
        species: Pokemon species to predict. Defaults to opponent's
            active Pokemon.  When specified, searches the opponent
            team for the matching member.

    Returns:
        JSON with confirmed and predicted moves.
    """
    ctx = get_battle_context()
    target = _find_opponent_pokemon(species, ctx)

    if target is None:
        return json.dumps({"error": "No opponent Pokemon in context"})

    try:
        # Get confirmed + predicted moves via LocalSim
        if ctx.sim:
            moves = ctx.sim.get_opponent_current_moves(
                mon=target, return_separate=True
            )
            if isinstance(moves, tuple) and len(moves) == 2:
                confirmed, predicted = moves
            else:
                confirmed = list(moves) if moves else []
                predicted = []
        else:
            confirmed = [str(m.id) for m in target.moves.values()]
            predicted = []

        # Fallback: species move pool from cache
        if not confirmed and not predicted:
            pokemon_move_dict = get_cached_pokemon_move_dict()
            species_key = str(target.species).lower()
            if species_key in pokemon_move_dict:
                predicted = list(pokemon_move_dict[species_key].keys())[:8]

        result = {
            "species": str(target.species),
            "confirmed_moves": confirmed,
            "predicted_moves": predicted[:8],
        }
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool(parse_docstring=True)
def simulate_turn(player_move: str, estimated_opponent_move: str) -> str:
    """Simulate one turn with given moves and return the result.

    Args:
        player_move: Move the player will use.
        estimated_opponent_move: Move the opponent is estimated to use.

    Returns:
        JSON with resulting HP, status changes, and field effects.
    """
    ctx = get_battle_context()
    mon = ctx.active_pokemon
    mon_opp = ctx.opponent_pokemon

    if mon is None or mon_opp is None:
        return json.dumps({"error": "No active Pokemon in context"})

    try:
        # Create Move objects
        player_m = _find_move(player_move, ctx)
        opp_m = _find_move(estimated_opponent_move, ctx)

        # Resolve BOTH moves via the oracle on the same Showdown-accurate
        # yardstick (player and opponent). Each move's power is reflected via
        # the hp_lost correction below (not overridden on the move — EXP-035
        # double-correction guard). Falls back to the base move on any failure.
        player_outcome = _resolve_move_outcome_via_oracle(
            ctx, player_m, mon, mon_opp
        )
        player_resolved_type = player_outcome["type"] if player_outcome else None
        if player_resolved_type:
            player_m = _clone_move_with_type(player_m, player_resolved_type)

        # Opponent's estimated move — attacker is the opponent active, target
        # is the player active (argument order drives payload actor mapping).
        opp_outcome = _resolve_move_outcome_via_oracle(
            ctx, opp_m, mon_opp, mon
        )
        opp_resolved_type = opp_outcome["type"] if opp_outcome else None
        if opp_resolved_type:
            opp_m = _clone_move_with_type(opp_m, opp_resolved_type)

        # Save current HP for comparison
        hp_before_player = mon.current_hp_fraction
        hp_before_opp = mon_opp.current_hp_fraction

        # Simulate via LocalSim
        hp1, hp2, m1_ok, m2_ok = ctx.sim.calculate_remaining_hp(
            p1=mon, p2=mon_opp, m1=player_m, m2=opp_m
        )

        # Oracle damage correction (median 기반; N-roll 난수 분산 반영):
        # player's damage → opponent HP (hp2); opponent's → player HP (hp1).
        # Guard: only apply a real (>0) median; zero keeps the sim value.
        pmed = player_outcome.get("damage_pct_median") if player_outcome else None
        omed = opp_outcome.get("damage_pct_median") if opp_outcome else None
        if player_outcome and (pmed or 0) > 0:
            hp2 = max(0, round(100 - pmed))
        if opp_outcome and (omed or 0) > 0:
            hp1 = max(0, round(100 - omed))

        result = {
            "player_move": player_move,
            "opponent_move": estimated_opponent_move,
            "player_hp_before": round(hp_before_player, 3),
            "player_hp_after": f"{hp1}%",
            "opponent_hp_before": round(hp_before_opp, 3),
            "opponent_hp_after": f"{hp2}%",
            "player_move_success": m1_ok,
            "opponent_move_success": m2_ok,
        }
        # N-roll damage range (난수 분산). player가 가한 damage는 opponent HP,
        # opp가 가한 damage는 player HP 쪽에 부가.
        for outcome, med, hpkey in (
            (player_outcome, pmed, "opponent_hp_lost"),
            (opp_outcome, omed, "player_hp_lost"),
        ):
            if not outcome:
                continue
            dmin = outcome.get("damage_pct_min")
            dmax = outcome.get("damage_pct_max")
            if dmin is not None and dmax is not None and not (dmin == dmax == med):
                result[f"{hpkey}_min"] = f"{round(dmin)}%"
                result[f"{hpkey}_max"] = f"{round(dmax)}%"
        if player_resolved_type:
            result["player_effective_type"] = player_resolved_type.capitalize()
            result["player_type_source"] = "showdown_oracle"
        if opp_resolved_type:
            result["opponent_effective_type"] = opp_resolved_type.capitalize()
            result["opponent_type_source"] = "showdown_oracle"
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool(parse_docstring=True)
def get_move_details(move_name: str) -> str:
    """Get detailed information about a move including dynamic properties.

    Resolves the move's type, base power, and priority based on current
    battle conditions (weather, terrain, tera type, items, etc.).

    Args:
        move_name: The move name to look up (e.g. "thunderbolt").

    Returns:
        JSON with move stats, type, dynamic properties, and effect.
    """
    ctx = get_battle_context()
    mon = ctx.active_pokemon

    try:
        move = _find_move(move_name, ctx)
    except Exception:
        return json.dumps({"error": f"Move '{move_name}' not found"})

    # Static properties — use .name for clean type strings
    result: dict[str, Any] = {
        "name": str(move.id),
        "base_type": move.type.name if move.type else None,
        "base_power": move.base_power,
        "accuracy": move.accuracy,
        "pp": move.current_pp,
        "category": move.category.name if move.category else None,
        "priority": move.priority,
    }

    # Dynamic type resolution
    if mon is not None:
        try:
            dyn_type = resolve_dynamic_type(
                move.id,
                weather=ctx.weather,
                user=mon,
                tera_type=getattr(mon, "_terastallized_type", None),
                user_species=mon.species,
            )
            if dyn_type:
                result["dynamic_type"] = dyn_type
                result["effective_type"] = dyn_type
            else:
                result["effective_type"] = result["base_type"]
        except Exception:
            result["effective_type"] = result["base_type"]

        # Dynamic power resolution
        try:
            dyn_power = resolve_dynamic_power(
                move.id,
                weather=ctx.weather,
                user=mon,
                target=ctx.opponent_pokemon,
                user_item=mon.item if mon.item else None,
                user_status=mon.status if mon.status else None,
            )
            if dyn_power is not None:
                result["dynamic_power"] = dyn_power
                result["effective_power"] = dyn_power
            else:
                result["effective_power"] = result["base_power"]
        except Exception:
            result["effective_power"] = result["base_power"]

        # Dynamic priority resolution
        try:
            dyn_priority = resolve_dynamic_priority(
                move.id,
                terrain=ctx.terrain,
                user=mon,
            )
            if dyn_priority is not None:
                result["dynamic_priority"] = dyn_priority
                result["effective_priority"] = move.priority + dyn_priority
            else:
                result["effective_priority"] = result["priority"]
        except Exception:
            result["effective_priority"] = result["priority"]
    else:
        result["effective_type"] = result["base_type"]
        result["effective_power"] = result["base_power"]
        result["effective_priority"] = result["priority"]

    # Move effect from cache
    try:
        move_effect = get_cached_move_effect()
        move_id = str(move.id)
        if move_id in move_effect:
            result["effect"] = move_effect[move_id]
    except Exception:
        pass

    return json.dumps(result, ensure_ascii=False)


@tool(parse_docstring=True)
def evaluate_position() -> str:
    """Evaluate the current battle position and estimate win probability.

    Uses heuristic evaluation considering HP advantage, team size,
    type matchups, and field conditions.

    Returns:
        JSON with position score (0-100, 50=neutral) and breakdown.
    """
    ctx = get_battle_context()
    battle = ctx.battle
    mon = ctx.active_pokemon
    mon_opp = ctx.opponent_pokemon

    if battle is None:
        return json.dumps({"error": "No battle context"})

    try:
        # Team counts
        my_alive = sum(1 for p in battle.team.values() if not p.fainted)
        opp_alive = sum(1 for p in battle.opponent_team.values() if not p.fainted)

        # HP fractions
        my_hp = round(mon.current_hp_fraction, 3) if mon else 0
        opp_hp = round(mon_opp.current_hp_fraction, 3) if mon_opp else 0

        # Use fast heuristic evaluation from minimax_optimizer
        from pokechamp.minimax_optimizer import fast_battle_evaluation

        score = fast_battle_evaluation(
            active_hp_player=int(my_hp * 100) if mon else 0,
            active_hp_opp=int(opp_hp * 100) if mon_opp else 0,
            team_count_player=my_alive,
            team_count_opp=opp_alive,
            turn=getattr(battle, "turn", 0),
        )

        # Apply team-count correction: if we're down in team numbers,
        # reduce the score heavily — being outnumbered in Pokemon is a
        # massive strategic disadvantage (no switches, game over on faint).
        team_diff = my_alive - opp_alive
        if team_diff < 0:
            # Per-missing-Pokemon penalty
            team_penalty = abs(team_diff) * 25
            # Additional "last Pokemon" penalty: can't switch out
            last_mon_penalty = 35 if my_alive == 1 and opp_alive > 1 else 0
            score = max(0, score - team_penalty - last_mon_penalty)
        elif team_diff > 0:
            # Winning in team count: moderate bonus
            team_bonus = team_diff * 10
            score = min(100, score + team_bonus)

        # Clamp again
        score = max(0, min(100, score))

        result = {
            "score": round(score, 2),
            "interpretation": (
                "strongly winning"
                if score > 70
                else (
                    "slightly winning"
                    if score > 55
                    else (
                        "neutral"
                        if score >= 45
                        else "slightly losing" if score >= 30 else "strongly losing"
                    )
                )
            ),
            "breakdown": {
                "player_active_hp": my_hp,
                "opponent_active_hp": opp_hp,
                "player_team_alive": my_alive,
                "opponent_team_alive": opp_alive,
                "turn": getattr(battle, "turn", 0),
            },
        }
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


# ---------------------------------------------------------------------------
# Tool list export for easy agent configuration
# ---------------------------------------------------------------------------

ALL_BATTLE_TOOLS = [
    calculate_damage,
    check_type_effectiveness,
    analyze_matchup,
    get_team_analysis,
    predict_opponent_moves,
    simulate_turn,
    get_move_details,
    evaluate_position,
]
"""All battle tools as a list for passing to LangGraph agents."""
