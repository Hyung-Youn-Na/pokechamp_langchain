"""Dynamic move calculation module for PokéChamp.

Pure functions for resolving dynamic move properties (type, power, priority,
fixed damage) based on battle state. All functions are stateless, have no
side effects, and do not depend on the player layer or battle servers.

Usage::

    from pokechamp.dynamic_move import (
        resolve_dynamic_type,
        resolve_dynamic_power,
        resolve_dynamic_priority,
        get_fixed_damage,
        format_dynamic_info,
    )
"""

from typing import Any, Dict, Optional, Union

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _normalize_move_id(move: Any) -> str:
    """Normalize a move identifier to a lowercase id string."""
    if isinstance(move, str):
        return move.lower().replace(" ", "").replace("-", "")
    if hasattr(move, "id"):
        return str(getattr(move, "id")).lower()
    return str(move).lower()


def _normalize_weather(weather: Any) -> Optional[str]:
    """Extract the active weather name (upper-cased), or None if no weather."""
    if weather is None:
        return None
    if isinstance(weather, dict):
        if not weather:
            return None
        w = list(weather.keys())[0]
        return w.name if hasattr(w, "name") else str(w).upper()
    if hasattr(weather, "name"):
        return weather.name
    return str(weather).upper()


def _normalize_terrain(fields: Any) -> Optional[str]:
    """Extract the active terrain name from fields dict, or None."""
    if fields is None:
        return None
    if isinstance(fields, dict):
        for field in fields:
            if hasattr(field, "is_terrain") and field.is_terrain:
                return field.name
        return None
    if hasattr(fields, "name"):
        return fields.name
    if isinstance(fields, str):
        name = fields.upper().replace(" ", "_")
        # Handle "grassyterrain" → "GRASSY_TERRAIN"
        for suffix in ("TERRAIN",):
            if name.endswith(suffix) and "_" not in name:
                name = name[: -len(suffix)] + "_" + suffix
        return name
    return None


def _get_status_name(status: Any) -> Optional[str]:
    """Get status name from Status enum or string. Returns upper-case or None."""
    if status is None:
        return None
    if hasattr(status, "name"):
        return status.name
    s = str(status).strip()
    if not s or s.lower() in ("none", ""):
        return None
    return s.upper()


def _has_status(status: Any) -> bool:
    """Check if a pokemon has a meaningful status condition (not FNT)."""
    s = _get_status_name(status)
    return s is not None and s != "FNT"


_UNSET = object()  # Sentinel for "not provided"


def _get_item(pokemon: Any, fallback: Any = _UNSET) -> Optional[str]:
    """Get item string from a pokemon object or explicit fallback."""
    if fallback is not _UNSET:
        return fallback
    if pokemon is not None:
        return getattr(pokemon, "item", None)
    return None


def _get_weight(pokemon: Any, fallback: Any = _UNSET) -> Optional[float]:
    """Get weight in kg from a pokemon object or explicit fallback."""
    if fallback is not _UNSET:
        return float(fallback) if fallback is not None else None
    if pokemon is not None:
        w = getattr(pokemon, "weight", None)
        if w is not None:
            return float(w)
    return None


def _item_is_removable(item: Any) -> bool:
    """Check if a held item can be knocked off."""
    if item is None:
        return False
    item_str = str(item).strip().lower()
    if not item_str or item_str in ("none", "unknown", ""):
        return False
    # Z-crystals
    if item_str.endswith("iumz") or item_str.endswith("z"):
        return False
    # Mega stones (typically contain 'ite')
    if "ite" in item_str and item_str not in ("whiteherb", "mentalherb"):
        return False
    # Griseous orb, etc.
    if item_str == "griseousorb":
        return False
    # Rusted items (Zacian/Zamazenta)
    if item_str.startswith("rusted"):
        return False
    return True


# Hidden Power type table (Gen VI+ formula)
_HIDDEN_POWER_TYPES = [
    "FIGHTING",
    "FLYING",
    "POISON",
    "GROUND",
    "ROCK",
    "BUG",
    "GHOST",
    "STEEL",
    "FIRE",
    "WATER",
    "GRASS",
    "ELECTRIC",
    "PSYCHIC",
    "ICE",
    "DRAGON",
    "DARK",
]


def _hiddenpower_type_from_ivs(ivs: Dict[str, int]) -> str:
    """Calculate Hidden Power type from IVs using the Gen VI+ formula.

    The type index is ``floor(15 * sum(lsb of each IV) / 63)``.
    """
    a = ivs.get("hp", 31) & 1
    b = (ivs.get("atk", 31) & 1) * 2
    c = (ivs.get("def", 31) & 1) * 4
    d = (ivs.get("spe", 31) & 1) * 8
    e = (ivs.get("spd", 31) & 1) * 16
    f = (ivs.get("spa", 31) & 1) * 32

    index = (15 * (a + b + c + d + e + f)) // 63
    return _HIDDEN_POWER_TYPES[index]


# Weight-tier tables
_LOW_KICK_TIERS = [
    (200.0, 120),
    (100.0, 100),
    (50.0, 80),
    (25.0, 60),
    (10.0, 40),
]

_HEAVY_SLAM_TIERS = [
    (0.2000, 120),
    (0.2500, 100),
    (0.3334, 80),
    (0.5000, 60),
]

# Weather groupings
_SUN_WEATHERS = frozenset({"SUNNYDAY", "DESOLATELAND"})
_RAIN_WEATHERS = frozenset({"RAINDANCE", "PRIMORDIALSEA"})
_HAIL_WEATHERS = frozenset({"HAIL", "SNOW", "SNOWSCAPE"})

# Items that are treated as "no item" for acrobatics
_NO_ITEM_SENTINELS = frozenset({None, "", "none"})


# ---------------------------------------------------------------------------
# Dynamic Type Resolution
# ---------------------------------------------------------------------------


def resolve_dynamic_type(
    move_id: Any,
    *,
    weather: Any = None,
    user: Any = None,
    tera_type: Any = None,
    user_species: Any = None,
    user_form: Any = None,
    ivs: Optional[Dict[str, int]] = None,
    terrain: Any = None,
    user_type_1: Any = None,
    user_grounded: Optional[bool] = None,
    user_item: Any = None,
) -> Optional[str]:
    """Resolve the dynamic type of a move based on battle conditions.

    Parameters
    ----------
    move_id : str or Move
        Move identifier.
    weather : Weather enum, Dict[Weather, int], or None
        Active weather condition.
    user : Pokemon, optional
        User pokemon (used to extract tera_type, species, form, ivs).
    tera_type : str or PokemonType, optional
        Explicit override for the user's Tera type.
    user_species : str, optional
        Explicit override for user's species.
    user_form : str, optional
        Explicit override for user's form.
    ivs : dict, optional
        Explicit override for user's IVs.
    terrain : str or Field enum, optional
        Active terrain (for terrainpulse).
    user_type_1 : str or PokemonType, optional
        User's primary type (for revelationdance).
    user_grounded : bool, optional
        Whether the user is grounded (for terrainpulse).
    user_item : str, optional
        User's held item (for judgment, multiattack, technoblast, naturalgift).

    Returns
    -------
    str or None
        Resolved type name (e.g. ``"Fire"``, ``"Water"``) or ``None``
        when no dynamic type applies.
    """
    mid = _normalize_move_id(move_id)

    if mid == "weatherball":
        return _weatherball_type(weather)
    if mid == "terablast":
        return _terablast_type(user, tera_type)
    if mid == "aurawheel":
        return _aurawheel_type(user, user_species, user_form)
    if mid == "hiddenpower":
        return _hiddenpower_type(user, ivs)
    if mid == "ivycudgel":
        return _ivycudgel_type(user, user_species)
    if mid == "ragingbull":
        return _ragingbull_type(user, user_species)
    if mid == "terastarstorm":
        return _terastarstorm_type(user, user_species)
    if mid == "revelationdance":
        return _revelationdance_type(user_type_1, tera_type)
    if mid == "terrainpulse":
        return _terrainpulse_type(terrain, user_grounded)
    if mid == "judgment":
        return _judgment_type(user_item)
    if mid == "multiattack":
        return _multiattack_type(user_item)
    if mid == "technoblast":
        return _technoblast_type(user_item)
    if mid == "naturalgift":
        return _naturalgift_type(user_item)
    return None


#: Move ids whose type is resolved dynamically. Mirrors the dispatch in
#: :func:`resolve_dynamic_type` (single source of truth) so callers can
#: short-circuit — static moves never need an oracle query.
DYNAMIC_TYPE_MOVE_IDS = frozenset(
    {
        "weatherball",
        "terablast",
        "aurawheel",
        "hiddenpower",
        "ivycudgel",
        "ragingbull",
        "terastarstorm",
        "revelationdance",
        "terrainpulse",
        "judgment",
        "multiattack",
        "technoblast",
        "naturalgift",
    }
)


def is_dynamic_type_move(move_id: Any) -> bool:
    """Return True if ``move_id`` has a dynamically-resolved type.

    Uses :func:`_normalize_move_id` so it accepts any move identifier form
    (str, Move, hyphenated, etc.) consistent with :func:`resolve_dynamic_type`.
    """
    return _normalize_move_id(move_id) in DYNAMIC_TYPE_MOVE_IDS


#: Move ids whose base power is resolved dynamically. Mirrors the dispatch in
#: :func:`resolve_dynamic_power` (single source of truth).
DYNAMIC_POWER_MOVE_IDS = frozenset(
    {
        "acrobatics",
        "facade",
        "knockoff",
        "weatherball",
        "lowkick",
        "grassknot",
        "heavyslam",
        "heatcrash",
        "hex",
        "naturalgift",
    }
)


def is_dynamic_power_move(move_id: Any) -> bool:
    """Return True if ``move_id`` has a dynamically-resolved base power."""
    return _normalize_move_id(move_id) in DYNAMIC_POWER_MOVE_IDS


def is_dynamic_move(move_id: Any) -> bool:
    """Return True if ``move_id`` has a dynamic type OR base power."""
    mid = _normalize_move_id(move_id)
    return mid in DYNAMIC_TYPE_MOVE_IDS or mid in DYNAMIC_POWER_MOVE_IDS


def _weatherball_type(weather: Any) -> str:
    w = _normalize_weather(weather)
    if w is None:
        return "Normal"
    if w in _SUN_WEATHERS:
        return "Fire"
    if w in _RAIN_WEATHERS:
        return "Water"
    if w in _HAIL_WEATHERS:
        return "Ice"
    if w == "SANDSTORM":
        return "Rock"
    return "Normal"


def _terablast_type(user: Any, tera_type: Any = None) -> str:
    # Explicit tera_type kwarg takes precedence
    tt = tera_type
    if tt is not None:
        return tt.name if hasattr(tt, "name") else str(tt)

    # Try to read from user object
    if user is not None:
        is_tera = getattr(user, "terastallized", False)
        if is_tera:
            utt = getattr(user, "_terastallized_type", None)
            if utt is not None:
                return utt.name if hasattr(utt, "name") else str(utt)
    return "Normal"


def _aurawheel_type(
    user: Any, user_species: Any = None, user_form: Any = None
) -> Optional[str]:
    species = user_species
    form = user_form
    if species is None and user is not None:
        species = getattr(user, "species", None)
    if form is None and user is not None:
        # Try common attribute names
        form = getattr(user, "forme", None) or getattr(user, "_forme", None)

    if species is None:
        return None

    species_str = str(species).lower().replace(" ", "").replace("-", "")
    if "morpeko" not in species_str:
        return None

    form_str = str(form).lower() if form else ""
    if "hangry" in form_str or "hangry" in species_str:
        return "Dark"
    return "Electric"


def _hiddenpower_type(user: Any, ivs: Optional[Dict[str, int]] = None) -> Optional[str]:
    if ivs is not None:
        return _hiddenpower_type_from_ivs(ivs)
    if user is not None:
        user_ivs = getattr(user, "ivs", None)
        if user_ivs is not None:
            return _hiddenpower_type_from_ivs(user_ivs)
    return None


# Ogerpon form → Ivy Cudgel type mapping
_OGERPON_FORM_TYPES = {
    "ogerponwellspring": "Water",
    "ogerponhearthflame": "Fire",
    "ogerponcornerstone": "Rock",
}


def _ivycudgel_type(user: Any, user_species: Any = None) -> Optional[str]:
    """Resolve Ivy Cudgel type based on Ogerpon form.

    Wellspring → Water, Hearthflame → Fire, Cornerstone → Rock,
    base Ogerpon → Grass, non-Ogerpon → None.
    """
    species = user_species
    if species is None and user is not None:
        species = getattr(user, "species", None)
    if species is None:
        return None
    species_str = str(species).lower().replace(" ", "").replace("-", "")
    if "ogerpon" not in species_str:
        return None
    # Check specific forms
    if species_str in _OGERPON_FORM_TYPES:
        return _OGERPON_FORM_TYPES[species_str]
    # Base form (ogerpon, ogerpontera) defaults to Grass
    return "Grass"


# Tauros form → Raging Bull type mapping
def _ragingbull_type(user: Any, user_species: Any = None) -> Optional[str]:
    """Resolve Raging Bull type based on Tauros form.

    Paldea-Combat → Fighting, Paldea-Blaze → Fire, Paldea-Aqua → Water,
    base Tauros → Normal, Tauros-Paldea (no breed) → Fighting,
    non-Tauros → None.
    """
    species = user_species
    if species is None and user is not None:
        species = getattr(user, "species", None)
    if species is None:
        return None
    species_str = str(species).lower().replace(" ", "").replace("-", "")
    if "tauros" not in species_str:
        return None
    if "taurospaldeacombat" in species_str:
        return "Fighting"
    if "taurospaldeablaze" in species_str:
        return "Fire"
    if "taurospaldeaaqua" in species_str:
        return "Water"
    if "taurospaldea" in species_str:
        return "Fighting"
    # Base Tauros
    return "Normal"


def _terastarstorm_type(
    user: Any, user_species: Any = None
) -> Optional[str]:
    """Resolve Tera Star Storm type based on Terapagos form.

    Terapagos-Stellar → Stellar, Terapagos-Terastal → Stellar,
    base Terapagos → None, non-Terapagos → None.
    """
    species = user_species
    if species is None and user is not None:
        species = getattr(user, "species", None)
    if species is None:
        return None
    species_str = str(species).lower().replace(" ", "").replace("-", "")
    if "terapagosstellar" in species_str or "terapagosterastal" in species_str:
        return "Stellar"
    return None


def _revelationdance_type(
    user_type_1: Any = None, tera_type: Any = None
) -> Optional[str]:
    """Resolve Revelation Dance type based on user's primary type.

    If terastallized (tera_type provided), use Tera type instead.
    Returns the type string directly, or None if no type provided.
    """
    # Tera type overrides base type_1 when terastallized
    if tera_type is not None:
        return tera_type.name if hasattr(tera_type, "name") else str(tera_type)
    if user_type_1 is None:
        return None
    return user_type_1.name if hasattr(user_type_1, "name") else str(user_type_1)


# Terrain → type mapping for Terrain Pulse
_TERRAIN_TYPES = {
    "ELECTRIC_TERRAIN": "Electric",
    "GRASSY_TERRAIN": "Grass",
    "MISTY_TERRAIN": "Fairy",
    "PSYCHIC_TERRAIN": "Psychic",
}


def _terrainpulse_type(
    terrain: Any = None, user_grounded: Optional[bool] = None
) -> Optional[str]:
    """Resolve Terrain Pulse type based on active terrain.

    Returns the terrain's corresponding type if the user is grounded,
    or None if no terrain, user is not grounded, or terrain is unknown.
    """
    if user_grounded is not True:
        return None
    terrain_name = _normalize_terrain(terrain)
    if terrain_name is None:
        return None
    terrain_upper = str(terrain_name).upper()
    # Handle both "ELECTRIC_TERRAIN" and "ELECTRICTERRAIN" formats
    for key, dtype in _TERRAIN_TYPES.items():
        if terrain_upper == key or terrain_upper == key.replace("_", ""):
            return dtype
    return None


# Plate → type mapping for Judgment (17 plates, Z-crystals excluded)
_PLATE_TYPES: Dict[str, str] = {
    "dracoplate": "Dragon",
    "dreadplate": "Dark",
    "earthplate": "Ground",
    "fistplate": "Fighting",
    "flameplate": "Fire",
    "icicleplate": "Ice",
    "insectplate": "Bug",
    "ironplate": "Steel",
    "meadowplate": "Grass",
    "mindplate": "Psychic",
    "pixieplate": "Fairy",
    "skyplate": "Flying",
    "splashplate": "Water",
    "spookyplate": "Ghost",
    "stoneplate": "Rock",
    "toxicplate": "Poison",
    "zapplate": "Electric",
}

# Memory → type mapping for Multi-Attack (17 memories)
_MEMORY_TYPES: Dict[str, str] = {
    "bugmemory": "Bug",
    "darkmemory": "Dark",
    "dragonmemory": "Dragon",
    "electricmemory": "Electric",
    "fairymemory": "Fairy",
    "fightingmemory": "Fighting",
    "firememory": "Fire",
    "flyingmemory": "Flying",
    "ghostmemory": "Ghost",
    "grassmemory": "Grass",
    "groundmemory": "Ground",
    "icememory": "Ice",
    "poisonmemory": "Poison",
    "psychicmemory": "Psychic",
    "rockmemory": "Rock",
    "steelmemory": "Steel",
    "watermemory": "Water",
}

# Drive → type mapping for Techno Blast (4 drives)
_DRIVE_TYPES: Dict[str, str] = {
    "burndrive": "Fire",
    "chilldrive": "Ice",
    "dousedrive": "Water",
    "shockdrive": "Electric",
}

# Berry → type mapping for Natural Gift
_BERRY_TYPES: Dict[str, str] = {
    "aguavberry": "Dragon",
    "apicotberry": "Ground",
    "aspearberry": "Ice",
    "babiriberry": "Steel",
    "belueberry": "Electric",
    "bitterberry": "Ground",
    "blukberry": "Fire",
    "burntberry": "Ice",
    "chartiberry": "Rock",
    "cheriberry": "Fire",
    "chestoberry": "Water",
    "chilanberry": "Normal",
    "chopleberry": "Fighting",
    "cobaberry": "Flying",
    "colburberry": "Dark",
    "cornnberry": "Bug",
    "custapberry": "Ghost",
    "durinberry": "Water",
    "enigmaberry": "Bug",
    "figyberry": "Bug",
    "ganlonberry": "Ice",
    "goldberry": "Psychic",
    "grepaberry": "Flying",
    "habanberry": "Dragon",
    "hondewberry": "Ground",
    "iapapaberry": "Dark",
    "iceberry": "Grass",
    "jabocaberry": "Dragon",
    "kasibberry": "Ghost",
    "kebiaberry": "Poison",
    "keeberry": "Fairy",
    "kelpsyberry": "Fighting",
    "lansatberry": "Flying",
    "leppaberry": "Fighting",
    "liechiberry": "Grass",
    "lumberry": "Flying",
    "magoberry": "Ghost",
    "magostberry": "Rock",
    "marangaberry": "Dark",
    "micleberry": "Rock",
    "mintberry": "Water",
    "miracleberry": "Flying",
    "mysteryberry": "Fighting",
    "nanabberry": "Water",
    "nomelberry": "Dragon",
    "occaberry": "Fire",
    "oranberry": "Poison",
    "pamtresberry": "Steel",
    "passhoberry": "Water",
    "payapaberry": "Psychic",
    "pechaberry": "Electric",
    "persimberry": "Ground",
    "petayaberry": "Poison",
    "pinapberry": "Grass",
    "pomegberry": "Ice",
    "przcureberry": "Fire",
    "psncureberry": "Electric",
    "qualotberry": "Poison",
    "rabutaberry": "Ghost",
    "rawstberry": "Grass",
    "razzberry": "Steel",
    "rindoberry": "Grass",
    "roseliberry": "Fairy",
    "rowapberry": "Dark",
    "salacberry": "Fighting",
    "shucaberry": "Ground",
    "sitrusberry": "Psychic",
    "spelonberry": "Dark",
    "starfberry": "Psychic",
    "tamatoberry": "Psychic",
    "tangaberry": "Bug",
    "wacanberry": "Electric",
    "watmelberry": "Fire",
    "wepearberry": "Electric",
    "wikiberry": "Rock",
    "yacheberry": "Ice",
}

# Berry → base power mapping for Natural Gift
_BERRY_POWERS: Dict[str, int] = {
    "aguavberry": 80,
    "apicotberry": 100,
    "aspearberry": 80,
    "babiriberry": 80,
    "belueberry": 100,
    "bitterberry": 80,
    "blukberry": 90,
    "burntberry": 80,
    "chartiberry": 80,
    "cheriberry": 80,
    "chestoberry": 80,
    "chilanberry": 80,
    "chopleberry": 80,
    "cobaberry": 80,
    "colburberry": 80,
    "cornnberry": 90,
    "custapberry": 100,
    "durinberry": 100,
    "enigmaberry": 100,
    "figyberry": 80,
    "ganlonberry": 100,
    "goldberry": 80,
    "grepaberry": 90,
    "habanberry": 80,
    "hondewberry": 90,
    "iapapaberry": 80,
    "iceberry": 80,
    "jabocaberry": 100,
    "kasibberry": 80,
    "kebiaberry": 80,
    "keeberry": 100,
    "kelpsyberry": 90,
    "lansatberry": 100,
    "leppaberry": 80,
    "liechiberry": 100,
    "lumberry": 80,
    "magoberry": 80,
    "magostberry": 90,
    "marangaberry": 100,
    "micleberry": 100,
    "mintberry": 80,
    "miracleberry": 80,
    "mysteryberry": 80,
    "nanabberry": 90,
    "nomelberry": 90,
    "occaberry": 80,
    "oranberry": 80,
    "pamtresberry": 90,
    "passhoberry": 80,
    "payapaberry": 80,
    "pechaberry": 80,
    "persimberry": 80,
    "petayaberry": 100,
    "pinapberry": 90,
    "pomegberry": 90,
    "przcureberry": 80,
    "psncureberry": 80,
    "qualotberry": 90,
    "rabutaberry": 90,
    "rawstberry": 80,
    "razzberry": 80,
    "rindoberry": 80,
    "roseliberry": 80,
    "rowapberry": 100,
    "salacberry": 100,
    "shucaberry": 80,
    "sitrusberry": 80,
    "spelonberry": 90,
    "starfberry": 100,
    "tamatoberry": 90,
    "tangaberry": 80,
    "wacanberry": 80,
    "watmelberry": 100,
    "wepearberry": 90,
    "wikiberry": 80,
    "yacheberry": 80,
}


def _judgment_type(user_item: Any = None) -> Optional[str]:
    """Resolve Judgment type based on held plate item.

    Looks up the item in _PLATE_TYPES. Z-crystals and non-plate items
    return None.
    """
    if user_item is None:
        return None
    item_str = str(user_item).lower().replace(" ", "").replace("-", "")
    return _PLATE_TYPES.get(item_str)


def _multiattack_type(user_item: Any = None) -> Optional[str]:
    """Resolve Multi-Attack type based on held memory item."""
    if user_item is None:
        return None
    item_str = str(user_item).lower().replace(" ", "").replace("-", "")
    return _MEMORY_TYPES.get(item_str)


def _technoblast_type(user_item: Any = None) -> Optional[str]:
    """Resolve Techno Blast type based on held drive item."""
    if user_item is None:
        return None
    item_str = str(user_item).lower().replace(" ", "").replace("-", "")
    return _DRIVE_TYPES.get(item_str)


def _naturalgift_type(user_item: Any = None) -> Optional[str]:
    """Resolve Natural Gift type based on held berry item.

    Looks up the item in _BERRY_TYPES. Unknown berries (even those
    ending with 'berry') return None.
    """
    if user_item is None:
        return None
    item_str = str(user_item).lower().replace(" ", "").replace("-", "")
    return _BERRY_TYPES.get(item_str)


def _naturalgift_power(user_item: Any = None) -> Optional[int]:
    """Resolve Natural Gift base power based on held berry item."""
    if user_item is None:
        return None
    item_str = str(user_item).lower().replace(" ", "").replace("-", "")
    return _BERRY_POWERS.get(item_str)


# ---------------------------------------------------------------------------
# Dynamic Power Resolution
# ---------------------------------------------------------------------------


def resolve_dynamic_power(
    move_id: Any,
    *,
    weather: Any = None,
    user: Any = None,
    target: Any = None,
    user_item: Any = None,
    user_status: Any = None,
    target_item: Any = None,
    target_status: Any = None,
    user_weightkg: Optional[float] = None,
    target_weightkg: Optional[float] = None,
) -> Optional[Union[int, float]]:
    """Resolve the dynamic base power of a move based on battle conditions.

    Parameters
    ----------
    move_id : str or Move
        Move identifier.
    weather : Weather enum, Dict[Weather, int], or None
        Active weather.
    user : Pokemon, optional
        User pokemon.
    target : Pokemon, optional
        Target pokemon.
    user_item, user_status : overrides
        Explicit values for user's item and status.
    target_item, target_status : overrides
        Explicit values for target's item and status.
    user_weightkg, target_weightkg : float, optional
        Explicit weight overrides.

    Returns
    -------
    int, float, or None
        Resolved base power, or ``None`` if no dynamic power applies.
    """
    mid = _normalize_move_id(move_id)

    if mid == "acrobatics":
        return _acrobatics_power(user, user_item)
    if mid == "facade":
        return _facade_power(user, user_status)
    if mid == "knockoff":
        return _knockoff_power(target, target_item)
    if mid == "weatherball":
        return _weatherball_power(weather)
    if mid in ("lowkick", "grassknot"):
        return _low_kick_power(target, target_weightkg)
    if mid in ("heavyslam", "heatcrash"):
        return _heavy_slam_power(user, target, user_weightkg, target_weightkg)
    if mid == "hex":
        return _hex_power(target, target_status)
    if mid == "naturalgift":
        return _naturalgift_power(user_item)
    return None


def _acrobatics_power(user: Any, user_item: Any = None) -> int:
    item = _get_item(user, user_item)
    if item in _NO_ITEM_SENTINELS or (
        isinstance(item, str) and item.strip().lower() == ""
    ):
        return 110
    return 55


def _facade_power(user: Any, user_status: Any = None) -> int:
    status = user_status
    if status is None and user is not None:
        status = getattr(user, "status", None)
    if _has_status(status):
        return 140
    return 70


def _knockoff_power(target: Any, target_item: Any = None) -> float:
    item = _get_item(target, target_item)
    if _item_is_removable(item):
        return 97.5
    return 65


def _weatherball_power(weather: Any) -> int:
    w = _normalize_weather(weather)
    if w is not None and w != "UNKNOWN":
        return 100
    return 50


def _low_kick_power(target: Any, target_weightkg: Any = None) -> int:
    weight = _get_weight(target, target_weightkg)
    if weight is None:
        return 40
    for threshold, power in _LOW_KICK_TIERS:
        if weight > threshold:
            return power
    return 20


def _heavy_slam_power(
    user: Any,
    target: Any,
    user_weightkg: Any = None,
    target_weightkg: Any = None,
) -> int:
    user_w = _get_weight(user, user_weightkg)
    target_w = _get_weight(target, target_weightkg)
    if user_w is None or target_w is None:
        return 40
    if user_w == 0:
        return 40
    ratio = target_w / user_w
    for threshold, power in _HEAVY_SLAM_TIERS:
        if ratio < threshold:
            return power
    return 40


def _hex_power(target: Any, target_status: Any = None) -> int:
    status = target_status
    if status is None and target is not None:
        status = getattr(target, "status", None)
    if _has_status(status):
        return 130
    return 65


# ---------------------------------------------------------------------------
# Dynamic Priority Resolution
# ---------------------------------------------------------------------------


def resolve_dynamic_priority(
    move_id: Any,
    *,
    fields: Any = None,
    terrain: Any = None,
    user: Any = None,
    user_grounded: Optional[bool] = None,
) -> Optional[int]:
    """Resolve the dynamic priority modifier of a move.

    Parameters
    ----------
    move_id : str or Move
        Move identifier.
    fields : Dict[Field, int], optional
        Active battle fields.
    terrain : Field enum or str, optional
        Explicit terrain override.
    user : Pokemon, optional
        User pokemon (checked for grounded status).
    user_grounded : bool, optional
        Explicit override for whether the user is grounded.

    Returns
    -------
    int or None
        Priority modifier (e.g. ``1`` for +1), or ``None`` when no dynamic
        priority applies.
    """
    mid = _normalize_move_id(move_id)

    if mid == "grassyglide":
        return _grassyglide_priority(fields, terrain, user, user_grounded)
    return None


def _is_grounded(user: Any, user_grounded: Optional[bool] = None) -> bool:
    if user_grounded is not None:
        return user_grounded
    if user is not None:
        for t in (getattr(user, "type_1", None), getattr(user, "type_2", None)):
            if t is not None:
                tn = t.name if hasattr(t, "name") else str(t)
                if tn.upper() == "FLYING":
                    return False
        ability = getattr(user, "ability", None)
        if ability and str(ability).lower() == "levitate":
            return False
        item = getattr(user, "item", None)
        if item and str(item).lower() == "airballoon":
            return False
    return True


def _grassyglide_priority(
    fields: Any = None,
    terrain: Any = None,
    user: Any = None,
    user_grounded: Optional[bool] = None,
) -> int:
    if terrain is not None:
        terrain_name = _normalize_terrain(terrain)
    else:
        terrain_name = _normalize_terrain(fields)

    if terrain_name is None:
        terrain_name = ""
    else:
        terrain_name = str(terrain_name).upper()

    if terrain_name == "GRASSY_TERRAIN" and _is_grounded(user, user_grounded):
        return 1
    return 0


# ---------------------------------------------------------------------------
# Fixed Damage
# ---------------------------------------------------------------------------

# Alias matching the validation contract naming
resolve_fixed_damage = None  # reassigned after get_fixed_damage definition


def get_fixed_damage(
    move_id: Any,
    *,
    user: Any = None,
    target: Any = None,
    user_level: Optional[int] = None,
    user_current_hp: Optional[int] = None,
    target_current_hp: Optional[int] = None,
    last_physical_damage: Optional[int] = None,
    last_special_damage: Optional[int] = None,
) -> Optional[Union[int, str]]:
    """Calculate fixed damage for moves with damageCallback.

    Parameters
    ----------
    move_id : str or Move
        Move identifier.
    user, target : Pokemon, optional
        Pokemon objects for extracting level, HP, etc.
    user_level : int, optional
        Explicit override for user's level.
    user_current_hp : int, optional
        Explicit override for user's current HP.
    target_current_hp : int, optional
        Explicit override for target's current HP.
    last_physical_damage : int, optional
        Physical damage taken this turn (for Counter).
    last_special_damage : int, optional
        Special damage taken this turn (for Mirror Coat).

    Returns
    -------
    int, str, or None
        Exact damage amount, descriptive string, or ``None`` if the move
        is not a fixed-damage move.
    """
    mid = _normalize_move_id(move_id)

    if mid in ("seismictoss", "nightshade"):
        level = user_level
        if level is None and user is not None:
            level = getattr(user, "level", None)
        return level

    if mid == "counter":
        if last_physical_damage is not None:
            return last_physical_damage * 2
        return "2x physical damage taken"

    if mid == "mirrorcoat":
        if last_special_damage is not None:
            return last_special_damage * 2
        return "2x special damage taken"

    if mid == "finalgambit":
        hp = user_current_hp
        if hp is None and user is not None:
            hp = getattr(user, "current_hp", None)
        return hp

    if mid == "endeavor":
        u_hp = user_current_hp
        t_hp = target_current_hp
        if u_hp is None and user is not None:
            u_hp = getattr(user, "current_hp", None)
        if t_hp is None and target is not None:
            t_hp = getattr(target, "current_hp", None)
        if u_hp is not None and t_hp is not None:
            return max(t_hp - u_hp, 0)
        return "Sets target HP to user HP"

    return None


# Alias for backward compatibility with validation contract naming
resolve_fixed_damage = get_fixed_damage


# ---------------------------------------------------------------------------
# Dynamic Info Formatting
# ---------------------------------------------------------------------------


def format_dynamic_info(
    move_id: Any,
    *,
    weather: Any = None,
    user: Any = None,
    target: Any = None,
    fields: Any = None,
    terrain: Any = None,
    tera_type: Any = None,
    user_species: Any = None,
    user_form: Any = None,
    ivs: Optional[Dict[str, int]] = None,
    user_item: Any = None,
    user_status: Any = None,
    target_item: Any = None,
    target_status: Any = None,
    user_weightkg: Optional[float] = None,
    target_weightkg: Optional[float] = None,
    user_grounded: Optional[bool] = None,
    user_type_1: Any = None,
    user_level: Optional[int] = None,
    user_current_hp: Optional[int] = None,
    target_current_hp: Optional[int] = None,
    last_physical_damage: Optional[int] = None,
    last_special_damage: Optional[int] = None,
) -> str:
    """Format a concise summary of dynamic move information.

    Returns a string like ``'rain→Water/100BP'`` or ``'no item→110BP'``.
    Returns an empty string when no dynamic information applies.

    All keyword arguments are forwarded to the appropriate resolver
    functions internally.
    """
    mid = _normalize_move_id(move_id)
    parts = []

    # --- Type ---
    dtype = resolve_dynamic_type(
        mid,
        weather=weather,
        user=user,
        tera_type=tera_type,
        user_species=user_species,
        user_form=user_form,
        ivs=ivs,
        terrain=terrain,
        user_type_1=user_type_1,
        user_grounded=user_grounded,
        user_item=user_item,
    )
    if dtype is not None:
        if mid == "weatherball":
            w = _normalize_weather(weather)
            if w:
                wl = w.lower()
                if "sunny" in wl or "desolate" in wl:
                    label = "sun"
                elif "rain" in wl or "primordial" in wl:
                    label = "rain"
                elif "hail" in wl or "snow" in wl:
                    label = "hail"
                elif "sand" in wl:
                    label = "sand"
                else:
                    label = wl
                parts.append(f"{label}→{dtype}")
        elif mid == "terablast":
            parts.append(f"tera→{dtype}")
        elif mid == "aurawheel":
            parts.append(f"form→{dtype}")
        elif mid == "hiddenpower":
            parts.append(f"ivs→{dtype}")
        elif mid == "ivycudgel":
            parts.append(f"form→{dtype}")
        elif mid == "ragingbull":
            parts.append(f"form→{dtype}")
        elif mid == "terastarstorm":
            parts.append(f"tera→{dtype}")
        elif mid == "revelationdance":
            parts.append(f"type1→{dtype}")
        elif mid == "terrainpulse":
            parts.append(f"terrain→{dtype}")
        elif mid == "judgment":
            parts.append(f"plate→{dtype}")
        elif mid == "multiattack":
            parts.append(f"memory→{dtype}")
        elif mid == "technoblast":
            parts.append(f"drive→{dtype}")
        elif mid == "naturalgift":
            parts.append(f"berry→{dtype}")
        else:
            parts.append(dtype)

    # --- Power ---
    dpower = resolve_dynamic_power(
        mid,
        weather=weather,
        user=user,
        target=target,
        user_item=user_item,
        user_status=user_status,
        target_item=target_item,
        target_status=target_status,
        user_weightkg=user_weightkg,
        target_weightkg=target_weightkg,
    )
    if dpower is not None:
        if mid == "acrobatics":
            item = _get_item(user, user_item)
            if item in _NO_ITEM_SENTINELS or (
                isinstance(item, str) and item.strip().lower() == ""
            ):
                parts.append(f"no item→{int(dpower)}BP")
            else:
                parts.append(f"{int(dpower)}BP")
        elif mid == "facade":
            status = user_status
            if status is None and user is not None:
                status = getattr(user, "status", None)
            if _has_status(status):
                parts.append(f"status→{int(dpower)}BP")
            else:
                parts.append(f"{int(dpower)}BP")
        elif mid == "knockoff":
            item = _get_item(target, target_item)
            if _item_is_removable(item):
                parts.append(f"item→{dpower}BP")
            else:
                parts.append(f"{int(dpower)}BP")
        elif mid == "hex":
            status = target_status
            if status is None and target is not None:
                status = getattr(target, "status", None)
            if _has_status(status):
                parts.append(f"status→{int(dpower)}BP")
            else:
                parts.append(f"{int(dpower)}BP")
        else:
            parts.append(f"{int(dpower)}BP")

    # --- Priority ---
    dpri = resolve_dynamic_priority(
        mid,
        fields=fields,
        terrain=terrain,
        user=user,
        user_grounded=user_grounded,
    )
    if dpri is not None and dpri != 0:
        parts.append(f"pri+{dpri}")

    # --- Fixed damage ---
    fdmg = get_fixed_damage(
        mid,
        user=user,
        target=target,
        user_level=user_level,
        user_current_hp=user_current_hp,
        target_current_hp=target_current_hp,
        last_physical_damage=last_physical_damage,
        last_special_damage=last_special_damage,
    )
    if fdmg is not None:
        if isinstance(fdmg, int):
            parts.append(f"fixed:{fdmg}")
        else:
            parts.append(str(fdmg))

    return "/".join(parts) if parts else ""
