# Experiment Results: Flags Only (Condition B)

## Configuration

- **Backend:** vllm/google/gemma-4-26B-A4B-it
- **Model:** google/gemma-4-26B-A4B-it
- **Algorithm:** minimax
- **Opponent:** abyssal
- **Battles:** 30
- **Battle Format:** gen9ou
- **Feature Flags:** `--enable_dynamic_flags` (flag annotations only, no dynamic calculations)
- **vLLM Config:** temperature=1.0, top_p=0.95, presence_penalty=1.5, max_tokens=32768, top_k=64, thinking=false
- **Date:** 2026-05-26

## Results

| Metric | Value |
|--------|-------|
| Win Rate | 20/30 (66.67%) |
| Avg Turns per Battle | 21.2 |
| Avg Prompt Tokens per Battle | 109,278 |
| Avg Completion Tokens per Battle | 967 |
| Avg LLM Calls per Battle | 52.7 |

## Per-Battle Breakdown

| Battle | Result | Turns |
|--------|--------|-------|
| 1 (335) | WIN | 11 |
| 2 (336) | WIN | 22 |
| 3 (337) | LOSS | 28 |
| 4 (338) | LOSS | 21 |
| 5 (339) | LOSS | 23 |
| 6 (340) | LOSS | 18 |
| 7 (341) | LOSS | 46 |
| 8 (342) | WIN | 23 |
| 9 (343) | WIN | 19 |
| 10 (344) | WIN | 15 |
| 11 (345) | WIN | 23 |
| 12 (346) | WIN | 33 |
| 13 (347) | WIN | 18 |
| 14 (348) | LOSS | 24 |
| 15 (349) | LOSS | 20 |
| 16 (350) | WIN | 22 |
| 17 (351) | WIN | 17 |
| 18 (352) | WIN | 19 |
| 19 (353) | WIN | 25 |
| 20 (354) | WIN | 18 |
| 21 (355) | WIN | 20 |
| 22 (356) | LOSS | 18 |
| 23 (357) | LOSS | 14 |
| 24 (358) | WIN | 22 |
| 25 (359) | WIN | 17 |
| 26 (360) | LOSS | 17 |
| 27 (361) | WIN | 19 |
| 28 (362) | WIN | 23 |
| 29 (363) | WIN | 25 |
| 30 (364) | WIN | 17 |

## Notes

- **Variance Disclaimer:** With temperature=1.0 and only 30 battles, results have high noise. Statistical significance is limited — the true win rate could differ substantially from 66.67%. A larger sample (100+ battles) would be needed for reliable estimates.
- **Win rate verification:** The experiment infrastructure's per-battle win tracking had a known bug (used max-turns battle instead of latest battle), so win rates were cross-verified against HTML battle logs. The aggregate `player.win_rate` of 66.67% was confirmed correct via battle log analysis.
- **Comparison with Baseline (Condition A):** Win rate increased from 63.33% (19/30) to 66.67% (20/30), a +3.33 percentage point improvement. However, this difference is within noise given the small sample size and high temperature.
- **Prompt tokens:** Avg prompt tokens decreased from 115,176 (baseline) to 109,278 (flags only). This is likely within normal variance — flag annotations add minimal text per move, and total tokens are dominated by the number of LLM calls and game state complexity.
- **Avg turns:** Decreased from 23.0 (baseline) to 21.2 (flags only), though battle 7 (46 turns) was the longest.
- **Battle 7 (gen9ou-341)** ran for 46 turns — an outlier that pulled the average up. Excluding it, average turns would be (637-46)/29 = 20.4.
- Total experiment runtime: ~1 hour 28 minutes (~2.9 minutes per battle).
- No vLLM server issues or connection drops during the experiment.
- Flag annotations added to prompts include: `[dynamic type]`, `[always crits]`, `[crash damage on miss]`, `[costs 50% HP]`, `[conditional use]`, `[retargeted]`, `[dynamic priority]` — applied only to moves that have these flags in the game data.
