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

# Add the project root to Python path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, project_root)

from common import *
from poke_env.ps_client.account_configuration import AccountConfiguration
from poke_env.player.team_util import (
    get_llm_player,
    get_metamon_teams,
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
parser.add_argument("--opponent_prompt_algo", default="io", choices=all_prompt_algos)
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
parser.add_argument("--enable_llm_lead_selection", action="store_true", default=False)

args = parser.parse_args()

# Set random seed if provided
if args.seed is not None:
    import random
    import numpy as np

    random.seed(args.seed)
    np.random.seed(args.seed)
    print(f"Using random seed: {args.seed}")


def save_battle_replay(battle, log_dir: str) -> bool:
    """Explicitly save HTML replay for a battle.

    This is a safety net in case ``AbstractBattle._finish_battle()`` was not
    called or failed silently (e.g. due to a blocked event-loop from a
    synchronous LangGraph ``graph.invoke()`` call).

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
    )
    return player


async def main():
    print(f"\n{'='*50}")
    print("LANGCHAIN BATTLE")
    print(f"{'='*50}")
    print(f"Player: {args.player_name} ({args.player_backend})")
    print(f"  Algorithm: {args.player_prompt_algo}")
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

    try:
        player_teamloader = get_metamon_teams(args.battle_format, "competitive")
        opponent_teamloader = get_metamon_teams(args.battle_format, "modern_replays")
    except (ValueError, Exception) as e:
        print(f"Metamon teams not available: {e}")
        print("Falling back to static teams...")

    if "random" not in args.battle_format:
        if player_teamloader is None or opponent_teamloader is None:
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

        latest_battle = None
        latest_turn = 0
        for tag, b in player.battles.items():
            if b.turn > latest_turn:
                latest_turn = b.turn
                latest_battle = b

        won = 1 if (latest_battle and latest_battle.won) else 0
        turns = latest_battle.turn if latest_battle else 0

        # Explicitly save HTML replay as a safety net.  The standard
        # mechanism (``AbstractBattle._finish_battle``) may fail to fire
        # when the synchronous LangGraph agent blocks the event-loop.
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
            }
        )

        if "random" not in args.battle_format:
            if "vgc" in args.battle_format:
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

    print(f"\n{'='*50}")
    print(f"LANGCHAIN EXPERIMENT RESULTS ({n_battles} battles)")
    print(f"{'='*50}")
    print(f"Algorithm:             {args.player_prompt_algo}")
    print(f"Backend:               {args.player_backend}")
    print(f"Win Rate:              {win_rate:.1f}% ({wins}/{n_battles})")
    print(f"Avg Turns per Battle:  {avg_turns:.1f}")
    print(f"Avg LLM Calls/Battle:  {avg_calls:.1f}")
    print(f"JSON Parse Failures:   {total_parse_failures}")
    print(f"Avg Prompt Tokens:     {avg_prompt:.0f}")
    print(f"Avg Completion Tokens: {avg_completion:.0f}")
    print(f"Avg Time per Battle:   {avg_elapsed:.1f}s")
    print(f"Seed:                  {args.seed}")
    print(f"{'='*50}")


if __name__ == "__main__":
    asyncio.run(main())
