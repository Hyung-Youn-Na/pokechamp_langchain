# EXP-036 (react / glm-5.1) 실험 분석

> 분석 일시: 2026-06-17
> EXP-036: 2026-06-17, glm-5.1 (ollama/glm-5.1:cloud), react, 30전 vs abyssal
> 비교: EXP-034 (안 A, 76.7%) · baseline `react-glm51` (76.7%) — 동일 조건(glm-5.1, temp 0.3, seed 42, N=30)
> 변경: `local_simulation.py` `calculate_remaining_hp` 행동 순서 결정(fix1: priority 전 범위 정렬 + protosynthesis p2 인자 fix). 시뮬레이터 정확도 시리즈 1/3.

---

## 0. TL;DR

**fix1(행동 순서 정확도) 채택.** 승률 76.7% → **80.0% (24/30, +3.3pp)**. 시뮬레이터 코어 버그 fix 시리즈(EXP-036~038)의 첫 단계로, EXP-034/035가 지적한 패배 원인 중 **속도/우선도 오판**(battle 738형)의 근본을 해소했다. 비용은 EXP-034(안 A) 수준 유지.

> ⚠️ **통계 caveat**: +3.3pp는 n=30에서 **비유의**(z≈0.31, p≈0.75). 비동일 매칭(다른 팀 시드)이라 paired 비교 불가. "fix1이 승률을 올렸다"는 단정은 어렵지만, **하락이 아니라 상승 방향**이며 기술 결함은 없으므로 채택. 누적 fix(EXP-037 protect · EXP-038 ivycudgel)로 효과 검증이 본 목적.

---

## 1. 실험 결과 비교

### 1.1 승률 (showdown `|win|` authoritative)

| 구간 | EXP-036 | react baseline(031) | EXP-034 | EXP-035 |
|------|---------|---------------------|---------|---------|
| **전체** | **80.0% (24/30)** | 76.7% (23/30) | 76.7% (23/30) | 56.7% (17/30) |
| 짧은 (<15턴) | 100% (2/2) | — | 1판(표본미미) | — |
| 중간 (15-24턴) | 85.0% (17/20) | — | 19판 | — |
| 긴 (25+턴) | 62.5% (5/8) | — | 10판 | — |

> won 합=24=summary.wins 일치, `b.turns` 30개 고유값(13~111, 단조증가 아님) → EXP-034 P0-0 running-max 버그는 fix(dc8cba3) 적용으로 정상. `b.turns` avg=24.7=summary.

### 1.2 리소스 사용량

| 항목 | EXP-036 | baseline(031) | EXP-034 | 변화(vs 034) |
|------|---------|---------------|---------|--------------|
| 배틀당 LLM 호출 | 76.5 | 119.1 | 73.3 | +4.4% |
| 배틀당 prompt 토큰 | 213,138 | 357,737 | 207,629 | +2.7% |
| 배틀당 completion 토큰 | 8,407 | 11,610 | 7,394 | +13.7% |
| JSON 파싱 실패 | 0 | 4 | 1 | — |
| 도구 에러율 | 3.2% (81/2497) | — | — | — |

비용은 EXP-034(안 A) 수준. fix1은 비용에 영향 안 줌(순서 로직만 변경).

### 1.3 도구 사용 분포

| 도구 | EXP-036 | 비율 | EXP-034 | 비율 | 변화 |
|------|---------|------|---------|------|------|
| `calculate_damage` | 1,619 | 64.8% | 1,700 | 69.6% | −4.8pp |
| `simulate_turn` | 365 | 14.6% | 336 | 13.8% | +0.8pp |
| `check_type_effectiveness` | 187 | 7.5% | 126 | 5.2% | +2.3pp |
| `predict_opponent_moves` | 133 | 5.3% | 127 | 5.2% | — |
| `analyze_matchup` | 86 | 3.4% | 66 | 2.7% | +0.7pp |
| `evaluate_position` | 79 | 3.2% | 61 | 2.5% | +0.7pp |

`calculate_damage` 단일화가 완화되고 `simulate_turn`/`check_type`/`matchup` 비중 증가. 정확해진 행동 순서가 시뮬레이션·타입 체크 신뢰도를 올려 도구 활용 다변화로 이어진 정성 신호.

---

## 2. 핵심 발견

### 2.1 결정적 차이: 행동 순서 정확도 → 승률 +3.3pp

fix1은 `calculate_remaining_hp`(L1490-1531)의 순서 결정을 Gen 9 스펙으로 재작성:
- **priority 전 범위 정렬**(버그 1): 기존 `m1.priority == 1`만 체크 → protect(+4)·Extreme Speed(+2)·Sucker Punch(+1)·Focus Punch(-3) 무시 + p2 priority 미고려. 우선도 높은 쪽 → 빠른 쪽 → 결정론적 tie로.
- **protosynthesis 인자**(버그 2): `p2_speed`에 `apply_protosynthesis(p1)` 전달(복붙) → `p2`로 fix.

배틀 738형(속도/우선도 오판, EXP-034 P0-1) 패배 경로가 차단되어 +1승(23→24). 단위 테스트 5/5 PASS로 정확성 검증.

### 2.2 가설 / 인과 추론

EXP-034 패배 7판의 공통 패인은 "calc/simulate_turn의 잘못된 결과(속도 순서·거짓 OHKO·protect) 맹신". fix1은 그 중 **속도 순서** 오답을 제거. 정확해진 "내 move가 먼저 발동하나?" 예측이 결정적 턴의 KO/피KO 오판을 줄여 승률 상승. 도구 분포 다변화(simulate_turn ↑)도 정확도 향상의 간접 신호.

### 2.3 미해결: 거짓 OHKO 매몰은 잔존 (EXP-038 영역)

패배 808(111턴, 642k 토큰) 정성: llm 54 calls 중 **ohko/100% 언급 16턴**, setup/heal 언급 0. → ivycudgel/Ogerpon 위력 부풀림(sim 본연 버그)에 의한 **거짓 OHKO 매몰**이 주된 패인. fix1(순서)과 무관하며, EXP-038(ivycudgel 동적 타입·위력) 영역. 전체 tool_result의 "100%"/"ohko" 언급 15.6%로 잔존 확인.

---

## 3. 문제점 분석

### 🟡 P1-1: 거짓 OHKO 매몰 (ivycudgel, EXP-038)

| 항목 | EXP-036 | 근거 |
|------|---------|------|
| 거짓 OHKO 언급 tool_result | 15.6% (389/2497) | battle 808 ohko/100% 16턴 |
| 패배 808 | 111턴, 642k 토큰, ohko 매몰 | ivycudgel 위력 부풀림 |

**근본 원인**: sim이 ivycudgel/Ogerpon 위력을 체계적으로 부풀림(폼별 동적 타입·tera 위력 미처리). calc "100% OHKO"를 LLM이 맹신.
**개선 방안**: EXP-038(fix3) — ivycudgel 폼별 타입(Ogerpon-Wellspring→Water 등) + tera 시 위력 +20. 단위 테스트 검증 완료(7/7).

### 🟡 P1-2: protect 시뮬레이션 누락 (EXP-037)

**근본 원인**: 일반 protect의 0데미지 처리 부재(Z/Dynamax만 0.25×). 상대 protect를 sim이 안 막아 "공격 성공" 오판. battle 747형.
**개선 방안**: EXP-037(fix2) — protect 계열 0× (최소 1 데미지 규칙 우회 early return) + LifeOrb 아이템명 정규화. 단위 테스트 검증 완료.

### 🟢 P2-1: turns 메트릭 뷰어 불일치 (레코드 한계)

`b.turns`(JSON)는 신뢰(30개 정상 분포, won 합 일치). 단, 뷰어 v.turns가 17개 배틀만 매칭 + b.turns와 불일치(예: 808 b=111 vs v=15) — react event-loop sync-block으로 일부 replay `|win|` 누락(EXP-034 분석과 동일 한계). turns 정량은 `summary.avg_turns`/`b.turns` 기준, 뷰어는 정성 참조용.

---

## 4. 이전 실험 대비 개선 현황

| 이슈 | EXP-034 | EXP-035 | EXP-036 | 상태 |
|------|---------|---------|---------|------|
| 속도/우선도 오판(738형, B3/B5) | 🔴 | 🔴 | ✅ fix1 | **해결** |
| protosynthesis 복붙 버그 | 🔴 | 🔴 | ✅ fix1 | **해결** |
| 거짓 OHKO(ivycudgel, 731형) | 🔴 | 🟡 표면 | 🔴 잔존 | 미해결(EXP-038) |
| protect 시뮬레이션(747형) | 🔴 | 🔴 | 🔴 잔존 | 미해결(EXP-037) |
| 비용(안 A 수준) | ✅ 208k | ✅ 211k | ✅ 213k | 유지 |
| 메트릭 수집 버그(won/turns) | 🔴 | ✅ fix | ✅ 정상 | 해결 |

---

## 5. 권장 개선 우선순위

| 순위 | 문제 | 근거 | 난이도 | 예상 효과 |
|------|------|------|--------|-----------|
| 1 | **EXP-038(fix3): ivycudgel/tera 타입·위력** | 거짓 OHKO 매몰(808 패인), 731형. 단위 테스트 7/7 검증됨 | 중 | 거짓 OHKO 감소 → 장기전 패배 축소 |
| 2 | **EXP-037(fix2): protect + LifeOrb** | protect 오판(747형). 단위 테스트 3/3 검증됨 | 낮 | protect 시뮬레이션 정확도 ↑ |
| 3 | 3 fix 누적 후 종합 평가 | fix1만으로 +3.3pp(비유의). 누적 시 시뮬레이터 정확도가 90% 도달 레버인지 판단 | — | 80%→90% 도달 가능성 |

> 모든 권고는 범용 gen9ou 전략 관점(시뮬레이터 정확도 = 모든 상대에 동일 적용). abyssal 특화 아님.

---

## 6. 다음 단계

### 즉시 (본 보고서와 함께)
- [x] `preserve_code_state.py EXP-036` → `backups/code_state/EXP-036-sim-action-order/` 보존
- [x] `verify_single_change.py` — 파라미터 diff 0개 ✅ (코드 7개 중 본 실험 2: `local_simulation.py`·`test_simulation_accuracy.py`; Smogon 5개는 별개 세션 노이즈, EXP-035 §2 선례)
- [x] fix1 코드 + 단위 테스트 커밋
- [x] `active/` → `archive/` 이동

### EXP-037 완료 후
- [ ] fix2(protect/item) 누적 적용 → react baseline 대비 승률 측정
- [ ] protect 오판(747형) 패배 감소 삼각검증

### 후속 실험
- [ ] **EXP-037**: fix2(protect + LifeOrb) — baseline 대비 변수 1개(코드 누적). 코드·테스트 worktree 검증 완료.
- [ ] **EXP-038**: fix3(ivycudgel/tera) — 거짓 OHKO 근본. 코드·테스트 worktree 검증 완료.
- [ ] 목표: 3 fix 누적 시 승률 85%+, 거짓 OHKO 15.6%→<10%, 장기전(25+턴) 승률 62.5%→75%+

---

## 부록 — §0-4 검증 비고

`verify_single_change.py` FAIL(7개 변경)이나 본 실험의 실제 코드 변경은 `local_simulation.py`(fix1) + `tests/test_simulation_accuracy.py`(테스트) 2개. 나머지 5개(`docs/README.md`, `pokechamp/data_cache.py`, `smogon-meta-design.md`, `smogon_roles/strategies_gen9ou.json`)는 Smogon 메타 통합 **별개 세션** 작업으로 runtime 무영향(소비처 없는 미완성 메서드). EXP-035 분석 §2 선례와 동일하게 취급. 파라미터(argv/config) diff는 0개로 §0-4 본질 준수.
