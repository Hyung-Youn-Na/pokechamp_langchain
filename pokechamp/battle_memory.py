"""Battle-scoped memory for the ReAct agent (EXP-049a, design D).

Persists across turns within a single battle so the agent can reason about
long-term strategy instead of re-deciding from scratch each turn. Stored on
the ``LangChainPlayer`` instance keyed by ``battle_tag`` (same pattern as
``_decision_counts`` / ``_last_battle_tag`` in ``langchain_player.py``).

Four memory slices:
  1. ``opp_role_balance`` / ``opp_team_roles`` — team-preview role analysis
     (Smogon role compendium). Battle-invariant.
  2. ``opp_revealed`` — per-species revealed moves / item / tera, accumulated
     each turn from the opponent active pokemon.
  3. ``opp_win_condition`` — LLM-inferred opponent win path (updated from the
     agent's JSON output by the player after each turn).
  4. ``my_plan`` — LLM-authored own win plan + next setup/KO timing (updated
     from agent output). ``plan_turn`` gates staleness.

Slices 1-2 are observation-driven; 3-4 are LLM-driven.

See ``docs/architecture/react-architecture-redesign.md`` §4.
"""

from __future__ import annotations

import string
from dataclasses import dataclass, field
from typing import Any, Dict, List


def to_species_key(name: str) -> str:
    """Normalise a species/alias name to the canonical ``species_key``.

    Mirrors the rule in ``parse_sets.py`` / ``smogon-meta-design.md`` §5.3:
    lowercase + strip all punctuation + strip whitespace.
    e.g. ``"Ogerpon-Wellspring"`` → ``"ogerponwellspring"``.
    """
    if not name:
        return ""
    cleaned = name.lower()
    cleaned = cleaned.translate(str.maketrans("", "", string.punctuation))
    cleaned = cleaned.replace(" ", "")
    return cleaned


@dataclass
class BattleMemory:
    """Per-battle accumulated memory (D design)."""

    # ① team-preview role analysis (battle-invariant)
    opp_role_balance: Dict[str, int] = field(default_factory=dict)
    opp_team_roles: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)

    # ② per-species revealed observations (accumulated each turn)
    opp_revealed: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    # ③④ LLM-driven strategy state (written from agent JSON output)
    opp_win_condition: str = ""
    my_plan: str = ""
    plan_turn: int = 0

    # ⑤ team-preview seed (EXP-050a, design B / human-thought point 1):
    # own-team role balance (symmetric to opp_role_balance) and a flag
    # showing whether ``teampreview()`` already seeded a win plan.
    my_role_balance: Dict[str, int] = field(default_factory=dict)
    # ⑤b per-pokemon own role labels (EXP-050a v2, full info injection).
    my_team_roles: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    preview_seed_turn: int = -1  # -1 = no preview seed (fallback); 0 = seeded at preview


def refresh_team_roles(memory: BattleMemory, battle: Any) -> None:
    """Refresh opponent team role analysis from the Smogon role compendium.

    Idempotent: role data is battle-invariant, so calling each turn is safe
    and cheap (one cached dict lookup). Considers every opponent team member
    currently known to the player.
    """
    # Lazy import to avoid a module-load circular dependency through
    # data_cache <-> poke_env.player.baselines.
    from pokechamp.data_cache import get_cached_smogon_roles

    roles_by_pokemon = get_cached_smogon_roles().get("by_pokemon", {}) or {}
    opp_team = getattr(battle, "opponent_team", None) or {}
    if not opp_team:
        # Team-preview stage: opponent_team may not be populated yet, fall
        # back to the preview roster (a list) so preview win-plan seeding
        # (EXP-050a) can see the opponent's role balance.
        preview = getattr(battle, "_teampreview_opponent_team", None)
        if preview:
            opp_team = list(preview)

    if isinstance(opp_team, dict):
        mons = opp_team.values()
    else:
        mons = opp_team

    team_roles: Dict[str, List[Dict[str, Any]]] = {}
    balance: Dict[str, int] = {}
    for mon in mons:
        key = to_species_key(getattr(mon, "species", "") or "")
        if not key:
            continue
        rlist = roles_by_pokemon.get(key)
        if not rlist:
            continue
        team_roles[key] = rlist
        for role in rlist:
            category = role.get("category")
            if category:
                balance[category] = balance.get(category, 0) + 1

    memory.opp_team_roles = team_roles
    memory.opp_role_balance = balance


def refresh_own_team_roles(memory: BattleMemory, battle: Any) -> None:
    """Refresh own team role balance from the Smogon role compendium.

    Symmetric to :func:`refresh_team_roles` but for the player's own team
    (``battle.team``), which has full info (ability/item/moves known), so the
    role mapping is accurate. Only the category balance is stored
    (``my_role_balance``); per-pokemon role lists are not needed at turn
    level (EXP-050a). Idempotent and cheap — role data is battle-invariant.
    """
    # Lazy import to avoid a module-load circular dependency through
    # data_cache <-> poke_env.player.baselines.
    from pokechamp.data_cache import get_cached_smogon_roles

    roles_by_pokemon = get_cached_smogon_roles().get("by_pokemon", {}) or {}
    own_team = getattr(battle, "team", None) or {}

    balance: Dict[str, int] = {}
    team_roles: Dict[str, List[Dict[str, Any]]] = {}
    for mon in own_team.values():
        key = to_species_key(getattr(mon, "species", "") or "")
        if not key:
            continue
        rlist = roles_by_pokemon.get(key)
        if not rlist:
            continue
        team_roles[key] = rlist
        for role in rlist:
            category = role.get("category")
            if category:
                balance[category] = balance.get(category, 0) + 1

    memory.my_role_balance = balance
    memory.my_team_roles = team_roles


# Lead-prediction role weights: categories that commonly open the game.
_LEAD_ROLE_CATEGORIES = ("Entry Hazards", "Pivots", "Setup Sweepers")


def _avg_type_threat(opp_mon: Any, own_team: dict) -> float:
    """How hard ``opp_mon``'s STAB types hit the own team on average (EXP-050a v2).

    ``own_mon.damage_multiplier(attacking_type)`` returns the multiplier when
    the own mon is attacked by ``attacking_type`` (``pokemon.py:543``). Averaged
    over own team × opp's two types. Falls back to 1.0 (neutral) on any error
    so lead prediction never breaks team preview.
    """
    types = [
        t for t in (getattr(opp_mon, "type_1", None), getattr(opp_mon, "type_2", None))
        if t is not None
    ]
    own = list(own_team.values()) if own_team else []
    if not types or not own:
        return 1.0
    total = 0.0
    n = 0
    for own_mon in own:
        for t in types:
            try:
                total += float(own_mon.damage_multiplier(t))
                n += 1
            except Exception:
                pass
    return (total / n) if n else 1.0


def predict_opp_leads(
    battle: Any, memory: BattleMemory, top_n: int = 6
) -> List[Dict[str, Any]]:
    """Rank likely opponent leads from speed tier + role + type threat (EXP-050a v2).

    Deterministic code precompute (no LLM). Each opponent mon is scored:
    ``base spe + LEAD_ROLE_CATEGORIES bonus + type-threat bonus``. Returns the
    ranked list (capped at ``top_n``) with the score breakdown so it can be
    surfaced in the preview prompt as structured reasoning. Considers every
    known opponent mon; at preview time this is the preview roster.
    """
    opp_team = getattr(battle, "opponent_team", None) or {}
    if not opp_team:
        preview = getattr(battle, "_teampreview_opponent_team", None)
        if preview:
            opp_team = list(preview)
    own_team = getattr(battle, "team", None) or {}

    # Lazy import to avoid the module-load circular dependency.
    from pokechamp.data_cache import get_cached_smogon_roles

    roles_by_pokemon = get_cached_smogon_roles().get("by_pokemon", {}) or {}

    mons = opp_team.values() if isinstance(opp_team, dict) else opp_team
    scored: List[Dict[str, Any]] = []
    for mon in mons:
        species = getattr(mon, "species", "") or ""
        key = to_species_key(species)
        if not key:
            continue
        base_stats = getattr(mon, "base_stats", None) or {}
        spe = base_stats.get("spe", 0) if isinstance(base_stats, dict) else 0
        roles = roles_by_pokemon.get(key, [])
        cats = sorted({r.get("category", "") for r in roles if r.get("category")})
        cat_bonus = sum(1 for c in cats if c in _LEAD_ROLE_CATEGORIES)
        threat = _avg_type_threat(mon, own_team)
        score = float(spe) + cat_bonus * 50.0 + threat * 30.0
        scored.append(
            {
                "species": species,
                "key": key,
                "speed": spe,
                "roles": cats,
                "lead_role_bonus": cat_bonus,
                "type_threat": round(threat, 2),
                "score": round(score, 1),
            }
        )
    scored.sort(key=lambda d: -d["score"])
    return scored[:top_n] if top_n > 0 else scored


def gather_preview_strategy(
    species_list: List[str], cap: int = 0
) -> Dict[str, str]:
    """Prefetch Smogon overview text for a list of species (EXP-050a v2).

    Used at team preview to inject community strategy (checks / weaknesses /
    win paths) into the win-plan prompt. ``cap`` > 0 truncates each overview
    (``cap=0`` = no truncation). Missing species / empty overview map to a
    placeholder so the LLM sees the data limitation explicitly. Cached via
    ``get_cached_smogon_strategies`` (lru_cache) — repeated lookups are cheap.
    """
    from pokechamp.data_cache import get_cached_smogon_strategies

    strats = get_cached_smogon_strategies()
    out: Dict[str, str] = {}
    for name in species_list:
        key = to_species_key(name or "")
        if not key:
            continue
        entry = strats.get(key) or {}
        ov = (entry.get("overview") or "").strip()
        if cap > 0:
            ov = ov[:cap]
        out[key] = ov if ov else "(no overview available)"
    return out


def update_opp_revealed(memory: BattleMemory, battle: Any) -> None:
    """Accumulate revealed opponent observations from the active opponent pokemon.

    Records the currently-known moveset, item and tera state for the opponent
    active pokemon. ``poke_env``'s ``Pokemon.moves`` only contains revealed
    moves, so this grows monotonically within a battle.
    """
    mon = getattr(battle, "opponent_active_pokemon", None)
    if mon is None:
        return

    key = to_species_key(getattr(mon, "species", "") or "")
    if not key:
        return

    entry = memory.opp_revealed.setdefault(
        key,
        {"moves": [], "item": None, "tera": None, "first_seen_turn": None},
    )

    # Revealed moves (Dict[str, Move] → move ids)
    moves = list((getattr(mon, "moves", {}) or {}).keys())
    if moves:
        entry["moves"] = moves

    item = getattr(mon, "item", None)
    if item:
        entry["item"] = str(item)

    tera_type = getattr(mon, "_terastallized_type", None)
    if tera_type is not None:
        entry["tera"] = str(tera_type)

    turn = getattr(battle, "turn", 0) or 0
    if entry.get("first_seen_turn") is None:
        entry["first_seen_turn"] = turn
    entry["last_seen_turn"] = turn


def plan_is_stale(memory: BattleMemory, current_turn: int, max_age: int = 5) -> bool:
    """Whether ``my_plan`` is too old to trust (freshness gate).

    A plan older than ``max_age`` turns is treated as stale so the agent is
    nudged to re-formulate it rather than lean on an obsolete plan.
    """
    if not memory.my_plan:
        return True
    if memory.plan_turn <= 0:
        return True
    return (current_turn - memory.plan_turn) > max_age
