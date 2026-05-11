"""Experimental battle runner using LangChain + LangGraph + Langfuse.

Usage:
    # Simple LangChain mode (default)
    uv run python experimental/runners/run_battle.py

    # LangGraph multi-node decision pipeline
    uv run python experimental/runners/run_battle.py --use_graph

    # Options
    --N 10                     Number of battles
    --battle_format gen9ou     Battle format
    --temperature 0.3          LLM temperature
    --use_graph                Enable LangGraph pipeline
    --langfuse_off             Disable Langfuse tracing
"""
import argparse
import asyncio
import os
import sys

from dotenv import load_dotenv
from tqdm import tqdm

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, project_root)

import numpy as np

from common import PNUMBER1
from poke_env.player.team_util import get_llm_player, get_metamon_teams, load_random_team

parser = argparse.ArgumentParser(description="Experimental LangChain battle runner")
parser.add_argument("--use_graph", action="store_true", help="Use LangGraph decision pipeline")
parser.add_argument("--langfuse_off", action="store_true", help="Disable Langfuse tracing")
parser.add_argument("--experiment_name", type=str, default="langchain_exp", help="Experiment name for Langfuse traces")
parser.add_argument("--N", type=int, default=10, help="Number of battles")
parser.add_argument("--battle_format", default="gen9ou", choices=["gen9ou", "gen9randombattle"])
parser.add_argument("--temperature", type=float, default=0.3, help="LLM temperature")
parser.add_argument("--seed", type=int, default=None, help="Random seed")
args = parser.parse_args()

if args.seed is not None:
    import random

    random.seed(args.seed)
    np.random.seed(args.seed)
    print(f"Random seed: {args.seed}")


class _Args:
    """Minimal args namespace compatible with get_llm_player()."""

    def __init__(self, temperature, log_dir):
        self.temperature = temperature
        self.log_dir = log_dir


async def main():
    load_dotenv(os.path.join(os.path.dirname(__file__), "../config/.env"))

    print("=" * 60)
    print("  Experimental Battle: LangChain + LangGraph + Langfuse")
    print("=" * 60)
    print(f"  Mode:       {'LangGraph Pipeline' if args.use_graph else 'LangChain Direct'}")
    print(f"  Opponent:   AbyssalPlayer (heuristic)")
    print(f"  Format:     {args.battle_format}")
    print(f"  Battles:    {args.N}")
    print(f"  Temperature:{args.temperature}")
    print(f"  Langfuse:   {'OFF' if args.langfuse_off else 'ON'}")
    print("=" * 60)

    langfuse_handler = None
    if not args.langfuse_off:
        try:
            from experimental.tracing.langfuse_setup import init_langfuse, create_callback_handler

            init_langfuse()
            langfuse_handler = create_callback_handler(trace_id=f"{args.experiment_name}_init")
        except Exception as e:
            print(f"[Langfuse] Initialization failed: {e}")
            print("[Langfuse] Continuing without tracing...")
            args.langfuse_off = True

    from experimental.backends.langchain_vllm_backend import LangChainVLLMBackend

    backend = LangChainVLLMBackend(
        use_graph=args.use_graph,
        langfuse_handler=langfuse_handler,
    )

    os.makedirs("./battle_log/experimental", exist_ok=True)
    runner_args = _Args(temperature=args.temperature, log_dir="./battle_log/experimental")

    player = get_llm_player(
        runner_args,
        backend="vllm/Qwen/Qwen3.6-27B",
        prompt_algo="io",
        name="pokechamp",
        llm_backend=backend,
        device=0,
        PNUMBER1=PNUMBER1,
        battle_format=args.battle_format,
    )

    opponent = get_llm_player(
        runner_args,
        backend="vllm/Qwen/Qwen3.6-27B",
        prompt_algo="io",
        name="abyssal",
        device=0,
        PNUMBER1=PNUMBER1 + "2",
        battle_format=args.battle_format,
    )

    player_teamloader = None
    opponent_teamloader = None
    try:
        player_teamloader = get_metamon_teams(args.battle_format, "competitive")
        opponent_teamloader = get_metamon_teams(args.battle_format, "modern_replays")
    except Exception as e:
        print(f"Metamon teams unavailable ({e}), using static teams")

    if "random" not in args.battle_format:
        if player_teamloader and opponent_teamloader:
            player.set_teamloader(player_teamloader)
            opponent.set_teamloader(opponent_teamloader)
            player.update_team(player_teamloader.yield_team())
            opponent.update_team(opponent_teamloader.yield_team())
        else:
            player.update_team(load_random_team(id=None, vgc=False))
            opponent.update_team(load_random_team(id=None, vgc=False))

    pbar = tqdm(total=args.N, desc="Battles")
    for i in range(args.N):
        if not args.langfuse_off:
            backend.set_battle_context(
                battle_num=i + 1,
                experiment_name=args.experiment_name,
                metadata={"battle_format": args.battle_format, "opponent": "abyssal"},
            )

        prev_wins = player.n_won_battles

        if np.random.randint(0, 100) > 50:
            await player.battle_against(opponent, n_battles=1)
        else:
            await opponent.battle_against(player, n_battles=1)

        won = player.n_won_battles > prev_wins

        if not args.langfuse_off and backend._session_id:
            try:
                from experimental.tracing.langfuse_setup import get_langfuse_client
                client = get_langfuse_client()
                page = client.api.trace.list(session_id=backend._session_id, limit=100)
                traces = page.data if hasattr(page, "data") else page
                for t in traces:
                    client.score(
                        trace_id=t.id,
                        name="battle_outcome",
                        value=1 if won else 0,
                    )
            except Exception as e:
                print(f"[Langfuse] Score failed: {e}")

        if "random" not in args.battle_format:
            if player_teamloader and opponent_teamloader:
                player.update_team(player_teamloader.yield_team())
                opponent.update_team(opponent_teamloader.yield_team())
            else:
                player.update_team(load_random_team(id=None, vgc=False))
                opponent.update_team(load_random_team(id=None, vgc=False))

        pbar.set_description(f"Win {player.win_rate * 100:.1f}%")
        pbar.update(1)

    print(f"\nFinal winrate: {player.win_rate * 100:.2f}%")
    print(f"Completion tokens: {backend.completion_tokens}")
    print(f"Prompt tokens: {backend.prompt_tokens}")
    if backend._latencies:
        import statistics
        print(f"Avg turn latency: {statistics.mean(backend._latencies):.2f}s (p50={statistics.median(backend._latencies):.2f}s)")

    if not args.langfuse_off:
        try:
            from experimental.tracing.langfuse_setup import get_langfuse_client
            client = get_langfuse_client()
            client.flush()
            print("[Langfuse] Flush complete.")
        except Exception as e:
            print(f"[Langfuse] Flush failed: {e}")


if __name__ == "__main__":
    asyncio.run(main())
