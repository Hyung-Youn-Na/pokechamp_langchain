#!/bin/bash
# Run IO Baseline experiments for all models that complete within 10 minutes
# EXP-011 through EXP-016
# Total estimated time: ~500 minutes (~8.3 hours)

set -e

# Ensure uv is in PATH
export PATH="/root/.local/bin:$PATH"

PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$PROJECT_ROOT"

echo "============================================"
echo "IO Baseline Experiments - 6 Models × 30 Battles"
echo "============================================"
echo "Starting at: $(date)"
echo ""

declare -A MODELS
MODELS=(
    ["EXP-011"]="ollama/glm-5.1:cloud"
    ["EXP-012"]="ollama/deepseek-v4-pro:cloud"
    ["EXP-013"]="ollama/nemotron-3-super:cloud"
    ["EXP-014"]="ollama/deepseek-v4-flash:cloud"
    ["EXP-015"]="ollama/gemma4:31b-cloud"
    ["EXP-016"]="ollama/kimi-k2.6:cloud"
)

declare -A DIRS
DIRS=(
    ["EXP-011"]="EXP-011-io-baseline-glm51"
    ["EXP-012"]="EXP-012-io-baseline-deepseek-v4-pro"
    ["EXP-013"]="EXP-013-io-baseline-nemotron3s"
    ["EXP-014"]="EXP-014-io-baseline-deepseek-v4-flash"
    ["EXP-015"]="EXP-015-io-baseline-gemma4"
    ["EXP-016"]="EXP-016-io-baseline-kimi-k26"
)

# Allow running specific experiments via args (e.g., ./run_io_baselines.sh EXP-011 EXP-012)
if [ $# -gt 0 ]; then
    EXPS=("$@")
else
    EXPS=("EXP-011" "EXP-012" "EXP-013" "EXP-014" "EXP-015" "EXP-016")
fi

for EXP_ID in "${EXPS[@]}"; do
    MODEL="${MODELS[$EXP_ID]}"
    DIR="${DIRS[$EXP_ID]}"
    LOG_DIR=".temp/experiments/$DIR/battle_log"

    if [ -z "$MODEL" ]; then
        echo "ERROR: Unknown experiment $EXP_ID"
        continue
    fi

    echo "============================================"
    echo "[$EXP_ID] Running: $MODEL"
    echo "Log dir: $LOG_DIR"
    echo "Started at: $(date)"
    echo "============================================"

    START_TIME=$(date +%s)

    uv run python scripts/battles/local_1v1.py \
        --player_name pokechamp \
        --player_prompt_algo io \
        --player_backend "$MODEL" \
        --opponent_name abyssal \
        --N 30 \
        --battle_format gen9ou \
        --temperature 0.3 \
        --seed 42 \
        --log_dir "$LOG_DIR" \
        2>&1 | tee ".temp/experiments/$DIR/run.log"

    END_TIME=$(date +%s)
    ELAPSED=$((END_TIME - START_TIME))
    MINUTES=$((ELAPSED / 60))
    SECONDS=$((ELAPSED % 60))

    echo ""
    echo "[$EXP_ID] Completed in ${MINUTES}m ${SECONDS}s"
    echo ""
done

TOTAL_END=$(date +%s)
echo "============================================"
echo "All experiments completed at: $(date)"
echo "============================================"
