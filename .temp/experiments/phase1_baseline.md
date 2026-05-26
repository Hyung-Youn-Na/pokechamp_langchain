# Experiment Results: Baseline (Condition A)

## Configuration

- **Backend:** vllm/google/gemma-4-26B-A4B-it
- **Model:** google/gemma-4-26B-A4B-it
- **Algorithm:** minimax
- **Opponent:** abyssal
- **Battles:** 30
- **Battle Format:** gen9ou
- **Feature Flags:** None (baseline — no code changes to prompts)
- **vLLM Config:** temperature=1.0, top_p=0.95, presence_penalty=1.5, max_tokens=32768, top_k=64, thinking=false
- **Date:** 2026-05-26

## Results

| Metric | Value |
|--------|-------|
| Win Rate | 19/30 (63.33%) |
| Avg Turns per Battle | 23.0 |
| Avg Prompt Tokens per Battle | 115,176 |
| Avg Completion Tokens per Battle | 1,081 |
| Avg LLM Calls per Battle | 55.8 |

## Per-Battle Breakdown

| Battle | Result | Turns |
|--------|--------|-------|
| 1 (305) | WIN | 10 |
| 2 (306) | WIN | 25 |
| 3 (307) | WIN | 21 |
| 4 (308) | LOSS | 35 |
| 5 (309) | LOSS | 20 |
| 6 (310) | WIN | 19 |
| 7 (311) | LOSS | 28 |
| 8 (312) | WIN | 32 |
| 9 (313) | WIN | 17 |
| 10 (314) | WIN | 13 |
| 11 (315) | WIN | 27 |
| 12 (316) | WIN | 17 |
| 13 (317) | WIN | 16 |
| 14 (318) | LOSS | 12 |
| 15 (319) | WIN | 27 |
| 16 (320) | LOSS | 15 |
| 17 (321) | WIN | 19 |
| 18 (322) | LOSS | 18 |
| 19 (323) | WIN | 21 |
| 20 (324) | LOSS | 20 |
| 21 (325) | WIN | 16 |
| 22 (326) | WIN | 15 |
| 23 (327) | LOSS | 15 |
| 24 (328) | WIN | 19 |
| 25 (329) | WIN | 15 |
| 26 (330) | LOSS | 18 |
| 27 (331) | WIN | 21 |
| 28 (332) | WIN | 32 |
| 29 (333) | LOSS | 108 |
| 30 (334) | LOSS | 18 |

## Notes

- **Variance Disclaimer:** With temperature=1.0 and only 30 battles, results have high noise. Statistical significance is limited — the true win rate could differ substantially from 63.33%. A larger sample (100+ battles) would be needed for reliable estimates.
- Battle 29 (gen9ou-333) ran for 108 turns — an extreme outlier that significantly impacts the per-battle metrics. Excluding it, the average turns would be (689-108)/29 = 20.0 turns per battle.
- The experiment infrastructure's per-battle win tracking had a bug (used max-turns battle instead of latest battle), so win rates were cross-verified against HTML battle logs.
- Avg prompt tokens (115,176) includes all LLM calls for a full battle (minimax tree search makes multiple LLM calls per turn for leaf evaluation). This is consistent with ~55.8 LLM calls per battle and ~2,068 prompt tokens per individual LLM call.
- Total experiment runtime: ~1 hour 31 minutes (~3 minutes per battle).
- No vLLM server issues or connection drops during the experiment.
- vLLM response variance with temperature=1.0 means the LLM may produce different evaluations for identical game states across battles, contributing to result noise.
