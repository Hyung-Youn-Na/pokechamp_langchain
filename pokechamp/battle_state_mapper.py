"""Battle state mapper — converts poke_env state to oracle request payloads.

This module provides ``battle_to_oracle_payload``, which translates a
poke_env ``Battle`` / ``Pokemon`` / ``Move`` snapshot into a JSON-serializable
dict suitable for the Node oracle worker's stdin/stdout JSON-line protocol.

Key design constraints:
- **Read-only**: source objects are never mutated.
- **Defensive**: missing optional fields fall back to ``getattr`` defaults.
- **Normalized IDs**: all identifiers are lowercased with non-alphanumeric
  characters removed (Showdown convention).
- **JSON-safe**: the returned dict passes ``json.dumps`` without error.
"""

from __future__ import annotations

import json
import random
import uuid
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    from poke_env.environment.battle import Battle
    from poke_env.environment.move import Move
    from poke_env.environment.pokemon import Pokemon


# ---------------------------------------------------------------------------
# ID normalisation
# ---------------------------------------------------------------------------


def _normalize_id(raw: Any) -> str:
    """Convert an identifier to Showdown format: lowercase, no non-alphanum."""
    if raw is None:
        return ""
    return "".join(ch for ch in str(raw) if ch.isalnum()).lower()


# ---------------------------------------------------------------------------
# Weather / Terrain mapping
# ---------------------------------------------------------------------------

# Weather enum name → Showdown weather id
_WEATHER_MAP: Dict[str, str] = {
    "RAINDANCE": "raindance",
    "SUNNYDAY": "sunnyday",
    "SANDSTORM": "sandstorm",
    "HAIL": "hail",
    "SNOW": "snow",
    "SNOWSCAPE": "snowscape",
    "DESOLATELAND": "desolateland",
    "DELTASTREAM": "deltastream",
    "PRIMORDIALSEA": "primordialsea",
}

# Field enum names that are terrains → Showdown terrain id
_TERRAIN_MAP: Dict[str, str] = {
    "ELECTRIC_TERRAIN": "electricterrain",
    "GRASSY_TERRAIN": "grassyterrain",
    "MISTY_TERRAIN": "mistyterrain",
    "PSYCHIC_TERRAIN": "psychicterrain",
}


def _extract_weather(weather_dict: Any) -> Optional[str]:
    """Return the active Showdown weather id, or ``None``."""
    if not weather_dict or not isinstance(weather_dict, dict):
        return None
    for weather_enum in weather_dict:
        name = getattr(weather_enum, "name", str(weather_enum))
        mapped = _WEATHER_MAP.get(name.upper())
        if mapped:
            return mapped
        # Fallback: normalize the enum name
        return _normalize_id(name)
    return None


def _extract_terrain(fields_dict: Any) -> Optional[str]:
    """Return the active Showdown terrain id, or ``None``."""
    if not fields_dict or not isinstance(fields_dict, dict):
        return None
    for field_enum in fields_dict:
        if getattr(field_enum, "is_terrain", False):
            name = getattr(field_enum, "name", str(field_enum))
            mapped = _TERRAIN_MAP.get(name.upper())
            if mapped:
                return mapped
            return _normalize_id(name)
    return None


# ---------------------------------------------------------------------------
# Status mapping
# ---------------------------------------------------------------------------

# Status enum name → Showdown abbreviated format
_STATUS_MAP: Dict[str, str] = {
    "BRN": "brn",
    "PAR": "par",
    "PSN": "psn",
    "TOX": "tox",
    "FRZ": "frz",
    "SLP": "slp",
    "FNT": "fnt",
}


def _map_status(status: Any) -> Optional[str]:
    """Map a poke_env ``Status`` enum value to a Showdown status string."""
    if status is None:
        return None
    name = getattr(status, "name", str(status))
    return _STATUS_MAP.get(name.upper(), _normalize_id(name))


# ---------------------------------------------------------------------------
# Volatiles / Effects mapping
# ---------------------------------------------------------------------------


def _map_volatiles(effects: Any) -> List[str]:
    """Extract volatile IDs from a poke_env ``effects`` dict."""
    if not effects or not isinstance(effects, dict):
        return []
    volatiles: List[str] = []
    for effect_enum in effects:
        name = getattr(effect_enum, "name", str(effect_enum))
        vid = _normalize_id(name)
        if vid:
            volatiles.append(vid)
    return volatiles


# ---------------------------------------------------------------------------
# Boosts mapping
# ---------------------------------------------------------------------------

_DEFAULT_BOOSTS: Dict[str, int] = {
    "atk": 0,
    "def": 0,
    "spa": 0,
    "spd": 0,
    "spe": 0,
    "accuracy": 0,
    "evasion": 0,
}


def _map_boosts(boosts: Any) -> Dict[str, int]:
    """Return a boosts dict with defaults for missing stats."""
    if not boosts or not isinstance(boosts, dict):
        return dict(_DEFAULT_BOOSTS)
    result = dict(_DEFAULT_BOOSTS)
    for stat, value in boosts.items():
        key = _normalize_id(stat)
        if key in result and isinstance(value, int):
            result[key] = value
    return result


# ---------------------------------------------------------------------------
# Active Pokémon state
# ---------------------------------------------------------------------------


def _build_active_state(
    pokemon: Any,
) -> Dict[str, Any]:
    """Build the per-Pokémon active-state dict for the oracle payload."""
    current_hp = getattr(pokemon, "current_hp", 0) or 0
    max_hp = getattr(pokemon, "max_hp", 0) or 0
    hp_pct: float = 100.0
    if max_hp > 0:
        hp_pct = round(current_hp / max_hp * 100, 1)

    species = _normalize_id(getattr(pokemon, "species", ""))
    item = getattr(pokemon, "item", None)
    # The poke_env uses 'unknown_item' for unrevealed items
    if item is not None and str(item).lower() in ("unknown_item", ""):
        item = None
    ability = getattr(pokemon, "ability", None)

    # Tera type
    tera_type = None
    terastallized = getattr(pokemon, "terastallized", False)
    if terastallized:
        raw_tera = getattr(pokemon, "_terastallized_type", None)
        if raw_tera is not None:
            tera_type = _normalize_id(getattr(raw_tera, "name", str(raw_tera)))

    return {
        "species_id": species,
        "level": getattr(pokemon, "level", 100),
        "hp_pct": hp_pct,
        "max_hp": max_hp,
        "status": _map_status(getattr(pokemon, "status", None)),
        "volatiles": _map_volatiles(getattr(pokemon, "effects", None)),
        "boosts": _map_boosts(getattr(pokemon, "boosts", None)),
        "ability": _normalize_id(ability) if ability else None,
        "item": _normalize_id(item) if item else None,
        "tera_type": tera_type,
        "is_terastallized": bool(terastallized),
    }


# ---------------------------------------------------------------------------
# Team packing
# ---------------------------------------------------------------------------


def _pack_pokemon(pokemon: Any) -> str:
    """Pack a single Pokémon into a Showdown packed-team string segment.

    Format (pipe-separated):
        nickname|species|item|ability|moves|nature|evs|gender|ivs|shiny|level|happiness

    Missing fields are left empty.
    """
    parts: List[str] = []

    # nickname (same as species if not set)
    parts.append(_normalize_id(getattr(pokemon, "species", "")) or "mon")
    # species
    parts.append(_normalize_id(getattr(pokemon, "species", "")))
    # item
    item = getattr(pokemon, "item", None)
    if item is not None and str(item).lower() not in ("unknown_item", ""):
        parts.append(_normalize_id(item))
    else:
        parts.append("")
    # ability
    ability = getattr(pokemon, "ability", None)
    parts.append(_normalize_id(ability) if ability else "")
    # moves (comma-separated)
    moves = getattr(pokemon, "moves", {})
    if isinstance(moves, dict):
        parts.append(",".join(_normalize_id(mid) for mid in moves))
    else:
        parts.append("")
    # nature (not available in poke_env for opponent Pokémon)
    parts.append("")
    # evs (not available — leave empty)
    parts.append("")
    # gender
    gender = getattr(pokemon, "gender", None)
    if gender is not None:
        gender_str = str(gender)
        # Gender shows as "M (gender) object" etc. — extract first letter
        parts.append(gender_str[0].upper() if gender_str else "")
    else:
        parts.append("")
    # ivs (not available — leave empty)
    parts.append("")
    # shiny
    parts.append("S" if getattr(pokemon, "shiny", False) else "")
    # level
    level = getattr(pokemon, "level", 100)
    parts.append(str(level) if level != 100 else "")
    # happiness (not available)
    parts.append("")

    return "|".join(parts)


def _pack_team(team: Any) -> str:
    """Pack a team (Dict[str, Pokemon]) into a Showdown packed-team string.

    Each Pokémon is separated by ``]``.
    """
    if not team:
        return ""
    if isinstance(team, dict):
        mons = list(team.values())
    elif isinstance(team, (list, tuple)):
        mons = list(team)
    else:
        return ""
    return "]".join(_pack_pokemon(p) for p in mons)


# ---------------------------------------------------------------------------
# Side conditions mapping
# ---------------------------------------------------------------------------


def _map_side_conditions(
    conditions: Any,
) -> Dict[str, Any]:
    """Map poke_env side conditions to Showdown format."""
    if not conditions or not isinstance(conditions, dict):
        return {}
    result: Dict[str, Any] = {}
    for cond_enum, value in conditions.items():
        name = getattr(cond_enum, "name", str(cond_enum))
        key = _normalize_id(name)
        if key:
            result[key] = value
    return result


# ---------------------------------------------------------------------------
# Actor / target side detection
# ---------------------------------------------------------------------------


def _determine_sides(
    battle: Any,
    user: Any,
    target: Any,
) -> Tuple[str, int, str, int]:
    """Determine actor/target side (p1/p2) and slot (0-based).

    Returns ``(actor_side, actor_slot, target_side, target_slot)``.
    """
    player_role = getattr(battle, "player_role", "p1")

    # Determine which side the user belongs to
    user_species = _normalize_id(getattr(user, "species", ""))
    user_side = player_role  # default: user is on player's side

    # Check if user is in the player's team
    player_team = getattr(battle, "team", {})
    if isinstance(player_team, dict):
        for _key, mon in player_team.items():
            if getattr(mon, "active", False):
                if _normalize_id(getattr(mon, "species", "")) == user_species:
                    user_side = player_role
                    break
        else:
            # Not found in player team — check opponent team
            opp_team = getattr(battle, "opponent_team", {})
            if isinstance(opp_team, dict):
                for _key, mon in opp_team.items():
                    if _normalize_id(getattr(mon, "species", "")) == user_species:
                        user_side = "p2" if player_role == "p1" else "p1"
                        break

    target_side = "p2" if user_side == "p1" else "p1"

    return user_side, 0, target_side, 0


# ---------------------------------------------------------------------------
# Main mapper function
# ---------------------------------------------------------------------------


def battle_to_oracle_payload(
    battle: Battle,
    user: Pokemon,
    target: Pokemon,
    move: Move,
    *,
    request_id: Optional[str] = None,
) -> dict:
    """Convert poke_env Battle state to oracle worker request payload.

    All IDs are normalized to Showdown format (lowercase, no spaces).
    Returns a dict suitable for ``json.dumps()``.

    Parameters
    ----------
    battle : Battle
        The current battle state.
    user : Pokemon
        The Pokémon using the move.
    target : Pokemon
        The Pokémon targeted by the move.
    move : Move
        The move being used.
    request_id : str, optional
        A unique identifier for the request. Auto-generated if not provided.

    Returns
    -------
    dict
        A JSON-serializable payload for the oracle worker.
    """
    # Ensure the payload is fully JSON-serializable by building from
    # primitive types only.  Never mutate the source objects.
    if request_id is None:
        request_id = str(uuid.uuid4())

    # Weather & terrain
    weather = _extract_weather(getattr(battle, "weather", None))
    terrain = _extract_terrain(getattr(battle, "fields", None))

    # Actor / target sides
    actor_side, actor_slot, target_side, target_slot = _determine_sides(
        battle, user, target
    )

    # Move ID
    move_id = _normalize_id(getattr(move, "id", ""))

    # Teams (packed format)
    player_role = getattr(battle, "player_role", "p1")
    player_team = getattr(battle, "team", {})
    opp_team = getattr(battle, "opponent_team", {})

    if player_role == "p1":
        team_p1 = _pack_team(player_team)
        team_p2 = _pack_team(opp_team)
    else:
        team_p1 = _pack_team(opp_team)
        team_p2 = _pack_team(player_team)

    # Active state
    if player_role == "p1":
        p1_pokemon = [user] if actor_side == "p1" else [target]
        p2_pokemon = [target] if actor_side == "p2" else [user]
        if actor_side == "p1":
            p1_pokemon = [user]
            p2_pokemon = [target]
        else:
            p1_pokemon = [target]
            p2_pokemon = [user]
    else:
        if actor_side == "p2":
            p1_pokemon = [target]
            p2_pokemon = [user]
        else:
            p1_pokemon = [user]
            p2_pokemon = [target]

    active_state = {
        "p1": [_build_active_state(p) for p in p1_pokemon],
        "p2": [_build_active_state(p) for p in p2_pokemon],
    }

    # Side conditions
    player_sc = getattr(battle, "side_conditions", {})
    opp_sc = getattr(battle, "opponent_side_conditions", {})

    if player_role == "p1":
        sc_p1 = _map_side_conditions(player_sc)
        sc_p2 = _map_side_conditions(opp_sc)
    else:
        sc_p1 = _map_side_conditions(opp_sc)
        sc_p2 = _map_side_conditions(player_sc)

    # Build the payload
    payload = {
        "id": request_id,
        "format": "gen9ou",
        "seed": [random.randint(0, 0xFFFFFFFF) for _ in range(4)],
        "actor_side": actor_side,
        "actor_slot": actor_slot,
        "target_side": target_side,
        "target_slot": target_slot,
        "move_id": move_id,
        "weather": weather,
        "terrain": terrain,
        "pseudoweather": [],
        "team_p1": team_p1,
        "team_p2": team_p2,
        "active_state": active_state,
        "side_conditions": {
            "p1": sc_p1,
            "p2": sc_p2,
        },
    }

    # Verify JSON-serializability (defensive — should always succeed)
    json.dumps(payload)

    return payload
