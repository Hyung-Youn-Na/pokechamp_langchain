# EXP-050a 분석: react + team preview 풀 정보 (oracle 버그 수정 후)

> **알고리즘**: react · **백엔드**: ollama/glm-5.1:cloud · **상대**: abyssal (io, gemini-2.5-pro)
> **N**: 30 · **seed**: 42 · **temperature**: 0.3 · **팀 모드**: fixed (`dynamic-v2.json`) · **max_tokens**: 65536
> **oracle**: on · **enable_llm_lead_selection**: on · **날짜**: 2026-06-26
> **baseline**: **EXP-049c 재검** (60.0%) — 동일 조건 위에서 "teampreview 풀 정보 분석 + oracle 버그 수정"이 변수.
> **참조**: [`exp-049c`](exp-049c-react-glm51-analysis.md) · 버그 사후분석 [`.temp/experiments/archive/EXP-050a-teampreview/BUG_POSTMORTEM.md`] · 설계 [`react-architecture-redesign.md`](../architecture/react-architecture-redesign.md)

---

## 0. 실험 조건 — 2가지 변경 (oracle 버그 수정 + teampreview 강화)

본 실험은 **oracle 데미지 버그 2건 수정 + team preview 풀 정보 강화**가 함께 들어갔다.

**oracle 버그 수정 (★ 본 실험의 실제 주원인)**:
- **1차** (`c9ac112`): `battle_state_mapper._pack_pokemon`이 nature/evs/ivs/level 빈칸 → Showdown `Teams.unpack` 파싱 실패 → **랜덤 데모 팀 폴백** → oracle이 Pelipper/Ogerpon-W가 아닌 Girafarig/Swanna/Blastoise 등 엉뚱한 포켓몬으로 데미지 계산.
- **2차** (`dd9b040`): opp poke_env `max_hp`(Showdown 퍼센트=100)가 `active_state.max_hp`로 전달 → `applyActiveState`가 **dex maxhp(Ogerpon-W 301/Clodsire 401/Blissey 651)를 100으로 덮어쓰기** → `is_ohko = damage>=100` 거짓 OHKO.
- **영향**: EXP-044~049c **전 시리즈가 같은 버그** (빈 pack + max_hp는 항상 발생). 즉 이전 승률(049b/c 60% 포함)은 oracle 결과가 무작위에 가까운 상태에서 측정됨. **050a 70%가 oracle 수정 후 첫 정상 측정** — 절대 승률이 버그 왜곡에서 해방됨.

**team preview 풀 정보 강화** (원래 의도된 변수):
- `LangChainPlayer.teampreview()` 오버라이드 + `--enable_llm_lead_selection` on.
- 분석 파이프라인: 상대 likely-lead 예측(`predict_opp_leads` — speed tier + 역할 + 타입 매치업) + 12종 Smogon overview prefetch(`gather_preview_strategy`, 블로트 제한 해제) + per-pokemon 역할 상세 → 구조화된 "preview analysis" 주입 → 장기 win plan 시드.

> ⚠️ 변수가 2개(oracle 수정 + teampreview)이므로 70% 상승의 귀인 분리는 불가. 그러나 oracle 수정이 지배적 — 동일 teampreview 코드로 버그 전(53.3%)·후(70%) 차이가 +16.7pp이고, probe가 버그를 완전히 재현/해소 입증.

---

## 1. 정량 결과 — 시리즈 최고 70.0%

### 1.1 승률

| EXP | 승률 | avg 턴 | 비고 |
|-----|------|--------|------|
| EXP-048 | 53.3% (16/30) | 16.4 | (oracle 버그 하) |
| EXP-049a | 40.0% (12/30) | 17.6 | (oracle 버그 하) |
| EXP-049b | 60.0% (18/30) | 18.2 | (oracle 버그 하) |
| EXP-049c 재검 | 60.0% (18/30) | 16.5 | (oracle 버그 하) |
| **EXP-050a** | **70.0% (21/30)** | 18.0 | **oracle 수정 후 첫 정상** |

> 049c(60%) 대비 **+10.0pp**, 048(53.3%) 대비 **+16.7pp**. 기존 "60% 한계" 첫 돌파.

### 1.2 리소스

| 항목 | 049c 재검 | EXP-050a | 변화 |
|------|-----------|----------|------|
| avg prompt tokens | 267,214 | 280,377 | +5% (teampreview 풀 overview 12종) |
| avg completion tokens | 9,663 | 10,987 | +14% |
| avg LLM calls/판 | 85.0 | 87.5 | +2.5 |
| avg time/판 | 261s | 284s | +23s |
| json_parse_failures | 5 | 1 | −4 |

> prompt +13k는 teampreview 1회 풀 overview 주입. 매턴 주입이 아니라 배틀당 1회라 증가 미미.

---

## 2. ★ oracle 버그 해소 확인 (본 실험 핵심)

### 2.1 100% OHKO — 63% 정당, 37% 비현실 (정정 2026-06-26)

> **정정**: 초안 "100%가 진짜 강력 매치업에서만"은 부분 틀림. dex type chart(oracle과 동일)로 305회 100% OHKO를 전수 검증한 결과 **193회(63.3%)만 2×+ 정당**, **112회(36.7%)는 type 1×/0.5× 비현실**.

| 구분 | 비율 | 예시 |
|------|------|------|
| **정당 (2×+)** 193회 | 63.3% | `closecombat→kingambit`(4×), `icebeam→landorust`(4×), `hurricane→ironvaliant`(2×), `hydropump→clodsire`(2×) |
| **비현실 (1×/0.5×)** 112회 | 36.7% | `water→gholdengo`(1×) x7, `ghost/fire→zamazenta`(1×) x10, `dragon→moltres`(1×) x4, `grass→ogerponwellspring`(1×) |

- 이전 `uturn→ogerpon 100%`(랜덤 폴백 + max_hp 덮어쓰기) 소멸은 사실. **하지만 opp stats가 0 EV 기본**(`_pack_pokemon` neutral — poke_env에 nature/evs/ivs 속성이 없어 own·opp 모두 dex 기본 0 EV) → opp 방어가 실제 경쟁 세팅(EV 투자)보다 낮아 **절대 데미지가 과대** → 1× 매치업도 100% OHKO로 둔갑. gholdengo/zamazenta/moltres(내구형)에서 두드러짐(실제론 절대 OHKO 안 됨).
- max_hp 버그(`dd9b040`)는 dex maxhp를 존중하도록 고쳤으나, **방어력(EV/IV/nature)은 여전히 0 EV 기본** → 절대 데미지 왜곡 잔존. **2차(opp stats 추정)** 로 감소 가능.

### 2.2 데미지 분포 정상화 (1482회 oracle 쿼리)

| hp_lost | 100% | 50-99% | 25-49% | 1-24% | 0% |
|---------|------|--------|--------|-------|----|
| 비율 | 20.6% | 31.6% | 25.4% | 19.6% | 2.7% |

정상 분포(버그 전 무작위와 다름). 단 100% 구간의 **36.7%는 1× 비현실**(§2.1) — 절대 데미지는 여전히 opp 0 EV로 과대. dex maxhp(301/401/651)는 정상 반영됐으나 **방어력 EV/IV/nature가 0 EV 기본**이라 절대값 왜곡 잔존.

### 2.3 probe 입증 (stderr probe)
- D(`max_hp=None` = 수정후): Pelipper U-turn vs Ogerpon-Wellspring **37.9%** 정상.
- E(`max_hp=100` = 실제배틀 시뮬): **100%** 재현.
- → probe vs 실제의 유일한 차이가 `active_state.max_hp` 존재 여부. 상세 = `BUG_POSTMORTEM.md`.

---

## 3. team preview 풀 정보 — 정상 작동, 블로트 역효과 無

- `preview_llm_log`: order 326514(Pelipper 선발), my_plan *"Lead Pelipper to set rain (neuters Iron Moth/Raging Bolt) → Tyranitar back for sand/SpD wall → Kingdra primary win condition"* — **장기 win path** (STRATEGY_SYSTEM_PROMPT GOOD 예시 준수).
- **풀 정보(overview 12종 + 역할 + 선발 예측)가 블로트 역효과 없이 승률 향상에 기여** — 과거 EXP-002~004/049a의 "정보 주입=역효과" 패턴과 다른 결과. **해석: oracle이 정확해져 LLM이 주입된 정보를 제대로 활용** (이전엔 도구 결과가 무작위라 아무 정보나 무의미했음).

---

## 4. 의미 / 시리즈 재해석

1. **oracle 정확성이 최우선 레버**: 구조(teampreview) 개선이 아니라, 도구 결과가 틀리면 아무것도 의미 없다는 것이 53.3%(버그) → 70%(수정)로 입증. EXP-044~049c의 "정확성≠승률" 가설은 **버그 오염下的 가짜 결론** — 정확한 oracle에서 오히려 큰 승률 향상.
2. **049b/c 60%는 버그 하 편행**: 빈 pack 랜덤 폴백이 매 실행마다 다른 포켓몬 → 우연히 60%. 050a 70%가 첫 신뢰 가능 측정.
3. **teampreview 풀 정보 + 정확 oracle = 시너지**: 둘 다 정상일 때 +10pp. 남은 목표(90%)까지 +20pp.

---

## 5. 결론 / 다음 방향

### EXP-050a(70%)의 공로 분배
- **oracle 버그 수정(1·2차)**: 지배적. probe가 완전 입증.
- **teampreview 풀 정보**: 정상 작동하나, oracle 수정 없이는 효과 측정 불가(버그가 결과를 무력화). 수정 후 시너지로 작용.

### 다음 레버 (목표 90%까지 +20pp)
1. **opp stats 정확화** (2차): §2.1에서 100% OHKO의 **36.7%(112회)가 type 1×/0.5× 비현실**로 확인 — opp 0 EV 방어로 절대 데미지 과대. Smogon sets 기반 추정(EV/nature)으로 1× 비현실 100% 감소 → 데미지 절대값 sim(29-38%) 근접.
2. **044~049c 재측정 검토**: oracle 수정이 전 시리즈에 영향이므로, 핵심 실험(047/049b)을 수정된 oracle로 재측정하면 절대 승률 재해석 가능. (단, 비용 큼.)
3. **사람 사고 후속** (050b/c/d): 역할횟수·phase·자원 ledger.
4. calculate·simulate 중복 해소 / sim-oracle 교차검증(안전망).

---

## 부록: 측정 출처
- 승률/턴/토큰: `experiment_*.json` `summary`.
- oracle 데미지 분포·100% 예시: `langgraph_tool_log.jsonl` (`tool_result`).
- my_plan: `preview_llm_log.jsonl` (`seed`).
- oracle 버그 probe: `.temp/script/oracle_stderr_probe.py` (D=37.9% / E=100%).
