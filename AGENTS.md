# Repository Guidelines

## Project Structure & Module Organization

```
pokechamp/          # LLM player layer — prompts, backends, minimax search, data caching
poke_env/           # Battle engine (LLM-independent) — Showdown protocol, state tracking, LocalSim
bayesian/           # Bayesian prediction — opponent team/move/item/EV prediction
bots/                # Bot implementations (<name>_bot.py → bot name <name>, inherits LLMLayer)
scripts/battles/     # Battle runners (local_1v1, human_agent_1v1, showdown_ladder)
scripts/evaluation/  # Cross-evaluation with WHR rating
scripts/training/    # Dataset processing for 2M battle replay dataset
tests/               # Pytest test suite (markers: bayesian, moves, teamloader, oracle, slow)
pokemon-showdown/    # Vendored Pokémon Showdown server (TypeScript/Node.js)
resource/            # Static game data and assets
common.py            # Shared config: bot registry, prompt algorithms, random seeds
```

## Build, Test, and Development Commands

```sh
uv sync                                                                # Install dependencies
uv run python scripts/battles/local_1v1.py --player_name pokechamp --opponent_name abyssal  # Run a battle
uv run python run_with_timeout_vgc.py --continuous --max-concurrent 2  # VGC double battles
uv run python scripts/evaluation/evaluate_gen9ou.py                    # Evaluation
uv run pytest tests/                                                   # All tests
uv run pytest tests/ -m bayesian                                       # By marker
uv run pytest tests/ -m oracle                                         # Oracle integration tests
uv run black . && uv run flake8 . && uv run mypy .                     # Lint & typecheck
```

Requires a local Pokémon Showdown server on port 8000. API keys via env vars: `OPENROUTER_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY`.

## Architecture

Three-layer design: **poke_env** (battle engine, `LocalSim` for minimax search) → **pokechamp** (`LLMPlayer` orchestrates prompt generation via `prompts.py`, LLM backends, minimax via `minimax_optimizer.py`) → **bayesian** (opponent prediction via `pokemon_predictor.py`).

Core flow: `local_1v1.py` → `LLMPlayer(prompt_algo, backend)` → `choose_move()` → text prompt → LLM backend → parsed action → Showdown server.

Prompt algorithms (`--player_prompt_algo`): `io`, `sc`, `cot`, `tot`, `minimax`, `heuristic`, `max_power`, `one_step`, `random`, `mcp`.

## Coding Style & Naming Conventions

- Python 3.10+, managed with **uv**, formatted with **Black** (line-length 88).
- Linting: `flake8`. Type checking: `mypy`.
- Bot naming: `<name>_bot.py` in `bots/`, class inherits `LLMPlayer`.
- LLM backends: follow `pokechamp/gpt_player.py` interface.
- `pokemon-showdown/` is vendored — do not modify upstream code.

## Testing Guidelines

- Framework: **pytest** 6.0+ with `pytest-asyncio` (auto mode), strict markers and config.
- File/class/function naming: `tests/test_*.py`, `Test*`, `test_*`.
- Registered markers: `bayesian`, `moves`, `teamloader`, `oracle`, `slow`, `integration`, `unit`, `smoke`, `asyncio`.
- Config: `pytest.ini` + `pyproject.toml`. Timeout: 300s.

## Commit & Pull Request Guidelines

- Format: `<type>: <description>` (e.g., `feat: add oracle integration tests`).
- Common types: `feat`, `fix`, `clean`.
- Keep commits focused and atomic. Link related issues in PR descriptions.
- Never commit secrets — `passwords.json`, `passwords_vgc.json`, and `.env` files are gitignored.
