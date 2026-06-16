# EXP-031 (react / GLM-5.1) 실험 분석

> 분석 일시: 2026-06-15
> EXP-031: 2026-06-11 23:41 ~ 2026-06-12 03:16, GLM-5.1, ReAct, **30전** vs abyssal (gemini-2.5-pro, io)
> 비교: EXP-030 (react, GLM-5.1, 30전) — `react_agent.py` / `state.py` / `common.py` 의 **stopping-criteria 코드 변경** (working tree uncommitted)

> ⚠️ **비교 신뢰성 경고 (규칙 6.2)**: EXP-030 → EXP-031 사이에 `react_agent.py`·`state.py`·`common.py` 의 복수 코드 변경이 있다. 또한 EXP-030 의 `experiment_*.json` 이 유실되어 `config` 를 직접 교차검증할 수 없다 (opponent 는 `local_1v1_langchain.py` 기본값 `abyssal`/`gemini-2.5-pro`/`io` 로 동일 추정). 따라서 본 보고서의 승률 격차 원인은 **인과가 아닌 강한 상관** 으로 기술한다. 단일 변수 ablation 이 아님.

---

## 1. 실험 결과 비교

### 1.1 승률

| 구간 | EXP-031 (본) | EXP-030 (비교) | 변화 |
|------|--------------|----------------|------|
| **전체** | **76.7% (23/30)** | 33.3% (10/30) | ⬆ +43.3pp |
| 짧은 배틀 (<15턴) | — (0전, 최소 15턴) | 57.1% (4/7) | — |
| 중간 배틀 (15-24턴) | 73.7% (14/19) | 🔴 10.0% (1/10) | ⬆ +63.7pp |
| 긴 배틀 (25+턴) | 81.8% (9/11) | 38.5% (5/13) | ⬆ +43.3pp |

출처: `experiment_react_glm-5.1_cloud.json` summary + battles[] (4.3 스니펫). EXP-030 구간은 `docs/archive/exp-030-react-glm51-analysis.md`.

> EXP-031 은 **짧은 배틀(<15턴)이 0건** (최소 15턴, 평균 24.4턴). EXP-030 에는 짧은 배틀이 7건 있었다. EXP-031 의 배틀이 전반적으로 길어진 것은 상대(gemini-2.5-pro io)의 결정력 또는 pokechamp 의 킬각 포착 지연과 상관이 있어 보인다 (2.2절).

### 1.2 리소스 사용량

| 항목 | EXP-031 (본) | EXP-030 (비교) | 변화율 |
|------|--------------|----------------|--------|
| 배틀당 LLM 호출 | 119.1건 | 299.7건 | ⬇ -60% |
| 턴당 LLM 호출 | ~4.9건 | ~12건 | ⬇ -59% |
| 배틀당 도구 호출 | 172.5건 (5,174/30) | 353건 (10,599/30) | ⬇ -51% |
| 턴당 도구 호출 | 7.13건 (max 30) | 15.32건 (max **110**) | ⬇ -53% |
| 배틀당 prompt 토큰 | 357,737 | ~1.76M (기존 보고서) | ⬇ -80% |
| 배틀당 completion 토큰 | 11,610 | (기존 보고서 미기재) | — |
| 배틀당 총 토큰 | ~0.37M | ~1.76M | ⬇ -79% |
| 배틀당 소요 시간 | 426.3초 | — | — |

출처: `summary.avg_*` + `langgraph_tool_log.jsonl`. EXP-030 토큰은 기존 분석 보고서 인용 (EXP-030 JSON 유실).

### 1.3 도구 사용 분포

| 도구 | EXP-031 (본) | 비율 | EXP-030 (비교) | 비율 | 변화 |
|------|--------------|------|----------------|------|------|
| `calculate_damage` | 2,771 | **53.6%** | 2,456 | 23.2% | ⬆ 주도권 장악 |
| `simulate_turn` | 1,050 | **20.3%** | 6,855 | **64.7%** | ⬇ 대폭 감소 |
| `check_type_effectiveness` | 613 | 11.8% | 683 | 6.4% | ⬆ |
| `evaluate_position` | 256 | 4.9% | 159 | 1.5% | ⬆ |
| `predict_opponent_moves` | 247 | 4.8% | 204 | 1.9% | ⬆ |
| `analyze_matchup` | 159 | 3.1% | 171 | 1.6% | ⬆ |
| `get_move_details` | 71 | 1.4% | 66 | 0.6% | → |
| `get_team_analysis` | 7 | 0.1% | 5 | 0.0% | 🔴 여전히 미사용 |

출처: `langgraph_tool_log.jsonl` 의 `tool_call` 줄 (4.5 스니펫). EXP-031 총 5,174건 / EXP-030 총 10,599건.

**도구 패턴 전환**: EXP-030 의 주도 도구 `simulate_turn`(64.7%)이 EXP-031 에서 20.3%로 축소되고, `calculate_damage`가 23.2% → 53.6%로 주도권을 잡았다. 이것이 승률/리소스 변화의 가장 강한 상관 변수다.

---

## 2. 핵심 발견

### 2.1 결정적 차이: stopping-criteria 코드 변경이 도구 사용량을 반으로 줄였다

EXP-030 → EXP-031 의 가장 큰 정량 차이는 **턴당 도구 호출 max 110 → 30, mean 15.32 → 7.13** 이다. 이 감소는 런타임 랜덤이 아니라 `react_agent.py` / `state.py` 의 **코드 변경**과 일치한다 (working tree uncommitted diff):

| 변경 | 파일 | 효과 |
|------|------|------|
| `tool_call_count` 필드 + reducer 추가 | `state.py` (+3줄) | `Annotated[int, _add_int]` 로 누적 카운트 |
| 카운트 소스를 messages 스캔 → state 필드로 변경 | `react_agent.py` (`agent_loop`, `should_continue`) | ToolMessage 스캔의 일관성 없는 카운트 제거 |
| `tool_execution` 에 `max_tool_calls` 전달 + truncate | `react_agent.py` | 남은 버짓만큼만 실행 ("execute what fits") |
| `MAX_TOOL_CALLS`(전역 상수) → `_make_*(max_tool_calls)` 매개변수화 | `react_agent.py`, `common.py` | config `max_tool_calls=5` 주입 |

EXP-027 분석(`docs/archive/exp-027-react-glm51-analysis.md`)에서 지적된 *"messages 리듀서 누락 → `tool_call_count` 항상 0 → `MAX_TOOL_CALLS` 미작동 → 무한 도구 호출"* 문제의 **잔여 원인(messages 기반 카운트 + truncate 부재)**을 EXP-031 코드가 마저 해결한 것으로 보인다. EXP-030 은 `add_messages` 리듀서는 있었으나 카운트를 여전히 `sum(ToolMessage)`로 스캔했고, `tool_execution` 이 초과 분을 자르지 않아 한 턴에 최대 110건의 도구 호출이 연쇄 발생했다.

### 2.2 가설 / 인과 추론: `simulate_turn` 과의존 억제가 승률 향상의 주원인

1. **`simulate_turn` 은 상대 행동을 추정해야 하므로 불확실성이 높다.** EXP-030 에서 턴당 최대 110건까지 연쇄 호출되며, 특히 중간 배틀(15-24턴, 상대 교체/전략 변경 빈번)에서 시뮬레이션 오답을 양산했을 가능성이 높다 → **EXP-030 중간 배틀 승률 10%** 의 직접적 상관 원인으로 추정.
2. **EXP-031 은 `calculate_damage`(불확실성 낮음, 자체 기술 데미지만 계산)이 주도(53.6%).** 상대 행동 추정 없이 결정에 더 직접적인 정보를 제공한다.
3. **도구 호출량 절반 감소 → "분석 마비(analysis paralysis)" 완화.** EXP-030 턴당 ~15건 vs EXP-031 턴당 ~7건. 과도한 도구 호출이 노이즈를 키우던 패턴이 억제되었다.
4. **중간/긴 배틀 승률 급등**(10%→73.7%, 38.5%→81.8%)이 위 가설을 뒷받침: 시뮬레이션 노이즈에 가장 취약한 중간 구간에서 개선 폭이 가장 크다.

> ⚠️ 인과가 아닌 **강한 상관**. 코드 변경(stopping criteria)과 도구 패턴 변화가 동시에 일어났으므로, 어느 쪽이 주원인인지 단정 불가. 둘 다 기여했을 가능성이 높다.

### 2.3 미해결 문제

- **패배 7전 전부 `my_faints=6`(전멸)**, opp_faints 는 2~4에 불과. 즉 pokechamp 이 상대 2~4마리만 잡고 6마리 모두 쓰러진다 → **결정력/킬각 포착 부족** 또는 **위험 관상 포켓몬 교체 타이밍** 문제가 남아 있다 (3.x 참조).
- **`battle-gen9ou-655`**: 59턴 / 274 LLM 호출 / 400 도구 호출 / **1,062초**. 다른 패배 전(평균 ~15-27턴) 대비 비정상적으로 긴 소모전. 턴당 도구 호출(약6.8건) 자체는 EXP-031 평균(7.13)과 비슷하므로 무한루프는 아니나, 킬을 못 잡고 59턴을 끌어간 "결정력 부족"의 극단 사례다.

---

## 3. 문제점 분석

### 🔴 P0-1: 특수 데미지기 오분류 (calculate_damage 에러)

| 항목 | EXP-031 | EXP-030 |
|------|---------|---------|
| 도구 에러 | 158건 / 5,174 (3.1%) | 161건 / 10,599 (1.5%) |
| 절대 에러 건수 | 158건 | 161건 |

에러율은 1.5%→3.1%로 **비율은 증가**했으나, 절대 건수는 161→158로 **거의 동일**. 이는 도구 총량이 절반으로 줄면서 `calculate_damage` 비중(53.6%)이 커졌기 때문이다. 에러의 대부분이 `calculate_damage` 의 특수 데미지기 처리 실패:

| 기술 | 에러 수 | 실제 분류 | calculate_damage 오류 메시지 |
|------|---------|-----------|------------------------------|
| `ruination` | 62 | 비율 데미지기(상대 HP 50%) | "is a status move (category: SPECIAL)" |
| `seismictoss` | 21 | 고정 데미지기(레벨 비례) | "is a status move (category: PHYSICAL)" |
| `painsplit` | 13 | HP 평균기 | "is a status move" |
| `heavyslam` | 8 | 무게 비례기 | "is a status move" |
| `willowisp`/`irondefense` | 9 | (상태기 - 정상 에러) | "is a status move" |

**근본 원인:** `calculate_damage` 가 비율/고정/무게비례 데미지기를 "status move"로 오분류. 비데미지 공식이 구현되지 않았다.

**개선 방안 (범용, 6.1 준수):**
- `battle_tools.py` 의 `calculate_damage` 에 특수 데미지 공식(`ruination`=50% 현재 HP, `seismictoss`/`nightshade`=레벨 고정, `painsplit`=HP 평균, `heavyslam`=무게 비례) 구현
- 처리 불가 시 유의미한 에러 메시지 반환 (LLM 이 대안 도구를 선택하도록)

### 🟡 P1-1: switch 토큰 파싱 실패 (18건)

| 항목 | EXP-031 |
|------|---------|
| `Unknown move: switch*` 에러 | 18건 (`switchtoxapex` 3, `switchzapdos` 7, `switchgreattusk` 2, `switchcorviknight` 2, `switchwalkingwake` 2, `switchslowkinggalar` 2 등) |

**근본 원인:** LLM 이 `{"switch": "switchtoxapex"}` 처럼 값에 `switch` prefix 를 붙여 출력. `parse_action_json` 이 이를 정규화하지 못해 도구/파서에서 "Unknown move" 에러.

**개선 방안:** `parse_action_json`(`common.py`) 에 `^switch(.+)$` 패턴 감지 → prefix 제거 후 종족명 정규화. 기존 EXP-030 보고서의 P1-1 과 동일 이슈로, **미해결 상태 유지**.

### 🟡 P1-2: 팀 수준 분석 도구 미사용

| 도구 | EXP-031 | EXP-030 |
|------|---------|---------|
| `get_team_analysis` | 7건 (0.1%) | 5건 (0.0%) |
| `analyze_matchup` | 159건 (3.1%) | 171건 (1.6%) |

두 실험 모두 팀 수준 전략 분석 도구가 사실상 미사용. 패배 7전의 `my_faints=6`(전멸) 패턴과 연관 가능 — 교체 결정이 단발 매치업이 아닌 팀 잔여 포켓몬의 타입 커버리지를 고려하지 못해 위험 관리가 실패했을 수 있다.

**개선 방안 (범용):** 시스템 프롬프트(`react_agent.py` `REACT_SYSTEM_PROMPT`)에 "잔여 포켓몬이 2마리 이하일 때 `get_team_analysis` 로 교체 후보 평가" 가이드 추가. abyssal 특화가 아닌 모든 gen9ou 상대에 전이되는 위험 관리 개선.

### 🟢 P2-1: `dracometeor` 오타 인식 (3건)

`dracometeteor`(철자 오류) 2건 + `Move 'dracometeteor' not found` 1건. LLM 출력 오타에 대한 퍼지 매칭 부재. 영향은 미미하나, data_cache 의 무브명 정규화에 Levenshtein 기반 폴백을 추가하면 회복율 소폭 향상.

---

## 4. 이전 실험 대비 개선 현황

| 이슈 | EXP-027 | EXP-030 | EXP-031 | 상태 |
|------|---------|---------|---------|------|
| `add_messages` 리듀서 누락 | 🔴 근본원인 | ✅ 해결 | ✅ | 해결 |
| `tool_call_count` 카운트 (messages 스캔) | — | 🟡 불안정 | ✅ state 필드 + truncate | **해결** |
| 무한/과도 도구 호출 | 🔴 평균 19/턴 | 🔴 max 110/턴 | ✅ max 30/턴, mean 7/턴 | 해결 |
| `simulate_turn` 과의존 | — | 🔴 64.7% | ✅ 20.3% | 개선 |
| 중간 배틀(15-24턴) 성능 | — | 🔴 10% | ✅ 73.7% | 개선 |
| 특수 데미지기 에러 | — | 🟡 161건(1.5%) | 🟡 158건(3.1%) | 미해결(절대량 유지) |
| switch 토큰 파싱 | — | 🟡 49건 | 🟡 18건 | 완화 |
| `get_team_analysis` 미사용 | — | 🔴 5회 | 🔴 7회 | 미해결 |
| JSON 파싱 실패 | 69% | prose fallback | 4건 (json_parse_failures) | 거의 해결 |

출처: 본 EXP 데이터 + `docs/archive/exp-027`·`exp-030` 분석 보고서.

---

## 5. 권장 개선 우선순위

| 순위 | 문제 | 근거 | 난이도 | 예상 효과 |
|------|------|------|--------|-----------|
| 1 | 특수 데미지기 처리 (P0-1) | 절대 에러 158건, `calculate_damage` 주도(53.6%)에서 신뢰도 직결 | 중 | 에러율 3.1%→<1%, 데미지 계산 신뢰성 ↑ |
| 2 | `get_team_analysis` 활성화 (P1-2) | 두 실험 모두 0% 사용 + 패배 7전 전멸 패턴 | 낮 | 잔여 관리 / 교체 결정 품질 ↑, 전멸 패배 감소 |
| 3 | switch 토큰 파싱 강화 (P1-1) | 18건 `switch*` 파싱 실패 | 낮 | fallback 복구율 ↑ |
| 4 | `dracometeor` 퍼지 매칭 (P2-1) | 오타 무브명 3건 | 낮 | 소폭 회복율 ↑ |

> 모든 권고는 범용 gen9ou 전략 관점 (ANALYSIS_MANUAL.md 6.1·6.5절). abyssal 특화 공략 없음.

---

## 6. 다음 단계

### 즉시
- [ ] `battle_tools.py` `calculate_damage` 에 특수 데미지 공식 구현 (`ruination`, `seismictoss`/`nightshade`, `painsplit`, `heavyslam`) [EXP-032]
- [ ] `common.py` `parse_action_json` 에 `^switch(.+)$` prefix 제거 정규화 추가
- [ ] `react_agent.py` `REACT_SYSTEM_PROMPT` 에 잔여 2마리 이하 시 `get_team_analysis` 사용 가이드 추가

### 후속 실험
- [ ] 위 3개 변경 적용 후 **EXP-032** (react, GLM-5.1, 동일 opponent, seed 42, N=30) — 단, 코드 변경이 복수이므로 1개씩 staged ablation 권장
- [ ] 목표: 승률 80%+, 중간 배틀 승률 75%+ 유지, 도구 에러율 <1.5%, `get_team_analysis` 사용률 3%+
- [ ] EXP-030 ↔ EXP-031 의 stopping-criteria 인과 검증: 변경 전 코드로 1배틀 재현 후 턴당 도구 호출 max 비교 (단일 변수 확인)
