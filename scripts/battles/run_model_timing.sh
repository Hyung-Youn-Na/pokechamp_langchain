#!/bin/bash
# Model timing benchmark: run 1 battle per model with io prompt algo
# Measures wall-clock time for each model

export PATH="/root/.local/bin:$PATH"
set -e

LOG_BASE=".temp/experiments/model-timing"

MODELS=(
    "ollama/minimax-m3:cloud"
    "ollama/nemotron-3-ultra:cloud"
    "ollama/gemma4:31b-cloud"
    "ollama/qwen3.5:397b-cloud"
    "ollama/glm-5.1:cloud"
    "ollama/nemotron-3-super:cloud"
    "ollama/deepseek-v4-flash:cloud"
    "ollama/deepseek-v4-pro:cloud"
    "ollama/kimi-k2.6:cloud"
)

echo "============================================================"
echo "  OLLAMA CLOUD MODEL TIMING BENCHMARK"
echo "  Prompt algo: io | Opponent: abyssal | Battles: 1 per model"
echo "  Models: ${#MODELS[@]}"
echo "  Started: $(date '+%Y-%m-%d %H:%M:%S')"
echo "============================================================"
echo ""

RESULTS_FILE="${LOG_BASE}/timing_results.txt"
mkdir -p "${LOG_BASE}"
echo "# Model Timing Results - $(date '+%Y-%m-%d %H:%M:%S')" > "${RESULTS_FILE}"
echo "# Format: MODEL | WALL_TIME(s) | WIN_RATE | AVG_TURNS" >> "${RESULTS_FILE}"
echo "" >> "${RESULTS_FILE}"

for model in "${MODELS[@]}"; do
    model_slug=$(echo "$model" | tr '/' '_' | tr ':' '_')
    log_dir="${LOG_BASE}/${model_slug}/battle_log"
    mkdir -p "${log_dir}"

    echo "------------------------------------------------------------"
    echo "  Running: ${model}"
    echo "  Started: $(date '+%H:%M:%S')"
    echo "------------------------------------------------------------"

    START_TIME=$(date +%s)

    uv run python scripts/battles/local_1v1.py \
        --player_name pokechamp \
        --player_prompt_algo io \
        --player_backend "${model}" \
        --opponent_name abyssal \
        --N 1 \
        --battle_format gen9ou \
        --temperature 0.3 \
        --seed 42 \
        --log_dir "${log_dir}" \
        2>&1 | tee "${LOG_BASE}/${model_slug}.log" | tail -20

    END_TIME=$(date +%s)
    ELAPSED=$((END_TIME - START_TIME))
    ELAPSED_MIN=$(python3 -c "print(f'{$ELAPSED/60:.1f}')")

    echo ""
    echo "  >>> ${model} completed in ${ELAPSED}s (${ELAPSED_MIN} min)"
    echo ""

    # Extract win rate and turns from the output log
    WIN_RATE=$(grep -oP 'Win Rate:\s+\K[0-9.]+' "${LOG_BASE}/${model_slug}.log" | tail -1 || echo "N/A")
    AVG_TURNS=$(grep -oP 'Avg Turns per Battle:\s+\K[0-9.]+' "${LOG_BASE}/${model_slug}.log" | tail -1 || echo "N/A")

    echo "${model} | ${ELAPSED}s (${ELAPSED_MIN}min) | WinRate=${WIN_RATE}% | AvgTurns=${AVG_TURNS}" >> "${RESULTS_FILE}"
done

echo ""
echo "============================================================"
echo "  ALL MODELS COMPLETED"
echo "  Finished: $(date '+%Y-%m-%d %H:%M:%S')"
echo "============================================================"
echo ""
echo "RESULTS SUMMARY:"
echo "------------------------------------------------------------"
cat "${RESULTS_FILE}"
echo "------------------------------------------------------------"
echo ""
echo "Full results saved to: ${RESULTS_FILE}"
