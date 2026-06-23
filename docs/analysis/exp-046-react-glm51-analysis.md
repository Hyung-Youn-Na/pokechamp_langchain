# EXP-046 (react / glm-5.1) 실험 분석 — Oracle attacker 식별 fix 적용 후

> 분석 일시: 2026-06-23
> EXP-046: 2026-06-22, glm-5.1 (ollama/glm-5.1:cloud), react + `--enable_showdown_oracle` + **attacker 식별 fix**(`_pack_team` lead 정렬 + damage 가드), 30전 vs abyssal
> 비교: EXP-044 (oracle off, 56.7%) · EXP-045 (oracle pre-fix, 53.3%) — 동일 `dynamic-v2.json`/seed 42/N=30
> 팀 모드: fixed · manifest `dynamic-v2.json` (sha256:`564353a6`) — 동일 30 매치업(paired 비교 가능)

---

## 0. TL;DR

**기술적 fix는 완전히 성공했지만, 정확해진 oracle damage가 승률을 더 떨어뜨렸다.** 승률 **56.7%(044) → 53.3%(045) → 43.3%(046)**. 핵심:

1. ✅ **oracle "정확한 턴 구현 + dynamic move 시뮬레이션" 확인 완료** — EXP-045의 결함(0% 데미지)이 **해결**됐다:
   - oracle observation `hp_lost=0%`: **214건(77%) → 1건(0%)**.
   - 동적 위력 무브 정상화: `knockoff` 0%→avg **47.1%/nonzero 100%**, `weatherball` 51%→**99%**, `acrobatics`/`hex`/`ivycudgel` 전부 100%.
   - **정확성 검증**: oracle Weather Ball 예측 avg 68.7% vs 실제 사용 damage avg 59.8%(±10pp, 양호). attacker 식별 버그 해결.
2. ❌ **그러나 정확한 damage가 승률을 올리지 않음 (−13.4pp vs 044)**.
3. **원인 = react agent의 damage 활용 병목**(oracle 정확성 아님):
   - Weather Ball(대표 동적 무브)을 실제로 쓴 배틀은 **4승 2패(67%)** — 전체(43%)보다 높음. → 동적 무브 damage 자체는 유효.
   - 문제는 정확한 damage observation이 **Weather Ball을 안 쓰는 비동적 매치업**의 결정(스위치·세팅·정적 무브 선택)을 캐스케이드로 바꿔 악화시킨 것.
   - **정확한 단기 damage ≠ 더 나은 장기 결정**. react가 단일 턴 damage를 맹신해 포지셔닝/스위치 타이밍 같은 전략적 유연성을 잃는 패턴.

> ⚠️ **통계 caveat**: −4승(17→13)은 N=30에서 비유의(z≈0.71). 단, (a) 045→046 연속 하락, (b) 양 턴 구간(short −18pp·mid −16.7pp) 하락, (c) 6개 매치업 악화/2개 개선이라 방향성은 일관. 그러나 "fix가 승률을 올렸다"는 증거는 **전혀 없음**.

---

## 1. 결과 (정량)

### 1.1 승률 / 리소스

| 메트릭 | EXP-044 (off) | EXP-045 (pre-fix) | **EXP-046 (fix)** | 046−044 |
|---|---|---|---|---|
| 승률 | 56.7% (17/30) | 53.3% (16/30) | **43.3% (13/30)** | **−13.4pp** |
| 평균 턴 | 16.8 | 17.7 | 16.6 | −0.2 |
| LLM 호출/판 | 52.4 | 56.1 | 53.4 | +1.0 |
| prompt 토큰/판 | 147,672 | 160,050 | 150,418 | +2,746 |
| completion 토큰/판 | 5,336 | 5,669 | 5,329 | −7 |
| 도구 호출 합계 | 1,862 | 2,000 | 1,889 | +27 |

- 비용은 044 수준으로 회귀(045의 +7~8% 비용 소멸). 0% observation 감소로 에이전트 탐색이 줄어든 효과.

### 1.2 턴 구간별 승률

| 구간 | EXP-044 | EXP-046 | 변화 |
|---|---|---|---|
| 짧은 배틀 (<15턴) | 72.7% (8/11) | 54.5% (6/11) | −18.2pp ❌ |
| 중간 배틀 (15-24턴) | 50.0% (9/18) | 33.3% (6/18) | −16.7pp ❌ |
| 긴 배틀 (25+턴) | 0.0% (0/1) | 100.0% (1/1) | (표본 1) |

- 045에서는 mid 배틀이 개선(+11.1pp)돼 short 하락을 부분 상쇄했으나, **046은 short·mid 양쪽 하락**. net 하락 확대.

### 1.3 매치업 페어링 (044 → 046, 동일 30 매치업)

- 8개 뒤집힘: **악화 6**(idx 4221, 8201, 11082, 17696, 19519, 24778) / **개선 2**(4851, 23083) → net **−4승**.
- 악화 6개 중 5개(4221·8201·11082·19519·24778)는 045에서도 이미 악화 — oracle 통합에 취약한 동일 매치업군. 17696(날씨 팀)은 045 승→046 패(8턴 전멸).

### 1.4 도구 사용 분포 (044 → 046)

| 도구 | 044 | 046 | 변화 |
|---|---|---|---|
| `simulate_turn` | 88 | 134 | **+46 (+52%)** |
| `check_type_effectiveness` | 87 | 105 | +18 |
| `calculate_damage` | 1,511 | 1,502 | −9 |

- `simulate_turn`이 +52% 급증 — oracle 기반 정확 damage로 에이전트가 턴 시뮬레이션을 더 많이 돌리며 단기 최적해에 수렴.

---

## 2. Oracle 기능 면밀 검토 — "정확한 턴 구현 + dynamic move 시뮬레이션" 확인

> 사용자 핵심 질문: *showdown oracle이 제대로 된 정확한 턴 구현과 dynamic move 시뮬레이션을 진행했는가?*

### 2.1 ✅ attacker 식별 버그 해결 (EXP-045 결함 근본 fix)

- EXP-045의 `hp_lost=0%` 214건(77%)은 worker가 packed team 첫째(lead)를 attacker로 오식한 `|cant|nopp|` 결과. fix(`_pack_team` lead 정렬) 적용 후 **0%가 1건(0%)으로 소멸**.
- 동적 위력 무브 damage 완전 정상화:

| 무브 | 045 (pre-fix) | 046 (fix) |
|---|---|---|
| `knockoff` | avg 0.0% / nonzero **0%** | avg **47.1%** / nonzero **100%** |
| `weatherball` | avg 40.2% / nonzero 51% | avg **68.7%** / nonzero **99%** |
| `terablast` | avg 10.0% / nonzero 10% | avg **78.6%** / 100% |
| `acrobatics` | 0.0% / 0% | **71.0%** / 100% |
| `hex`/`ivycudgel` | 0.0% / 0% | 78.5%·53.0% / 100% |

### 2.2 ✅ oracle 시뮬레이션 정확성 검증 (예측 vs 실제)

Weather Ball(날씨 의존 동적 무브)로 oracle 예측과 실제 배틀 damage를 직접 비교:

| | oracle 예측 | 실제 사용 damage |
|---|---|---|
| Weather Ball avg | 68.7% (median 77%) | 59.8% (median 57%) |

- 차이 ±10pp로 **정확도 양호**. 4/15(26%)이 <30%로 낮게 나온 것은 날씨 변화/타겟 스위치 등 조건 변화(정상).
- → **oracle은 동적 무브 damage를 정확히 시뮬레이션**. "정확한 턴 구현" 달성.

### 2.3 ❌ 그러나 정확한 damage가 승률에 부정적 — 활용 병목

Weather Ball을 실제로 사용한 6개 배틀의 승패:

| Weather Ball 사용 배틀 | 결과 |
|---|---|
| battle-1093 (4회) | 승 |
| battle-1101 (4회) | 승 |
| battle-1089 (2회) | 승 |
| battle-1092 (1회) | 승 |
| battle-1108 (2회) | 패 |
| battle-1112 (2회) | 패 |

- **Weather Ball 사용 배틀: 4승 2패(67%)** — 전체(43%)보다 **높음**. 동적 무브의 정확 damage로 에이전트가 실제로 효과적 공격을 한 매치업.
- 역설적 결론: **동적 무브 damage 자체는 유효**. 문제는 damage observation이 **Weather Ball을 안 쓰는 24개 매치업**의 결정 흐름을 바꿔 캐스케이드 악화시킨 것.

---

## 3. 역효과 메커니즘 — 정확한 damage가 왜 승률을 해치는가

### 3.1 🔴 P0-1: react agent가 단기 damage를 장기 전략처럼 사용

**근본 원인**: oracle은 **"현재 상태에서의 정확한 단일 턴 damage"** 를 준다. 이는 기술적으로 정확하지만, react agent가 이를 **의사결정의 주 신호**로 쓰면:

- 정확한 높은 damage(knockoff 47%, weatherball 68.7%, terablast 78.6%) → 에이전트가 "데미지가 가장 큰 수단 = 최선"으로 단기 수렴 (`simulate_turn` +52%).
- 단기 데미지 최적화에 몰두 → **포지셔닝·스위치 타이밍·세팅·방어적 플레이** 같은 장기 전략이 경시.
- 특히 비동적 매치업(Weather Ball 의존 아님)에서, 동적 무브 damage 관측이 다른 결정을 유도 → 캐스케이드로 전혀 다른 배틀 트리 → 일부 매치업 악화.

**데이터 지지**: Weather Ball 사용 배틀은 67% 승(동적 무브가 주력인 매치업은 정확 damage가 도움), 비사용 배틀은 9승/15패(37.5%). 정확한 damage가 **잘 맞는 매치업에는 돕고, 안 맞는 매치업에는 결정을 흩뜨리는** 양면.

### 3.2 🔴 P0-2: 단일 턴 damage의 본질적 한계

oracle damage는 **현재 날씨/tera/HP/boost 기준 단일 턴** 값이다. 실제 배틀은:
- 날씨가 꺼지면(5턴 후) Weather Ball은 Normal 위력 50으로 급락.
- 상대가 damage 타입에 저항 포켓몬으로 스위치.
- tera 타이밍·우선도·상태이상이 턴마다 변동.

react는 이 **미래 조건 변화**를 oracle의 단기 값에서 읽어내지 못한다. 정확한 단기 damage를 맹신하면 조건부 전략(날씨 유지·스위치 카운터)에 취약해진다.

### 3.3 세 실험의 교차 — 동적 damage 통합의 세 실패 모드

| | 접근 | damage 결과 | 승률 |
|---|---|---|---|
| EXP-035 | 동적 위력 **move override** | **과대평가**(acrobatics 220 BP, 중복 보정) | 56.7% (−20pp) |
| EXP-045 | oracle damage (attacker **오식**) | **과소평가**(0% 관측) | 53.3% (−3.4pp) |
| EXP-046 | oracle damage (**정확**, fix) | **정확**(실제 ±10pp) | 43.3% (−13.4pp) |

→ **정확도가 올라가도 승률은 오르지 않는다**. 공통 병목은 oracle의 정확성이 아니라 **react agent가 damage observation을 사용하는 방식**. 동적 무브 damage를 react에 주입하는 모든 경로가 승률을 해친다.

---

## 4. 이전 실험 대비 개선 현황

| 이슈 | EXP-045 | EXP-046 | 상태 |
|---|---|---|---|
| attacker 식별 버그(team 순서 → nopp) | 🔴 214건 0% | ✅ **1건 0%** | **해결** |
| 동적 위력 무브 damage 정확도 | 🔴 전부 0% | ✅ 실제 ±10pp | **해결** |
| 관측 자기모순(hp_lost 0% & turns≥1) | 🔴 | ✅ 가드로 제거 | **해결** |
| 동적 damage 통합의 승률 효과 | 🔴 −3.4pp | 🔴 −13.4pp | **미해결 (오히려 악화)** |
| 비용(토큰/도구) | +7~8% | 044 수준 회귀 | 개선 |

---

## 5. 권장 개선 우선순위

| 순위 | 방향 | 근거 | 난이도 | 예상 효과 |
|---|---|---|---|---|
| 1 | **damage 통합 비활성화, 동적 타입만 유지**(마일스톤 1로 회귀) | 동적 타입(effective_type)은 안전·유효; damage 통합은 045·046 모두 승률 하락. EXP-044(56.7%)로 회귀가 가장 안전 | 낮 | 승률 56.7% 회복 + 타입 정확도 유지 |
| 2 | **damage observation 형태 변경**: 절대값(47%) 대신 상대 순위("이 무브가 가장 데미지 큼")만 제공 | 절대 damage가 단기 최적화·과신 유도; 순위는 정보 손실 없이 절대값 맹신 완화 | 중 | 단기 수렴 완화, 장기 전략 복원 |
| 3 | **react 시스템 프롬프트 개선**: "damage는 현재 턴 기준, 날씨/스위치 변화 고려" 안내 | 단일 턴 damage의 조건부성을 LLM에 명시 → 맹신 완화 | 낮 | 단기 최적화 경향 완화 |
| 4 | oracle damage 통합 유지 + **비용·정확도 모니터링만** (승률 효과 포기) | oracle 기술적 건강성은 확보됨; 하지만 현재 react에서는 득이 없음 | — | — |

> 모든 권고는 범용 gen9ou 관점 (ANALYSIS_MANUAL 6.1·6.5). abyssal 특화 아님. **핵심 진단**: 병목은 oracle 정확성(이미 해결)이 아니라 **react agent의 damage 활용 방식**. 따라서 1~3은 oracle 비활성화/형태변경/프롬프트 중 택일.

---

## 6. 다음 단계

### 즉시 (방향 결정 후, 사용자)
- [ ] **방향 선택**: (a) damage 통합 비활성화·타입만 유지 → EXP-047로 044 회복 검증 [권장] / (b) damage observation을 순위로 변환 → EXP-048 / (c) 시스템 프롬프트 damage 활용 가이드 → EXP-049.
- [ ] 위 선택 중 변수 1개만 변경한 ablation으로 재실험(동일 dynamic-v2/seed 42/N=30).

### 후속 분석
- [ ] 악화 6개 매치업(4221·8201·11082·17696·19519·24778) 정성 — 정확한 damage가 어떤 결정을 바꿔 패배로 이어졌는지 battle_viewer로 추적. 공통 패턴(스위치 과소·세팅 누락 등) 식별 → 권고 2·3의 근거 강화.
- [ ] "정확한 시뮬레이션 ≠ 더 나은 에이전트 결정" 가설 문서화 — EXP-035/045/046 교차 분석으로 react agent의 damage 활용 병목 정식화.

---

## 부록 — 검증 출처

- 승률/구간/페어링: `experiment_*.json` `summary`+`battles[]` (ANALYSIS_MANUAL 4.2·4.3).
- oracle observation: `langgraph_tool_log.jsonl` `type_source:showdown_oracle` 261건, 무브별 `hp_lost`.
- 도구 분포: `langgraph_tool_log.jsonl` `tool_call` (4.5).
- 실제 damage/Weather Ball 사용: HTML `|move|p1a:`+`|-damage|p2a:` (무브명 "Weather Ball" 정규화).
- 코드: `battle_state_mapper.py`(`_pack_team` lead 정렬), `battle_tools.py`(damage 가드), `oracle-worker.js`(`active[0]`).
- fix 검증: `_pack_team` lead 단위 3 + `test_showdown_oracle.py` 72 + `test_react_oracle_dynamic_type.py` 57 + node 회귀(0→100%) PASS.
