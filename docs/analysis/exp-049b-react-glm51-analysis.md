# EXP-049b 분석: react + B 노드 분리 (strategy_synthesis)

> **알고리즘**: react · **백엔드**: ollama/glm-5.1:cloud · **상대**: abyssal (io, gemini-2.5-pro)
> **N**: 30 · **seed**: 42 · **temperature**: 0.3 · **팀 모드**: fixed (`dynamic-v2.json`)
> **oracle**: on (`--enable_showdown_oracle`) · **날짜**: 2026-06-24
> **baseline**: **EXP-049a** (D 메모리, 40.0%) — 직전 EXP, 동일 조건 위에서 "B 노드 1개"만 변수.
> **참조**: [`exp-049a`](exp-049a-react-glm51-analysis.md) · 설계 [`react-architecture-redesign.md`](../architecture/react-architecture-redesign.md) §5

---

## 0. 실험 조건 (변경 1개)

EXP-049a(D 메모리) 위에 **그래프 노드 분리**(design B) 추가. 현행 `agent` 노드(도구호출+결정+강제종료 매몰)를:
- `tool_agent` — 도구 호출만
- `strategy_synthesis` ★ — clean rebuild로 정량 도구 결과 + D 메모리를 종합해 전략적 결정 + 장기 plan

엣지: `build_context → tool_agent ⇄ tool_execution → strategy_synthesis → parse_action → END`. `STRATEGY_SYSTEM_PROMPT`가 my_plan을 "배틀 전체 승리 경로"로 강제. dead field `reasoning` 활성화.

---

## 1. 정량 결과 — 승률 회복, 단 비용 증가

### 1.1 승률 — 049a +20pp, 048 +6.7pp 회복

| EXP | 승률 | avg 턴 |
|-----|------|--------|
| EXP-048 | 53.3% (16/30) | 16.4 |
| EXP-049a | 40.0% (12/30) | 17.6 |
| **EXP-049b** | **60.0% (18/30)** | 18.2 |

### 1.2 리소스 — 블로트 오히려 악화 (clean rebuild 가설 기각) ★

| 항목 | EXP-048 | EXP-049a | EXP-049b | 049a→049b |
|------|---------|----------|----------|-----------|
| avg prompt tokens | 150,823 | 205,930 | **261,061** | **+27%** |
| avg completion tokens | 5,458 | 8,395 | **10,526** | +25% |
| avg LLM calls/판 | 53.1 | 66.2 | **87.7** | +32% |
| avg time/판 | 204.3s | 237.1s | **295.6s** | +25% |

> **블로트 회피 가설(049b 설계 §B)은 기각**: strategy 노드가 clean rebuild로 tool_agent의 messages 누적을 대체하지만, **strategy 노드 자체가 매 턴 1회 추가 LLM 호출** → 총 LLM 호출 66→88, prompt 206k→261k. clean rebuild는 tool_agent 누적을 막았을 뿐, 전체 비용은 증가.

### 1.3 턴 구간별 승률 — 전반 회복

| 구간 | EXP-048 | EXP-049a | EXP-049b |
|------|---------|----------|----------|
| short(<15) | 63.6% (7/11) | 25.0% (2/8) | **50.0% (3/6)** |
| mid(15-24) | 41.2% (7/17) | 47.6% (10/21) | **60.0% (12/20)** |
| long(25+) | 100% (2/2) | 0% (0/1) | **75.0% (3/4)** |

> 049a에서 붕괴했던 short/mid가 모두 회복. mid 60%는 시리즈 최고. long도 샘플 늘어 75%.

---

## 2. 노드 분리의 역할 분석 ★ (사용자 가설 검증)

> 사용자 가설: *"노드 분리가 메모리의 단편적인 결정 기록을 막아줄 것이다."* → **검증됨 (부분)**

### 2.1 my_plan 질적 개선 — 장기 키워드 +15.4pp, 길이 +33%

| 지표 | EXP-049a | EXP-049b | 변화 |
|------|----------|----------|------|
| 단기 키워드(this turn/KO/then/switch) | 95.4% | 94.2% | −1.2pp (거의 유지) |
| **장기 키워드(sweep/setup/wincon/hazard/position/preserve)** | **40.4%** | **55.8%** | **+15.4pp** |
| my_plan 평균 길이 | 128자 | 170자 | +33% |
| my_plan 갱신률 | 24.1% | 37.6% | +13.5pp (더 적극) |

→ my_plan이 049a의 "순수 단기 재진술"에서 **"단기 KO + 장기 후속 전략 결합"**으로 진화. 단기 키워드는 여전 94%(여전히 "KO X this turn" 포함)이나, 장기 후속 전략이 부가됨.

### 2.2 정성 증거 — battle-gen9ou-1225 연속 턴 my_plan (61회)

**EXP-049a** (같은 타겟 4턴 연속 KO 재진술):
```
turn 3: KO Iron Moth with Earthquake... then use Great Tusk
turn 4: KO Iron Moth with Earthquake, then assess
```

**EXP-049b** (단기 KO + 장기 후속 전략 결합):
```
turn 1: OHKO Scizor with Earthquake. After KO, set Stealth Rock on the next switch-in.
turn 2: KO Scizor... Maintain sun for Protosynthesis and Weather Ball users.
turn 3: Switch Walking Wake into Dragonite to exploit 2x Dragon weakness... After Dragonite, maintain sun.
turn 4: KO Dragonite with Dragon Pulse (preserves SpA unlike Draco Meteor). After Dragonite, use sun-boosted attacks to break through.
turn 5: KO Dragonite... keep Walking Wake in to break. Preserve Ceruledge and Great Tusk as backup.
```

차이: ① KO 후 **후속 전략**(Stealth Rock 세팅, sun 유지, backup 보존) 명시, ② 타겟 KO 시 **다음 타겟으로 전환**하며 연속적 전략, ③ **기술 선택의 장기 고려**("preserves SpA unlike Draco Meteor" — SpA 하락 회피). 이것이 "단편적 결정 기록"에서 "누적되는 전략 서술"로의 질적 전환.

`opp_win_condition`도 개선: 049a "need to KO it fast"(현재 위협) → 049b "Break through with setup sweepers after Ogerpon falls"(장기 돌파 전략).

### 2.3 왜 승률이 올랐는가 — 두 기여

1. **my_plan 장기화 (부분)**: 장기 관점이 결정에 반영 → 단기 damage lock-in 완화. short/mid 회복의 원인.
2. **strategy 노드의 구조적 종합**: 도구 결과를 전략적 결론으로 번역하는 전담 단계 → "observation→전략 변환" 병목(EXP-048 지목) 직접 완화.

---

## 3. 문제점

### 🟡 P1 — 비용 증가 (블로트 악화)
- prompt 261k(048 대비 +73%), LLM 호출 88/판, time 296s. clean rebuild 가설 기각.
- 승률 60%로 비용을 상쇄하지만, 048(151k·53%) 대비 **비용 효율은 저하**. 승률 +6.7pp에 비용 +73%.
- 원인: strategy 노드가 매 턴 추가 LLM 호출. 본 목표(승률 90%)엔 비용 2차지만, 049c에서 도구 on-demand로 strategy 부담을 줄일 여지.

### 🟢 P2 — my_plan 완전 장기화 미달
- 장기 키워드 55.8%로 개선됐으나, 단기 키워드 94.2%는 잔존. my_plan이 여전 "이번 턴 KO"를 포함.
- STRATEGY_SYSTEM_PROMPT 강제가 부분 효과. 완전 장기화(순수 win condition)는 049c Smogon 자연어 전략 주입이 필요할 수 있음.

---

## 4. 시리즈 종합 — 3 실패 모드 → 회복

| EXP | 변경 | 승률 | 진단 |
|-----|------|------|------|
| 044 | oracle off baseline | 56.7% | 기준 |
| 048 | oracle on + N-roll | 53.3% | 정확도 한계 |
| 049a | + D 메모리 | 40.0% | **블로트 + 단기 재진술** (역효과) |
| **049b** | + B 노드 분리 | **60.0%** | **my_plan 장기화 + 구조적 종합** (회복) |

049a의 두 역효과 원인(블로트·단기 재진술) 중, **단기 재진술은 049b가 해소**(장기 키워드 +15.4pp, 질적 전환). **블로트는 미해소**(오히려 +27%). 그럼에도 승률 회복 = 노드 분리의 구조적 이점이 비용 증가를 상쇄.

---

## 5. 시사점 / 다음 단계

### EXP-049c (Smogon 방식 1 도구) — 방향 확정 근거 마련
049b가 구조적 개선을 입증했으므로, 049c는 그 위에 Smogon 자연어 전략(`get_strategy_insight` 도구)을 추가:
- **기대**: Smogon overview/description("이 포켓몬의 역할/승리 경로")이 strategy 노드에 주입되면, my_plan 장기화가 **더 강화** (장기 키워드 55.8% → 추가 상승), 완전 win condition화.
- **리스크**: on-demand 도구이므로 glm-5.1 호출 빈도가 관건(0이면 기각). 049b의 strategy 노드 구조가 도구 결과를 잘 종합하므로, get_strategy_insight 결과가 my_plan에 반영될 구조적 통로 확보.

### 비용 최적화 (후속)
- 049b 비용 증가(prompt 261k)가 지속 이슈. strategy 노드를 매 턴이 아닌 스위치/KO 시만, 또는 tool_agent 예산 축소로 비용 절감 옵션. 단, 승률 우선이므로 049c 이후 검토.

### §5 이력표 / README
- EXP-049a·049b 결과 §5 이력표 갱신 + 각 README 결과 기입 예정.

---

## 부록: 측정 출처

- 승률/턴/토큰/시간: `experiment_*.json` `summary` (3-way: 048/049a/049b)
- 턴 구간: `battles[]`
- my_plan 장기화율·길이·정성: `langgraph_llm_log.jsonl` (`llm_response` 정규식 추출)
- 뷰어 미생성(정량 + llm_log 직접 분석). `meta.git_dirty=True`.
