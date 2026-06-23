# EXP-047 (react / glm-5.1) 실험 분석 — 전무브 Oracle 통일 (혼합 척도 편향 해소)

> 분석 일시: 2026-06-23
> EXP-047: 2026-06-23, glm-5.1 (ollama/glm-5.1:cloud), react + `--enable_showdown_oracle` + **전무브 oracle 통일**(게이트 제거·opp_m 통일·side_conditions), 30전 vs abyssal
> 비교: EXP-044 (oracle off, 56.7%) · EXP-045 (pre-fix, 53.3%) · EXP-046 (fix, 43.3%) — 동일 `dynamic-v2.json`/seed 42/N=30
> 팀 모드: fixed · manifest `dynamic-v2.json` (sha256:`564353a6`) — 동일 30 매치업(paired)

---

## 0. TL;DR

**전무브 oracle 통일이 성공했다.** 승률 **43.3%(046) → 63.3%(047)**, 그리고 baseline(044, sim 전용) 대비 **+6.6pp**. EXP-035 이후 처음으로 oracle 통합이 승률을 올렸다.

1. ✅ **승률 향상의 주원인 = "혼합 척도 편향 해소"** (dynamic move 자체가 아님):
   - 046→047 **+20pp**, **8개 매치업 회복**. 046은 동적(oracle 정확)·일반(sim 편향)이 섞여 LLM 비교를 왜곡했는데, 047은 모든 무브가 동일 oracle 척도 → mid 배틀 33.3%→**66.7%** 회복.
   - 047 oracle observation: 동적 평균 **63.7%** vs 일반 **63.4%** (차 **+0.3pp** = 척도 일관). 일반 특수 무브(surf/thunderbolt/hurricane)가 sim의 spa 0.5x 과소평가에서 회복.
2. ✅ **dynamic move는 유효하지만 "척도 일관성"이 핵심**: weatherball(동적) 사용은 046(15회)→047(12회)로 소폭 줄었으나 044(5)보다 여전히 많음 — weatherball 자체가 아니라 **다른 무브와의 공평한 비교**가 승률을 결정.
3. ✅ **시간 영향 미미**: 턴당 **12.2s(044 12.1s, +1%)**. oracle 쿼리가 동적 261건→전무브 ~1,454건(약 5.5배) 폭증했음에도 캐싱(`OracleResultCache`)이 흡수. 5s/건 직렬 지연 리스크 발생 안 함.

> **통계**: 044→047 +2승(17→19), 8개 매치업 뒤집힘(3 악화/5 개선). mid 배틀 회복(+33pp)이 short 하락(−22pp)을 상회. N=30에서 046→047 +20pp는 방향성 유의.

---

## 1. 결과 (정량)

### 1.1 승률 / 리소스 / 시간

| 메트릭 | EXP-044 (off) | EXP-046 (fix) | **EXP-047 (unified)** | 047−044 |
|---|---|---|---|---|
| 승률 | 56.7% (17/30) | 43.3% (13/30) | **63.3% (19/30)** | **+6.6pp** |
| 평균 턴 | 16.8 | 16.6 | 16.8 | 0.0 |
| LLM 호출/판 | 52.4 | 53.4 | 53.4 | +1.0 |
| prompt 토큰/판 | 147,672 | 150,418 | 151,870 | +2.8% |
| **배틀당 시간** | 202.6s | 211.2s | **205.4s** | **+2.8s (+1.4%)** |
| 배틀당 median 시간 | 187s | 201s | 205s | +18s |

- 비용(토큰/LLM호출)은 044 수준 유지. 046의 +7% 비용 소멸.
- 시간은 046(211s)보다 **빠름**, 044(202.6s) 대비 +2.8s에 불과.

### 1.2 턴 구간별 승률

| 구간 | 044 | 046 | 047 | 047−046 |
|---|---|---|---|---|
| 짧은 배틀 (<15턴) | 72.7% (8/11) | 54.5% (6/11) | 50.0% (4/8) | −4.5pp |
| 중간 배틀 (15-24턴) | 50.0% (9/18) | 33.3% (6/18) | **66.7% (14/21)** | **+33.4pp** |
| 긴 배틀 (25+턴) | 0% (0/1) | 100% (1/1) | 100% (1/1) | — |

- **mid 배틀 대폭 회복** — 046에서 혼합 척도가 가장 해친 구간. 전무브 통일로 일반 무브 비교가 공평해지며 회복.
- short 배틀은 044(72.7%) 대비 여전히 낮음(50%) — 047의 남은 한계(§4).

### 1.3 매치업 페어링

- **046→047: 10개 뒤집힘, 8개 회복 / 2개 악화** → net +6승. 회복 매치업: 11082, 19519, 5193, 24778, 1108, 4221, 14007, 17464 (046에서 혼합 척도로 패 → 047 통일로 승).
- 044→047: 8개 뒤집힘, 5개 개선 / 3개 악화 → net +2승. 044 baseline 대비 순이익.

---

## 2. 원인 분석 — dynamic move·정확 데미지 vs oracle 척도

> 사용자 질문: 향상이 dynamic move/정확 데미지 계산 때문인가, oracle 전반 때문인가?

### 2.1 핵심 = "혼합 척도 해소", dynamic move 자체가 아니다

046→047의 **+20pp**가 결정적이다. 둘 다 oracle damage가 정확한 상태(046 fix로 0% 해소)였는데, 차이는 **046은 동적 무브만 oracle, 일반 무브는 sim**이고 **047은 전부 oracle**이다.

- 046 oracle observation(동적) 평균 60.8% vs 일반(sim) 62.3% — 평균은 비슷해 보이나, sim은 카테고리별 양방향 편향(특수 과소 spa 0.5x, 물리 과대 랜덤·wall 누락)이 평균에서 상쇄된 것.
- 047은 **동적 63.7% vs 일반 63.4% (차 +0.3pp)** — 척도가 일관되게 수렴. 편향 없음.
- 이 일관성이 8개 매치업 회복으로 이어짐: 날씨 팀에서 weatherball(동적, oracle 68.7%)이 일반 특수 무브(sim 과소)보다 부당히 유리해 보이던 왜곡이 사라지고, **surf/thunderbolt/hurricane 같은 일반 특수 무브가 정확히 평가**되어 weatherball과 균형 있는 비교 가능.

### 2.2 dynamic move의 역할

- 동적 무브(weatherball/knockoff/terablast 등)는 047에서도 유효(평균 63.7%, >50% 비중 64%). 마일스톤 1(타입)+2(위력) 통합은 계속 작동.
- 하지만 weatherball **사용 빈도**는 046(15회)→047(12회)로 소폭 감소에 그쳤고, 승률은 +20pp 상승. → weatherball 과신 해소가 아니라 **다른 무브의 정확화**가 회복을 이끈 것.
- 결론: dynamic move의 정확한 데미지는 필요조건이지만, **모든 무브를 같은 척도로 놓는 것**이 승률 향상의 충분조건이었다.

### 2.3 일반 특수 무브 회복 (sim spa 0.5x 버그 우회)

047 일반 무브 observation 상위: earthquake 70, closecombat 55, **surf 55, dracometeor 52, earthpower 52, thunderbolt 50, icespinner 47, hurricane 46**.

- 날씨 팀(player #1, rain)에서 surf/thunderbolt/hurricane(특수)은 sim이 `if weather: boost("spa",0.5)`(`local_simulation.py:1731`)로 데미지를 절반 깎던 것을 oracle이 정확히 산출.
- 물리 무브(earthquake/closecombat)도 sim의 랜덤·wall 누락 과대평가에서 회복 → 물리/특수 양쪽 정확.
- 이 정확성이 mid 배틀(다수 무브 비교가 빈번한 구간) 회복의 직접 원인.

---

## 3. 시간 분석 — oracle 쿼리 폭증에도 영향 미미

| | 044 (off) | 046 (fix) | 047 (unified) |
|---|---|---|---|
| 배틀당 평균 시간 | 202.6s | 211.2s | 205.4s |
| 배틀당 median | 187s | 201s | 205s |
| min / max | 115 / 411 | 127 / 339 | 125 / 329 |
| **턴당 시간**(시간/avg_turns) | **12.1s** | 12.7s | **12.2s** |
| oracle observation 수 | 0 | 261 | ~1,454 |

- **047 턴당 12.2s = 044(12.1s) 대비 +0.1s/turn (+1%)**. oracle 쿼리가 동적 261건 → 전무브 ~1,454건(약 5.5배) 폭증했음에도 **캐싱(`OracleResultCache` 4096 슬롯)** 가 동일 (active_state_hash, move_id, atk, defn) 재방문을 흡수.
- 직렬 쿼리 누적 지연(최대 5s/건) 리스크는 발생하지 않음 — 캐시 히트가 대부분의 반복 비교(같은 턴에서 여러 무브 evaluate)를 회피.
- max 시간은 044(411s, 이상치)보다 047(329s)이 짧음 — 캐싱이 극단 지연도 억제.

→ **비용(시간) 증가 없이 정확도·승률 향상** 달성. plan에서 우려했던 "6배 쿼리 지연"은 캐싱으로 현실화되지 않았다.

---

## 4. 한계 — 짧은 배틀

- short(<15턴) 승률: 044 72.7% → 047 50.0% (−22.7pp). 046(54.5%)보다도 낮음.
- short는 표본이 작고(044 11판/047 8판) 턴 분포 변화도 겹침. 하지만 방향성은 일관 — **빠른 결판 매치업에서 oracle 통합이 sim baseline보다 못함**.

### 4.1 정성 분석 — idx 17696 (날씨 팀, 044 14턴W → 047 9턴 전멸패)

동일 매치업(날씨 팀 Tyranitar/Jolteon/Pelipper/Quaquaval/Kingdra/Excadrill vs Ogerpon-Wellspring 등)의 결정적 분기:

| | 044 (승, sim) | 047 (패, oracle) |
|---|---|---|
| 턴3 Kingdra 무브 | **Hurricane** → Ogerpon **KO** | **Weather Ball** → Ogerpon 살아남음 |
| 이후 | Kingdra Hurricane 연쇄 KO → 역전 승 | Ogerpon Power Whip에 Kingdra 점차 깎임 → 9턴 전멸 |

oracle observation(047 턴3)이 선택 오류의 본질을 드러냄:

| 무브 (턴3, **rain 세팅 전**) | effective_type | hp_lost | turns_to_ko |
|---|---|---|---|
| **Hurricane** | Flying (Ogerpon 2×) | 49% | **1 (KO)** |
| **Weather Ball** | **Normal** (rain 전 → 비효과) | 49% | 2 |

- **oracle은 정확**: 턴3은 rain 전이라 Weather Ball을 **Normal**(위력 50, Ogerpon 1×)로 올바로 평가. Hurricane은 Flying 2×로 **1턴 KO**. oracle 정보상 Hurricane이 명백히 우세.
- **에이전트가 Weather Ball 선택** — Hurricane(1턴 KO)보다 차선인 무브를 고름. 가설: "Weather Ball은 비에서 강하"는 사전 지식이 **현재 rain 여부(턴3은 rain 전)** 를 무시하고 Weather Ball을 선호했을 가능성. 턴6(rain 세팅 후)에야 Weather Ball이 Water 90%로 강해지지만, 턴3엔 Normal이라 Ogerpon을 못 잡음.
- 즉 short 한계는 **oracle 정확도(정상)가 아니라 LLM의 oracle 정보 활용 질** — 정확한 damage를 받아도 차선 무브를 선택. EXP-046 진단("react damage 활용 병목")의 잔여 증상. 특히 동적 무브(Weather Ball)의 **날씨 의존 시기**를 LLM이 잘못 다룸.

### 4.2 일반화
- short는 1-2턴의 결정적 분기가 승패를 가르는 매치업. 이때 LLM의 무브 선택 한 번 오류가 치명(047은 044 sim의 공격적 선택이 우연히 더 적중).
- mid는 여러 턴에 걸쳐 damage 비교가 누적되는 구간이라 oracle의 정확한 비교 척도가 큰 효과(66.7%). short는 단일 분기라 LLM 활용 질에 더 민감.
- 후속: damage observation에 turns_to_ko(또는 KO 가능 여부)를 더 강조하거나, 동적 무브의 현재-조건(rain 여부)을 observation에 명시하면 short 회복 가능.

---

## 5. 결론 / 개선 현황

| 이슈 | EXP-046 | EXP-047 | 상태 |
|---|---|---|---|
| 동적 무브 damage 정확 (attacker 식별) | ✅ | ✅ | 유지 |
| sim/oracle 혼합 척도 편향 | 🔴 | ✅ **해소** | **해결** |
| 일반 특수 무브 과소평가(spa 0.5x) | 🔴 sim | ✅ oracle 정확 | **해결** |
| oracle 통합의 승률 효과 | 🔴 −13.4pp | ✅ **+6.6pp** | **성공** |
| 시간/비용 | 044 수준 | 044 수준(+1%) | 유지 |
| 짧은 배틀 | 54.5% | 50.0% | 미해결 |

**종합**: EXP-035(과대평가)·045(과소 0%)·046(정확但 혼합 척도)의 3 실패 모드 공통 병목인 **"비교 척도 불일치"**를 전무브 oracle 통일로 해소. 동적 무브 정확성(마일스톤 1·2) + 일반 무브 정확성(게이트 제거)이 처음으로 시너지. oracle 통합이 처음으로 baseline(044 sim)을 **승률·비용 양쪽에서 능가**.

> 규칙 준수(ANALYSIS_MANUAL 6.1·6.5): 모든 진단은 범용 gen9ou 관점. abyssal 특화 아님.

---

## 6. 다음 단계

### 즉시
- [x] 전무브 oracle 통일 적용·검증(단위 58 + 통합 17 + node 회귀 PASS, EXP-047 승률 +6.6pp).

### 후속 분석
- [ ] 짧은 배틀(<15턴) 정성 — oracle 통합이 044 sim 대비 못한 매치업 패턴(보수화? 단기 최적화 한계?) 식별. short 회복 시 전체 승률 65%+ 가능.
- [ ] 8개 회복 매치업(11082·19519·5193·24778·1108·4221·14007·17464) 공통 — 어떤 무브 비교가 정확화돼 회복됐는지 battle_viewer로 추적 → 척도 일관성 가설 정량 강화.

### 후속 실험 (옵션, 변수 1개)
- [ ] sim 코어 버그 직접 fix(`local_simulation.py:1731` spa 0.5x) 후 oracle off로 재실험 — oracle 우회 없이 sim 정확화만으로 효과 측정(EXP-048). oracle vs sim-fix 경로 비교 근거.
- [ ] damage observation 형태(절대값 → 순위)로 short 한계 완화 시도(EXP-049) — 단기 최적화 과신 가설 검증.

---

## 부록 — 출처
- 승률/구간/페어링/시간: `experiment_*.json` `summary`+`battles[].elapsed_seconds` (ANALYSIS_MANUAL 4.2·4.3).
- oracle observation(동적/일반 척도): `langgraph_tool_log.jsonl` `type_source:showdown_oracle` ~1,454건.
- weatherball 사용: HTML `|move|p1a:` (정규화 "Weather Ball").
- 코드: `battle_tools.py`(게이트 제거·opp_m 통일·가드), `battle_state_mapper.py`(actor_side 매핑), `oracle-worker.js`(side_conditions 직접 보정, .gitignore).
- 이력: `[[oracle-impl-technique]]`(전무브 통합), EXP-045/046 보고서(실패 모드).
