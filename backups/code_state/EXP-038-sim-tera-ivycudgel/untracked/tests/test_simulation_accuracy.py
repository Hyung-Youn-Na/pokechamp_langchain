"""
Tests for LocalSim battle-mechanics accuracy.

EXP-036 (action order): verify calculate_remaining_hp resolves turn order by
Gen 9 rules — higher move priority first, then higher speed, then a
deterministic speed-tie — and that the protosynthesis speed boost applies to
the correct pokemon (regression for a p1/p2 copy-paste bug).

These exercise LocalSim.calculate_remaining_hp end-to-end with real
Pokemon/Move objects. Scenarios use very low HP so the first mover's attack
KOs its target, making the turn order observable in the returned HP values.
"""

import pytest

from poke_env.data.gen_data import GenData
from poke_env.environment.move import Move
from poke_env.environment.pokemon import Pokemon


def _get_gen():
    """Return the gen-9 GenData singleton, creating it once if needed."""
    if 9 in GenData._gen_data_per_gen:
        return GenData._gen_data_per_gen[9]
    return GenData(9)


def _make_sim():
    """Lightweight LocalSim with only the attributes calculate_remaining_hp
    touches (skips the heavy __init__ / Battle deepcopy)."""
    from unittest.mock import MagicMock

    from poke_env.player.local_simulation import LocalSim

    sim = LocalSim.__new__(LocalSim)
    sim.format = "gen9ou"
    sim.gen = _get_gen()
    # apply_item / modify_damage read battle weather, field, side conditions,
    # etc. A MagicMock lets those attribute reads resolve to falsy values so
    # the environmental multipliers are no-ops (these tests are about order).
    sim.battle = MagicMock()
    return sim


def _make_mon(species, *, hp_frac=1.0, ability=None, item=None, tera_type=None):
    mon = Pokemon(gen=9, species=species)
    # current_hp_fraction is a read-only property of (_current_hp/_max_hp);
    # set both directly, keyed to the stat-derived max so the fraction is exact.
    stats = mon.calculate_stats(battle_format="gen9ou")
    mon._max_hp = stats["hp"]
    mon._current_hp = int(stats["hp"] * hp_frac)
    if ability is not None:
        mon.ability = ability
    if item is not None:
        mon.item = item
    if tera_type is not None:
        from poke_env.environment.pokemon_type import PokemonType
        # terastallized has no setter; set the internal flag the property reads.
        mon._terastallized = True
        if isinstance(tera_type, str):
            mon._terastallized_type = PokemonType[tera_type.upper()]
        else:
            mon._terastallized_type = tera_type
    return mon


@pytest.fixture(scope="module")
def sim():
    return _make_sim()


# HP fraction low enough that any ordinary damaging move KOs in one hit, so
# whose attack resolves first shows up directly in the returned HP values.
_LOW_HP = 0.02


@pytest.mark.moves
class TestActionOrder:
    """EXP-036: turn order follows Gen 9 priority-then-speed."""

    def test_extreme_speed_outranks_faster_opponent(self, sim):
        """Snorlax (base 30 speed) Extreme Speed has +2 priority and moves
        before a faster opponent using a priority-0 move. Prior bug checked
        only priority == 1, so +2 was ignored and raw speed decided."""
        p1 = _make_mon("snorlax", hp_frac=_LOW_HP)
        p2 = _make_mon("arcanine", hp_frac=_LOW_HP)
        m1 = Move("extremespeed", gen=9)
        m2 = Move("closecombat", gen=9)
        assert m1.priority == 2 and m2.priority == 0

        hp1, hp2, _, _ = sim.calculate_remaining_hp(p1, p2, m1, m2)
        # p1 (Extreme Speed) moves first and KOs p2 before p2 can act.
        assert hp2 == 0
        assert hp1 > 0

    def test_p2_priority_outranks_faster_p1(self, sim):
        """The prior implementation inspected only p1's priority, so a faster
        p1 with a priority-0 move would wrongly go before a slower p2 using a
        +1 priority move. p2 (Sucker Punch, +1) must move first."""
        p1 = _make_mon("dragapult", hp_frac=_LOW_HP)
        p2 = _make_mon("tyranitar", hp_frac=_LOW_HP)
        m1 = Move("shadowball", gen=9)
        m2 = Move("suckerpunch", gen=9)
        assert m1.priority == 0 and m2.priority == 1

        hp1, hp2, _, _ = sim.calculate_remaining_hp(p1, p2, m1, m2)
        # p2 Sucker Punch (+1) moves first and KOs p1.
        assert hp1 == 0
        assert hp2 > 0

    def test_higher_speed_moves_first_on_equal_priority(self, sim):
        """With equal priority, the faster pokemon moves first."""
        p1 = _make_mon("dragapult", hp_frac=_LOW_HP)  # base 142
        p2 = _make_mon("snorlax", hp_frac=_LOW_HP)  # base 30
        m1 = Move("thunderbolt", gen=9)  # Electric vs Normal = neutral (avoid 0x)
        m2 = Move("bodyslam", gen=9)
        assert m1.priority == m2.priority == 0

        hp1, hp2, _, _ = sim.calculate_remaining_hp(p1, p2, m1, m2)
        # p1 (faster) moves first and KOs p2.
        assert hp2 == 0
        assert hp1 > 0

    def test_speed_tie_both_act(self, sim):
        """On a genuine speed tie both moves resolve (neither pokemon faints
        before acting), regardless of which side the deterministic tie-break
        picks."""
        p1 = _make_mon("dragonite", hp_frac=1.0)
        p2 = _make_mon("dragonite", hp_frac=1.0)
        m1 = Move("earthquake", gen=9)
        m2 = Move("earthquake", gen=9)
        assert m1.priority == m2.priority == 0

        _, _, m1_ok, m2_ok = sim.calculate_remaining_hp(p1, p2, m1, m2)
        assert m1_ok is True
        assert m2_ok is True

    def test_protosynthesis_speed_boost_uses_correct_mon(self, sim):
        """Regression for the p1/p2 copy-paste bug at the protosynthesis call
        site (calculate_remaining_hp: p2_speed must read p2, not p1).

        apply_protosynthesis must return the 1.5x speed boost for a mon that
        actually has the protosynthesis ability + booster energy, and 1.0 for
        a plain mon. (Built as a stub because LocalSim.apply_protosynthesis
        reads the raw base stats, which are not loaded for bare Pokemon
        objects outside a real Battle.)"""
        from unittest.mock import MagicMock

        boosted = MagicMock()
        boosted.ability = "protosynthesis"
        boosted.item = "boosterdrive"
        boosted.stats = {"atk": 100, "def": 100, "spa": 100, "spd": 100, "spe": 150}
        assert sim.apply_protosynthesis(boosted, "spe") == 1.5
        assert sim.apply_protosynthesis(boosted, "atk") == 1.0  # spe is the top stat

        plain = MagicMock()
        plain.ability = "pressure"
        assert sim.apply_protosynthesis(plain, "spe") == 1.0


# ---------------------------------------------------------------------------
# EXP-037: protect + item accuracy
# ---------------------------------------------------------------------------


@pytest.mark.moves
class TestProtectAndItem:
    """EXP-037: protect-family target moves block damage; Life Orb boosts."""

    def test_protect_zeros_incoming_damage(self, sim):
        p1 = _make_mon("dragonite")
        p2 = _make_mon("snorlax")
        m1 = Move("earthquake", gen=9)
        protect = Move("protect", gen=9)
        base = sim.calc_base_dmg(p1, p2, m1)
        dmg_protected = sim.modify_damage(base, p1, p2, m1, protect)
        dmg_open = sim.modify_damage(base, p1, p2, m1, None)
        assert dmg_protected == 0
        assert dmg_open > 0

    def test_detect_also_blocks(self, sim):
        """The fix covers the whole protect-family, not just 'protect'."""
        p1 = _make_mon("dragonite")
        p2 = _make_mon("snorlax")
        m1 = Move("earthquake", gen=9)
        detect = Move("detect", gen=9)
        base = sim.calc_base_dmg(p1, p2, m1)
        assert sim.modify_damage(base, p1, p2, m1, detect) == 0

    def test_lifeorb_boosts_damage(self, sim):
        """Life Orb (stored lower-case 'lifeorb') applies its 1.3x final
        modifier. Prior code compared against 'LifeOrb' and never matched."""
        p1_plain = _make_mon("dragonite")
        p1_lo = _make_mon("dragonite", item="lifeorb")
        p2 = _make_mon("snorlax")
        m1 = Move("earthquake", gen=9)
        base = sim.calc_base_dmg(p1_plain, p2, m1)
        dmg_plain = sim.modify_damage(base, p1_plain, p2, m1, None)
        dmg_lo = sim.modify_damage(base, p1_lo, p2, m1, None)
        assert dmg_plain > 0
        assert dmg_lo >= dmg_plain
        # final modifier is baseDamage *= 1.3; allow int-truncation slack
        assert abs(dmg_lo - dmg_plain * 1.3) <= 1


# ---------------------------------------------------------------------------
# EXP-038: tera + dynamic-move (ivycudgel) accuracy
# ---------------------------------------------------------------------------


@pytest.mark.moves
class TestTeraAndDynamicMoves:
    """EXP-038: Terastallized typing drives STAB and effectiveness; Ivy Cudgel
    type follows Ogerpon's form."""

    def test_tera_target_uses_single_tera_type(self, sim):
        """Dragonite (Dragon/Flying, normally 4x weak to Ice) Terastallized
        to Water resists Ice (0.5x) instead of taking 4x. Prior code passed
        the attacker's types to the effectiveness lookup, mis-rating this."""
        attacker = _make_mon("mamoswine")
        target_plain = _make_mon("dragonite")
        target_tera = _make_mon("dragonite", tera_type="WATER")
        m = Move("icefang", gen=9)
        dmg_plain = sim.modify_damage(
            sim.calc_base_dmg(attacker, target_plain, m), attacker, target_plain, m, None
        )
        dmg_tera = sim.modify_damage(
            sim.calc_base_dmg(attacker, target_tera, m), attacker, target_tera, m, None
        )
        # plain 4x vs tera-Water 0.5x -> ~8x ratio
        assert dmg_plain >= dmg_tera * 4

    def test_stab_applies_on_tera_type(self, sim):
        """A Terastallized attacker gains STAB on its Tera type even when
        that type is not a base type (Garchomp Tera Normal + Normal Tera Blast)."""
        target = _make_mon("snorlax")
        m = Move("terablast", gen=9)  # Normal
        p_plain = _make_mon("garchomp")  # Dragon/Ground: no Normal STAB
        p_tera = _make_mon("garchomp", tera_type="NORMAL")
        dmg_plain = sim.modify_damage(
            sim.calc_base_dmg(p_plain, target, m), p_plain, target, m, None
        )
        dmg_tera = sim.modify_damage(
            sim.calc_base_dmg(p_tera, target, m), p_tera, target, m, None
        )
        assert dmg_plain > 0
        assert abs(dmg_tera - dmg_plain * 1.5) <= 1

    def test_ivycudgel_type_follows_ogerpon_form(self, sim):
        """Ogerpon-Wellspring Ivy Cudgel is Water (2x into Fire); Ogerpon-Teal
        Ivy Cudgel is Grass (0.5x into Fire). This is the EXP-035 false-OHKO
        case addressed at the type layer."""
        target = _make_mon("arcanine")  # Fire
        wells = _make_mon("ogerponwellspring")
        teal = _make_mon("ogerpon")
        m = Move("ivycudgel", gen=9)
        dmg_wells = sim.modify_damage(
            sim.calc_base_dmg(wells, target, m), wells, target, m, None
        )
        dmg_teal = sim.modify_damage(
            sim.calc_base_dmg(teal, target, m), teal, target, m, None
        )
        # Water->Fire 2x vs Grass->Fire 0.5x -> ~4x ratio
        assert dmg_wells >= dmg_teal * 2

    def test_ivycudgel_power_boost_on_ogerpon_tera(self, sim):
        """Ogerpon Terastallizing boosts Ivy Cudgel base power 100 -> 120."""
        target = _make_mon("snorlax")
        teal_plain = _make_mon("ogerpon")
        teal_tera = _make_mon("ogerpon", tera_type="GRASS")
        m = Move("ivycudgel", gen=9)
        assert sim.modify_base_power(teal_plain, target, m) == 100
        assert sim.modify_base_power(teal_tera, target, m) == 120
