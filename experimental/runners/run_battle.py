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
    --log_dir PATH             Base directory for experiment logs (default: .temp/experiments)
"""
import argparse
import asyncio
import glob
import json
import os
import shutil
import sys
import threading
from datetime import datetime

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
parser.add_argument("--log_dir", type=str, default=None, help="Base directory for experiment logs (default: <project_root>/.temp/experiments)")
args = parser.parse_args()


class TeeStream:
    """Tee stdout/stderr to both console and a log file."""

    def __init__(self, original, log_path):
        self._original = original
        self._log_file = open(log_path, "a", encoding="utf-8")
        self._lock = threading.Lock()

    def write(self, text):
        with self._lock:
            self._original.write(text)
            self._log_file.write(text)
            self._log_file.flush()

    def flush(self):
        self._original.flush()
        self._log_file.flush()

    def close(self):
        self._log_file.close()


class ExperimentLogger:
    """Manages per-experiment logging directory and file capture."""

    def __init__(self, experiment_name, log_base_dir=None):
        if log_base_dir is None:
            log_base_dir = os.path.join(project_root, ".temp", "experiments")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.experiment_dir = os.path.join(log_base_dir, f"{experiment_name}_{timestamp}")
        self.replay_dir = os.path.join(self.experiment_dir, "battle_replays")
        os.makedirs(self.replay_dir, exist_ok=True)

        self._config_path = os.path.join(self.experiment_dir, "experiment_config.json")
        self._metrics_path = os.path.join(self.experiment_dir, "metrics.json")
        self._stdout_path = os.path.join(self.experiment_dir, "stdout.log")
        self._stderr_path = os.path.join(self.experiment_dir, "stderr.log")

        self._original_stdout = sys.stdout
        self._original_stderr = sys.stderr

    def start(self):
        """Redirect stdout/stderr to tee into log files."""
        sys.stdout = TeeStream(self._original_stdout, self._stdout_path)
        sys.stderr = TeeStream(self._original_stderr, self._stderr_path)

    def save_config(self, config: dict):
        """Save experiment configuration."""
        config["experiment_dir"] = self.experiment_dir
        config["started_at"] = datetime.now().isoformat()
        with open(self._config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

    def save_metrics(self, metrics: dict):
        """Save final experiment metrics."""
        metrics["finished_at"] = datetime.now().isoformat()
        with open(self._metrics_path, "w", encoding="utf-8") as f:
            json.dump(metrics, f, indent=2, ensure_ascii=False)

    def copy_replays(self, source_dir: str):
        """Copy HTML battle replays into the experiment replay directory."""
        if not os.path.isdir(source_dir):
            return
        for html_file in glob.glob(os.path.join(source_dir, "*.html")):
            shutil.copy2(html_file, self.replay_dir)

    def finish(self):
        """Restore original stdout/stderr."""
        if isinstance(sys.stdout, TeeStream):
            sys.stdout.close()
            sys.stdout = self._original_stdout
        if isinstance(sys.stderr, TeeStream):
            sys.stderr.close()
            sys.stderr = self._original_stderr

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

    logger = ExperimentLogger(args.experiment_name, args.log_dir)
    logger.start()

    print("=" * 60)
    print("  Experimental Battle: LangChain + LangGraph + Langfuse")
    print("=" * 60)
    print(f"  Mode:       {'LangGraph Pipeline' if args.use_graph else 'LangChain Direct'}")
    print(f"  Opponent:   AbyssalPlayer (heuristic)")
    print(f"  Format:     {args.battle_format}")
    print(f"  Battles:    {args.N}")
    print(f"  Temperature:{args.temperature}")
    print(f"  Langfuse:   {'OFF' if args.langfuse_off else 'ON'}")
    print(f"  Log dir:    {logger.experiment_dir}")
    print("=" * 60)

    logger.save_config({
        "experiment_name": args.experiment_name,
        "mode": "LangGraph Pipeline" if args.use_graph else "LangChain Direct",
        "battle_format": args.battle_format,
        "n_battles": args.N,
        "temperature": args.temperature,
        "langfuse_enabled": not args.langfuse_off,
        "seed": args.seed,
    })

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

    avg_latency = None
    p50_latency = None
    if backend._latencies:
        import statistics
        avg_latency = statistics.mean(backend._latencies)
        p50_latency = statistics.median(backend._latencies)
        print(f"Avg turn latency: {avg_latency:.2f}s (p50={p50_latency:.2f}s)")

    if not args.langfuse_off:
        try:
            from experimental.tracing.langfuse_setup import get_langfuse_client
            client = get_langfuse_client()
            client.flush()
            print("[Langfuse] Flush complete.")
        except Exception as e:
            print(f"[Langfuse] Flush failed: {e}")

    logger.save_metrics({
        "win_rate": player.win_rate,
        "n_wins": player.n_won_battles,
        "n_losses": args.N - player.n_won_battles,
        "n_battles": args.N,
        "completion_tokens": backend.completion_tokens,
        "prompt_tokens": backend.prompt_tokens,
        "avg_turn_latency": avg_latency,
        "p50_turn_latency": p50_latency,
        "n_turn_latencies": len(backend._latencies) if backend._latencies else 0,
    })

    battle_log_dir = "./battle_log/experimental"
    logger.copy_replays(battle_log_dir)

    print(f"\nLogs saved to: {logger.experiment_dir}")
    logger.finish()


if __name__ == "__main__":
    asyncio.run(main())
