# EXP-056 (react / glm-5.1) 실험 분석

> 분석 일시: 2026-07-01
> EXP-056: 2026-07-01, glm-5.1:cloud, react, **N=1** smoke 진단 (screen 생략)
> 팀 모드: fixed · manifest `dynamic-v2.json` (sha256:`564353a6`)

---

## 0. 실험 조건

| 항목 | 값 |
|------|-----|
| 코드 상태 | HEAD `ffa6e9f` (050e 순수, EXP-055 회수) + **056 (_find_move 가짜 move 차단)** |
| 변경 | `battle_tools.py` `_find_move:154` — dex에 없는 move id → `None` 반환(기존: 무조건 `Move()` 생성). 호출처(simulate_turn/calculate_damage/get_move_details) None 가드 → `"error": "unknown move"`. fork additive, one-change |
| oracle / lead | on / on |

---

## 1. smoke 진단 (N=1)

- 승 0(패), 11턴, JSON실패 0. 회귀 155 passed(`_find_move` dex 체크: earthquake/thunderbolt/tackle=True, garbage=False 정상).
- **가짜 move 차단('unknown move') 빈도: 0회** ← 핵심.

## 2. 기각 근거 (screen 생략)

`_find_move` 가드가 **한 번도 발동하지 않음** = LLM이 simulate_turn에 넘기는 opp estimated move가 **항상 dex에 존재하는 valid move**. 따라서:
1. 코드 변경이 런타임에 발동 안 함 → 050e와 기능적 동일 → screen 결과도 050e 동급(6/10) 예상.
2. EXP-056이 잡는 것은 "존재 자체를 안 하는 move id(typo/hallucination)"이며, 빈도 0으로 확인.

**한계**: EXP-056은 dex 부재 move만 차단. opp의 **valid-but-wrong**(다른 포켓몬 move / opp 실제 movepool 아님) 추정은 여전히 `Move()` 생성 → 이 경로의 왜곡은 미해결(opp movepool 교차 검증이 필요하나, 더 무거운 레버).

→ **screen 생략(자원 절약)**, 진단 기각. 자원은 가장 유망한 EXP-055 N=30 확증으로 집중.

## 3. 결론 / 후속

- **기각(진단)**: 가짜 move 빈도 0 → 도구 정확성 레버 중 "move 존재 검증"은 실질 효과 없음. 메모리 `react-memory-lever-ceiling`의 "도구 정확성" 세분화 — simulate_turn 정확성은 HP 맥락(EXP-054, 역행)·priority(poke_env 본체) 쪽이 실효 영역; move 존재 검증은 아님.
- **3후보 완결**: EXP-054(기각) · EXP-055(가장 유망, N=30 확증) · EXP-056(진단 기각). 도구 정확성 단독 레버는 한계; 결정 품질(EXP-055)이 가장 유망.
- 후속: EXP-055 N=30 확증 후 최종 보고. 그 이후 권고 — opp stats 추정(bayesian, 무거움) · priority/protosynthesis(poke_env 본체) · EXP-055+054 결합("교정 프레임 + HP 정확화" 시너지) 후보.
