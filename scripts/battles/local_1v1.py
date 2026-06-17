import asyncio
from tqdm import tqdm
import os
import sys
import argparse
import json
from datetime import datetime, timezone

# Import visual effects early
try:
    from pokechamp.visual_effects import visual, print_banner, print_status

    VISUAL_EFFECTS = True
except ImportError:
    VISUAL_EFFECTS = False

# Add the project root to Python path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, project_root)

from pathlib import Path

# §8: git 상태 메타 수집 헬퍼 (같은 디렉토리). 배틀 로그에 코드 상태 자동 기록.
from _experiment_meta import build_meta, dump_dirty_patch, REPO  # noqa: E402

from common import *
from poke_env.player.team_util import (
    get_llm_player,
    get_metamon_teams,
    load_random_team,
)

parser = argparse.ArgumentParser()

# Player arguments
parser.add_argument("--player_prompt_algo", default="io", choices=prompt_algos)
parser.add_argument(
    "--player_backend",
    type=str,
    default="gemini-2.5-flash",
    choices=[
        # OpenAI models
        "gpt-4o-mini",
        "gpt-4o",
        "gpt-4o-2024-05-13",
        "gpt-4-turbo",
        "gpt-4",
        "gpt-3.5-turbo",
        # Anthropic models
        "anthropic/claude-3.5-sonnet",
        "anthropic/claude-3-opus",
        "anthropic/claude-3-haiku",
        # Google models
        "google/gemini-pro",
        "gemini-2.0-flash",
        "gemini-2.0-pro",
        "gemini-2.0-flash-lite",
        "gemini-2.5-flash",
        "gemini-2.5-pro",
        "gemini-2.5-flash-lite",
        # Meta models
        "meta-llama/llama-3.1-70b-instruct",
        "meta-llama/llama-3.1-8b-instruct",
        # Mistral models
        "mistralai/mistral-7b-instruct",
        "mistralai/mixtral-8x7b-instruct",
        # Cohere models
        "cohere/command-r-plus",
        "cohere/command-r",
        # Perplexity models
        "perplexity/llama-3.1-sonar-small-128k",
        "perplexity/llama-3.1-sonar-large-128k",
        # DeepSeek models
        "deepseek-ai/deepseek-coder-33b-instruct",
        "deepseek-ai/deepseek-llm-67b-chat",
        # Microsoft models
        "microsoft/wizardlm-2-8x22b",
        "microsoft/phi-3-medium-128k-instruct",
        # Ollama models
        "ollama/gpt-oss:20b",
        "ollama/llama3.1:8b",
        "ollama/mistral",
        "ollama/qwen2.5",
        "ollama/gemma3:4b",
        "ollama/gemma4:31b",
        "ollama/gemma4:31b-cloud",
        "ollama/deepseek-v4-flash:cloud",
        "ollama/deepseek-v4-pro:cloud",
        "ollama/nemotron-3-super:cloud",
        "ollama/nemotron-3-ultra:cloud",
        "ollama/minimax-m3:cloud",
        "ollama/qwen3.5:397b-cloud",
        "ollama/glm-5.1:cloud",
        "ollama/kimi-k2.6:cloud",
        # vLLM models
        "vllm/Qwen/Qwen3.6-27B",
        "vllm/google/gemma-4-26B-A4B-it",
        # Featherless AI models
        "featherless/deepseek-ai/DeepSeek-V4-Pro",
        "featherless/deepseek-ai/DeepSeek-V3-0324",
        "featherless/Qwen/Qwen3-235B-A22B",
        # Local models (via OpenRouter)
        "llama",
        "None",
    ],
)
parser.add_argument("--player_name", type=str, default="pokechamp", choices=bot_choices)
parser.add_argument("--player_device", type=int, default=0)

# Opponent arguments
parser.add_argument("--opponent_prompt_algo", default="io", choices=prompt_algos)
parser.add_argument(
    "--opponent_backend",
    type=str,
    default="gemini-2.5-pro",
    choices=[
        # OpenAI models
        "gpt-4o-mini",
        "gpt-4o",
        "gpt-4o-2024-05-13",
        "gpt-4-turbo",
        "gpt-4",
        "gpt-3.5-turbo",
        # Anthropic models
        "anthropic/claude-3.5-sonnet",
        "anthropic/claude-3-opus",
        "anthropic/claude-3-haiku",
        # Google models
        "google/gemini-pro",
        "gemini-2.0-flash",
        "gemini-2.0-pro",
        "gemini-2.0-flash-lite",
        "gemini-2.5-flash",
        "gemini-2.5-pro",
        # Ollama models
        "ollama/gpt-oss:20b",
        "ollama/llama3.1:8b",
        "ollama/mistral",
        "ollama/qwen2.5",
        "ollama/gemma3:4b",
        "ollama/gemma4:31b",
        "ollama/gemma4:31b-cloud",
        "ollama/deepseek-v4-flash:cloud",
        "ollama/deepseek-v4-pro:cloud",
        "ollama/nemotron-3-super:cloud",
        "ollama/nemotron-3-ultra:cloud",
        "ollama/minimax-m3:cloud",
        "ollama/qwen3.5:397b-cloud",
        "ollama/glm-5.1:cloud",
        "ollama/kimi-k2.6:cloud",
        # Meta models
        "meta-llama/llama-3.1-70b-instruct",
        "meta-llama/llama-3.1-8b-instruct",
        # Mistral models
        "mistralai/mistral-7b-instruct",
        "mistralai/mixtral-8x7b-instruct",
        # Cohere models
        "cohere/command-r-plus",
        "cohere/command-r",
        # Perplexity models
        "perplexity/llama-3.1-sonar-small-128k",
        "perplexity/llama-3.1-sonar-large-128k",
        # DeepSeek models
        "deepseek-ai/deepseek-coder-33b-instruct",
        "deepseek-ai/deepseek-llm-67b-chat",
        # Microsoft models
        "microsoft/wizardlm-2-8x22b",
        "microsoft/phi-3-medium-128k-instruct",
        # vLLM models
        "vllm/Qwen/Qwen3.6-27B",
        "vllm/google/gemma-4-26B-A4B-it",
        # Featherless AI models
        "featherless/deepseek-ai/DeepSeek-V4-Pro",
        "featherless/deepseek-ai/DeepSeek-V3-0324",
        "featherless/Qwen/Qwen3-235B-A22B",
        # Local models (via OpenRouter)
        "llama",
        "None",
        "mcp",
    ],
)
parser.add_argument(
    "--opponent_name", type=str, default="pokellmon", choices=bot_choices
)
parser.add_argument("--opponent_device", type=int, default=0)

# Shared arguments
parser.add_argument("--temperature", type=float, default=0.3)
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
parser.add_argument("--log_dir", type=str, default="./battle_log/one_vs_one")
parser.add_argument("--N", type=int, default=25)
parser.add_argument(
    "--seed", type=int, default=None, help="Random seed for reproducibility"
)
parser.add_argument(
    "--player_api_key", type=str, default="", help="API key for the player LLM backend (e.g. Featherless, OpenRouter)"
)
parser.add_argument(
    "--opponent_api_key", type=str, default="", help="API key for the opponent LLM backend"
)

# Experiment infrastructure flags
parser.add_argument(
    "--enable_dynamic_flags",
    action="store_true",
    default=False,
    help="Enable dynamic move flag annotations in prompts",
)
parser.add_argument(
    "--enable_dynamic_calcs",
    action="store_true",
    default=False,
    help="Enable dynamic move calculations in prompts",
)
parser.add_argument(
    "--enable_showdown_oracle",
    action="store_true",
    default=False,
    help="Enable Showdown oracle for move outcome prediction (Node.js required)",
)
parser.add_argument(
    "--enable_llm_lead_selection",
    action="store_true",
    default=False,
    help="Enable LLM-based lead Pokemon selection during team preview",
)

args = parser.parse_args()

# Set random seed if provided
if args.seed is not None:
    import random
    import numpy as np

    random.seed(args.seed)
    np.random.seed(args.seed)
    print(f"Using random seed: {args.seed}")


async def main():
    # Visual banner for local battles
    if VISUAL_EFFECTS:
        print_banner("LOCAL", "fire")
        print_banner("BATTLE", "water")
        print(f"Player: {args.player_name} ({args.player_backend})")
        print(f"Opponent: {args.opponent_name} ({args.opponent_backend})")
        print(f"Format: {args.battle_format}")
        print("=" * 50)
    else:
        print(f"\n=== LOCAL BATTLE ===")
        print(f"Player: {args.player_name} vs Opponent: {args.opponent_name}")
        print(f"Format: {args.battle_format}\n")
    player = get_llm_player(
        args,
        args.player_backend,
        args.player_prompt_algo,
        args.player_name,
        KEY=args.player_api_key,
        device=args.player_device,
        PNUMBER1=PNUMBER1,  # for name uniqueness locally
        battle_format=args.battle_format,
        enable_dynamic_flags=args.enable_dynamic_flags,
        enable_dynamic_calcs=args.enable_dynamic_calcs,
        enable_showdown_oracle=args.enable_showdown_oracle,
        enable_llm_lead_selection=args.enable_llm_lead_selection,
    )

    opponent = get_llm_player(
        args,
        args.opponent_backend,
        args.opponent_prompt_algo,
        args.opponent_name,
        KEY=args.opponent_api_key,
        device=args.opponent_device,
        PNUMBER1=PNUMBER1 + "2",  # for name uniqueness locally
        battle_format=args.battle_format,
    )

    # Try to use metamon teams, fallback to static teams if not available
    player_teamloader = None
    opponent_teamloader = None

    try:
        player_teamloader = get_metamon_teams(args.battle_format, "competitive")
        opponent_teamloader = get_metamon_teams(args.battle_format, "modern_replays")
    except (ValueError, Exception) as e:
        if VISUAL_EFFECTS:
            print_status(
                f"Metamon teams not available for {args.battle_format}: {e}", "warning"
            )
            print_status("Falling back to static teams...", "info")
        else:
            print(f"Metamon teams not available for {args.battle_format}: {e}")
            print(f"Falling back to static teams...")

    if not "random" in args.battle_format:
        if player_teamloader is None or opponent_teamloader is None:
            # Fallback to static teams when metamon teams not available
            player.update_team(load_random_team(id=None, vgc=False))
            opponent.update_team(load_random_team(id=None, vgc=False))
        else:
            # Use metamon teams if available
            player.set_teamloader(player_teamloader)
            opponent.set_teamloader(opponent_teamloader)

            player.update_team(player_teamloader.yield_team())
            opponent.update_team(opponent_teamloader.yield_team())

    # play N battles against the opponent
    N = args.N

    # Per-battle metrics tracking for experiment output
    battle_metrics = []

    pbar = tqdm(total=N)
    for i in range(N):
        # Snapshot token counters before battle
        prompt_tokens_before = (
            getattr(player.llm, "prompt_tokens", 0) if hasattr(player, "llm") else 0
        )
        completion_tokens_before = (
            getattr(player.llm, "completion_tokens", 0) if hasattr(player, "llm") else 0
        )

        x = np.random.randint(0, 100)
        if x > 50:
            await player.battle_against(opponent, n_battles=1)
        else:
            await opponent.battle_against(player, n_battles=1)

        # Collect per-battle metrics
        prompt_tokens_after = (
            getattr(player.llm, "prompt_tokens", 0) if hasattr(player, "llm") else 0
        )
        completion_tokens_after = (
            getattr(player.llm, "completion_tokens", 0) if hasattr(player, "llm") else 0
        )

        # Find the most recently finished battle (직전 종료 배틀).
        # player.battles 는 삽입순을 보존하는 dict 이므로 list[-1] 이 직전 배틀.
        # 이전 코드는 max-turn 배틀을 재사용(reuse)해 won/turns 가 단일
        # 배틀 값으로 고정되는 버그(running-max reuse)가 있었다 — EXP-034 발견.
        battles_list = list(player.battles.values())
        latest_battle = battles_list[-1] if battles_list else None

        won = 1 if (latest_battle and latest_battle.won) else 0
        turns = latest_battle.turn if latest_battle else 0
        llm_calls = getattr(player, "llm_call_count", 0)
        prompt_tokens_delta = prompt_tokens_after - prompt_tokens_before
        completion_tokens_delta = completion_tokens_after - completion_tokens_before

        battle_metrics.append(
            {
                "won": won,
                "turns": turns,
                "prompt_tokens": prompt_tokens_delta,
                "completion_tokens": completion_tokens_delta,
                "llm_calls": llm_calls,
            }
        )

        if not "random" in args.battle_format:
            if "vgc" in args.battle_format:
                player.update_team(load_random_team(id=None, vgc=True))
                opponent.update_team(load_random_team(id=None, vgc=True))
            elif player_teamloader is None or opponent_teamloader is None:
                # Fallback to static teams when metamon teams not available
                player.update_team(load_random_team(id=None, vgc=False))
                opponent.update_team(load_random_team(id=None, vgc=False))
            else:
                # Use metamon teams if available
                player.update_team(player_teamloader.yield_team())
                opponent.update_team(opponent_teamloader.yield_team())
        pbar.set_description(f"{player.win_rate*100:.2f}%")
        pbar.update(1)

    # Print experiment results summary
    n_battles = player.n_finished_battles
    wins = player.n_won_battles
    win_rate = wins / n_battles * 100 if n_battles > 0 else 0
    avg_turns = (
        sum(m["turns"] for m in battle_metrics) / n_battles if n_battles > 0 else 0
    )
    avg_prompt_tokens = (
        sum(m["prompt_tokens"] for m in battle_metrics) / n_battles
        if n_battles > 0
        else 0
    )
    avg_completion_tokens = (
        sum(m["completion_tokens"] for m in battle_metrics) / n_battles
        if n_battles > 0
        else 0
    )
    avg_llm_calls = (
        sum(m["llm_calls"] for m in battle_metrics) / n_battles if n_battles > 0 else 0
    )

    summary_text = (
        f"{'='*50}\n"
        f"EXPERIMENT RESULTS ({n_battles} battles)\n"
        f"{'='*50}\n"
        f"Win Rate:              {win_rate:.1f}% ({wins}/{n_battles})\n"
        f"Avg Turns per Battle:  {avg_turns:.1f}\n"
        f"Avg Prompt Tokens:     {avg_prompt_tokens:.0f}\n"
        f"Avg Completion Tokens: {avg_completion_tokens:.0f}\n"
        f"Avg LLM Calls/Battle:  {avg_llm_calls:.1f}\n"
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
        "script": "local_1v1",
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
            "enable_dynamic_flags": args.enable_dynamic_flags,
            "enable_dynamic_calcs": args.enable_dynamic_calcs,
            "enable_showdown_oracle": args.enable_showdown_oracle,
            "enable_llm_lead_selection": args.enable_llm_lead_selection,
        },
        "summary": {
            "win_rate": round(win_rate, 1),
            "wins": wins,
            "n_battles": n_battles,
            "avg_turns": round(avg_turns, 1),
            "avg_llm_calls": round(avg_llm_calls, 1),
            "avg_prompt_tokens": round(avg_prompt_tokens),
            "avg_completion_tokens": round(avg_completion_tokens),
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
