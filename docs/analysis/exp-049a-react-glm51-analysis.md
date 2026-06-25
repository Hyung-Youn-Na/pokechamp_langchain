# EXP-049a 분석: react + D 턴 간 메모리 (BattleMemory)

> **알고리즘**: react · **백엔드**: ollama/glm-5.1:cloud · **상대**: abyssal (io, gemini-2.5-pro)
> **N**: 30 · **seed**: 42 · **temperature**: 0.3 · **팀 모드**: fixed (`dynamic-v2.json`, EXP-048과 동일 매치업)
> **oracle**: on (`--enable_showdown_oracle`, EXP-048과 동일) · **날짜**: 2026-06-24
> **baseline**: **EXP-048** (전무브 oracle 통일 + N-roll, 53.3%) — 동일 조건 위에서 "D 메모리 1개"만 변수.
> **설계**: [`docs/architecture/react-architecture-redesign.md`](../architecture/react-architecture-redesign.md) §4 (D), §7 (분할 로드맵 1/3)

---

## 0. 실험 조건 (변경 1개)

EXP-048(현행 그래프 + oracle) 위에 **배틀 단위 턴 간 메모리 4종**(`BattleMemory`)을 도입. 그래프 토폴로지는 유지(노드 분리는 EXP-049b).

- ① `opp_role_balance` / `opp_team_roles` — Smogon role compendium에서 상대 팀 역할 집계 (team preview 1회, 불변)
- ② `opp_revealed` — 상대 active의 드러난 무브/아이템/tera (매 턴 관측 누적)
- ③ `opp_win_condition` — LLM 추론 상대 승리 경로 (LLM 갱신)
- ④ `my_plan` — LLM 작성 내 승리 계획 (LLM 갱신)

매 턴 `_format_memory_brief`가 이 4종을 user_prompt에 주입(`## Battle Memory` 섹션). LLM은 JSON 출력에 `win_condition_opponent`/`my_plan` 키로 ③④ 갱신.

---

## 1. 정량 결과

### 1.1 승률 — EXP-048 대비 −13.3pp

| 항목 | EXP-048 | EXP-049a | delta |
|------|---------|----------|-------|
| **승률** | **53.3% (16/30)** | **40.0% (12/30)** | **−13.3pp** |
| 평균 턴 수 | 16.4 | 17.6 | +1.2 |

### 1.2 리소스 — 프롬프트 블로트 폭증 ★

| 항목 | EXP-048 | EXP-049a | delta |
|------|---------|----------|-------|
| avg prompt tokens | 150,823 | **205,930** | **+55,107 (+36.5%)** |
| avg completion tokens | 5,458 | **8,395** | **+2,937 (+53.8%)** |
| avg LLM calls/판 | 53.1 | 66.2 | +13.1 |
| LLM calls/턴 | 3.24 | 3.76 | +0.52 |
| avg time/판 | 204.3s | 237.1s | +32.8s |

> prompt +36.5% / completion +53.8% = 매 턴 주입되는 `## Battle Memory` brief와 매 응답마다 작성되는 `my_plan`/`win_condition_opponent`가 프롬프트·응답 양쪽을 비대하게 만듦. **EXP-002~004 "프롬프트 블로트 역효과" 패턴의 정확한 재현**.

### 1.3 턴 구간별 승률 — short 치명적 붕괴 ★

| 구간 | EXP-048 | EXP-049a | delta |
|------|---------|----------|-------|
| short(<15턴) | 63.6% (7/11) | **25.0% (2/8)** | **−38.6pp** |
| mid(15-24턴) | 41.2% (7/17) | 47.6% (10/21) | +6.4pp |
| long(25+턴) | 100% (2/2) | 0% (0/1) | (샘플 작음, 무의미) |

> 도입 목적이 "단기 damage 수렴 완화"였으나 **오히려 short 배틀 승률이 −38.6pp로 붕괴**. mid는 소폭 회복. short에서 결정이 가장 빈번히 일어나므로 brief 노이즈의 타격이 집중.

---

## 2. 메모리 역할 분석 ★ (핵심)

### 2.1 메모리는 "활성"이었다 — 그러나 역효과

| 지표 | 값 | 의미 |
|------|-----|------|
| `## Battle Memory` brief 주입률 | **100% (1985/1985 응답)** | 매 턴 무조건 주입 — on-demand 아님 |
| brief 평균 길이 | **1,761자** (median 1817, max 5964) | 매 턴 user_prompt에 고정 비용 |
| role_balance 포함률 | 98.1% | ① 관측은 정상 주입 |
| revealed 포함률 | 99.1% | ② 관측은 정상 주입 |
| `my_plan` 갱신 | 478/1985 = **24.1%** 응답 (422 고유 turn) | ④ LLM 갱신 활성 |
| `win_condition_opponent` 갱신 | 427/1985 = **21.5%** | ③ LLM 갱신 활성 |

→ 메모리 시스템 자체는 정상 작동. LLM도 `my_plan`/`win_condition_opponent`를 적극 출력(24%/21%). **문제는 "활성"이 곧 "유효"가 아니었다는 점.**

### 2.2 my_plan은 "장기 전략"이 아니라 "단기 행동 재진술" (95.4%) ★★

`my_plan` 478개의 키워드 분석:

| 범주 | 포함율 | 예시 |
|------|--------|------|
| **단기** (this turn / KO / then / switch) | **95.4%** | "KO Ogerpon-Wellspring with Thunderbolt this turn, then assess" |
| 장기 (sweep / setup / wincon / hazard / position) | 40.4% | (대부분 "Moxie boost will help sweep" 식의 단기 KO 부연) |

**결정적 증거 — battle-gen9ou-1195 연속 턴 my_plan** (31회 갱신):
```
turn 2: Switch Venusaur into Iron Moth, OHKO with Earth Power, then assess
turn 3: KO Iron Moth with Earth Power... then use Great Tusk/Ceruledge
turn 3: KO Iron Moth with Earthquake... then use Great Tusk/Ceruledge   ← 같은 턴 2회 재작성
turn 4: KO Iron Moth with Earthquake, then assess
turn 5: Set Stealth Rock... then switch to Ceruledge
turn 6: Break Multiscale with Knock Off... then next turn switch
turn 7: Poltergeist this turn to put Dragonite to 12%, then Shadow Sneak to KO next turn
```

같은 타겟(Iron Moth)을 **4턴 연속 "KO"로 my_plan에 재진술**. 매 decision_index마다 재작성. 이것은 **누적되는 장기 전략적 통찰이 아니라, 즉각적 행동의 반복 기록**. 도입 목적("장기 win condition 일관성으로 단기 damage 수렴 완화")과 정반대로 작동.

`opp_win_condition`(427개)도 동일: "Ogerpon-Wellspring with Power Whip threatens; need to KO it fast" / "about to be KO'd; remaining 5 need scouting" — 장기 승리 경로가 아닌 **현재 위협 기술** 서술.

### 2.3 ①② 관측(역할 밸런스/드러난 정보)의 한계

brief에 주입된 role_balance 샘플:
```
Opponent team roles: Other Utility x3, Entry Hazards x1, Wallbreakers x1, Setup Sweepers x1, Pivots x1
Opponent revealed so far: - ogerponwellspring (item: unknown_item)
```

- 역할 밸런스가 **카테고리 카운트만**("Setup Sweepers x1"). 어떤 포켓몬이 스위퍼인지, 어떻게 견제해야 하는지 안 나옴 → LLM이 전략적으로 활용하기엔 정보 부족.
- `item: unknown_item` — poke_env에서 미드러난 아이템이 `unknown_item`으로 기록되어 노이즈.

→ ①②는 무해할 수 있으나, **그 자체로 승률 향상을 이끌 만큼 정보 밀도가 높지 않음**.

---

## 3. 문제점

### 🔴 P0 — 매 턴 brief 주입 = 프롬프트 블로트 (EXP-002~004 재현)
- brief 100% 주입, 평균 1761자/턴 → prompt +36.5%, completion +53.8%, 시간 +16%.
- EXP-002~004가 증명한 "추가 프롬프트 텍스트 = 일관된 승률 하락" 패턴. 본 설계에서도 `## Battle Memory`가 매 턴 고정 비용으로 누적.
- **근본 원인**: D의 ③④(my_plan/opp_win_condition)를 매 턴 갱신·주입하도록 설계 → 자기 증식적 블로트.

### 🔴 P0 — my_plan 의도-실제 불일치 (장기 전략 ≠ 단기 재진술)
- my_plan 95.4%가 단기 행동 재진술. LLM이 "내 계획"을 "이번 턴 할 일"로 해석.
- 장기 win condition 일관성(도입 목적) 달성 실패 → ④ 메모리의 전략적 가치 사실상 0.
- 매 턴 재작성으로 이전 턴 plan과 충돌/누적 노이즈 (같은 타겟 4턴 연속 "KO").

### 🟡 P1 — 단기 수렴 완화 실패, 오히려 악화
- short 배틀 승률 −38.6pp. my_plan이 단기 KO 재진술이라 LLM이 단기 damage에 더 강하게 lock-in.
- 도입 의도(단기 수렴 완화)가 정반대 결과.

### 🟢 P2 — role_balance 정보 밀도 부족 + revealed 노이즈
- 카테고리 카운트만으로 전략적 활용 어려움. revealed의 `unknown_item` 등 노이즈.

---

## 4. EXP-048 대비 종합

| 영역 | EXP-048 → EXP-049a | 진단 |
|------|--------------------|------|
| 승률 | 53.3 → 40.0 (−13.3pp) | 블로트로 인한 역효과 |
| short 승률 | 63.6 → 25.0 (−38.6pp) | 단기 결정 빈번 → brief 노이즈 타격 집중 |
| prompt 토큰 | 150k → 206k (+36.5%) | 매 턴 brief 고정 비용 |
| my_plan 유효성 | (없음) → 95.4% 단기 재진술 | 의도 무효 |

**EXP 시리즈 문맥**: 이전 oracle 시리즈(044→048)는 "정확한 damage ≠ 더 나은 결정"을 증명. EXP-049a는 구조 변환(B+D)의 **첫 시도(D만)** 가 "추가 정보/메모리 주입 ≠ 더 나은 결정"을 재확인 — EXP-002~004/035의 데이터·프롬프트 주입 역효과 교훈과 동일 선상.

---

## 5. 시사점 / 다음 단계

### D 메모리의 교훈
1. **매 턴 고정 주입은 블로트** → on-demand(도구) 또는 이벤트 기준(스위치/KO 시) 주입이어야.
2. **LLM 자유 형식 my_plan은 단기 재진술로 퇴화** → 장기 전략을 강제하려면 구조적 제약(길이/형식/갱신 빈도) 필요.
3. **관측(①②)은 무해할 수 있으나, ③④(LLM 갱신) 노이즈가 상쇄** — 분리 평가 필요.

### EXP-049b (B 노드) 진행 전 재검토 필요 ★
블로트가 주원인이므로, **D 메모리를 현재 형태로 049b에 가져가면 B 노드 효과가 블로트에 묻힘**. 049b 전에 D 형태를 수정해야. 옵션:

- [ ] **(a) 관측만 유지**: ③④(my_plan/opp_win_condition) 제거, ①②(역할/드러난 정보)만 경량 brief로. 블로트 원천 제거.
- [ ] **(b) 주입 빈도 제한**: brief를 매 턴이 아닌 스위치/KO/드러난 정보 변경 시에만 주입.
- [ ] **(c) my_plan 강제 장기화**: "1줄 win condition, N턴마다 또는 변경 시만 갱신" 스키마 제약 + 단기 재진술 거부.

→ **권고 (a)**: ③④ 제거로 블로트를 끊고, ①②의 정보 밀도를 높인 뒤(역할별 포켓몬명 포함), 049b에서 B 노드 효과를 깨끗하게 측정. 이것이 "변경 1개" 원칙에도 부합(D 메모리 축소 = 049a 대비 변수 1개).

### 049b/c는 (a) 적용 후
- EXP-049b: B 노드(strategy_synthesis 분리) — ①② 관측만 활용.
- EXP-049c: Smogon 방식 1 도구(`get_strategy_insight`) — on-demand 메타 지식.

---

## 부록: 측정 출처

- 승률/턴/토큰/시간: `experiment_*.json` `summary` (4.2 스니펫)
- 턴 구간: `experiment_*.json` `battles[]` (4.3 스니펫)
- my_plan/win_condition 빈도·패턴·정성: `langgraph_llm_log.jsonl` (`llm_response`, `user_prompt`)
- 뷰어 미생성(정량 + llm_log 직접 분석으로 충분). `meta.git_commit_short=f0414be`, `git_dirty=True`.
