# EXP-049c 분석: react + Smogon 자연어 전략 도구 (get_strategy_insight)

> **알고리즘**: react · **백엔드**: ollama/glm-5.1:cloud · **상대**: abyssal (io, gemini-2.5-pro)
> **N**: 30 · **seed**: 42 · **temperature**: 0.3 · **팀 모드**: fixed (`dynamic-v2.json`)
> **oracle**: on · **날짜**: 2026-06-24
> **baseline**: **EXP-049b** (B 노드, 60.0%) — 동일 조건 위에서 "Smogon 도구 1개"만 변수.
> **참조**: [`exp-049a`](exp-049a-react-glm51-analysis.md) · [`exp-049b`](exp-049b-react-glm51-analysis.md) · 설계 [`react-architecture-redesign.md`](../architecture/react-architecture-redesign.md) §6

---

> ## ⚠️ 정정 (2026-06-25) — "방식 1 기각"은 데이터 결함으로 무효
>
> 본 보고서 §2의 진단 "방식 1 기각 = glm-5.1이 get_strategy_insight를 안 부른다(0.3%)"는 **잘못됨**. 실제 원인:
> - `get_strategy_insight` 도구가 **88.9%(96/108종) 빈 overview 반환** → LLM이 도구를 무의미하다고 판단 → 더 안 부름
> - 빈 overview 근원: **Smogon dex `_rpc` `dump-pokemon` API가 96종의 OU overview를 빈으로 반환** (crawler `normalize()` / 정제 / 도구 로직은 버그 아님)
> - 즉 **데이터 결함이 원인, 모델 탓 아님**. 방식 1은 아직 정당하게 평가되지 않음.
>
> **복구 진행 중**: crawler `normalize()`에 Draft format "Overview:" 섹션 fallback 추가 — toxapex/rillaboom dry-run 검증 672/610자 채워짐. 재스크래핑 후 049c 재검증 예정. 상세 = `docs/architecture/smogon-meta-design.md` §6.
>
> 본 보고서의 승률(56.7%)·my_plan 장기화(61.7%)·블로트 수치는 사실이나, **"Smogon 도구 효과 미발현" 결론은 데이터 결함으로 인한 것**이지 방식 1 자체의 한계가 아님.

---

## 0. 실험 조건 (변경 1개)

EXP-049b(B 노드) 위에 Smogon **방식 1(새 도구)** 추가. `get_strategy_insight(species, aspect)` — Smogon overview/moveset description을 2000자 cap으로 반환, on-demand 호출. `REACT_SYSTEM_PROMPT` Available Tools에 설명 1줄 추가(별도 지시문 없음).

---

## 1. 정량 결과 — 049b 대비 미세 하락, 048 대비 유지

### 1.1 승률 4-way

| EXP | 승률 | avg 턴 |
|-----|------|--------|
| EXP-048 | 53.3% | 16.4 |
| EXP-049a | 40.0% | 17.6 |
| EXP-049b | **60.0%** | 18.2 |
| **EXP-049c** | **56.7% (17/30)** | 17.0 |

> 049b 대비 −3.3pp, 048 대비 +3.4pp. n=30 비유의 범위(z≈0.27).

### 1.2 리소스

| 항목 | 049b | 049c | 변화 |
|------|------|------|------|
| avg prompt tokens | 261,061 | 264,356 | +1.3% (거의 동일) |
| avg LLM calls/판 | 87.7 | 85.2 | −2.5 |
| avg time/판 | 295.6s | 273.4s | −22s (턴 수 감소 효과) |

> overview 2000자 cap이 블로트 가중을 막음 (도구 호출이 많아도 prompt 거의 동일).

### 1.3 턴 구간 — 혼재

| 구간 | 049b | 049c |
|------|------|------|
| short(<15) | 50.0% (3/6) | **62.5% (5/8)** |
| mid(15-24) | **60.0% (12/20)** | 52.6% (10/19) |
| long(25+) | 75.0% (3/4) | 66.7% (2/3) |

---

## 2. ★ 방식 1 판정 — 기각 (get_strategy_insight 0.3% 호출)

| 지표 | 값 | 판정 |
|------|-----|------|
| get_strategy_insight 호출 | **7회 / 2002 tool calls = 0.3%** | 사실상 미사용 |
| 사용 배틀 | **5/30** | 25배틀은 1회도 안 부름 |
| 도구 호출 1위 | calculate_damage 74.3% | glm-5.1은 damage 도구에 집중 |

**7회 호출 상세** (전부 배틀 중반, 특정 포켓몰 등장 시):
```
battle-1240 turn 3:  enamorus
battle-1241 turn 7:  landorustherian
battle-1244 turn 9:  rillaboom    ┐ 같은 배틀 2회
battle-1244 turn 14: gholdengo    ┘
battle-1254 turn 13: kingambit
battle-1264 turn 3:  corviknight  ┐ 같은 배틀 2회
battle-1264 turn 19: toxapex      ┘
```

→ **방식 1 기각 근거 확보**: 도구를 시스템 프롬프트에 노출만 하면 glm-5.1은 거의 안 부름 (tera 발동 0%, EXP-035 "보유≠실사용" 교훈과 동일 패턴). calculate_damage 같은 즉각적 정량 도구에만 집중. Smogon 자연어의 **장기 전략적 가치**를 작은 모델이 자발 인식하지 못함.

---

## 3. my_plan 장기화 — 049b 구조의 공로, Smogon 효과 아님

| 지표 | 049a | 049b | 049c |
|------|------|------|------|
| 단기 키워드 | 95.4% | 94.2% | 92.8% |
| **장기 키워드** | 40.4% | 55.8% | **61.7%** |
| my_plan 길이 | 128자 | 170자 | 171자 |

> 장기 키워드 55.8% → 61.7% (+5.9pp)로 추가 상승. **하지만 get_strategy_insight를 거의 안 썼으므로(0.3%) 이것은 Smogon 효과가 아님**. 049b의 strategy 노드 + STRATEGY_SYSTEM_PROMPT 구조가 이미 my_plan 장기화를 이끌고 있었고, 049c에서 자연 유지/샘플 변동. my_plan 장기화의 원동력은 **B 노드 구조**이지 Smogon 도구가 아님.

---

## 4. 시리즈 종합 — 3 실험 (049a/b/c)

| EXP | 변경 | 승률 | 핵심 진단 |
|-----|------|------|-----------|
| 049a | + D 메모리 | 40.0% | 매 턴 brief 블로트(prompt +36.5%) + my_plan 95.4% 단기 재진술 (역효과) |
| **049b** | + B 노드 분리 | **60.0%** ★ | strategy 노드 clean-rebuild 종합 + my_plan 장기화(55.8%) (회복, 시리즈 최고) |
| 049c | + Smogon 도구 | 56.7% | 도구 미사용(0.3%) → Smogon 효과 미발현. 049b 구조가 주효 |

### 시리즈가 증명한 것
1. **B 노드(구조 분리)가 핵심 승률 레버**: 049b 60%가 최고. strategy_synthesis 노드가 "observation→전략 변환" 병목(EXP-048 지목)을 구조적으로 해소.
2. **my_plan 장기화는 STRATEGY_SYSTEM_PROMPT + 노드 구조의 공로**: Smogon 없이도 40.4%→61.7%로 진행. 전용 프롬프트 강제가 도구 주입보다 효과적.
3. **D 메모리(049a)와 Smogon 도구(049c) 모두 "추가 정보 주입" 경로** — 전자는 매 턴 주입(블로트 역효과), 후자는 on-demand(미사용). 두 극단 모두 glm-5.1에서 한계.
4. **블로트 회피 가설(049b)은 기각됐으나**, clean-rebuild + strategy 노드의 **구조적 종합**이 비용 증가를 상쇄해 승률 향상.

---

## 5. 결론 / 다음 방향

### 방식 1(도구) 기각 — Smogon 활용의 대안
glm-5.1이 get_strategy_insight를 안 부르므로, Smogon 자연어를 살리려면:
- **방식 2(전략 노드 직접 주입)**: strategy 노드가 매 턴 active 양측 overview를 컨텍스트에 포함. 미사용 리스크 제거 but 블로트(EXP-002~004). 049b clean-rebuild 구조 위에서 overview만 추가하면 블로트 통제 가능할 수 있음.
- **방식 3(구조화 요약)**: overview → 체크관계/역할 3~5줄 요약 사전 추출. 경량·제어 가능 but 요약 품질 관건.
- **방식 1 + 약한 유도**: 시스템 프롬프트에 "스위치/새 포켓몬 등장 시 get_strategy_insight 조회" 1줄. EXP-002~004 리스크 but 최소.

### 049b(60%) 기반 최적화 방향
- 049b가 현재 최고. 비용(prompt 261k) 최적화(strategy 노드 빈도/예산) 또는 my_plan 장기화 더 강화(STRATEGY_SYSTEM_PROMPT 튜닝)가 049c보다 유망.
- **목표 90%** 관점: 049b 60% → 추가 +30pp 필요. 구조적 종합(strategy 노드) + my_plan 장기화(61.7%) 기반 위에, ① 비용 절감 ② my_plan 완전 win condition화 ③ 다른 병목(팀 구성·예측 정확도) 탐색.

### §5 이력표 / README 정리 (대기)
- EXP-049a/b/c 3종 결과 §5 이력표 갱신 + 각 README 결과 기입. 시리즈 종료 후 일괄 처리 권장.

---

## 부록: 측정 출처

- 승률/턴/토큰: `experiment_*.json` `summary` (4-way: 048/049a/049b/049c)
- get_strategy_insight 빈도·상세: `langgraph_tool_log.jsonl` (`tool_call` 줄)
- my_plan 장기화율: `langgraph_llm_log.jsonl` (`llm_response` 정규식)
- `meta.git_dirty=True`. 뷰어 미생성(정량 + 로그 직접 분석).
