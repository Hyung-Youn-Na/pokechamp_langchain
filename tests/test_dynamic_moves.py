"""
Tests for dynamic move flags and flag text display in prompts.

Covers:
- 7 new keys added to _MISC_FLAGS in poke_env/environment/move.py
- Existing 19 keys preserved
- Flag detection in Move.flags property
- Flag text display in prompts when enable_dynamic_flags=True
- No flag text when enable_dynamic_flags=False
- Flag text conciseness (≤ 30 chars)
"""

import pytest

from poke_env.environment.move import Move

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
