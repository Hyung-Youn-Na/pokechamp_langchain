"""Unit tests for team-preview lead selection + win-plan seeding (EXP-050a).

Covers the team-preview override on ``LangChainPlayer`` and the own-team role
helper on ``BattleMemory``. The react graph topology is unchanged by EXP-050a,
so these tests exercise only the preview path + memory seeding.
"""

from __future__ import annotations

from types import SimpleNamespace

from pokechamp.battle_memory import (
    BattleMemory,
    refresh_own_team_roles,
)
from pokechamp.langchain_player import LangChainPlayer


# ---------------------------------------------------------------------------
# _parse_preview_response
# ---------------------------------------------------------------------------


def test_parse_preview_valid_json():
    raw = (
        '{"team_order": "421365", "my_plan": "Set rocks then sweep", '
        '"opp_win_condition": "Dragon Dance sweep"}'
    )
    order, seed = LangChainPlayer._parse_preview_response(raw, 6)
    assert order == "421365"
    assert seed["my_plan"] == "Set rocks then sweep"
    assert seed["opp_win_condition"] == "Dragon Dance sweep"


def test_parse_preview_dup_digits_invalid_order():
    # "111111" is not a permutation of 1..6 → order None, but seed text kept.
    order, seed = LangChainPlayer._parse_preview_response(
        '{"team_order": "111111", "my_plan": "x"}', 6
    )
    assert order is None
    assert seed["my_plan"] == "x"


def test_parse_preview_out_of_range_invalid_order():
    order, _ = LangChainPlayer._parse_preview_response(
        '{"team_order": "789012"}', 6
    )
    assert order is None


def test_parse_preview_wrong_length_invalid_order():
    order, _ = LangChainPlayer._parse_preview_response(
        '{"team_order": "123"}', 6
    )
    assert order is None


def test_parse_preview_code_fence_stripped():
    raw = '```json\n{"team_order": "312645"}\n```'
    order, _ = LangChainPlayer._parse_preview_response(raw, 6)
    assert order == "312645"


def test_parse_preview_empty_response():
    assert LangChainPlayer._parse_preview_response("", 6) == (None, {})
    assert LangChainPlayer._parse_preview_response(None, 6) == (None, {})


def test_parse_preview_json_failed_digit_fallback():
    # Not valid JSON, but a bare 6-digit permutation should still rescue the
    # order (mirrors the parent _parse_teampreview_response robustness).
    order, seed = LangChainPlayer._parse_preview_response("lead with 421365", 6)
    assert order == "421365"
    assert seed == {"my_plan": "", "opp_win_condition": ""}


def test_parse_preview_missing_plan_keys():
    # team_order present, win-plan keys absent → order parsed, empty seed.
    order, seed = LangChainPlayer._parse_preview_response(
        '{"team_order": "654321"}', 6
    )
    assert order == "654321"
    assert seed["my_plan"] == ""
    assert seed["opp_win_condition"] == ""


# ---------------------------------------------------------------------------
# _render_role_balance_brief
# ---------------------------------------------------------------------------


def test_render_role_balance_aggregates_only():
    m = BattleMemory()
    m.my_role_balance = {"Walls": 2, "Setup Sweepers": 1}
    m.opp_role_balance = {"Wallbreakers": 2}
    brief = LangChainPlayer._render_role_balance_brief(m)
    assert "Your team roles: Walls x2, Setup Sweepers x1" in brief
    assert "Opponent team roles: Wallbreakers x2" in brief


def test_render_role_balance_empty_is_unknown():
    m = BattleMemory()
    brief = LangChainPlayer._render_role_balance_brief(m)
    assert "unknown" in brief


# ---------------------------------------------------------------------------
# refresh_own_team_roles
# ---------------------------------------------------------------------------


def test_refresh_own_team_roles_aggregates_categories():
    # Own team has full info; use real species that appear in the role
    # compendium so the mapping resolves.
    battle = SimpleNamespace(
        team={
            "p1": SimpleNamespace(species="Gholdengo"),
            "p2": SimpleNamespace(species="Ting-Lu"),
        }
    )
    m = BattleMemory()
    refresh_own_team_roles(m, battle)
    # Non-empty balance once at least one species maps to a role.
    assert m.my_role_balance, "expected non-empty role balance"
    assert all(isinstance(v, int) and v > 0 for v in m.my_role_balance.values())


def test_refresh_own_team_roles_unknown_species_empty():
    battle = SimpleNamespace(
        team={"p1": SimpleNamespace(species="DefinitelyNotAPokemon")}
    )
    m = BattleMemory()
    refresh_own_team_roles(m, battle)
    assert m.my_role_balance == {}


def test_refresh_own_team_roles_idempotent():
    battle = SimpleNamespace(
        team={"p1": SimpleNamespace(species="Gholdengo")}
    )
    m = BattleMemory()
    refresh_own_team_roles(m, battle)
    first = dict(m.my_role_balance)
    refresh_own_team_roles(m, battle)
    assert m.my_role_balance == first


# ---------------------------------------------------------------------------
# BattleMemory seed fields
# ---------------------------------------------------------------------------


def test_battle_memory_seed_field_defaults():
    m = BattleMemory()
    assert m.my_role_balance == {}
    assert m.preview_seed_turn == -1  # -1 = no preview seed (fallback)


def test_battle_memory_seed_fields_writable():
    m = BattleMemory()
    m.my_plan = "preview plan"
    m.preview_seed_turn = 0
    assert m.my_plan == "preview plan"
    assert m.preview_seed_turn == 0


# ---------------------------------------------------------------------------
# _log_preview (teampreview decision logging, EXP-050a)
# ---------------------------------------------------------------------------


def test_log_preview_writes_jsonl(tmp_path):
    import json as _json

    from types import SimpleNamespace

    fake_self = SimpleNamespace(log_dir=str(tmp_path))
    battle = SimpleNamespace(battle_tag="battle-gen9ou-1")
    LangChainPlayer._log_preview(
        fake_self,
        battle,
        status="llm_ok",
        order="421365",
        seed={"my_plan": "sweep late", "opp_win_condition": "DD sweep"},
        response='{"team_order":"421365","my_plan":"sweep late"}',
        user_prompt="team data...",
    )
    out = tmp_path / "preview_llm_log.jsonl"
    assert out.exists()
    lines = out.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1
    rec = _json.loads(lines[0])
    assert rec["status"] == "llm_ok"
    assert rec["order"] == "421365"
    assert rec["battle_tag"] == "battle-gen9ou-1"
    assert rec["seed"]["my_plan"] == "sweep late"
    assert "timestamp" in rec


def test_log_preview_appends_multiple_records(tmp_path):
    import json as _json

    from types import SimpleNamespace

    fake_self = SimpleNamespace(log_dir=str(tmp_path))
    battle = SimpleNamespace(battle_tag="battle-gen9ou-1")
    LangChainPlayer._log_preview(fake_self, battle, status="llm_ok", order="123456")
    LangChainPlayer._log_preview(fake_self, battle, status="parse_fail_fallback")
    lines = (tmp_path / "preview_llm_log.jsonl").read_text().strip().split("\n")
    assert len(lines) == 2
    assert _json.loads(lines[1])["status"] == "parse_fail_fallback"


def test_log_preview_noop_without_log_dir(tmp_path):
    from types import SimpleNamespace

    # log_dir unset → no-op, must not raise or write.
    fake_self = SimpleNamespace(log_dir=None)
    LangChainPlayer._log_preview(
        fake_self, SimpleNamespace(battle_tag="b1"), status="llm_ok", order="1"
    )
    assert not (tmp_path / "preview_llm_log.jsonl").exists()
