# EXP-052 (react / glm-5.1) 실험 분석

> 분석 일시: 2026-06-30
> EXP-052: 2026-06-30, glm-5.1:cloud, react, **N=10**전 vs abyssal (시간 제약)
> 팀 모드: fixed · manifest `dynamic-v2.json` (sha256:`564353a6`, 050 시리즈 동일 30 매치업 중 첫 10판)

---

## 0. 실험 조건

| 항목 | 값 |
|------|-----|
| 코드 상태 | **합성**: 050a(HEAD) + **051(plan-resilience)** + **052(opp_alive 정확화)** |
| 변경 | opp_alive revealed-only 집계 버그 수정 — teampreview 6명 ∪ revealed species 병합 헬퍼(`battle_memory.py`) → `evaluate_position`·`get_team_analysis`·`prompts.py` "left" 적용. fork additive(poke_env 본체 수정 없음) |
| oracle / lead | on / on (`--max_tokens 65536`, 050 시리즈 argv 일치) |
| 비교 기준 | EXP-051(동일 10 매치업 9/10), EXP-050a(시리즈 최고 70%), EXP-050e(63.3%) |

---

## 1. 결과 (N=10)

| 실험 | 승률 | 평균턴 | LLM/판 | prompt tok | comp tok | JSON실패 |
|------|------|--------|--------|------------|----------|----------|
| **EXP-052** | **60.0% (6/10)** | 17.5 | 85.3 | 277,437 | 11,095 | 0 |
| EXP-051 (참조) | 90.0% (9/10) | 14.3 | 69.8 | 228,420 | 8,217 | 1 |
| EXP-050a (30판) | 70.0% (21/30) | 18.0 | 87.5 | 280,377 | 10,987 | 1 |
| EXP-050e (30판) | 63.3% (19/30) | 17.6 | 87.4 | 281,319 | 10,892 | 1 |

### 1.1 paired (052의 10 매치업 기준)

| 비교 | 패→승 | 승→패 | net |
|------|-------|-------|-----|
| 052 vs 050e | 2 | 2 | **+0** |
| 052 vs 050a | 2 | 4 | **-2** |
| 052 vs 051 | 0 | 3 | **-3** |

역행 상세: idx 2(p11964/o819), idx 6(p20865/o7321), idx 9(p5193/o3361) — 모두 051 승 → 052 패. 051 패→052 승 0건.

---

## 2. 기각 근거

**gate 미달 (8/10 및 paired net +1)**:
- 승률 6/10 < 8/10.
- paired net: vs 050e +0, vs 050a -2, vs 051 -3 → +1 미달.

→ **기각/보류**. N=30 미승격.

---

## 3. 역행 원인 분석

1. **합성 정합성**: 본 측정은 051(plan-resilience) 코드 위에 052를 얹은 상태. 순수 opp_alive 단독 효과 분리 불가 (051 과발동이 지배).
2. **051 과발동 잔존**: PLAN DISRUPTED **346회/10배틀**(~40% 턴, pivot/switch 오탭)이 my_plan 단기 재진술을 유도한 상태에서, opp_alive 정확화가 evaluate_position score를 중립화(거짓 "strongly winning" 제거).
3. 두 효과 결합 + N=10 노이즈 → 051 대비 3패 역행.
4. "정확성=승률"이 이 맥락에선 반례 (과소 집계의 거짓 우위가 LLM 공격성→빠른 KO로 작용했을 가능성) 이거나 노이즈. **합성 상태라 단정 불가**.

### 3.1 prompt↔tool 일치 (양호)
smoke에서 prompt "Opponent has X left" 6(49)/5(10)로 `_opp_alive_count` 정상 동작 (KO 반영). 도구 호출(smoke 1배틀)은 calculate_damage 중심, evaluate_position/get_team_analysis는 본측정에서만 — opp_alive 정확화 자체는 동작 확인.

---

## 4. 결론 / 후속

- **기각**: 8/10·net +1 게이트 미달 + 합성 정합성 문제.
- **opp_alive 변경 자체의 가치는 미확정** (051 과발동 하에서 역행 측정됨). 합성을 제거한 순수 환경(050a/050e 단독)에서 재측정이 필요하나, 본 세션에서는 후보 예산(3개)을 **범용 P0(KO-only plan resilience, EXP-053)**에 우선 배분.
- 후속(EXP-053): 052 제거 + 051 detect를 KO-only로 수정 → 순수 plan-resilience 효과 격리.
