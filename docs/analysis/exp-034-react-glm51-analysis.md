# EXP-034 (react / glm-5.1) 실험 분석

> 분석 일시: 2026-06-17
> EXP-034: 2026-06-16, glm-5.1 (ollama/glm-5.1:cloud), react, 30전 vs abyssal
> 비교: EXP-031 / baseline `react-glm51` (react, glm-5.1) — 동일 조건(glm-5.1, temp 0.3, seed 42, N=30, opponent abyssal)

---

## 0. TL;DR

**안 A(BUDGET 힌트 정밀화) 채택.** 도구 사용 후반(3·4회째)에 runtime HumanMessage nudge
("이 도구가 결정을 바꿀까? 아니면 지금 JSON 출력")를 주입해, **승률 76.7%(23/30)을 baseline과 동일하게
유지하면서 비용을 대폭 절감**했다.

| 신뢰 메트릭 | baseline(031) | EXP-034 | 변화 |
|---|---|---|---|
| 승률 | 76.7% (23/30) | 76.7% (23/30) | **유지** ✅ |
| LLM 호출/판 | 119.1 | 73.3 | **−38.5%** ✅ |
| prompt 토큰/판 | 357,737 | 207,629 | **−42.0%** ✅ |
| 응답 시간/판 | 426.3s | 241.9s | **−43.2%** ✅ |
| 조기 종료율(<5 calls) | 34.3% | 80.1% | **+45.8pp** ✅ |

> ⚠️ **메트릭 버그 주의**: experiment JSON의 `battles[].turns`(33.8)와 `battles[].won`(합=30)은
> 메트릭 수집 버그(latest_battle running-max 재사용)로 **무효**. **§3 참조.** 보고된 "+9.4턴"은 이 버그의
> 인공값이며, replay 복원 실제 평균 턴은 **22.6**(baseline 24.4 대비 오히려 −1.8턴).

---

## 1. 실험 결과 비교

### 1.1 승률 (showdown-engine `|win|` authoritative)

`summary.win_rate`는 `player.n_won_battles`(showdown 엔진이 `|win|` 메시지로 설정, `abstract_battle.py:916-921`) 기반이라 신뢰.

| 구간 | EXP-034 (실측 replay 턴) | 비율 |
|---|---|---|
| **전체** | **76.7% (23/30)** | — |
| 짧은 (<15턴) | 1판(14턴) | 표본 미미 |
| 중간 (15-24턴) | 19판 | 다수 |
| 긴 (25+턴) | 10판 | 다수 |

> 구간별 승률은 replay-faint 역추론(react가 event loop를 sync-block해 `|win|`이 replay HTML에 안 써짐)으로는
> 신뢰할 수 없어 표에서 제외. showdown 카운터(23W/7L)만 authoritative.

### 1.2 리소스 사용량 (per-call delta 합으로 검증 — 신뢰)

| 항목 | EXP-034 | baseline(031) | 변화율 |
|---|---|---|---|
| 배틀당 LLM 호출 | 73.3건 | 119.1건 | **−38.5%** |
| 턴당 LLM 호출 | ~3.2건 | ~4.9건 | −34.7% |
| 배틀당 prompt 토큰 | 207,629 | 357,737 | **−42.0%** |
| 배틀당 completion 토큰 | 7,394 | 11,610 | −36.3% |
| 배틀당 총 토큰 | 215,023 | 369,347 | −41.8% |
| 응답 시간/판 | 241.9s | 426.3s | −43.2% |
| JSON 파싱 실패 | 1회 | 4회 | 완화 |

> 검증: `prompt`/`completion` 토큰은 `langgraph_llm_log.jsonl`의 per-call `token_usage` 합과 **정확히 일치**.
> `llm_calls`는 `llm_log` 2200행 / 30 = 73.33 = summary와 일치(per-battle 카운터, 신뢰).

### 1.3 도구 사용 분포 (`langgraph_tool_log.jsonl`)

| 도구 | EXP-034 | 비율 | baseline(031) | 비율 | 절대 변화 |
|---|---|---|---|---|---|
| `calculate_damage` | 1,700 | **69.6%** | 2,771 | 53.6% | −1,071 (비중 ↑) |
| `simulate_turn` | 336 | 13.8% | 1,050 | 20.3% | **−68%** |
| `predict_opponent_moves` | 127 | 5.2% | 247 | 4.8% | −49% |
| `check_type_effectiveness` | 126 | 5.2% | 613 | 11.9% | **−79%** |
| `analyze_matchup` | 66 | 2.7% | 159 | 3.1% | −58% |
| `evaluate_position` | 61 | 2.5% | 256 | 5.0% | **−76%** |
| `get_move_details` | 18 | 0.7% | 71 | 1.4% | — |
| `get_team_analysis` | 7 | 0.3% | 7 | 0.1% | — |
| **합계** | 2,441 | | 5,174 | | **−52.8%** |

안 A가 퇴행적·중복 도구 호출을 절단하면서 **모든 도구의 절대 사용량이 감소**했고, 특히 비용이 큰
`simulate_turn`/`check_type`/`evaluate_position`이 −68~−79%로 크게 줄었다. 비중만 보면 `calculate_damage`가
단일화되는 경향(69.6%).

---

## 2. 핵심 발견

### 2.1 안 A의 조기 종료 메커니즘이 의도대로 작동했다

| 지표 | baseline | EXP-034 | 비고 |
|---|---|---|---|
| 조기 종료율(한 턴 도구 <5) | 34.3% | **80.1%** | +45.8pp — 안 A 효과 직접 신호 |
| hint zone 정지율(3·4회째 도구 후 중단) | 19.7% | **57.6%** | **~3배 증가** — 힌트 발동 구간에서 멈춤 |
| 히스토그램 peak | 5+ cluster(477) | **3-4 band**(388) | 도구 수 분포 이동 |

안 A nudge는 `tool_call_count >= 2 and remaining <= 2`(= 3번째 도구 호출 시점)에서 발동하며,
실제로 LLM이 그 구간에서 도구 호출을 멈추고 JSON 결정으로 넘어가는 비율이 3배 늘었다.
**새 system instruction 추가 없이** runtime `HumanMessage`만 바꿔 EXP-002~004의 prompt-bloat 역효과 함정을 회피했다.

### 2.2 비용 절감 + 승률 유지의 인과

결정적 정보(OHKO calc, matchup)는 보통 1~2번째 도구에서 이미 얻는다. 그 뒤의 3~5번째 도구는
중복 확인·퇴행적 반복인 경우가 많았고, 안 A nudge가 이를 잘라냈다.
LLM 호출 −38.5% → messages 누적 감소 → 입력 토큰 −42% · 응답 시간 −43%로 이어졌다.
승률이 유지된 이유: (a) 핵심 정보는 도구 1~2회로 확보, (b) nudge는 도구 사용을 금지하지 않고
'결정을 바꿀지 자문'만 하므로 필요하면 더 씀.

### 2.3 미해결: 시뮬레이터 오답에 대한 비판적 검증 부족 (승률 상한의 진짜 원인)

패배 7판의 도구 사용량(2.6~3.2 calls/턴)은 승리 23판(2.3~3.4 calls/턴)과 **통계적으로 겹친다** —
즉 안 A의 비용 절감은 승패를 좌우하지 않는다. 진짜 패인은 도구 **횟수**가 아니라 도구 **결과의 정확도**에
대한 비판적 검증 부족(§3 P0-1).

---

## 3. 메트릭 수집 버그 진단 (결론에 영향) ★

`scripts/battles/local_1v1_langchain.py` L370-405 에 2개 확증 버그. **EXP-034 결과 해석에 필수.**

### 🔴 P0-0: `battles[].won` · `battles[].turns` 무효 (latest_battle running-max 재사용)

```python
# L370-378 — 버그: 매 i마다 player.battles(누적 dict)에서 max-turn battle 선택
latest_turn = 0
for tag, b in player.battles.items():
    if b.turn > latest_turn:        # ← 역대 최대 turn 배틀 = latest
        latest_turn = b.turn; latest_battle = b
won = 1 if (latest_battle and latest_battle.won) else 0
turns = latest_battle.turn          # ← 역대 최대 turn (실제 i번째 배틀 턴이 아님)
```

| 증상 | EXP-034 | 의미 |
|---|---|---|
| `won` 합 | 30 (전부 1) | summary.wins=23과 충돌 → **won 불신뢰** |
| `turns` 고유값 | 31×12, 32×7, 38×11 (단 3개) | 러닝맥스 단계값 → **실제 분포 아님** |
| `summary.avg_turns` | 33.8 | 버그값 배열의 평균 → **무효** |

**실제 평균 턴 = 22.6** (replay HTML 30개의 `|turn|N` max + `llm_log` battle_tag별 max turn, 양쪽 일치).
baseline `react-glm51`은 **이 버그가 없는 구 snapshot**(meta block 이전 커밋)이라 won 합=23=summary 정상,
turns 17개 고유값 정상분포, 보고 avg_turns 24.4 = 실제.

→ **"+9.4턴" = 33.8(버그) − 24.4(정상 baseline)**. 안 A가 게임을 늘린 것이 아님. 실제로는 22.6 vs 24.4 = **−1.8턴(−7.4%)**.

**신뢰 메트릭** (delta/카운터 기반, per-call 합으로 검증): `win_rate`, `avg_llm_calls`, `avg_prompt_tokens`,
`avg_completion_tokens`, `avg_time`. **무효 메트릭**: `battles[].won`, `battles[].turns`, `summary.avg_turns`.

**개선 방안**: L370-378을 직전 종료 배틀 객체 추적(`player.n_finished_battles` 인덱스 또는 battle_tag 시간순)으로
수정. 본 보고서 작성과 함께 별도 fix 진행(§6). `local_1v1.py` 동일 버그 확인 후 같이 fix.

### 🔴 P0-1: 시뮬레이터 오답에 대한 맹신 (패배 7판의 공통 패인)

| 항목 | EXP-034(패배 7판) | 근거 battle_tag |
|---|---|---|
| 거짓 OHKO 보고 | calc "100% HP lost, guaranteed OHKO" → 실제 19% | 731 |
| 속도/내구 오판 | "Dragonite outspeeds(259>255), Earthquake KO first" → 실제 Basculegion Ice Fang OHKO | 738 |
| 시뮬레이션 매몰 | simulate_turn "Knock Off fails" 반복 → 실제 Moonblast 연속 KO | 747 |

**근본 원인**: `calculate_damage`/`simulate_turn`의 결과(특히 OHKO 보장, 속도 순서, protect 성공)를 LLM이
비판 없이 수용. 731에서는 LLM이 t11에 "historical data shows Ivy Cudgel only 19%"라 **스스로 의심**했음에도
calc의 "100%"를 신뢰해 Ivy Cudgel을 고집했다.

**개선 방안**: 안 A와 직교하는 **시뮬레이터 self-verification** — 동일 calc가 반복 보고하는 OHKO/극단적 결과에
대해 historical/replay 기반 의심 트리거. (후속 안 B 후보 — 단, 이는 도구 횟수와 무관하므로 안 A를 기각할 근거 아님)

### 🟡 P1-1: 도구 믹스의 `calculate_damage` 단일화

`calculate_damage` 비중 53.6% → 69.6%. 비-calc 도구(simulate_turn/check_type/evaluate_position) 절대
사용량이 −68~−79%로 줄면서 도구 믹스가 calc 중심으로 좁아졌다. 팀 수준 분석(`get_team_analysis` 0.3%,
`analyze_matchup` 2.7%)은 EXP-031에서도 낮았고 본 실험에서도 개선 없음 — 장기 전략·교체 결정 품질의
잠재적 상한.

**개선 방안**: 후반 도구 가이드에 범용 "교체 결정 시 matchup/team 분석 우선" 힌트(단, §0-1 범용성, prompt-bloat 주의).

---

## 4. 이전 실험 대비 개선 현황

| 이슈 | EXP-031(baseline) | EXP-034 | 상태 |
|---|---|---|---|
| 무한/과도 도구 호출 | 🟡 턴당 ~5회 | ✅ 턴당 ~3.2회 | **해결** |
| simulate_turn 과의존 | ✅ 19% (이미 완화) | ✅ 13.8% | 유지·개선 |
| 도구 사용 비용 | 🔴 357k token/판 | ✅ 208k/판 | **해결** |
| 응답 지연 | 🟡 426s/판 | ✅ 242s/판 | **해결** |
| JSON 파싱 실패 | 🟡 4회 | ✅ 1회 | 완화 |
| 시뮬레이터 오답 맹신 | 🔴 (731/738/747) | 🔴 동일 | **미해결** |
| 팀 수준 분석 미사용 | 🔴 0.1% | 🔴 0.3% | 미해결 |
| **메트릭 수집 버그** | — (구 snapshot, 정상) | 🔴 EXP-034에만 | **신규 발견·fix 예정** |

---

## 5. 권장 개선 우선순위

| 순위 | 문제 | 근거 | 난이도 | 예상 효과 |
|---|---|---|---|---|
| 1 | **메트릭 수집 버그 fix** (won/turns) | EXP-034 절대값 무효, 향후 실험 신뢰성 | 낮 | turns/won 절대값 회복 |
| 2 | **시뮬레이터 self-verification** (안 B 후보) | 패배 7판 공통 패인(731/738/747), 도구 횟수와 무관 | 중 | 승률 상한 해소 — 80%+ 도달 레버 |
| 3 | 팀/matchup 분석 활성화 | 두 실험 모두 <3% | 낮~중 | 교체 결정 품질 ↑ |

> 모든 권고는 범용 gen9ou 전략 관점. abyssal 특화 아님.

---

## 6. 다음 단계

### 즉시 (본 보고서와 함께)
- [x] 메트릭 수집 버그 fix (`local_1v1_langchain.py` L370-405, `local_1v1.py` 동일) — 별도 커밋
- [x] 안 A 코드(`react_agent.py`) 커밋 + `backups/code_state/EXP-034` 보존
- [x] `active/` → `archive/` 이동

### 후속 실험 (EXP-035 권고)
- [ ] **안 B: 시뮬레이터 self-verification** — 안 A(budget hint)와 직교. 동일 calc가 반복 보고하는
      극단적 결과(OHKO 100%, 속도 역전)에 대해 의심/교차검증 유도. baseline `react-glm51` 대비 변수 1개.
- [ ] 목표: 승률 80%+, 비용 208k token/판 유지, 시뮬레이터 오답 매몰 감소

---

## 부록 A — 신뢰 메트릭 검증 증거

- `summary.win_rate=76.7` ↔ `player.n_won_battles=23` (`player.py:1313`, showdown `|win|` authoritative)
- `avg_prompt_tokens=207629` ↔ `llm_log` per-call `token_usage.input_tokens` 합 정확 일치 (delta 기반)
- `avg_completion_tokens=7394` ↔ per-call `output_tokens` 합 일치
- `avg_llm_calls=73.3` ↔ `llm_log` 2200행 / 30 = 73.33 (per-battle 카운터)
- 실제 avg_turns=22.6 ↔ replay HTML `|turn|N` max(30개) + `llm_log` battle_tag max turn (양쪽 일치)

## 부록 B — 패배 7판 정성 타임라인

- **731**: calc "Ivy Cudgel 100% HP lost, guaranteed OHKO on Alomomola" 반복 보고. t11 LLM이
  "historical data shows only 19%"라 의심했으나 calc 신뢰 → Ivy Cudgel 고집 → 실제 19%만, Alomomola 생존,
  paralysis 25% 리스크 겹쳐 패배.
- **738**: t13 LLM "Dragonite outspeeds (259 vs 255), Earthquake will KO first" → earthquake 결정.
  실제 replay t13에서 Basculegion Ice Fang이 Dragonite를 OHKO (calc 속도/내구 오답).
- **747**: t15-17 simulate_turn "Knock Off fails / Glscor faints before moving" 반복. Iron Valiant(13% HP)에
  Knock Off 93% calc가 있었으나 Protect→Knock Off로 미련 → 실제 Moonblast 연속 KO.

공통점: 결정적 턴에서 calc/simulate_turn의 **잘못된 결과**(거짓 OHKO, 속도 순서, protect 성공)를 맹신하고
검증 없이 같은 판단 반복. 도구 부족이 아니라 **도구 결과 비판적 검증 부족**.
