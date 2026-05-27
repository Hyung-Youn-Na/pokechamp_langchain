"""
Tests for dynamic move flags, flag text display, and dynamic move calculations.

Covers:
- 7 new keys added to _MISC_FLAGS in poke_env/environment/move.py
- Existing 19 keys preserved
- Flag detection in Move.flags property
- Flag text display in prompts when enable_dynamic_flags=True
- No flag text when enable_dynamic_flags=False
- Flag text conciseness (≤ 30 chars)
- Dynamic type resolution (weatherball, terablast, aurawheel, hiddenpower)
- Dynamic power resolution (acrobatics, facade, knockoff, weatherball, low_kick,
  heavy_slam, hex)
- Dynamic priority resolution (grassyglide)
- Fixed damage calculation (seismictoss, nightshade, counter, mirrorcoat,
  finalgambit, endeavor)
- Dynamic info formatting
- Module purity and importability
"""

import pytest

from poke_env.environment.move import Move
from poke_env.environment.weather import Weather
from poke_env.environment.field import Field
from poke_env.environment.status import Status
from pokechamp.dynamic_move import (
    resolve_dynamic_type,
    resolve_dynamic_power,
    resolve_dynamic_priority,
    get_fixed_damage,
    resolve_fixed_damage,
    format_dynamic_info,
)

# ---------------------------------------------------------------------------
# Area 1: _MISC_FLAGS additions
# ---------------------------------------------------------------------------


@pytest.mark.moves
class TestMiscFlags:
    """Verify the 7 new keys are present in _MISC_FLAGS."""

    def test_onmodifytype_in_misc_flags(self):
        assert "onModifyType" in Move._MISC_FLAGS

    def test_ontryimmunity_in_misc_flags(self):
        assert "onTryImmunity" in Move._MISC_FLAGS

    def test_onmodifytarget_in_misc_flags(self):
        assert "onModifyTarget" in Move._MISC_FLAGS

    def test_onmodifypriority_in_misc_flags(self):
        assert "onModifyPriority" in Move._MISC_FLAGS

    def test_willcrit_in_misc_flags(self):
        assert "willCrit" in Move._MISC_FLAGS

    def test_hascrashdamage_in_misc_flags(self):
        assert "hasCrashDamage" in Move._MISC_FLAGS

    def test_mindblownrecoil_in_misc_flags(self):
        assert "mindBlownRecoil" in Move._MISC_FLAGS


@pytest.mark.moves
class TestMiscFlagsPreserved:
    """Verify the original 19 keys are still present."""

    ORIGINAL_FLAGS = [
        "onModifyMove",
        "onEffectiveness",
        "onHitField",
        "onAfterMoveSecondarySelf",
        "onHit",
        "onTry",
        "beforeTurnCallback",
        "onAfterMove",
        "onTryHit",
        "onTryMove",
        "hasCustomRecoil",
        "onMoveFail",
        "onPrepareHit",
        "onAfterHit",
        "onBasePower",
        "basePowerCallback",
        "damageCallback",
        "onTryHitSide",
        "beforeMoveCallback",
    ]

    @pytest.mark.parametrize("flag", ORIGINAL_FLAGS)
    def test_original_flag_preserved(self, flag):
        assert flag in Move._MISC_FLAGS

    def test_total_flags_count(self):
        # 19 original + 7 new = 26
        assert len(Move._MISC_FLAGS) >= 26


# ---------------------------------------------------------------------------
# Area 2: Flag detection via Move.flags property
# ---------------------------------------------------------------------------


@pytest.mark.moves
class TestFlagDetection:
    """Verify specific moves report expected flags."""

    def test_weatherball_onmodifytype(self):
        m = Move("weatherball", gen=9)
        assert "onModifyType" in m.flags

    def test_terablast_onmodifytype(self):
        m = Move("terablast", gen=9)
        assert "onModifyType" in m.flags

    def test_flowertrick_willcrit(self):
        m = Move("flowertrick", gen=9)
        assert "willCrit" in m.flags

    def test_frostbreath_willcrit(self):
        m = Move("frostbreath", gen=9)
        assert "willCrit" in m.flags

    def test_stormthrow_willcrit(self):
        m = Move("stormthrow", gen=9)
        assert "willCrit" in m.flags

    def test_wickedblow_willcrit(self):
        m = Move("wickedblow", gen=9)
        assert "willCrit" in m.flags

    def test_highjumpkick_hascrashdamage(self):
        m = Move("highjumpkick", gen=9)
        assert "hasCrashDamage" in m.flags

    def test_jumpkick_hascrashdamage(self):
        m = Move("jumpkick", gen=9)
        assert "hasCrashDamage" in m.flags

    def test_axekick_hascrashdamage(self):
        m = Move("axekick", gen=9)
        assert "hasCrashDamage" in m.flags

    def test_mindblown_mindblownrecoil(self):
        m = Move("mindblown", gen=9)
        assert "mindBlownRecoil" in m.flags

    def test_steelbeam_mindblownrecoil(self):
        m = Move("steelbeam", gen=9)
        assert "mindBlownRecoil" in m.flags

    def test_dreameater_ontryimmunity(self):
        m = Move("dreameater", gen=9)
        assert "onTryImmunity" in m.flags

    def test_comeuppance_onmodifytarget(self):
        m = Move("comeuppance", gen=9)
        assert "onModifyTarget" in m.flags

    def test_grassyglide_onmodifypriority(self):
        m = Move("grassyglide", gen=9)
        assert "onModifyPriority" in m.flags


# ---------------------------------------------------------------------------
# Area 3: Flag text in prompts
# ---------------------------------------------------------------------------


# Mapping used for flag display text
FLAG_DISPLAY_TEXT = {
    "onModifyType": "[dynamic type]",
    "willCrit": "[always crits]",
    "hasCrashDamage": "[crash damage on miss]",
    "mindBlownRecoil": "[costs 50% HP]",
    "onTryImmunity": "[conditional use]",
    "onModifyTarget": "[retargeted]",
    "onModifyPriority": "[dynamic priority]",
}


@pytest.mark.moves
class TestFlagDisplayText:
    """Verify flag display text is concise (≤ 30 chars)."""

    @pytest.mark.parametrize(
        "flag_key,expected_text",
        list(FLAG_DISPLAY_TEXT.items()),
        ids=list(FLAG_DISPLAY_TEXT.keys()),
    )
    def test_flag_text_concise(self, flag_key, expected_text):
        assert len(expected_text) <= 30

    def test_all_new_flags_have_display_text(self):
        new_flags = [
            "onModifyType",
            "onTryImmunity",
            "onModifyTarget",
            "onModifyPriority",
            "willCrit",
            "hasCrashDamage",
            "mindBlownRecoil",
        ]
        for flag in new_flags:
            assert flag in FLAG_DISPLAY_TEXT


@pytest.mark.moves
class TestGetFlagAnnotations:
    """Test the get_flag_annotations helper function in prompts.py."""

    def test_import(self):
        from pokechamp.prompts import get_flag_annotations

    def test_weatherball_has_dynamic_type(self):
        from pokechamp.prompts import get_flag_annotations

        m = Move("weatherball", gen=9)
        annotations = get_flag_annotations(m)
        assert any("[dynamic type]" in a for a in annotations)

    def test_flowertrick_has_always_crits(self):
        from pokechamp.prompts import get_flag_annotations

        m = Move("flowertrick", gen=9)
        annotations = get_flag_annotations(m)
        assert any("[always crits]" in a for a in annotations)

    def test_highjumpkick_has_crash_damage(self):
        from pokechamp.prompts import get_flag_annotations

        m = Move("highjumpkick", gen=9)
        annotations = get_flag_annotations(m)
        assert any("[crash damage on miss]" in a for a in annotations)

    def test_mindblown_has_recoil(self):
        from pokechamp.prompts import get_flag_annotations

        m = Move("mindblown", gen=9)
        annotations = get_flag_annotations(m)
        assert any("[costs 50% HP]" in a for a in annotations)

    def test_dreameater_has_conditional_use(self):
        from pokechamp.prompts import get_flag_annotations

        m = Move("dreameater", gen=9)
        annotations = get_flag_annotations(m)
        assert any("[conditional use]" in a for a in annotations)

    def test_comeuppance_has_retargeted(self):
        from pokechamp.prompts import get_flag_annotations

        m = Move("comeuppance", gen=9)
        annotations = get_flag_annotations(m)
        assert any("[retargeted]" in a for a in annotations)

    def test_grassyglide_has_dynamic_priority(self):
        from pokechamp.prompts import get_flag_annotations

        m = Move("grassyglide", gen=9)
        annotations = get_flag_annotations(m)
        assert any("[dynamic priority]" in a for a in annotations)

    def test_flamethrower_no_annotations(self):
        from pokechamp.prompts import get_flag_annotations

        m = Move("flamethrower", gen=9)
        annotations = get_flag_annotations(m)
        # flamethrower has no dynamic flags
        dynamic_flag_keys = set(FLAG_DISPLAY_TEXT.keys())
        for a in annotations:
            assert not any(f"[{k}]" in a for k in dynamic_flag_keys)

    def test_format_flag_text_produces_string(self):
        from pokechamp.prompts import format_flag_text

        m = Move("weatherball", gen=9)
        result = format_flag_text(m)
        assert isinstance(result, str)
        assert "[dynamic type]" in result

    def test_format_flag_text_empty_for_no_flags(self):
        from pokechamp.prompts import format_flag_text

        m = Move("tackle", gen=9)
        result = format_flag_text(m)
        # tackle shouldn't have any of our 7 dynamic flags
        assert result == ""


@pytest.mark.moves
class TestBackwardCompatibility:
    """Verify that enable_dynamic_flags=False produces no flag annotations."""

    def test_flag_text_helper_still_works_independently(self):
        """The helper function works regardless of flags, but integration
        only appends when enable_dynamic_flags=True."""
        from pokechamp.prompts import get_flag_annotations

        m = Move("weatherball", gen=9)
        annotations = get_flag_annotations(m)
        # Helper always returns annotations — the integration code checks
        # enable_dynamic_flags before appending
        assert len(annotations) > 0


# ===========================================================================
# Area 4: Dynamic Type Resolution  (VAL-DTYPE-*)
# ===========================================================================


@pytest.mark.moves
class TestResolveDynamicTypeWeatherball:
    """Weather Ball type resolution for all weather conditions."""

    def test_weatherball_rain_water_type(self):
        """VAL-DTYPE-002: Rain → Water."""
        assert resolve_dynamic_type("weatherball", weather=Weather.RAINDANCE) == "Water"

    def test_weatherball_primordial_sea_water(self):
        assert (
            resolve_dynamic_type("weatherball", weather=Weather.PRIMORDIALSEA)
            == "Water"
        )

    def test_weatherball_sun_fire_type(self):
        """VAL-DTYPE-001: Sun → Fire."""
        assert resolve_dynamic_type("weatherball", weather=Weather.SUNNYDAY) == "Fire"

    def test_weatherball_desolate_land_fire(self):
        assert (
            resolve_dynamic_type("weatherball", weather=Weather.DESOLATELAND) == "Fire"
        )

    def test_weatherball_sand_rock_type(self):
        """VAL-DTYPE-003: Sand → Rock."""
        assert resolve_dynamic_type("weatherball", weather=Weather.SANDSTORM) == "Rock"

    def test_weatherball_hail_ice_type(self):
        """VAL-DTYPE-004: Hail → Ice."""
        assert resolve_dynamic_type("weatherball", weather=Weather.HAIL) == "Ice"

    def test_weatherball_snow_ice(self):
        assert resolve_dynamic_type("weatherball", weather=Weather.SNOW) == "Ice"

    def test_weatherball_no_weather_normal(self):
        """VAL-DTYPE-005: No weather → Normal."""
        assert resolve_dynamic_type("weatherball", weather=None) == "Normal"

    def test_weatherball_empty_dict_normal(self):
        assert resolve_dynamic_type("weatherball", weather={}) == "Normal"

    def test_weatherball_with_weather_dict(self):
        """Works with Dict[Weather, int] as returned by battle.weather."""
        assert (
            resolve_dynamic_type("weatherball", weather={Weather.RAINDANCE: 1})
            == "Water"
        )


@pytest.mark.moves
class TestResolveDynamicTypeTerablast:
    """Tera Blast type resolution."""

    def test_terablast_tera_type_fire(self):
        """VAL-DTYPE-006: Tera type Fire → Fire when terastallized."""
        assert resolve_dynamic_type("terablast", tera_type="Fire") == "Fire"

    def test_terablast_no_tera_normal(self):
        """VAL-DTYPE-007: Not terastallized → Normal."""
        assert resolve_dynamic_type("terablast", tera_type=None) == "Normal"

    def test_terablast_stellar_type(self):
        """VAL-DTYPE-008: Stellar tera type edge case."""
        result = resolve_dynamic_type("terablast", tera_type="Stellar")
        assert result in ("Stellar", "Normal")

    def test_terablast_with_pokemon_type_enum(self):
        from poke_env.environment.pokemon_type import PokemonType

        assert resolve_dynamic_type("terablast", tera_type=PokemonType.WATER) == "WATER"


@pytest.mark.moves
class TestResolveDynamicTypeAurawheel:
    """Aura Wheel type resolution based on Morpeko form."""

    def test_aurawheel_full_belly_electric(self):
        """VAL-DTYPE-009: Full Belly → Electric."""
        assert (
            resolve_dynamic_type(
                "aurawheel", user_species="morpeko", user_form="fullbelly"
            )
            == "Electric"
        )

    def test_aurawheel_hangry_dark(self):
        """VAL-DTYPE-010: Hangry → Dark."""
        assert (
            resolve_dynamic_type(
                "aurawheel", user_species="morpeko", user_form="hangry"
            )
            == "Dark"
        )

    def test_aurawheel_non_morpeko_none(self):
        """VAL-DTYPE-011: Non-Morpeko returns None gracefully."""
        result = resolve_dynamic_type("aurawheel", user_species="pikachu")
        assert result is None

    def test_aurawheel_no_species_none(self):
        assert resolve_dynamic_type("aurawheel") is None

    def test_aurawheel_default_form_electric(self):
        """Morpeko without explicit form defaults to Electric (Full Belly)."""
        assert resolve_dynamic_type("aurawheel", user_species="morpeko") == "Electric"


@pytest.mark.moves
class TestResolveDynamicTypeHiddenPower:
    """Hidden Power type from IVs."""

    def test_hiddenpower_all_31(self):
        """All 31 IVs → type index 15 → Dark."""
        assert (
            resolve_dynamic_type(
                "hiddenpower",
                ivs={"hp": 31, "atk": 31, "def": 31, "spa": 31, "spd": 31, "spe": 31},
            )
            == "DARK"
        )

    def test_hiddenpower_all_0(self):
        """All 0 IVs → type index 0 → Fighting."""
        assert (
            resolve_dynamic_type(
                "hiddenpower",
                ivs={"hp": 0, "atk": 0, "def": 0, "spa": 0, "spd": 0, "spe": 0},
            )
            == "FIGHTING"
        )

    def test_hiddenpower_partial_ivs(self):
        """Partial IVs dict uses 31 as default for missing keys."""
        result = resolve_dynamic_type(
            "hiddenpower", ivs={"atk": 0, "def": 0, "spa": 0, "spd": 0, "spe": 0}
        )
        assert isinstance(result, str)
        assert result in {
            t
            for t in (
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
            )
        }

    def test_hiddenpower_no_ivs_no_user(self):
        """Without IVs or user, returns None."""
        assert resolve_dynamic_type("hiddenpower") is None


@pytest.mark.moves
class TestResolveDynamicTypeUnknown:
    """Unknown move returns None."""

    def test_unknown_move_none(self):
        """VAL-DTYPE-013: Unknown move → None."""
        assert resolve_dynamic_type("nonexistentmove") is None

    def test_regular_move_none(self):
        """Static moves like flamethrower return None."""
        assert resolve_dynamic_type("flamethrower") is None


# ===========================================================================
# Area 5: Dynamic Power Resolution  (VAL-DPOWER-*)
# ===========================================================================


@pytest.mark.moves
class TestResolveDynamicPowerAcrobatics:
    def test_acrobatics_no_item_double_power(self):
        """VAL-DPOWER-001: No item → 110."""
        assert resolve_dynamic_power("acrobatics", user_item=None) == 110

    def test_acrobatics_has_item_base_power(self):
        """VAL-DPOWER-002: Has item → 55."""
        assert resolve_dynamic_power("acrobatics", user_item="leftovers") == 55

    def test_acrobatics_empty_string_item(self):
        assert resolve_dynamic_power("acrobatics", user_item="") == 110


@pytest.mark.moves
class TestResolveDynamicPowerFacade:
    def test_facade_status_brn_double_power(self):
        """VAL-DPOWER-003: Status → 140."""
        assert resolve_dynamic_power("facade", user_status="brn") == 140

    def test_facade_status_psn(self):
        assert resolve_dynamic_power("facade", user_status="psn") == 140

    def test_facade_status_par(self):
        assert resolve_dynamic_power("facade", user_status="par") == 140

    def test_facade_status_tox(self):
        assert resolve_dynamic_power("facade", user_status="tox") == 140

    def test_facade_status_enum(self):
        """Works with Status enum."""
        assert resolve_dynamic_power("facade", user_status=Status.BRN) == 140

    def test_facade_no_status_base_power(self):
        """VAL-DPOWER-004: No status → 70."""
        assert resolve_dynamic_power("facade", user_status=None) == 70


@pytest.mark.moves
class TestResolveDynamicPowerKnockoff:
    def test_knockoff_target_has_item_boosted(self):
        """VAL-DPOWER-005: Target has removable item → 97.5."""
        assert resolve_dynamic_power("knockoff", target_item="choicescarf") == 97.5

    def test_knockoff_target_no_item_base(self):
        """VAL-DPOWER-006: Target has no item → 65."""
        assert resolve_dynamic_power("knockoff", target_item=None) == 65

    def test_knockoff_z_crystal_not_removable(self):
        """Z-crystals cannot be knocked off."""
        assert resolve_dynamic_power("knockoff", target_item="decidiumz") == 65


@pytest.mark.moves
class TestResolveDynamicPowerWeatherball:
    def test_weatherball_power_100_in_weather(self):
        """VAL-DPOWER-007: Weather active → 100."""
        assert resolve_dynamic_power("weatherball", weather=Weather.SUNNYDAY) == 100

    def test_weatherball_power_50_no_weather(self):
        """VAL-DPOWER-008: No weather → 50."""
        assert resolve_dynamic_power("weatherball", weather=None) == 50

    def test_weatherball_power_rain(self):
        assert resolve_dynamic_power("weatherball", weather=Weather.RAINDANCE) == 100


@pytest.mark.moves
class TestResolveDynamicPowerLowKick:
    def test_low_kick_light_target(self):
        """VAL-DPOWER-009: Light target (< 10kg) → 20."""
        assert resolve_dynamic_power("lowkick", target_weightkg=5.0) == 20

    def test_low_kick_heavy_target(self):
        """VAL-DPOWER-010: Heavy target (> 200kg) → 120."""
        assert resolve_dynamic_power("lowkick", target_weightkg=420.0) == 120

    def test_low_kick_medium_100kg(self):
        assert resolve_dynamic_power("lowkick", target_weightkg=150.0) == 100

    def test_low_kick_medium_50kg(self):
        assert resolve_dynamic_power("lowkick", target_weightkg=75.0) == 80

    def test_low_kick_medium_25kg(self):
        assert resolve_dynamic_power("lowkick", target_weightkg=30.0) == 60

    def test_low_kick_medium_10kg(self):
        assert resolve_dynamic_power("lowkick", target_weightkg=15.0) == 40

    def test_grassknot_same_as_lowkick(self):
        """Grass Knot uses the same weight tiers as Low Kick."""
        assert resolve_dynamic_power("grassknot", target_weightkg=420.0) == 120


@pytest.mark.moves
class TestResolveDynamicPowerHeavySlam:
    def test_heavy_slam_heavy_user_light_target(self):
        """VAL-DPOWER-011: Very heavy user, light target → 120."""
        assert (
            resolve_dynamic_power("heavyslam", user_weightkg=400.0, target_weightkg=5.0)
            == 120
        )

    def test_heavy_slam_similar_weights(self):
        """VAL-DPOWER-012: Similar weights → 40."""
        assert (
            resolve_dynamic_power("heavyslam", user_weightkg=50.0, target_weightkg=45.0)
            == 40
        )

    def test_heavy_slam_medium_ratio(self):
        # 20kg / 100kg = 0.2 < 0.25 → 100
        assert (
            resolve_dynamic_power(
                "heavyslam", user_weightkg=100.0, target_weightkg=20.0
            )
            == 100
        )

    def test_heat_crash_same_as_heavy_slam(self):
        """Heat Crash uses same weight ratio tiers."""
        assert (
            resolve_dynamic_power("heatcrash", user_weightkg=400.0, target_weightkg=5.0)
            == 120
        )


@pytest.mark.moves
class TestResolveDynamicPowerHex:
    def test_hex_target_has_status(self):
        """VAL-DPOWER-013: Target has status → 130."""
        assert resolve_dynamic_power("hex", target_status="psn") == 130

    def test_hex_target_status_enum(self):
        assert resolve_dynamic_power("hex", target_status=Status.TOX) == 130

    def test_hex_target_no_status(self):
        """VAL-DPOWER-014: Target no status → 65."""
        assert resolve_dynamic_power("hex", target_status=None) == 65


@pytest.mark.moves
class TestResolveDynamicPowerUnknown:
    def test_unknown_move_none(self):
        """VAL-DPOWER-015: Unknown move → None."""
        assert resolve_dynamic_power("nonexistentmove") is None

    def test_regular_move_none(self):
        assert resolve_dynamic_power("flamethrower") is None


# ===========================================================================
# Area 6: Dynamic Priority Resolution  (VAL-DPRI-*)
# ===========================================================================


@pytest.mark.moves
class TestResolveDynamicPriorityGrassyGlide:
    def test_grassyglide_grassy_terrain_grounded(self):
        """VAL-DPRI-001: Grassy Terrain + grounded → +1."""
        assert (
            resolve_dynamic_priority(
                "grassyglide", terrain="grassyterrain", user_grounded=True
            )
            == 1
        )

    def test_grassyglide_grassy_terrain_field_enum(self):
        """Works with Field enum."""
        assert (
            resolve_dynamic_priority(
                "grassyglide",
                fields={Field.GRASSY_TERRAIN: 1},
                user_grounded=True,
            )
            == 1
        )

    def test_grassyglide_no_terrain(self):
        """VAL-DPRI-002: No terrain → 0."""
        assert (
            resolve_dynamic_priority("grassyglide", terrain=None, user_grounded=True)
            == 0
        )

    def test_grassyglide_non_grounded(self):
        """VAL-DPRI-003: Grassy Terrain but not grounded → 0."""
        assert (
            resolve_dynamic_priority(
                "grassyglide", terrain="grassyterrain", user_grounded=False
            )
            == 0
        )

    def test_grassyglide_wrong_terrain(self):
        assert (
            resolve_dynamic_priority(
                "grassyglide", terrain="electricterrain", user_grounded=True
            )
            == 0
        )


@pytest.mark.moves
class TestResolveDynamicPriorityUnknown:
    def test_unknown_move_none(self):
        """VAL-DPRI-004: Unknown move → None."""
        assert resolve_dynamic_priority("nonexistentmove") is None

    def test_regular_move_none(self):
        assert resolve_dynamic_priority("tackle") is None


# ===========================================================================
# Area 7: Fixed Damage  (VAL-FIXDMG-*)
# ===========================================================================


@pytest.mark.moves
class TestGetFixedDamageSeismicToss:
    def test_seismictoss_user_level(self):
        """VAL-FIXDMG-001: Fixed damage = user level."""
        assert get_fixed_damage("seismictoss", user_level=50) == 50

    def test_seismictoss_level_100(self):
        assert get_fixed_damage("seismictoss", user_level=100) == 100

    def test_nightshade_same_as_seismictoss(self):
        """Night Shade also deals damage equal to user level."""
        assert get_fixed_damage("nightshade", user_level=75) == 75


@pytest.mark.moves
class TestGetFixedDamageCounter:
    def test_counter_2x_physical(self):
        """VAL-FIXDMG-002: 2x physical damage taken."""
        assert get_fixed_damage("counter", last_physical_damage=40) == 80

    def test_counter_no_damage_descriptive(self):
        """Without damage info, returns descriptive string."""
        result = get_fixed_damage("counter")
        assert isinstance(result, str)
        assert "2x" in result.lower() or "physical" in result.lower()


@pytest.mark.moves
class TestGetFixedDamageMirrorCoat:
    def test_mirrorcoat_2x_special(self):
        assert get_fixed_damage("mirrorcoat", last_special_damage=50) == 100

    def test_mirrorcoat_no_damage_descriptive(self):
        result = get_fixed_damage("mirrorcoat")
        assert isinstance(result, str)


@pytest.mark.moves
class TestGetFixedDamageFinalGambit:
    def test_finalgambit_current_hp(self):
        """VAL-FIXDMG-003: Fixed damage = current HP."""
        assert get_fixed_damage("finalgambit", user_current_hp=120) == 120

    def test_finalgambit_low_hp(self):
        assert get_fixed_damage("finalgambit", user_current_hp=1) == 1


@pytest.mark.moves
class TestGetFixedDamageEndeavor:
    def test_endeavor_reduces_to_user_hp(self):
        """VAL-FIXDMG-004: Target HP - user HP."""
        assert (
            get_fixed_damage("endeavor", user_current_hp=10, target_current_hp=100)
            == 90
        )

    def test_endeavor_user_higher_hp(self):
        """If user HP is higher, damage is 0."""
        assert (
            get_fixed_damage("endeavor", user_current_hp=100, target_current_hp=50) == 0
        )

    def test_endeavor_no_hp_descriptive(self):
        """Without HP info, returns descriptive string."""
        result = get_fixed_damage("endeavor")
        assert isinstance(result, str)
        assert "target" in result.lower() or "hp" in result.lower()


@pytest.mark.moves
class TestGetFixedDamageCallbackFlag:
    def test_damagecallback_flag_counter(self):
        """VAL-FIXDMG-005: damageCallback in Move.flags for counter."""
        m = Move("counter", gen=9)
        assert "damageCallback" in m.flags

    def test_damagecallback_flag_finalgambit(self):
        m = Move("finalgambit", gen=9)
        assert "damageCallback" in m.flags

    def test_damagecallback_flag_endeavor(self):
        m = Move("endeavor", gen=9)
        assert "damageCallback" in m.flags

    def test_damagecallback_flag_mirrorcoat(self):
        m = Move("mirrorcoat", gen=9)
        assert "damageCallback" in m.flags

    def test_seismictoss_has_damage_key(self):
        """Seismic toss uses 'damage' key rather than 'damageCallback'."""
        m = Move("seismictoss", gen=9)
        assert m.entry.get("damage") is not None


@pytest.mark.moves
class TestGetFixedDamageUnknown:
    def test_unknown_move_none(self):
        assert get_fixed_damage("tackle") is None

    def test_regular_attack_none(self):
        assert get_fixed_damage("flamethrower") is None


@pytest.mark.moves
class TestResolveFixedDamageAlias:
    """Verify resolve_fixed_damage is an alias for get_fixed_damage."""

    def test_alias_exists(self):
        assert resolve_fixed_damage is get_fixed_damage

    def test_alias_works(self):
        assert resolve_fixed_damage("seismictoss", user_level=50) == 50


# ===========================================================================
# Area 8: format_dynamic_info  (VAL-MOD-*)
# ===========================================================================


@pytest.mark.moves
class TestFormatDynamicInfo:
    def test_weatherball_rain(self):
        """Weatherball in rain → 'rain→Water/100BP'."""
        result = format_dynamic_info("weatherball", weather=Weather.RAINDANCE)
        assert "Water" in result
        assert "100" in result

    def test_weatherball_no_weather(self):
        result = format_dynamic_info("weatherball", weather=None)
        # No dynamic change → either empty or shows Normal/50BP
        # With no weather, type=Normal (same as base) and power=50 (same as base)
        # format_dynamic_info may or may not show info for "no change" cases
        assert isinstance(result, str)

    def test_acrobatics_no_item(self):
        result = format_dynamic_info("acrobatics", user_item=None)
        assert "110" in result
        assert "no item" in result.lower() or "110" in result

    def test_facade_status(self):
        result = format_dynamic_info("facade", user_status="brn")
        assert "140" in result

    def test_knockoff_target_item(self):
        result = format_dynamic_info("knockoff", target_item="choicescarf")
        assert "97.5" in result

    def test_grassyglide_grassy_terrain(self):
        result = format_dynamic_info(
            "grassyglide",
            terrain="grassyterrain",
            user_grounded=True,
        )
        assert "pri+1" in result

    def test_seismictoss_fixed_damage(self):
        result = format_dynamic_info("seismictoss", user_level=50)
        assert "50" in result

    def test_empty_for_regular_move(self):
        result = format_dynamic_info("tackle")
        assert result == ""

    def test_empty_for_unknown_move(self):
        result = format_dynamic_info("nonexistentmove")
        assert result == ""


# ===========================================================================
# Area 9: Module Purity and Importability  (VAL-MOD-*)
# ===========================================================================


@pytest.mark.moves
class TestModulePurity:
    """Verify the module is standalone and all functions are importable."""

    def test_import_resolve_dynamic_type(self):
        """VAL-MOD-003: Individual import works."""
        from pokechamp.dynamic_move import resolve_dynamic_type

        assert callable(resolve_dynamic_type)

    def test_import_resolve_dynamic_power(self):
        from pokechamp.dynamic_move import resolve_dynamic_power

        assert callable(resolve_dynamic_power)

    def test_import_resolve_dynamic_priority(self):
        from pokechamp.dynamic_move import resolve_dynamic_priority

        assert callable(resolve_dynamic_priority)

    def test_import_get_fixed_damage(self):
        from pokechamp.dynamic_move import get_fixed_damage

        assert callable(get_fixed_damage)

    def test_import_format_dynamic_info(self):
        from pokechamp.dynamic_move import format_dynamic_info

        assert callable(format_dynamic_info)

    def test_no_llmplayer_import(self):
        """VAL-MOD-004: No dependency on LLMPlayer."""
        import pokechamp.dynamic_move as dm

        source = open(dm.__file__).read()
        assert "llm_player" not in source
        assert "LLMPlayer" not in source

    def test_functions_are_pure(self):
        """VAL-MOD-002: Functions take explicit args, no self/class state."""
        # Call multiple times with same args → same result (no state mutation)
        r1 = resolve_dynamic_type("weatherball", weather=Weather.RAINDANCE)
        r2 = resolve_dynamic_type("weatherball", weather=Weather.RAINDANCE)
        assert r1 == r2 == "Water"

        p1 = resolve_dynamic_power("acrobatics", user_item=None)
        p2 = resolve_dynamic_power("acrobatics", user_item=None)
        assert p1 == p2 == 110

    def test_module_exists(self):
        """VAL-MOD-001: dynamic_move.py is importable."""
        import pokechamp.dynamic_move

        assert hasattr(pokechamp.dynamic_move, "resolve_dynamic_type")
        assert hasattr(pokechamp.dynamic_move, "resolve_dynamic_power")
        assert hasattr(pokechamp.dynamic_move, "resolve_dynamic_priority")
        assert hasattr(pokechamp.dynamic_move, "get_fixed_damage")
        assert hasattr(pokechamp.dynamic_move, "format_dynamic_info")


# ===========================================================================
# Area 10: Cross-Area / Edge Cases  (VAL-CROSS-*)
# ===========================================================================


@pytest.mark.moves
class TestEdgeCases:
    """Edge cases for dynamic move calculations."""

    def test_acrobatics_item_removed_mid_battle(self):
        """VAL-CROSS-009: Item removed → power updates."""
        assert resolve_dynamic_power("acrobatics", user_item="leftovers") == 55
        assert resolve_dynamic_power("acrobatics", user_item=None) == 110

    def test_facade_status_inflicted_mid_battle(self):
        """VAL-CROSS-010: Status inflicted → power updates."""
        assert resolve_dynamic_power("facade", user_status=None) == 70
        assert resolve_dynamic_power("facade", user_status="brn") == 140

    def test_weatherball_type_changes_with_weather(self):
        """VAL-CROSS-007: Weather changes → type updates."""
        assert resolve_dynamic_type("weatherball", weather=Weather.SUNNYDAY) == "Fire"
        assert resolve_dynamic_type("weatherball", weather=Weather.RAINDANCE) == "Water"
        assert resolve_dynamic_type("weatherball", weather=None) == "Normal"

    def test_terablast_before_and_after_tera(self):
        """VAL-CROSS-008: Terastallization state changes."""
        assert resolve_dynamic_type("terablast", tera_type=None) == "Normal"
        assert resolve_dynamic_type("terablast", tera_type="Fire") == "Fire"

    def test_move_object_as_input(self):
        """Functions accept Move objects as move_id."""
        m = Move("weatherball", gen=9)
        assert resolve_dynamic_type(m, weather=Weather.RAINDANCE) == "Water"

    def test_move_object_for_power(self):
        m = Move("acrobatics", gen=9)
        assert resolve_dynamic_power(m, user_item=None) == 110

    def test_hex_frozen_status(self):
        """FRZ also counts as a status for Hex."""
        assert resolve_dynamic_power("hex", target_status="frz") == 130

    def test_hex_sleep_status(self):
        assert resolve_dynamic_power("hex", target_status="slp") == 130

    def test_facade_frozen_status(self):
        assert resolve_dynamic_power("facade", user_status="frz") == 140

    def test_heavy_slam_exact_threshold(self):
        """Test edge of threshold: ratio == 0.5 → 60, not 40."""
        assert (
            resolve_dynamic_power(
                "heavyslam", user_weightkg=100.0, target_weightkg=49.9
            )
            == 60
        )
        assert (
            resolve_dynamic_power(
                "heavyslam", user_weightkg=100.0, target_weightkg=50.0
            )
            == 40
        )

    def test_low_kick_exact_threshold(self):
        """Test weight threshold boundaries."""
        # Exactly at boundary: >10.0 is False → falls through to 20
        assert resolve_dynamic_power("lowkick", target_weightkg=10.0) == 20
        # Just above: >10.0 is True, not >25.0 → 40
        assert resolve_dynamic_power("lowkick", target_weightkg=10.1) == 40
        assert resolve_dynamic_power("lowkick", target_weightkg=25.0) == 40
        assert resolve_dynamic_power("lowkick", target_weightkg=25.1) == 60


# ===========================================================================
# Area 11: Prompt Integration Tests (VAL-PROMPT-*, VAL-CROSS-*)
# ===========================================================================


@pytest.mark.moves
class TestApplyDynamicCalcsHelper:
    """Test the _apply_dynamic_calcs_to_move helper function in prompts.py."""

    def test_import(self):
        from pokechamp.prompts import _apply_dynamic_calcs_to_move

    def test_flags_disabled_returns_none(self):
        """When both flags are False, returns (None, None, "")."""
        from unittest.mock import MagicMock

        from pokechamp.prompts import _apply_dynamic_calcs_to_move

        sim = MagicMock()
        sim.enable_dynamic_calcs = False
        sim.enable_dynamic_flags = False
        battle = MagicMock()
        move = Move("weatherball", gen=9)

        dtype, dpower, info = _apply_dynamic_calcs_to_move(
            move, battle, sim, MagicMock(), MagicMock()
        )
        assert dtype is None
        assert dpower is None
        assert info == ""

    def test_flags_only_calcs_disabled_returns_none(self):
        """When enable_dynamic_flags=True but enable_dynamic_calcs=False,
        returns (None, None, "")."""
        from unittest.mock import MagicMock

        from pokechamp.prompts import _apply_dynamic_calcs_to_move

        sim = MagicMock()
        sim.enable_dynamic_calcs = False
        sim.enable_dynamic_flags = True
        battle = MagicMock()
        move = Move("weatherball", gen=9)

        dtype, dpower, info = _apply_dynamic_calcs_to_move(
            move, battle, sim, MagicMock(), MagicMock()
        )
        assert dtype is None
        assert dpower is None
        assert info == ""

    def test_both_flags_enabled_weatherball_rain(self):
        """With both flags enabled, weatherball in rain resolves to Water/100."""
        from unittest.mock import MagicMock

        from poke_env.environment.weather import Weather

        from pokechamp.prompts import _apply_dynamic_calcs_to_move

        sim = MagicMock()
        sim.enable_dynamic_calcs = True
        sim.enable_dynamic_flags = True

        battle = MagicMock()
        battle.weather = {Weather.RAINDANCE: 1}
        battle.fields = {}

        user = MagicMock()
        user.item = None
        user.status = None

        target = MagicMock()
        target.item = "leftovers"
        target.status = None

        move = Move("weatherball", gen=9)

        dtype, dpower, info = _apply_dynamic_calcs_to_move(
            move, battle, sim, user, target
        )

        assert dtype == "Water"
        assert dpower == 100
        assert "Water" in info
        assert "100" in info

    def test_both_flags_enabled_acrobatics_no_item(self):
        """With both flags enabled, acrobatics with no item resolves to 110."""
        from unittest.mock import MagicMock

        from pokechamp.prompts import _apply_dynamic_calcs_to_move

        sim = MagicMock()
        sim.enable_dynamic_calcs = True
        sim.enable_dynamic_flags = True

        battle = MagicMock()
        battle.weather = {}
        battle.fields = {}

        user = MagicMock()
        user.item = None
        user.status = None

        target = MagicMock()
        target.item = "leftovers"
        target.status = None

        move = Move("acrobatics", gen=9)

        dtype, dpower, info = _apply_dynamic_calcs_to_move(
            move, battle, sim, user, target
        )

        assert dtype is None  # acrobatics doesn't change type
        assert dpower == 110  # doubled power with no item
        assert "110" in info

    def test_both_flags_enabled_facade_with_status(self):
        """With both flags enabled, facade with status resolves to 140."""
        from unittest.mock import MagicMock

        from poke_env.environment.status import Status

        from pokechamp.prompts import _apply_dynamic_calcs_to_move

        sim = MagicMock()
        sim.enable_dynamic_calcs = True
        sim.enable_dynamic_flags = True

        battle = MagicMock()
        battle.weather = {}
        battle.fields = {}

        user = MagicMock()
        user.item = "leftovers"
        user.status = Status.BRN

        target = MagicMock()
        target.item = None
        target.status = None

        move = Move("facade", gen=9)

        dtype, dpower, info = _apply_dynamic_calcs_to_move(
            move, battle, sim, user, target
        )

        assert dtype is None  # facade doesn't change type
        assert dpower == 140  # doubled power with status
        assert "140" in info

    def test_regular_move_no_dynamic(self):
        """Regular moves like flamethrower return no dynamic info."""
        from unittest.mock import MagicMock

        from pokechamp.prompts import _apply_dynamic_calcs_to_move

        sim = MagicMock()
        sim.enable_dynamic_calcs = True
        sim.enable_dynamic_flags = True

        battle = MagicMock()
        battle.weather = {}
        battle.fields = {}

        user = MagicMock()
        user.item = None
        user.status = None

        target = MagicMock()
        target.item = None
        target.status = None

        move = Move("flamethrower", gen=9)

        dtype, dpower, info = _apply_dynamic_calcs_to_move(
            move, battle, sim, user, target
        )

        assert dtype is None
        assert dpower is None
        assert info == ""

    def test_grassyglide_priority_info(self):
        """Grassyglide in Grassy Terrain shows priority info."""
        from unittest.mock import MagicMock

        from poke_env.environment.field import Field

        from pokechamp.prompts import _apply_dynamic_calcs_to_move

        sim = MagicMock()
        sim.enable_dynamic_calcs = True
        sim.enable_dynamic_flags = True

        battle = MagicMock()
        battle.weather = {}
        battle.fields = {Field.GRASSY_TERRAIN: 1}

        user = MagicMock()
        user.item = None
        user.status = None
        user.type_1 = MagicMock()
        user.type_1.name = "GRASS"
        user.type_2 = None
        user.ability = "overgrow"

        target = MagicMock()
        target.item = None
        target.status = None

        move = Move("grassyglide", gen=9)

        dtype, dpower, info = _apply_dynamic_calcs_to_move(
            move, battle, sim, user, target
        )

        assert "pri+1" in info

    def test_knockoff_target_item_power(self):
        """Knock off with target having removable item → 97.5 power."""
        from unittest.mock import MagicMock

        from pokechamp.prompts import _apply_dynamic_calcs_to_move

        sim = MagicMock()
        sim.enable_dynamic_calcs = True
        sim.enable_dynamic_flags = True

        battle = MagicMock()
        battle.weather = {}
        battle.fields = {}

        user = MagicMock()
        user.item = None
        user.status = None

        target = MagicMock()
        target.item = "choicescarf"
        target.status = None

        move = Move("knockoff", gen=9)

        dtype, dpower, info = _apply_dynamic_calcs_to_move(
            move, battle, sim, user, target
        )

        assert dpower == 97.5
        assert "97.5" in info


@pytest.mark.moves
class TestPromptBackwardCompatibility:
    """Verify that when flags are disabled, prompts are unchanged."""

    def test_helper_returns_none_when_disabled(self):
        """The integration helper returns no-op values when flags off."""
        from unittest.mock import MagicMock

        from pokechamp.prompts import _apply_dynamic_calcs_to_move

        sim = MagicMock()
        sim.enable_dynamic_calcs = False
        sim.enable_dynamic_flags = False

        battle = MagicMock()
        battle.weather = {MagicMock(): 1}

        move = Move("weatherball", gen=9)

        dtype, dpower, info = _apply_dynamic_calcs_to_move(
            move, battle, sim, MagicMock(), MagicMock()
        )

        assert dtype is None
        assert dpower is None
        assert info == ""

    def test_calcs_without_flags_no_effect(self):
        """VAL-CROSS-001: enable_dynamic_calcs=True alone has no effect."""
        from unittest.mock import MagicMock

        from pokechamp.prompts import _apply_dynamic_calcs_to_move

        sim = MagicMock()
        sim.enable_dynamic_calcs = True
        sim.enable_dynamic_flags = False

        battle = MagicMock()
        battle.weather = {}

        move = Move("weatherball", gen=9)

        dtype, dpower, info = _apply_dynamic_calcs_to_move(
            move, battle, sim, MagicMock(), MagicMock()
        )

        # calcs require flags to be enabled
        assert dtype is None
        assert dpower is None
        assert info == ""

    def test_no_dynamic_for_non_applicable_moves(self):
        """VAL-CROSS-004: Non-applicable moves show no dynamic info."""
        from unittest.mock import MagicMock

        from pokechamp.prompts import _apply_dynamic_calcs_to_move

        sim = MagicMock()
        sim.enable_dynamic_calcs = True
        sim.enable_dynamic_flags = True

        battle = MagicMock()
        battle.weather = {}
        battle.fields = {}

        user = MagicMock()
        user.item = "leftovers"
        user.status = None

        target = MagicMock()
        target.item = None
        target.status = None

        for move_id in ("tackle", "flamethrower", "thunderbolt", "icebeam"):
            move = Move(move_id, gen=9)
            dtype, dpower, info = _apply_dynamic_calcs_to_move(
                move, battle, sim, user, target
            )
            assert dtype is None, f"{move_id} should not have dynamic type"
            assert dpower is None, f"{move_id} should not have dynamic power"
            assert info == "", f"{move_id} should not have dynamic info"


@pytest.mark.moves
class TestDynamicTypeOverrides:
    """Verify dynamic type correctly overrides static type for display."""

    def test_weatherball_type_is_capitalized(self):
        """Dynamic type is returned in capitalized form for display."""
        from unittest.mock import MagicMock

        from poke_env.environment.weather import Weather

        from pokechamp.prompts import _apply_dynamic_calcs_to_move

        sim = MagicMock()
        sim.enable_dynamic_calcs = True
        sim.enable_dynamic_flags = True

        for weather, expected_type in [
            ({Weather.RAINDANCE: 1}, "Water"),
            ({Weather.SUNNYDAY: 1}, "Fire"),
            ({Weather.SANDSTORM: 1}, "Rock"),
            ({Weather.HAIL: 1}, "Ice"),
        ]:
            battle = MagicMock()
            battle.weather = weather
            battle.fields = {}

            user = MagicMock()
            user.item = None
            user.status = None

            target = MagicMock()
            target.item = None
            target.status = None

            move = Move("weatherball", gen=9)
            dtype, _, _ = _apply_dynamic_calcs_to_move(move, battle, sim, user, target)
            assert dtype == expected_type, f"Weather {weather} → {expected_type}"

    def test_no_weather_type_is_normal(self):
        """Without weather, weatherball type is Normal."""
        from unittest.mock import MagicMock

        from pokechamp.prompts import _apply_dynamic_calcs_to_move

        sim = MagicMock()
        sim.enable_dynamic_calcs = True
        sim.enable_dynamic_flags = True

        battle = MagicMock()
        battle.weather = {}
        battle.fields = {}

        user = MagicMock()
        user.item = None
        user.status = None

        target = MagicMock()
        target.item = None
        target.status = None

        move = Move("weatherball", gen=9)
        dtype, _, _ = _apply_dynamic_calcs_to_move(move, battle, sim, user, target)
        # weatherball returns "Normal" in no weather
        assert dtype == "Normal"


@pytest.mark.moves
class TestDynamicPowerOverrides:
    """Verify dynamic power correctly overrides base_power."""

    def test_acrobatics_power_with_item(self):
        """Acrobatics with item = 55 (no change)."""
        from unittest.mock import MagicMock

        from pokechamp.prompts import _apply_dynamic_calcs_to_move

        sim = MagicMock()
        sim.enable_dynamic_calcs = True
        sim.enable_dynamic_flags = True

        battle = MagicMock()
        battle.weather = {}
        battle.fields = {}

        user = MagicMock()
        user.item = "leftovers"
        user.status = None

        target = MagicMock()
        target.item = None
        target.status = None

        move = Move("acrobatics", gen=9)
        _, dpower, _ = _apply_dynamic_calcs_to_move(move, battle, sim, user, target)
        assert dpower == 55

    def test_hex_no_status(self):
        """Hex without target status = 65 (no change)."""
        from unittest.mock import MagicMock

        from pokechamp.prompts import _apply_dynamic_calcs_to_move

        sim = MagicMock()
        sim.enable_dynamic_calcs = True
        sim.enable_dynamic_flags = True

        battle = MagicMock()
        battle.weather = {}
        battle.fields = {}

        user = MagicMock()
        user.item = None
        user.status = None

        target = MagicMock()
        target.item = None
        target.status = None

        move = Move("hex", gen=9)
        _, dpower, _ = _apply_dynamic_calcs_to_move(move, battle, sim, user, target)
        assert dpower == 65

    def test_hex_with_status(self):
        """Hex with target status = 130 (doubled)."""
        from unittest.mock import MagicMock

        from pokechamp.prompts import _apply_dynamic_calcs_to_move

        sim = MagicMock()
        sim.enable_dynamic_calcs = True
        sim.enable_dynamic_flags = True

        battle = MagicMock()
        battle.weather = {}
        battle.fields = {}

        user = MagicMock()
        user.item = None
        user.status = None

        target = MagicMock()
        target.item = None
        target.status = "psn"

        move = Move("hex", gen=9)
        _, dpower, _ = _apply_dynamic_calcs_to_move(move, battle, sim, user, target)
        assert dpower == 130


# ===========================================================================
# Area 12: Species/Form/Property/Terrain Dynamic Type Resolution
# ===========================================================================


@pytest.mark.moves
class TestResolveDynamicTypeIvyCudgel:
    """Ivy Cudgel type resolution based on Ogerpon form."""

    def test_wellspring_water(self):
        """VAL-SPECIES-001: Ogerpon-Wellspring → Water."""
        assert (
            resolve_dynamic_type("ivycudgel", user_species="ogerponwellspring")
            == "Water"
        )

    def test_hearthflame_fire(self):
        """VAL-SPECIES-002: Ogerpon-Hearthflame → Fire."""
        assert (
            resolve_dynamic_type("ivycudgel", user_species="ogerponhearthflame")
            == "Fire"
        )

    def test_cornerstone_rock(self):
        """VAL-SPECIES-003: Ogerpon-Cornerstone → Rock."""
        assert (
            resolve_dynamic_type("ivycudgel", user_species="ogerponcornerstone")
            == "Rock"
        )

    def test_base_form_grass(self):
        """VAL-SPECIES-004: Ogerpon (default) → Grass."""
        assert resolve_dynamic_type("ivycudgel", user_species="ogerpon") == "Grass"

    def test_species_normalization(self):
        """VAL-SPECIES-005: Species normalization handles hyphens/spaces."""
        assert (
            resolve_dynamic_type(
                "ivycudgel", user_species="Ogerpon-Wellspring"
            )
            == "Water"
        )

    def test_tera_form_grass(self):
        """VAL-SPECIES-006: Ogerpon-Tera → Grass (base form default)."""
        assert resolve_dynamic_type("ivycudgel", user_species="ogerpontera") == "Grass"

    def test_non_ogerpon_none(self):
        """VAL-SPECIES-007: Non-Ogerpon species returns None."""
        assert resolve_dynamic_type("ivycudgel", user_species="pikachu") is None

    def test_no_species_none(self):
        """VAL-SPECIES-008: No species provided returns None."""
        assert resolve_dynamic_type("ivycudgel") is None


@pytest.mark.moves
class TestResolveDynamicTypeRagingBull:
    """Raging Bull type resolution based on Tauros-Paldea form."""

    def test_combat_fighting(self):
        """VAL-SPECIES-009: Tauros-Paldea-Combat → Fighting."""
        assert (
            resolve_dynamic_type("ragingbull", user_species="taurospaldeacombat")
            == "Fighting"
        )

    def test_blaze_fire(self):
        """VAL-SPECIES-010: Tauros-Paldea-Blaze → Fire."""
        assert (
            resolve_dynamic_type("ragingbull", user_species="taurospaldeablaze")
            == "Fire"
        )

    def test_aqua_water(self):
        """VAL-SPECIES-011: Tauros-Paldea-Aqua → Water."""
        assert (
            resolve_dynamic_type("ragingbull", user_species="taurospaldeaaqua")
            == "Water"
        )

    def test_base_tauros_normal(self):
        """VAL-SPECIES-012: Tauros (default) → Normal."""
        assert resolve_dynamic_type("ragingbull", user_species="tauros") == "Normal"

    def test_paldea_default_fighting(self):
        """VAL-SPECIES-013: Tauros-Paldea (no breed) → Fighting."""
        assert (
            resolve_dynamic_type("ragingbull", user_species="taurospaldea")
            == "Fighting"
        )

    def test_non_tauros_none(self):
        """VAL-SPECIES-014: Non-Tauros species returns None."""
        assert resolve_dynamic_type("ragingbull", user_species="pikachu") is None


@pytest.mark.moves
class TestResolveDynamicTypeTeraStarStorm:
    """Tera Star Storm type resolution based on Terapagos form."""

    def test_stellar_form(self):
        """VAL-SPECIES-015: Terapagos-Stellar → Stellar."""
        assert (
            resolve_dynamic_type("terastarstorm", user_species="terapagosstellar")
            == "Stellar"
        )

    def test_base_terapagos_none(self):
        """VAL-SPECIES-016: Terapagos (base) → None."""
        assert (
            resolve_dynamic_type("terastarstorm", user_species="terapagos") is None
        )

    def test_terastal_form_stellar(self):
        """VAL-SPECIES-017: Terapagos-Terastal → Stellar."""
        assert (
            resolve_dynamic_type("terastarstorm", user_species="terapagosterastal")
            == "Stellar"
        )

    def test_non_terapagos_none(self):
        assert (
            resolve_dynamic_type("terastarstorm", user_species="pikachu") is None
        )

    def test_no_species_none(self):
        assert resolve_dynamic_type("terastarstorm") is None


@pytest.mark.moves
class TestResolveDynamicTypeRevelationDance:
    """Revelation Dance type resolution based on user's primary type."""

    def test_fire_type(self):
        """VAL-PROP-001: type_1 Fire → Fire."""
        assert resolve_dynamic_type("revelationdance", user_type_1="Fire") == "Fire"

    def test_water_type(self):
        """VAL-PROP-002: type_1 Water → Water."""
        assert (
            resolve_dynamic_type("revelationdance", user_type_1="Water") == "Water"
        )

    def test_grass_type(self):
        """VAL-PROP-003: type_1 Grass → Grass."""
        assert resolve_dynamic_type("revelationdance", user_type_1="Grass") == "Grass"

    def test_terastallized_override(self):
        """VAL-PROP-004: Tera type overrides base type_1."""
        assert (
            resolve_dynamic_type(
                "revelationdance", user_type_1="Fire", tera_type="Flying"
            )
            == "Flying"
        )

    def test_bird_edge_case(self):
        """VAL-PROP-005: Non-standard type like Bird passes through."""
        assert (
            resolve_dynamic_type("revelationdance", user_type_1="Bird") == "Bird"
        )

    def test_no_type_none(self):
        assert resolve_dynamic_type("revelationdance") is None

    def test_none_type_none(self):
        assert resolve_dynamic_type("revelationdance", user_type_1=None) is None


@pytest.mark.moves
class TestResolveDynamicTypeTerrainPulse:
    """Terrain Pulse type resolution based on active terrain."""

    def test_electric_terrain(self):
        """VAL-PROP-006: Electric Terrain → Electric."""
        assert (
            resolve_dynamic_type(
                "terrainpulse", terrain="electricterrain", user_grounded=True
            )
            == "Electric"
        )

    def test_grassy_terrain(self):
        """VAL-PROP-007: Grassy Terrain → Grass."""
        assert (
            resolve_dynamic_type(
                "terrainpulse", terrain="grassyterrain", user_grounded=True
            )
            == "Grass"
        )

    def test_misty_terrain(self):
        """VAL-PROP-008: Misty Terrain → Fairy."""
        assert (
            resolve_dynamic_type(
                "terrainpulse", terrain="mistyterrain", user_grounded=True
            )
            == "Fairy"
        )

    def test_psychic_terrain(self):
        """VAL-PROP-009: Psychic Terrain → Psychic."""
        assert (
            resolve_dynamic_type(
                "terrainpulse", terrain="psychicterrain", user_grounded=True
            )
            == "Psychic"
        )

    def test_not_grounded_none(self):
        """VAL-PROP-010: Not grounded → None."""
        assert (
            resolve_dynamic_type(
                "terrainpulse", terrain="electricterrain", user_grounded=False
            )
            is None
        )

    def test_no_terrain_none(self):
        """No terrain active → None."""
        assert (
            resolve_dynamic_type(
                "terrainpulse", terrain=None, user_grounded=True
            )
            is None
        )

    def test_no_kwargs_none(self):
        assert resolve_dynamic_type("terrainpulse") is None


@pytest.mark.moves
class TestNewKwargsBackwardCompatibility:
    """Verify new kwargs don't break existing calls."""

    def test_weatherball_still_works_with_new_kwargs_present(self):
        """Existing weatherball call with extra kwargs still works."""
        assert (
            resolve_dynamic_type(
                "weatherball",
                weather=Weather.RAINDANCE,
                terrain="electricterrain",
                user_type_1="Fire",
            )
            == "Water"
        )

    def test_terablast_still_works(self):
        assert resolve_dynamic_type("terablast", tera_type="Fire") == "Fire"

    def test_aurawheel_still_works(self):
        assert (
            resolve_dynamic_type(
                "aurawheel", user_species="morpeko", user_form="hangry"
            )
            == "Dark"
        )

    def test_hiddenpower_still_works(self):
        assert (
            resolve_dynamic_type(
                "hiddenpower",
                ivs={"hp": 31, "atk": 31, "def": 31, "spa": 31, "spd": 31, "spe": 31},
            )
            == "DARK"
        )

    def test_static_moves_return_none(self):
        """VAL-BACK-003: Static moves return None."""
        for move_id in ("flamethrower", "thunderbolt", "tackle"):
            assert resolve_dynamic_type(move_id) is None


# ===========================================================================
# Area 13: Integration — terrain and user_type_1 passed via prompts
# ===========================================================================


@pytest.mark.moves
class TestApplyDynamicCalcsTerrainPulse:
    """Test _apply_dynamic_calcs_to_move passes terrain and user_type_1."""

    def _make_sim(self):
        from unittest.mock import MagicMock

        sim = MagicMock()
        sim.enable_dynamic_calcs = True
        sim.enable_dynamic_flags = True
        return sim

    def test_terrainpulse_electric_terrain(self):
        """VAL-DISPATCH-004: terrainpulse resolves Electric from battle.fields."""
        from unittest.mock import MagicMock

        from poke_env.environment.field import Field

        from pokechamp.prompts import _apply_dynamic_calcs_to_move

        sim = self._make_sim()
        battle = MagicMock()
        battle.weather = {}
        battle.fields = {Field.ELECTRIC_TERRAIN: 1}

        user = MagicMock()
        user.item = None
        user.status = None
        user.type_1 = MagicMock()
        user.type_1.name = "ELECTRIC"
        user.type_2 = None
        user.ability = None

        target = MagicMock()
        target.item = None
        target.status = None

        move = Move("terrainpulse", gen=9)

        dtype, dpower, info = _apply_dynamic_calcs_to_move(
            move, battle, sim, user, target
        )
        assert dtype == "Electric"
        assert "Electric" in info

    def test_revelationdance_fire_type(self):
        """_apply_dynamic_calcs_to_move passes user_type_1 for revelationdance."""
        from unittest.mock import MagicMock

        from pokechamp.prompts import _apply_dynamic_calcs_to_move

        sim = self._make_sim()
        battle = MagicMock()
        battle.weather = {}
        battle.fields = {}

        user = MagicMock()
        user.item = None
        user.status = None
        user.type_1 = MagicMock()
        user.type_1.name = "FIRE"
        user.type_2 = None
        user.ability = None

        target = MagicMock()
        target.item = None
        target.status = None

        move = Move("revelationdance", gen=9)

        dtype, dpower, info = _apply_dynamic_calcs_to_move(
            move, battle, sim, user, target
        )
        assert dtype == "Fire"
        assert "Fire" in info

    def test_ivycudgel_ogerpon_wellspring(self):
        """_apply_dynamic_calcs_to_move passes species for ivycudgel."""
        from unittest.mock import MagicMock

        from pokechamp.prompts import _apply_dynamic_calcs_to_move

        sim = self._make_sim()
        battle = MagicMock()
        battle.weather = {}
        battle.fields = {}

        user = MagicMock()
        user.item = None
        user.status = None
        user.species = "ogerponwellspring"
        user.type_1 = MagicMock()
        user.type_1.name = "WATER"
        user.type_2 = None
        user.ability = None

        target = MagicMock()
        target.item = None
        target.status = None

        move = Move("ivycudgel", gen=9)

        dtype, dpower, info = _apply_dynamic_calcs_to_move(
            move, battle, sim, user, target
        )
        assert dtype == "Water"

    def test_ragingbull_tauros_blaze(self):
        """_apply_dynamic_calcs_to_move passes species for ragingbull."""
        from unittest.mock import MagicMock

        from pokechamp.prompts import _apply_dynamic_calcs_to_move

        sim = self._make_sim()
        battle = MagicMock()
        battle.weather = {}
        battle.fields = {}

        user = MagicMock()
        user.item = None
        user.status = None
        user.species = "taurospaldeablaze"
        user.type_1 = MagicMock()
        user.type_1.name = "FIRE"
        user.type_2 = None
        user.ability = None

        target = MagicMock()
        target.item = None
        target.status = None

        move = Move("ragingbull", gen=9)

        dtype, dpower, info = _apply_dynamic_calcs_to_move(
            move, battle, sim, user, target
        )
        assert dtype == "Fire"

    def test_terastarstorm_terapagos_stellar(self):
        """_apply_dynamic_calcs_to_move passes species for terastarstorm."""
        from unittest.mock import MagicMock

        from pokechamp.prompts import _apply_dynamic_calcs_to_move

        sim = self._make_sim()
        battle = MagicMock()
        battle.weather = {}
        battle.fields = {}

        user = MagicMock()
        user.item = None
        user.status = None
        user.species = "terapagosstellar"
        user.type_1 = MagicMock()
        user.type_1.name = "STELLAR"
        user.type_2 = None
        user.ability = None

        target = MagicMock()
        target.item = None
        target.status = None

        move = Move("terastarstorm", gen=9)

        dtype, dpower, info = _apply_dynamic_calcs_to_move(
            move, battle, sim, user, target
        )
        assert dtype == "Stellar"


# ===========================================================================
# Area 14: format_dynamic_info for new moves
# ===========================================================================


@pytest.mark.moves
class TestFormatDynamicInfoNewMoves:
    """Verify format_dynamic_info produces correct strings for new moves."""

    def test_ivycudgel_wellspring(self):
        result = format_dynamic_info(
            "ivycudgel", user_species="ogerponwellspring"
        )
        assert "Water" in result

    def test_ragingbull_combat(self):
        result = format_dynamic_info(
            "ragingbull", user_species="taurospaldeacombat"
        )
        assert "Fighting" in result

    def test_terastarstorm_stellar(self):
        result = format_dynamic_info(
            "terastarstorm", user_species="terapagosstellar"
        )
        assert "Stellar" in result

    def test_revelationdance_fire(self):
        result = format_dynamic_info(
            "revelationdance", user_type_1="Fire"
        )
        assert "Fire" in result

    def test_terrainpulse_electric(self):
        result = format_dynamic_info(
            "terrainpulse", terrain="electricterrain", user_grounded=True
        )
        assert "Electric" in result

    def test_ivycudgel_non_ogerpon_empty(self):
        result = format_dynamic_info(
            "ivycudgel", user_species="pikachu"
        )
        assert result == ""

    def test_revelationdance_no_type_empty(self):
        result = format_dynamic_info("revelationdance")
        assert result == ""

    def test_terrainpulse_no_terrain_empty(self):
        result = format_dynamic_info(
            "terrainpulse", terrain=None, user_grounded=True
        )
        assert result == ""


# ===========================================================================
# Area 15: Item-Based Dynamic Type Resolution
# ===========================================================================


@pytest.mark.moves
class TestResolveDynamicTypeJudgment:
    """Judgment type resolution based on held plate item."""

    @pytest.mark.parametrize(
        "item,expected",
        [
            ("flameplate", "Fire"),
            ("splashplate", "Water"),
            ("meadowplate", "Grass"),
            ("zapplate", "Electric"),
            ("mindplate", "Psychic"),
            ("icicleplate", "Ice"),
            ("fistplate", "Fighting"),
            ("toxicplate", "Poison"),
            ("earthplate", "Ground"),
            ("skyplate", "Flying"),
            ("insectplate", "Bug"),
            ("stoneplate", "Rock"),
            ("spookyplate", "Ghost"),
            ("dracoplate", "Dragon"),
            ("dreadplate", "Dark"),
            ("ironplate", "Steel"),
            ("pixieplate", "Fairy"),
        ],
    )
    def test_plate_mapping(self, item, expected):
        """VAL-ITEM-001: Plate item maps to correct type."""
        assert resolve_dynamic_type("judgment", user_item=item) == expected

    def test_no_item_none(self):
        """VAL-ITEM-002: No item → None."""
        assert resolve_dynamic_type("judgment", user_item=None) is None

    def test_z_crystal_excluded(self):
        """VAL-ITEM-003: Z-crystal (has onPlate but is zMove) → None."""
        assert resolve_dynamic_type("judgment", user_item="decidiumz") is None
        assert resolve_dynamic_type("judgment", user_item="firiumz") is None
        assert resolve_dynamic_type("judgment", user_item="buginiumz") is None

    def test_non_plate_item_none(self):
        """VAL-ITEM-004: Non-plate item → None."""
        assert resolve_dynamic_type("judgment", user_item="leftovers") is None
        assert resolve_dynamic_type("judgment", user_item="choicescarf") is None

    def test_no_kwarg_none(self):
        """VAL-ITEM-005: No user_item kwarg → None."""
        assert resolve_dynamic_type("judgment") is None


@pytest.mark.moves
class TestResolveDynamicTypeMultiAttack:
    """Multi-Attack type resolution based on held memory item."""

    @pytest.mark.parametrize(
        "item,expected",
        [
            ("firememory", "Fire"),
            ("watermemory", "Water"),
            ("grassmemory", "Grass"),
            ("electricmemory", "Electric"),
            ("psychicmemory", "Psychic"),
            ("icememory", "Ice"),
            ("fightingmemory", "Fighting"),
            ("poisonmemory", "Poison"),
            ("groundmemory", "Ground"),
            ("flyingmemory", "Flying"),
            ("bugmemory", "Bug"),
            ("rockmemory", "Rock"),
            ("ghostmemory", "Ghost"),
            ("dragonmemory", "Dragon"),
            ("darkmemory", "Dark"),
            ("steelmemory", "Steel"),
            ("fairymemory", "Fairy"),
        ],
    )
    def test_memory_mapping(self, item, expected):
        """VAL-ITEM-006: Memory item maps to correct type."""
        assert resolve_dynamic_type("multiattack", user_item=item) == expected

    def test_no_item_none(self):
        """VAL-ITEM-007: No item → None."""
        assert resolve_dynamic_type("multiattack", user_item=None) is None

    def test_non_memory_item_none(self):
        """VAL-ITEM-008: Non-memory item → None."""
        assert (
            resolve_dynamic_type("multiattack", user_item="choicescarf") is None
        )
        assert (
            resolve_dynamic_type("multiattack", user_item="leftovers") is None
        )

    def test_no_kwarg_none(self):
        """VAL-ITEM-009: No user_item kwarg → None."""
        assert resolve_dynamic_type("multiattack") is None


@pytest.mark.moves
class TestResolveDynamicTypeTechnoBlast:
    """Techno Blast type resolution based on held drive item."""

    @pytest.mark.parametrize(
        "item,expected",
        [
            ("burndrive", "Fire"),
            ("chilldrive", "Ice"),
            ("dousedrive", "Water"),
            ("shockdrive", "Electric"),
        ],
    )
    def test_drive_mapping(self, item, expected):
        """VAL-ITEM-010: Drive item maps to correct type."""
        assert resolve_dynamic_type("technoblast", user_item=item) == expected

    def test_no_item_none(self):
        """VAL-ITEM-011: No item → None."""
        assert resolve_dynamic_type("technoblast", user_item=None) is None

    def test_non_drive_item_none(self):
        """VAL-ITEM-012: Non-drive item → None."""
        assert (
            resolve_dynamic_type("technoblast", user_item="leftovers") is None
        )

    def test_no_kwarg_none(self):
        """VAL-ITEM-013: No user_item kwarg → None."""
        assert resolve_dynamic_type("technoblast") is None


@pytest.mark.moves
class TestResolveDynamicTypeNaturalGift:
    """Natural Gift type resolution based on held berry item."""

    @pytest.mark.parametrize(
        "item,expected",
        [
            ("cheriberry", "Fire"),
            ("rawstberry", "Grass"),
            ("pechaberry", "Electric"),
            ("sitrusberry", "Psychic"),
            ("oranberry", "Poison"),
            ("apicotberry", "Ground"),
            ("lansatberry", "Flying"),
            ("salacberry", "Fighting"),
            ("starfberry", "Psychic"),
            ("occaberry", "Fire"),
            ("wacanberry", "Electric"),
        ],
    )
    def test_berry_mapping(self, item, expected):
        """VAL-ITEM-014: Berry item maps to correct type."""
        assert resolve_dynamic_type("naturalgift", user_item=item) == expected

    def test_no_item_none(self):
        """VAL-ITEM-015: No item → None."""
        assert resolve_dynamic_type("naturalgift", user_item=None) is None

    def test_non_berry_item_none(self):
        """VAL-ITEM-016: Non-berry item → None."""
        assert (
            resolve_dynamic_type("naturalgift", user_item="leftovers") is None
        )
        assert (
            resolve_dynamic_type("naturalgift", user_item="choicescarf") is None
        )

    def test_unknown_berry_none(self):
        """VAL-ITEM-018: Unknown berry returns None."""
        assert (
            resolve_dynamic_type("naturalgift", user_item="fakeberry") is None
        )

    def test_power_resolution(self):
        """VAL-ITEM-017: Natural Gift resolves both type and power."""
        dtype = resolve_dynamic_type("naturalgift", user_item="cheriberry")
        assert dtype == "Fire"
        dpower = resolve_dynamic_power("naturalgift", user_item="cheriberry")
        assert dpower is not None
        assert isinstance(dpower, int)

    @pytest.mark.parametrize(
        "item,expected_power",
        [
            ("cheriberry", 80),
            ("apicotberry", 100),
            ("blukberry", 90),
            ("custapberry", 100),
            ("starfberry", 100),
            ("tamatoberry", 90),
        ],
    )
    def test_power_tiers(self, item, expected_power):
        """Verify berry power tiers (80/90/100)."""
        assert (
            resolve_dynamic_power("naturalgift", user_item=item) == expected_power
        )

    def test_power_no_item_none(self):
        """No item → None power."""
        assert (
            resolve_dynamic_power("naturalgift", user_item=None) is None
        )

    def test_no_kwarg_none(self):
        """No user_item kwarg → None."""
        assert resolve_dynamic_type("naturalgift") is None


@pytest.mark.moves
class TestAllOnModifyTypeMoves:
    """VAL-DISPATCH-001: All 13 onModifyType moves dispatch correctly."""

    def test_all_13_moves_dispatch(self):
        """Each of the 13 onModifyType moves returns expected type for
        known input, and None for unrecognized moves."""
        from unittest.mock import MagicMock

        from poke_env.environment.pokemon_type import PokemonType

        # All 13 moves and their expected output for a specific input
        cases = {
            "weatherball": (
                {"weather": Weather.RAINDANCE},
                "Water",
            ),
            "terablast": ({"tera_type": "Fire"}, "Fire"),
            "aurawheel": (
                {"user_species": "morpeko", "user_form": "hangry"},
                "Dark",
            ),
            "hiddenpower": (
                {"ivs": {"hp": 0, "atk": 0, "def": 0, "spa": 0, "spd": 0, "spe": 0}},
                "FIGHTING",
            ),
            "ivycudgel": ({"user_species": "ogerponwellspring"}, "Water"),
            "ragingbull": ({"user_species": "taurospaldeablaze"}, "Fire"),
            "terastarstorm": ({"user_species": "terapagosstellar"}, "Stellar"),
            "revelationdance": ({"user_type_1": "Fire"}, "Fire"),
            "terrainpulse": (
                {"terrain": "electricterrain", "user_grounded": True},
                "Electric",
            ),
            "judgment": ({"user_item": "flameplate"}, "Fire"),
            "multiattack": ({"user_item": "firememory"}, "Fire"),
            "technoblast": ({"user_item": "burndrive"}, "Fire"),
            "naturalgift": ({"user_item": "cheriberry"}, "Fire"),
        }

        for move_id, (kwargs, expected) in cases.items():
            result = resolve_dynamic_type(move_id, **kwargs)
            assert result == expected, (
                f"{move_id} with {kwargs} returned {result!r}, expected {expected!r}"
            )

    def test_unknown_move_none(self):
        """Unrecognized moves return None."""
        assert resolve_dynamic_type("tackle") is None
        assert resolve_dynamic_type("flamethrower") is None
        assert resolve_dynamic_type("thunderbolt") is None


@pytest.mark.moves
class TestFormatDynamicInfoItemMoves:
    """VAL-DISPATCH-006: format_dynamic_info for item-based moves."""

    def test_judgment_plate(self):
        result = format_dynamic_info("judgment", user_item="flameplate")
        assert "Fire" in result
        assert "plate→Fire" in result

    def test_multiattack_memory(self):
        result = format_dynamic_info("multiattack", user_item="watermemory")
        assert "Water" in result
        assert "memory→Water" in result

    def test_technoblast_drive(self):
        result = format_dynamic_info("technoblast", user_item="shockdrive")
        assert "Electric" in result
        assert "drive→Electric" in result

    def test_naturalgift_berry(self):
        result = format_dynamic_info("naturalgift", user_item="cheriberry")
        assert "Fire" in result
        assert "berry→Fire" in result
        assert "80" in result  # berry power

    def test_judgment_no_item_empty(self):
        result = format_dynamic_info("judgment", user_item=None)
        assert result == ""

    def test_multiattack_no_item_empty(self):
        result = format_dynamic_info("multiattack", user_item=None)
        assert result == ""

    def test_technoblast_no_item_empty(self):
        result = format_dynamic_info("technoblast", user_item=None)
        assert result == ""

    def test_naturalgift_no_item_empty(self):
        result = format_dynamic_info("naturalgift", user_item=None)
        assert result == ""


@pytest.mark.moves
class TestApplyDynamicCalcsItemMoves:
    """VAL-DISPATCH-003/005: _apply_dynamic_calcs_to_move passes user_item."""

    def _make_sim(self):
        from unittest.mock import MagicMock

        sim = MagicMock()
        sim.enable_dynamic_calcs = True
        sim.enable_dynamic_flags = True
        return sim

    def test_judgment_flameplate(self):
        """VAL-DISPATCH-005: judgment with flameplate resolves Fire."""
        from unittest.mock import MagicMock

        from pokechamp.prompts import _apply_dynamic_calcs_to_move

        sim = self._make_sim()
        battle = MagicMock()
        battle.weather = {}
        battle.fields = {}

        user = MagicMock()
        user.item = "flameplate"
        user.status = None
        user.type_1 = MagicMock()
        user.type_1.name = "FIRE"
        user.type_2 = None
        user.ability = None

        target = MagicMock()
        target.item = None
        target.status = None

        move = Move("judgment", gen=9)

        dtype, dpower, info = _apply_dynamic_calcs_to_move(
            move, battle, sim, user, target
        )
        assert dtype == "Fire"
        assert "Fire" in info

    def test_multiattack_firememory(self):
        """multiattack with firememory resolves Fire."""
        from unittest.mock import MagicMock

        from pokechamp.prompts import _apply_dynamic_calcs_to_move

        sim = self._make_sim()
        battle = MagicMock()
        battle.weather = {}
        battle.fields = {}

        user = MagicMock()
        user.item = "firememory"
        user.status = None
        user.type_1 = MagicMock()
        user.type_1.name = "NORMAL"
        user.type_2 = None
        user.ability = None

        target = MagicMock()
        target.item = None
        target.status = None

        move = Move("multiattack", gen=9)

        dtype, dpower, info = _apply_dynamic_calcs_to_move(
            move, battle, sim, user, target
        )
        assert dtype == "Fire"

    def test_technoblast_burndrive(self):
        """technoblast with burndrive resolves Fire."""
        from unittest.mock import MagicMock

        from pokechamp.prompts import _apply_dynamic_calcs_to_move

        sim = self._make_sim()
        battle = MagicMock()
        battle.weather = {}
        battle.fields = {}

        user = MagicMock()
        user.item = "burndrive"
        user.status = None
        user.type_1 = MagicMock()
        user.type_1.name = "NORMAL"
        user.type_2 = None
        user.ability = None

        target = MagicMock()
        target.item = None
        target.status = None

        move = Move("technoblast", gen=9)

        dtype, dpower, info = _apply_dynamic_calcs_to_move(
            move, battle, sim, user, target
        )
        assert dtype == "Fire"

    def test_naturalgift_cheriberry(self):
        """naturalgift with cheriberry resolves Fire type and 80 power."""
        from unittest.mock import MagicMock

        from pokechamp.prompts import _apply_dynamic_calcs_to_move

        sim = self._make_sim()
        battle = MagicMock()
        battle.weather = {}
        battle.fields = {}

        user = MagicMock()
        user.item = "cheriberry"
        user.status = None
        user.type_1 = MagicMock()
        user.type_1.name = "NORMAL"
        user.type_2 = None
        user.ability = None

        target = MagicMock()
        target.item = None
        target.status = None

        move = Move("naturalgift", gen=9)

        dtype, dpower, info = _apply_dynamic_calcs_to_move(
            move, battle, sim, user, target
        )
        assert dtype == "Fire"
        assert dpower == 80
        assert "berry→Fire" in info
        assert "80" in info

    def test_judgment_no_item_no_type(self):
        """judgment with no item returns None type."""
        from unittest.mock import MagicMock

        from pokechamp.prompts import _apply_dynamic_calcs_to_move

        sim = self._make_sim()
        battle = MagicMock()
        battle.weather = {}
        battle.fields = {}

        user = MagicMock()
        user.item = None
        user.status = None
        user.type_1 = MagicMock()
        user.type_1.name = "NORMAL"
        user.type_2 = None
        user.ability = None

        target = MagicMock()
        target.item = None
        target.status = None

        move = Move("judgment", gen=9)

        dtype, dpower, info = _apply_dynamic_calcs_to_move(
            move, battle, sim, user, target
        )
        assert dtype is None
        assert info == ""

    def test_user_item_backward_compat(self):
        """VAL-DISPATCH-003: user_item kwarg accepted without breaking
        existing calls."""
        # Weatherball still works when user_item is also present
        assert (
            resolve_dynamic_type(
                "weatherball", weather=Weather.RAINDANCE, user_item="flameplate"
            )
            == "Water"
        )
        # Non-item moves ignore user_item
        assert (
            resolve_dynamic_type("ivycudgel", user_species="ogerpon", user_item="leftovers")
            == "Grass"
        )


@pytest.mark.moves
class TestItemMoveBackwardCompatibility:
    """Verify item-based moves don't break existing functionality."""

    def test_existing_4_moves_unchanged(self):
        """VAL-BACK-001: Weatherball, terablast, aurawheel, hiddenpower
        still produce identical results."""
        assert resolve_dynamic_type("weatherball", weather=Weather.RAINDANCE) == "Water"
        assert resolve_dynamic_type("terablast", tera_type="Fire") == "Fire"
        assert (
            resolve_dynamic_type("aurawheel", user_species="morpeko", user_form="hangry")
            == "Dark"
        )
        assert (
            resolve_dynamic_type(
                "hiddenpower",
                ivs={"hp": 31, "atk": 31, "def": 31, "spa": 31, "spd": 31, "spe": 31},
            )
            == "DARK"
        )

    def test_static_moves_return_none(self):
        """VAL-BACK-003: Static non-dynamic moves return None."""
        for move_id in ("tackle", "flamethrower", "thunderbolt"):
            assert resolve_dynamic_type(move_id) is None
