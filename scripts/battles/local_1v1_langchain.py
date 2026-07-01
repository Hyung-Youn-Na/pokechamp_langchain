"""
LangChain/LangGraph battle script for PokéChamp.

This is the entry point for battles using the new LangGraph agent
workflows.  It mirrors the existing ``local_1v1.py`` but uses
``LangChainPlayer`` for the player side.

**The original ``local_1v1.py`` is not modified.**

Usage::

    uv run python scripts/battles/local_1v1_langchain.py \\
        --player_prompt_algo react \\
        --player_backend gemini-2.5-flash \\
        --opponent_name abyssal

New prompt_algo choices:
    - ``react`` — ReAct agent with battle tool calling
    - ``io_langchain`` — Basic IO via LangGraph
    - ``cot_langchain`` — Chain-of-thought via LangGraph

All existing prompt_algo choices (io, sc, cot, tot, minimax, etc.)
also work — they fall through to the original LLMPlayer code.
"""

import asyncio
from tqdm import tqdm
import os
import sys
import argparse
import time
import json
from datetime import datetime, timezone

# Add the project root to Python path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, project_root)

from pathlib import Path

# §8: git 상태 메타 수집 헬퍼 (같은 디렉토리). 배틀 로그에 코드 상태 자동 기록.
from _experiment_meta import build_meta, dump_dirty_patch, REPO  # noqa: E402

from common import *
from poke_env.ps_client.account_configuration import AccountConfiguration
from poke_env.player.team_util import (
    get_llm_player,
    get_metamon_teams,
    load_fixed_manifest,
    load_random_team,
)
from poke_env.data.replay_template import REPLAY_TEMPLATE

# LangChain-specific prompt algorithms
LANGCHAIN_PROMPT_ALGOS = ["react", "io_langchain", "cot_langchain"]

# Extended prompt algo list: original + new
all_prompt_algos = prompt_algos + LANGCHAIN_PROMPT_ALGOS

parser = argparse.ArgumentParser(
    description="PokéChamp battle with LangChain/LangGraph agent support"
)

# Player arguments
parser.add_argument(
    "--player_prompt_algo",
    default="react",
    choices=all_prompt_algos,
    help="Prompt algorithm. 'react' uses ReAct agent with battle tools.",
)
parser.add_argument(
    "--player_backend",
    type=str,
    default="gemini-2.5-flash",
    help="LLM backend model name (any model supported by the project)",
)
parser.add_argument(
    "--player_name",
    type=str,
    default="pokechamp",
    help="Player bot name",
)
parser.add_argument("--player_device", type=int, default=0)

# Opponent arguments
parser.add_argument(
    "--opponent_prompt_algo",
    default="io",
    choices=prompt_algos,
    help="Opponent always uses the standard LLMPlayer; only standard algos allowed.",
)
parser.add_argument("--opponent_backend", type=str, default="gemini-2.5-pro")
parser.add_argument(
    "--opponent_name", type=str, default="abyssal", choices=bot_choices
)
parser.add_argument("--opponent_device", type=int, default=0)

# Shared arguments
parser.add_argument("--temperature", type=float, default=0.3)
parser.add_argument(
    "--max_tokens",
    type=int,
    default=8192,
    help="Max tokens for LLM generation (default: 8192)",
)
parser.add_argument(
    "--max_tool_calls",
    type=int,
    default=5,
    help="Max tool calls per turn for ReAct agent (default: 5)",
)
parser.add_argument(
    "--battle_format",
    default="gen9ou",
    choices=[
        "gen8randombattle",
        "gen8ou",
        "gen9ou",
        "gen9randombattle",
        "gen9vgc2025regi",
    ],
)
parser.add_argument("--log_dir", type=str, default="./battle_log/langchain")
parser.add_argument("--N", type=int, default=30)
parser.add_argument(
    "--seed", type=int, default=42, help="Random seed for reproducibility"
)
parser.add_argument("--player_api_key", type=str, default="")
parser.add_argument("--opponent_api_key", type=str, default="")

# Experiment flags
parser.add_argument("--enable_dynamic_flags", action="store_true", default=False)
parser.add_argument("--enable_dynamic_calcs", action="store_true", default=False)
parser.add_argument("--enable_showdown_oracle", action="store_true", default=False)
parser.add_argument(
    "--oracle_backend",
    choices=["showdown", "damagecalc", "compare"],
    default="showdown",
    help=(
        "damage backend used when --enable_showdown_oracle is on: "
        "showdown (default) | damagecalc (@smogon/calc) | compare (both, log diff)"
    ),
)
parser.add_argument("--enable_llm_lead_selection", action="store_true", default=False)

# Team composition mode. "fixed" isolates matchups across ablations so a metric
# delta reflects the code change, not team composition noise (see
# docs/architecture/fixed-team-mode.md). Default "random" preserves the existing
# --seed baseline workflow unchanged.
parser.add_argument(
    "--team_mode",
    choices=["random", "fixed"],
    default="random",
    help="random (default, existing baseline) | fixed (manifest-driven deterministic teams)",
)
parser.add_argument(
    "--team_manifest",
    type=str,
    default=None,
    help="Path to fixed-team manifest JSON (required when --team_mode fixed)",
)

args = parser.parse_args()

# Damage backend selection (effective only when --enable_showdown_oracle is on).
# compare mode runs both backends, logs the diff, and returns the showdown result.
from pokechamp.oracle_backend import set_default_backend

set_default_backend(args.oracle_backend)

# Set random seed if provided
if args.seed is not None:
    import random
    import numpy as np

    random.seed(args.seed)
    np.random.seed(args.seed)
    print(f"Using random seed: {args.seed}")


def save_battle_replay(battle, log_dir: str) -> bool:
    """Explicitly save HTML replay for a battle.

    This is a safety net for when ``AbstractBattle._finish_battle()`` did not
    write the replay HTML file — most likely because the synchronous LangGraph
    ``graph.invoke()`` call blocked the event-loop so the replay-saving step
    inside ``_finish_battle()`` did not run. The win/loss result itself is
    still recorded normally via the ``|win|``/``|tie|`` message handler.

    Returns True if a replay was saved (newly created), False otherwise.
    """
    if not log_dir or not battle:
        return False

    folder = log_dir
    filename = f"{battle._player_username} - {battle.battle_tag}.html"
    filepath = os.path.join(folder, filename)

    # Already saved by _finish_battle() — skip
    if os.path.exists(filepath):
        return False

    os.makedirs(folder, exist_ok=True)

    try:
        formatted_replay = REPLAY_TEMPLATE
        formatted_replay = formatted_replay.replace(
            "{BATTLE_TAG}", f"{battle.battle_tag}"
        )
        formatted_replay = formatted_replay.replace(
            "{PLAYER_USERNAME}", f"{battle._player_username}"
        )
        formatted_replay = formatted_replay.replace(
            "{OPPONENT_USERNAME}", f"{battle._opponent_username or 'Opponent'}"
        )
        replay_log = f">{battle.battle_tag}" + "\n".join(
            ["|".join(split_message) for split_message in battle._replay_data]
        )
        formatted_replay = formatted_replay.replace("{REPLAY_LOG}", replay_log)

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(formatted_replay)
        return True
    except Exception as e:
        print(f"[WARN] Failed to save battle replay for {battle.battle_tag}: {e}")
        return False


def _get_langchain_player(
    args,
    backend: str,
    prompt_algo: str,
    name: str,
    KEY: str = "",
    battle_format: str = "gen9ou",
    llm_backend=None,
    device: int = 0,
    PNUMBER1: str = "",
    enable_dynamic_flags: bool = False,
    enable_dynamic_calcs: bool = False,
    enable_showdown_oracle: bool = False,
    enable_llm_lead_selection: bool = False,
    max_tool_calls: int = 5,
):
    """Create a LangChainPlayer for LangGraph-based algorithms."""
    from pokechamp.langchain_backend import LangChainBackend
    from pokechamp.langchain_player import LangChainPlayer

    server_config = None
    USERNAME = name
    PASSWORD = ""

    # Map backend string to LangChain provider spec
    if "gpt" in backend and not backend.startswith("openai/"):
        model_spec = f"openai:{backend}"
    elif "gemini" in backend:
        model_spec = f"google_genai:{backend}"
    elif backend.startswith("ollama/"):
        model_spec = f"ollama:{backend.replace('ollama/', '')}"
    else:
        model_spec = f"openrouter:{backend}"

    # Create LangChainBackend
    lc_backend = LangChainBackend(
        model_spec,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
    )

    player = LangChainPlayer(
        battle_format=battle_format,
        api_key=KEY,
        backend=backend,
        temperature=args.temperature,
        prompt_algo=prompt_algo,
        log_dir=args.log_dir,
        account_configuration=AccountConfiguration(f"{USERNAME}{PNUMBER1}", PASSWORD),
        server_configuration=server_config,
        save_replays=args.log_dir,
        device=device,
        llm_backend=lc_backend,
        enable_dynamic_flags=enable_dynamic_flags,
        enable_dynamic_calcs=enable_dynamic_calcs,
        enable_showdown_oracle=enable_showdown_oracle,
        enable_llm_lead_selection=enable_llm_lead_selection,
        max_tool_calls=max_tool_calls,
    )
    return player


async def main():
    print(f"\n{'='*50}")
    print("LANGCHAIN BATTLE")
    print(f"{'='*50}")
    print(f"Player: {args.player_name} ({args.player_backend})")
    print(f"  Algorithm: {args.player_prompt_algo}")
    if args.player_prompt_algo == "react":
        print(f"  Max Tool Calls: {args.max_tool_calls}")
    print(f"Opponent: {args.opponent_name} ({args.opponent_backend})")
    print(f"  Algorithm: {args.opponent_prompt_algo}")
    print(f"Format: {args.battle_format}")
    print(f"Battles: {args.N}")
    print(f"{'='*50}\n")

    # Create player — use LangChainPlayer for new algos, regular for old
    if args.player_prompt_algo in LANGCHAIN_PROMPT_ALGOS:
        player = _get_langchain_player(
            args,
            args.player_backend,
            args.player_prompt_algo,
            args.player_name,
            KEY=args.player_api_key,
            device=args.player_device,
            PNUMBER1=PNUMBER1,
            battle_format=args.battle_format,
            enable_dynamic_flags=args.enable_dynamic_flags,
            enable_dynamic_calcs=args.enable_dynamic_calcs,
            enable_showdown_oracle=args.enable_showdown_oracle,
            enable_llm_lead_selection=args.enable_llm_lead_selection,
            max_tool_calls=args.max_tool_calls,
        )
    else:
        player = get_llm_player(
            args,
            args.player_backend,
            args.player_prompt_algo,
            args.player_name,
            KEY=args.player_api_key,
            device=args.player_device,
            PNUMBER1=PNUMBER1,
            battle_format=args.battle_format,
            enable_dynamic_flags=args.enable_dynamic_flags,
            enable_dynamic_calcs=args.enable_dynamic_calcs,
            enable_showdown_oracle=args.enable_showdown_oracle,
            enable_llm_lead_selection=args.enable_llm_lead_selection,
        )

    # Create opponent (always uses standard player)
    opponent = get_llm_player(
        args,
        args.opponent_backend,
        args.opponent_prompt_algo,
        args.opponent_name,
        KEY=args.opponent_api_key,
        device=args.opponent_device,
        PNUMBER1=PNUMBER1 + "2",
        battle_format=args.battle_format,
    )

    # Load teams
    player_teamloader = None
    opponent_teamloader = None
    fixed_combo = None  # Fixed-team mode: deterministic matchups (experiment isolation)

    if args.team_mode == "fixed":
        if not args.team_manifest:
            raise SystemExit("--team_mode fixed requires --team_manifest PATH")
        fixed_combo = load_fixed_manifest(args.team_manifest)
        print(
            f"Fixed-team mode: manifest={args.team_manifest} "
            f"hash={fixed_combo.manifest_hash[:24]}..."
        )
    else:
        try:
            player_teamloader = get_metamon_teams(args.battle_format, "competitive")
            opponent_teamloader = get_metamon_teams(args.battle_format, "modern_replays")
        except (ValueError, Exception) as e:
            print(f"Metamon teams not available: {e}")
            print("Falling back to static teams...")

    if "random" not in args.battle_format:
        if fixed_combo is not None:
            player.update_team(fixed_combo.player_at(0))
            opponent.update_team(fixed_combo.opponent_at(0))
            if hasattr(player, "set_own_pack"):
                player.set_own_pack(fixed_combo.player_sets_at(0))
        elif player_teamloader is None or opponent_teamloader is None:
            player.update_team(load_random_team(id=None, vgc=False))
            opponent.update_team(load_random_team(id=None, vgc=False))
        else:
            player.set_teamloader(player_teamloader)
            opponent.set_teamloader(opponent_teamloader)
            player.update_team(player_teamloader.yield_team())
            opponent.update_team(opponent_teamloader.yield_team())

    # Run battles
    N = args.N
    battle_metrics = []

    pbar = tqdm(total=N)
    for i in range(N):
        # Snapshot counters before battle
        prompt_tokens_before = (
            getattr(player.llm, "prompt_tokens", 0) if hasattr(player, "llm") else 0
        )
        completion_tokens_before = (
            getattr(player.llm, "completion_tokens", 0) if hasattr(player, "llm") else 0
        )

        t_start = time.time()

        x = np.random.randint(0, 100)
        if x > 50:
            await player.battle_against(opponent, n_battles=1)
        else:
            await opponent.battle_against(player, n_battles=1)

        elapsed = time.time() - t_start

        # Collect metrics
        prompt_tokens_after = (
            getattr(player.llm, "prompt_tokens", 0) if hasattr(player, "llm") else 0
        )
        completion_tokens_after = (
            getattr(player.llm, "completion_tokens", 0) if hasattr(player, "llm") else 0
        )

        # 직전 종료 배틀 = player.battles 에 가장 최근 추가된 것
        # (Python dict 는 삽입순을 보존하므로 list[-1] 이 직전 배틀).
        # 이전 코드는 max-turn 배틀을 재사용(reuse)해 won/turns 가 단일
        # 배틀 값으로 고정되는 버그(running-max reuse)가 있었다 — EXP-034 발견.
        battles_list = list(player.battles.values())
        latest_battle = battles_list[-1] if battles_list else None

        won = 1 if (latest_battle and latest_battle.won) else 0
        turns = latest_battle.turn if latest_battle else 0

        # Explicitly save HTML replay as a safety net.  The replay-write step
        # inside ``AbstractBattle._finish_battle`` may be skipped when the
        # synchronous LangGraph agent blocks the event-loop.
        for tag, b in player.battles.items():
            if not getattr(b, "_finished", False):
                save_battle_replay(b, args.log_dir)
            else:
                # Even if _finished is True, verify the file exists
                expected = os.path.join(
                    args.log_dir,
                    f"{b._player_username} - {b.battle_tag}.html",
                )
                if not os.path.exists(expected):
                    save_battle_replay(b, args.log_dir)

        battle_metrics.append(
            {
                "won": won,
                "turns": turns,
                "prompt_tokens": prompt_tokens_after - prompt_tokens_before,
                "completion_tokens": completion_tokens_after - completion_tokens_before,
                "llm_calls": getattr(player, "llm_call_count", 0),
                "json_parse_failures": getattr(player, "json_parse_failures", 0),
                "elapsed_seconds": elapsed,
                "player_team_idx": (
                    fixed_combo.player_index(i) if fixed_combo is not None else None
                ),
                "opponent_team_idx": (
                    fixed_combo.opponent_index(i) if fixed_combo is not None else None
                ),
            }
        )

        if "random" not in args.battle_format:
            if fixed_combo is not None:
                # Fixed team: deterministic next-battle team (no global RNG use).
                # Battle 0 was staged before the loop; here we stage battle i+1.
                player.update_team(fixed_combo.player_at(i + 1))
                opponent.update_team(fixed_combo.opponent_at(i + 1))
                if hasattr(player, "set_own_pack"):
                    player.set_own_pack(fixed_combo.player_sets_at(i + 1))
            elif "vgc" in args.battle_format:
                player.update_team(load_random_team(id=None, vgc=True))
                opponent.update_team(load_random_team(id=None, vgc=True))
            elif player_teamloader is None or opponent_teamloader is None:
                player.update_team(load_random_team(id=None, vgc=False))
                opponent.update_team(load_random_team(id=None, vgc=False))
            else:
                player.update_team(player_teamloader.yield_team())
                opponent.update_team(opponent_teamloader.yield_team())

        pbar.set_description(f"{player.win_rate*100:.2f}%")
        pbar.update(1)

    # Print results
    n_battles = player.n_finished_battles
    wins = player.n_won_battles
    win_rate = wins / n_battles * 100 if n_battles > 0 else 0
    avg_turns = (
        sum(m["turns"] for m in battle_metrics) / n_battles if n_battles > 0 else 0
    )
    avg_prompt = (
        sum(m["prompt_tokens"] for m in battle_metrics) / n_battles
        if n_battles > 0
        else 0
    )
    avg_completion = (
        sum(m["completion_tokens"] for m in battle_metrics) / n_battles
        if n_battles > 0
        else 0
    )
    avg_calls = (
        sum(m["llm_calls"] for m in battle_metrics) / n_battles if n_battles > 0 else 0
    )
    total_parse_failures = sum(m["json_parse_failures"] for m in battle_metrics)
    avg_elapsed = (
        sum(m["elapsed_seconds"] for m in battle_metrics) / n_battles
        if n_battles > 0
        else 0
    )

    summary_text = (
        f"{'='*50}\n"
        f"LANGCHAIN EXPERIMENT RESULTS ({n_battles} battles)\n"
        f"{'='*50}\n"
        f"Algorithm:             {args.player_prompt_algo}\n"
        f"Backend:               {args.player_backend}\n"
        f"Win Rate:              {win_rate:.1f}% ({wins}/{n_battles})\n"
        f"Avg Turns per Battle:  {avg_turns:.1f}\n"
        f"Avg LLM Calls/Battle:  {avg_calls:.1f}\n"
        f"JSON Parse Failures:   {total_parse_failures}\n"
        f"Avg Prompt Tokens:     {avg_prompt:.0f}\n"
        f"Avg Completion Tokens: {avg_completion:.0f}\n"
        f"Avg Time per Battle:   {avg_elapsed:.1f}s\n"
        f"Seed:                  {args.seed}\n"
        f"{'='*50}"
    )
    print(f"\n{summary_text}")

    # Save experiment results as JSON for agent analysis.
    # §8: log_dir/ts 를 먼저 확정한 뒤 더티 patch dump → meta 조립 → JSON 쓰기 순으로.
    # 실험은 보통 코드 수정 후 커밋 전(더티 트리)에 돌아, 변경 diff 를 patch 로 남긴다.
    log_dir = args.log_dir
    os.makedirs(log_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    dirty_patch_name = (
        f"experiment_{args.player_prompt_algo}_"
        f"{args.player_backend.replace('/', '_')}_{ts}_dirty.patch"
    )
    dumped = dump_dirty_patch(REPO, Path(log_dir) / dirty_patch_name)
    patch_file = dirty_patch_name if dumped else None

    experiment_log = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "script": "local_1v1_langchain",
        "config": {
            "algorithm": args.player_prompt_algo,
            "backend": args.player_backend,
            "player_name": args.player_name,
            "opponent_name": args.opponent_name,
            "opponent_backend": args.opponent_backend,
            "opponent_algorithm": args.opponent_prompt_algo,
            "battle_format": args.battle_format,
            "n_battles": args.N,
            "seed": args.seed,
            "temperature": args.temperature,
            "max_tokens": args.max_tokens,
            "max_tool_calls": args.max_tool_calls,
            "enable_dynamic_flags": args.enable_dynamic_flags,
            "enable_dynamic_calcs": args.enable_dynamic_calcs,
            "enable_showdown_oracle": args.enable_showdown_oracle,
            "enable_llm_lead_selection": args.enable_llm_lead_selection,
            "team_mode": args.team_mode,
            "team_manifest": args.team_manifest,
            "team_manifest_hash": (
                fixed_combo.manifest_hash if fixed_combo is not None else None
            ),
            "teams": fixed_combo.describe() if fixed_combo is not None else None,
        },
        "summary": {
            "win_rate": round(win_rate, 1),
            "wins": wins,
            "n_battles": n_battles,
            "avg_turns": round(avg_turns, 1),
            "avg_llm_calls": round(avg_calls, 1),
            "json_parse_failures": total_parse_failures,
            "avg_prompt_tokens": round(avg_prompt),
            "avg_completion_tokens": round(avg_completion),
            "avg_time_per_battle_seconds": round(avg_elapsed, 1),
            "total_time_seconds": round(sum(m["elapsed_seconds"] for m in battle_metrics), 1),
        },
        "battles": battle_metrics,
        "meta": build_meta(REPO, patch_file),
    }

    log_path = os.path.join(
        log_dir,
        f"experiment_{args.player_prompt_algo}_{args.player_backend.replace('/', '_')}_{ts}.json",
    )
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(experiment_log, f, indent=2, ensure_ascii=False)
    print(f"Experiment log saved to: {log_path}")
    if patch_file:
        print(f"Dirty code patch saved to: {os.path.join(log_dir, patch_file)}")


if __name__ == "__main__":
    asyncio.run(main())
