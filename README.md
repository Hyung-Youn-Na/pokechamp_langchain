```
██████╗  ██████╗ ██╗  ██╗███████╗ ██████╗██╗  ██╗ █████╗ ███╗   ███╗██████╗ 
██╔══██╗██╔═══██╗██║ ██╔╝██╔════╝██╔════╝██║  ██║██╔══██╗████╗ ████║██╔══██╗
██████╔╝██║   ██║█████╔╝ █████╗  ██║     ███████║███████║██╔████╔██║██████╔╝
██╔═══╝ ██║   ██║██╔═██╗ ██╔══╝  ██║     ██╔══██║██╔══██║██║╚██╔╝██║██╔═══╝ 
██║     ╚██████╔╝██║  ██╗███████╗╚██████╗██║  ██║██║  ██║██║ ╚═╝ ██║██║     
╚═╝      ╚═════╝ ╚═╝  ╚═╝╚══════╝ ╚═════╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝     ╚═╝╚═╝     
```
# Pokémon Champion
<!-- project badges -->
[![Paper (ICML '25)](https://img.shields.io/badge/Paper-ICML-blue?style=flat)](https://openreview.net/pdf?id=SnZ7SKykHh)
[![Dataset on HuggingFace](https://img.shields.io/badge/Dataset-HuggingFace-brightgreen?logo=huggingface&logoColor=white&style=flat)](https://huggingface.co/datasets/milkkarten/pokechamp)
[![Source Code](https://img.shields.io/badge/Code-GitHub-black?logo=github&logoColor=white&style=flat)](https://github.com/sethkarten/pokechamp)

This is an experimental fork of **PokéChamp** (the ICML '25 paper *"PokéChamp: an Expert-level Minimax Language Agent"*), exploring how to improve the LLM battle agent with **LangChain** and **LangGraph**.

> **TL;DR** — 이 저장소는 원본 PokéChamp의 코드베이스 위에 LangChain/LangGraph 기반 에이전트 워크플로를 얹어 PokéChamp를 개선하려는 시도를 담고 있습니다. 기존 알고리즘(`io`, `minimax`, …)은 런타임에 `LangChainPlayer` → `LLMPlayer.choose_move()` 로 위임되어 원래 동작을 유지합니다. 단, `llm_player.py`와 `local_1v1.py`에는 실험 추적·오라클·리드 선택 등 **fork 고유 기능이 추가**되었으므로 원본 대비 소스가 수정되어 있습니다. 새 에이전트(`react`, `io_langchain`, `cot_langchain`)는 별도 모듈로 격리되어 있습니다.

### 이 fork에서 새로 시도하는 것

- **ReAct 에이전트 (`react`)**: LangGraph로 구성한 agent loop에서 LLM이 직접 **전투 분석 도구**(데미지 계산, 타입 상성, 매치업 분석, 턴 시뮬레이션 등)를 호출해 정량적 데이터를 모은 뒤 최적의 수를 선택합니다.
- **LangChain/LangGraph 백엔드 통합**: 기존 OpenAI/Gemini/Ollama 백엔드를 LangChain 추상 위에서 재사용 (`LangChainPlayer`, `LangChainBackend`).
- **새 프롬프트 알고리즘**: `react`, `io_langchain`, `cot_langchain` — 기존 알고리즘(`io`, `minimax`, …)은 변경 없이 그대로 동작합니다.
- **반복적 실험 파이프라인**: `.temp/experiments/` 기반의 EXP-NNN 실험 추적 + 코드/파라미터 자동 기록(`docs/analysis/`, `tools/battle_viewer.py`). 자세한 내용은 [`experiment-context.md`](experiment-context.md).

<div align="center">
  <img src="./resource/method.png" alt="PokemonChamp">
</div>

## Architecture

The codebase is organized into several clean modules:

```
pokechamp/
├── pokechamp/           # [CORE] LLM player implementation
│   ├── llm_player.py    # Core LLM player class (fork adds lead-selection / oracle / experiment hooks)
│   ├── minimax_optimizer.py # Minimax search caching/hashing over LocalSim
│   ├── data_cache.py    # Cached move/ability/item/pokédex data
│   ├── prompt_eval.py   # LLM leaf-node evaluation for minimax
│   ├── battle_state_mapper.py # Battle-state translation for agents
│   ├── showdown_oracle.py # Showdown oracle (ground-truth peek)
│   ├── timeout_llm_player.py # Time-budgeted LLM player wrapper
│   ├── langchain_player.py   # [NEW] LangGraph player (delegates legacy algos to LLMPlayer)
│   ├── langchain_backend.py  # [NEW] LangChain chat-model backend adapter
│   ├── agents/         # [NEW] LangGraph agent workflows
│   │   ├── react_agent.py     # ReAct agent (build_context → tool_agent ⇄ tool_execution → strategy_synthesis → parse_action)
│   │   ├── io_agent.py        # IO via LangGraph (baseline)
│   │   ├── cot_agent.py       # Chain-of-thought via LangGraph
│   │   ├── common.py          # Shared helpers (state build, action↔order, JSON parse)
│   │   ├── llm_logging.py     # LLM reasoning logging callback
│   │   └── state.py           # BattleAgentState / messaging
│   ├── battle_memory.py # [NEW] Turn-level battle memory (EXP-049a, design D)
│   ├── battle_tools.py # [NEW] Battle analysis tools (damage, type, matchup, simulate…)
│   ├── mcp_player.py    # MCP protocol support
│   ├── llm_vgc_player.py # VGC doubles support
│   ├── gpt_player.py    # OpenAI GPT backend (native)
│   ├── llama_player.py  # Meta LLaMA backend (native)
│   ├── gemini_player.py # Google Gemini backend (native)
│   ├── openrouter_player.py # OpenRouter API backend
│   ├── ollama_player.py # Ollama local-model backend
│   ├── vllm_player.py   # vLLM local-model backend
│   ├── featherless_player.py # Featherless API backend
│   ├── prompts.py       # Battle prompts & algorithms
│   ├── dynamic_move.py  # Dynamic move type/power/priority calculations
│   └── translate.py     # Battle translation utilities
├── bayesian/            # [PREDICT] Bayesian prediction system
│   ├── pokemon_predictor.py    # Pokemon team predictions
│   ├── team_predictor.py       # Bayesian team predictor
│   └── live_battle_predictor.py # Live battle predictions
├── scripts/             # [SCRIPTS] Battle execution scripts
│   ├── battles/         # Battle runners (local_1v1.py, local_1v1_langchain.py)
│   ├── evaluation/      # Evaluation tools
│   └── training/        # Dataset processing
├── poke_env/            # [ENGINE] Core battle engine (LLM-independent)
├── bots/                # [BOTS] Custom bot implementations
└── tests/               # [TESTS] Comprehensive test suite
```

**Key Benefits:**
- **Clean separation**: Core battle engine (`poke_env`) is independent of LLM code
- **Modular design**: Each component has clear responsibilities
- **Extensible**: Easy to add new LLM backends or battle algorithms
- **Dynamic Moves**: Real-time move type/power/priority resolution based on battle state (weather, tera type, items, status conditions)
- **Testable**: Comprehensive test coverage for the core engine, move normalization, and Bayesian prediction; the LangChain/LangGraph agent layer (`react` / `LangChainPlayer` / `battle_tools`) is not yet covered by automated tests

## Quick Start

### Requirements

```sh
# Install uv (modern Python package manager)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone and setup (this LangChain/LangGraph fork)
git clone https://github.com/Hyung-Youn-Na/pokechamp_langchain.git
cd pokechamp_langchain
uv sync                          # base dependencies
uv sync --extra langchain        # NEW: LangChain/LangGraph deps for the react/agent workflows
```

### Battle Any Agent Against Any Agent
```sh
# Basic battle
uv run python local_1v1.py --player_name pokechamp --opponent_name abyssal

# With dynamic move calculations (shows flag annotations + type/power/priority calcs in prompts)
uv run python local_1v1.py --player_name pokechamp --opponent_name abyssal --enable_dynamic_flags --enable_dynamic_calcs

# Try MCP integration
uv run python local_1v1.py --player_prompt_algo mcp --player_backend gemini-2.5-flash --opponent_name abyssal

# VGC double battles
uv run python run_with_timeout_vgc.py --continuous --max-concurrent 2
```

### NEW: LangChain / LangGraph ReAct Agent

The entry point `scripts/battles/local_1v1_langchain.py` runs the new LangGraph
workflows. Legacy algorithms fall through to the existing `LLMPlayer` at runtime;
`local_1v1.py` itself carries fork-specific experiment-tracking additions (per-battle
metrics, oracle flag, lead selection).

```sh
# ReAct agent that calls battle analysis tools (damage calc, type chart, matchup, …)
uv run python scripts/battles/local_1v1_langchain.py \
    --player_prompt_algo react \
    --player_backend gemini-2.5-flash \
    --opponent_name abyssal

# LangGraph baselines
uv run python scripts/battles/local_1v1_langchain.py --player_prompt_algo io_langchain  --player_backend gemini-2.5-flash --opponent_name abyssal
uv run python scripts/battles/local_1v1_langchain.py --player_prompt_algo cot_langchain --player_backend gemini-2.5-flash --opponent_name abyssal
```

New `--player_prompt_algo` choices: `react`, `io_langchain`, `cot_langchain`.
All existing choices (`io`, `sc`, `cot`, `tot`, `minimax`, …) also work.

### Evaluation
```sh
uv run python scripts/evaluation/evaluate_gen9ou.py
```

## Battle Configuration

### Local Pokémon Showdown Server Setup

1. Install Node.js v10+
2. Set up the battle server:

```sh
git clone git@github.com:jakegrigsby/pokemon-showdown.git
cd pokemon-showdown
npm install
cp config/config-example.js config/config.js
node pokemon-showdown start --no-security
```

3. Open http://localhost:8000/ in your browser

## Available Bots

### Built-in Bots
- `pokechamp` - Main PokéChamp LLM agent (`LLMPlayer`). Uses the minimax algorithm when run with `--player_prompt_algo minimax`; defaults to `io` (or `react` under `local_1v1_langchain.py`)
- `pokellmon` - LLM-based agent with various prompt algorithms
- `abyssal` - Abyssal Bot baseline
- `max_power` - Maximum base power move selection
- `one_step` - One-step lookahead agent
- `random` - Random move selection
- `vgc` - VGC-specialized agent for double battles

### Custom Bots
- `starter_kit` - Example LLM-based bot for creating custom implementations

### Prompt Algorithms
Available prompt algorithms for LLM-based bots:
- `io` - Input/Output prompting (default)
- `sc` - Self-consistency prompting
- `cot` - Chain-of-thought prompting
- `tot` - Tree-of-thought prompting
- `minimax` - Minimax algorithm with LLM evaluation
- `heuristic` - Heuristic-based decisions
- `max_power` - Maximum base power move selection
- `one_step` - One-step lookahead
- `random` - Random move selection
- `mcp` - Model Context Protocol integration
- `react` - **[NEW]** ReAct agent via LangGraph with battle tool calling (use `local_1v1_langchain.py`)
- `io_langchain` / `cot_langchain` - **[NEW]** IO / chain-of-thought reimplemented on LangGraph

### Creating Custom Bots

1. Create `bots/my_bot_bot.py`
2. Inherit from `LLMPlayer`:

```python
from pokechamp.llm_player import LLMPlayer

class MyCustomBot(LLMPlayer):
    def choose_move(self, battle):
        # Implement your strategy
        return self.choose_random_move(battle)
```

3. Your bot automatically becomes available in battle scripts

## LLM Backend Support

The system supports multiple LLM backends **natively** (OpenAI, Gemini, Ollama, vLLM, Featherless) plus hundreds more routed **through OpenRouter**. Which env var a backend needs is decided by the model spec you pass to `--player_backend` (see dispatch logic in `pokechamp/llm_player.py`):

### Native backends (no `provider/` prefix — set the provider's own key)

- **OpenAI**: bare `gpt-*` names → `GPTPlayer` → `OPENAI_API_KEY`
  - `gpt-4o`, `gpt-4o-mini`, `gpt-4-turbo`, `gpt-4`, `gpt-3.5-turbo`
- **Google Gemini**: any spec containing `gemini` → `GeminiPlayer` → `GEMINI_API_KEY`
  - `gemini-2.0-flash`, `gemini-2.0-pro`, `gemini-2.5-flash`, `gemini-2.5-pro`
  - *(Google note)* the `google/` prefix is ignored for Gemini models — `google/gemini-pro` still matches the native branch (substring `"gemini"`) and uses `GEMINI_API_KEY`, not OpenRouter.
- **Local via Ollama**: `ollama/*` → `OllamaPlayer` → `OLLAMA_API_KEY` for Ollama Cloud (no key for a local daemon)
  - `ollama/llama3.1:8b`, `ollama/mistral`, `ollama/qwen2.5`, `ollama/gemma3:4b`, `ollama/gpt-oss:20b`, `ollama/glm-5.1:cloud`
- **Other native**: `vllm/*` (vLLM server) and `featherless/*` (`FEATHERLESS_API_KEY`)

### OpenRouter backends (`provider/` slug — set `OPENROUTER_API_KEY`)

A `provider/`-prefixed slug (except Gemini, see above) routes to `OpenRouterPlayer`:

- **OpenAI via OpenRouter**: `openai/gpt-4o`, …
- **Anthropic**: `anthropic/claude-3.5-sonnet`, `anthropic/claude-3-opus`, `anthropic/claude-3-haiku` — *Anthropic has **no native backend**; it is reachable only through OpenRouter.*
- **Meta**: `meta-llama/llama-3.1-70b-instruct`, `meta-llama/llama-3.1-8b-instruct`
- **Mistral**: `mistralai/mistral-7b-instruct`, `mistralai/mixtral-8x7b-instruct`
- **Cohere**: `cohere/command-r-plus`, `cohere/command-r`
- **Perplexity**: `perplexity/llama-3.1-sonar-small-128k`, `perplexity/llama-3.1-sonar-large-128k`
- **DeepSeek**: `deepseek-ai/deepseek-coder-33b-instruct`, `deepseek-ai/deepseek-llm-67b-chat`
- **Microsoft**: `microsoft/wizardlm-2-8x22b`, `microsoft/phi-3-medium-128k-instruct`

> **Note:** these model IDs are OpenRouter slugs and are subject to provider availability/renaming (e.g. Microsoft WizardLM-2 was withdrawn, Perplexity `sonar` slugs were renamed). Verify current IDs at [openrouter.ai/models](https://openrouter.ai/models).

### Setup

Set the env var matching your backend (see `.env.example` for the full list):

- `OPENROUTER_API_KEY` — for `provider/` slugs (`anthropic/`, `meta/`, `mistral/`, …). Get a key from [OpenRouter](https://openrouter.ai/keys).
- `OPENAI_API_KEY` — for bare `gpt-*` models.
- `GEMINI_API_KEY` — for `gemini-*` models (incl. `google/gemini-*`).
- `OLLAMA_API_KEY` — for Ollama Cloud (`ollama/...`); omit for a local daemon.
- `FEATHERLESS_API_KEY` — for `featherless/*` models.

Example: `export OPENROUTER_API_KEY='your-api-key-here'`

Then use any supported model:

```sh
# Claude (via OpenRouter) vs Gemini (native) battle.
# Note: the player needs OPENROUTER_API_KEY; the opponent needs GEMINI_API_KEY.
uv run python local_1v1.py --player_backend anthropic/claude-3-haiku --opponent_backend gemini-2.5-flash

# Test different models
uv run python local_1v1.py --player_backend mistralai/mixtral-8x7b-instruct --opponent_backend gpt-4o

# Local models (no API key needed for a local daemon)
uv run python local_1v1.py --player_backend ollama/llama3.1:8b --opponent_name abyssal
```

### LangChain unified backend (NEW)

This fork adds `LangChainBackend` (`pokechamp/langchain_backend.py`), which supports **50+ LLM providers** through LangChain's `init_chat_model`. It is used by the new `react` / `io_langchain` / `cot_langchain` prompt algorithms via `scripts/battles/local_1v1_langchain.py`.

Unlike the legacy backends above (which take `provider/model` **slash** specs like `ollama/llama3.1:8b`), the LangChain backend takes **colon** specs of the form `provider:model`:

- `openai:gpt-4o`
- `google_genai:gemini-2.5-flash`
- `ollama:glm-5.1:cloud` *(Ollama Cloud — reads `OLLAMA_API_KEY`, no `langchain-ollama` dep needed)*
- `openrouter:anthropic/claude-sonnet-4-5`

Requires the optional deps:

```sh
uv sync --extra langchain
```

Example:

```sh
uv run python scripts/battles/local_1v1_langchain.py \
    --player_prompt_algo react \
    --player_backend openai:gpt-4o \
    --opponent_name abyssal
```

## Bayesian Prediction System

The codebase includes a sophisticated Bayesian predictor for real-time battle analysis:

### Features
- **Team Prediction**: Predict unrevealed opponent Pokemon
- **Move Prediction**: Predict opponent moves and items
- **Stats Prediction**: Predict EVs, natures, and hidden stats
- **Live Integration**: Real-time predictions during battles

### Usage
```python
from bayesian.pokemon_predictor import PokemonPredictor

predictor = PokemonPredictor()
predictions = predictor.predict_teammates(
    revealed_pokemon=["Kingambit", "Gholdengo"],
    max_predictions=5
)
```

### Live Battle Predictions
```sh
uv run python bayesian/live_battle_predictor.py
```

Shows turn-by-turn Bayesian predictions with probabilities for unrevealed Pokemon, predicted moves, items, and EVs.

## Battle Execution

### Local 1v1 Battles
```sh
# Basic battle
uv run python scripts/battles/local_1v1.py --player_name pokechamp --opponent_name abyssal

# Custom backends
uv run python scripts/battles/local_1v1.py --player_name starter_kit --player_backend gpt-4o

# MCP integration
uv run python local_1v1.py --player_prompt_algo mcp --player_backend gemini-2.5-flash --opponent_name abyssal
```

#### Dynamic Move Calculation Flags
```sh
# Enable flag annotations in prompts (type immunities, crit flags, etc.)
uv run python scripts/battles/local_1v1.py --player_name pokechamp --opponent_name abyssal --enable_dynamic_flags

# Enable full dynamic type/power/priority calculations (requires --enable_dynamic_flags)
uv run python scripts/battles/local_1v1.py --player_name pokechamp --opponent_name abyssal --enable_dynamic_flags --enable_dynamic_calcs
```

### VGC Double Battles
```sh
# VGC tournament
uv run python run_with_timeout_vgc.py --continuous --max-concurrent 2

# Single VGC battle
uv run python local_1v1.py --battle_format gen9vgc2025regi --player_name pokechamp --opponent_name abyssal
```

### Human vs Agent
```sh
uv run python scripts/battles/human_agent_1v1.py
```

### Ladder Battles
```sh
uv run python scripts/battles/showdown_ladder.py --USERNAME $USERNAME --PASSWORD $PASSWORD
```

## Evaluation & Analysis

### Cross-Evaluation
```sh
uv run python scripts/evaluation/evaluate_gen9ou.py
```

Runs battles between all agents and outputs:
- Win rates matrix
- Elo ratings
- Average turns per battle

### Dataset Processing
```sh
uv run python scripts/training/battle_translate.py --output data/battles.json --limit 5000 --gamemode gen9ou
```

## Dataset

The PokéChamp dataset contains over 2 million competitive Pokémon battles across 37+ formats.

### Dataset Features
- **Size**: 2M clean battles (1.9M train, 213K test)
- **Formats**: Gen 1-9 competitive formats
- **Skill Range**: All Elo ranges (1000-1800+)
- **Time Period**: Multiple months (2024-2025)

### Usage
```python
from datasets import load_dataset
from scripts.training.battle_translate import load_filtered_dataset

# Load filtered dataset
filtered_dataset = load_filtered_dataset(
    min_month="January2025",
    max_month="March2025", 
    elo_ranges=["1600-1799", "1800+"],
    split="train",
    gamemode="gen9ou"
)
```

## Testing

Run the comprehensive test suite:

```sh
# All tests
uv run pytest tests/

# Specific test categories  
uv run pytest tests/ -m bayesian      # Bayesian functionality
uv run pytest tests/ -m moves         # Move normalization & dynamic calculations
uv run pytest tests/ -m teamloader    # Team loading
```

The test suite includes:
- [OK] Bayesian prediction accuracy (100% success rate)
- [OK] Move normalization (284 unique moves tested)
- [OK] Dynamic move calculations (214 tests for type/power/priority resolution)
- [OK] Team loading and rejection handling
- [OK] Bot system integration
- [OK] Core battle engine functionality

## Reproducing Paper Results

### Gen 9 OU Evaluation
```sh
uv run python scripts/evaluation/evaluate_gen9ou.py
```

This runs the full cross-evaluation between PokéChamp and baseline bots, outputting win rates, Elo ratings, and turn statistics as reported in the paper.

### Action Prediction Benchmark

Not yet implemented in this fork (the upstream paper's action-prediction benchmark).

## Acknowledgments

This project is a fork of [**sethkarten/pokechamp**](https://github.com/sethkarten/pokechamp) — the official implementation of the ICML '25 paper *"PokéChamp: an Expert-level Minimax Language Agent"* (Karten, Nguyen, Jin). The battle engine, minimax search, dynamic-move logic, and Bayesian prediction system are all inherited from the original codebase.

All credit for the core PokéChamp architecture and the 2M-battle dataset belongs to the original authors. This fork merely layers LangChain/LangGraph agent experiments on top of their work. Many thanks to Seth Karten and collaborators for open-sourcing such a thorough and well-structured research codebase. 🙏

## Citation

```bibtex
@article{karten2025pokechamp,
  title={PokéChamp: an Expert-level Minimax Language Agent},
  author={Karten, Seth and Nguyen, Andy Luu and Jin, Chi},
  journal={arXiv preprint arXiv:2503.04094},
  year={2025}
}

@inproceedings{karten2025pokeagent,
  title        = {The PokeAgent Challenge: Competitive and Long-Context Learning at Scale},
  author       = {Karten, Seth and Grigsby, Jake and Milani, Stephanie and Vodrahalli, Kiran
                  and Zhang, Amy and Fang, Fei and Zhu, Yuke and Jin, Chi},
  booktitle    = {NeurIPS Competition Track},
  year         = {2025},
  month        = apr,
}
```