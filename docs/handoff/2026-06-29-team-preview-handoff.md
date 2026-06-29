# Team Preview (050) 시리즈 인수인계 — 2026-06-29 (050e 마무리 반영)

> **다음 세션용 단일 문서**. 이 파일 하나로 050 시리즈 결과 + 다음 실험을 파악.
> 소스 오브 트루스: [`experiment-context.md`](../../experiment-context.md) §0/§5. 분석: [`docs/analysis/`](../analysis/).

---

## TL;DR

- **050 시리즈 최고: 050a 70.0%** (oracle 버그 수정 + teampreview 풀 정보). 선발 실험은 **050e(63.3%)로 마무리**.
- **050e**(matrix 제거 + ability 회수): 050d(50%) 대비 **+13.3pp 회복**(matrix·ability 충돌 해소), 050a(70%) 대비 −6.7pp. **matrix 제거가 정답** 입증.
- **다음 세션 첫 EXP**: **승률 개선 레버** — plan resilience / phase / 자원 ledger / opp stats (050a 70% → 90% 목표). 선발(050)은 종료.

---

## 050 시리즈 결과 (완결)

| EXP | 승률 | 상태 | 진단 |
|-----|------|------|------|
| **050a** | **70.0% (21/30)** | ✅ **시리즈 최고** | oracle 버그 수정 + teampreview 풀 정보. ability Unknown·EV=0 상태. |
| 050b | 53.3% | ❌ archive | 매턴 자기 역할 주입 역효과 (−16.7pp). 회수. |
| 050c | 60.0% | ⚠️ 보류 | lead payoff matrix 자기모순(preserve rank1) + ability Unknown. |
| 050d | 50.0% | ❌ archive | ability 회수 + **matrix 유지 → 충돌** (−20pp, 시리즈 최저). |
| **050e** | **63.3% (19/30)** | ✅ **선발 마무리** | matrix 제거 + ability 회수. 050d 대비 +13.3pp 회복. 050a 대비 −6.7pp. |

실행 조건 공통: react · ollama/glm-5.1:cloud · abyssal · N=30 · seed 42 · temp 0.3 · fixed `dynamic-v2.json` · oracle on.

---

## ★ 핵심 학습 (재발견 금지)

1. **oracle 정확성 = 승률** (050a: 버그 53.3% → 수정 70%). EXP-048 "정확성≠승률"은 버그 오염下的 가짜 결론.
2. **매턴 정보 주입 = 역효과** (050b −16.7pp; brief 블로트). teampreview 1회성이 낫다.
3. **matrix·ability 충돌** (050c 60% / 050d 50%): role 기반 matrix(`preserve` sweeper) vs ability 기반 weather 전략(Sand Rush/Swift Swim=핵심 lead). **matrix 제거 = 정답**(050d→050e +13.3pp).
4. **ability 회수 + EV 회수 = 050a 대비 −6.7pp**: 회수 자체는 정확성↑이나 승률 약역효과. 추정 — (a) weather setter lead 편향(tyranitar 13번), (b) oracle EV 회수가 데미지 절대값 변화 → 050a의 EV=0 과대 데미지가 공격적 KO 판단에 우연히 유리. **050a(70%)가 최고** — 정보 회수가 항상 승률↑은 아님.
5. teampreview 풀 정보 + 정확 oracle = 시너지 (050a).
6. 로그 truncate 해제 (분석 충실도; battle_tools cap은 프롬프트 bloat guard라 유지).

---

## 다음 세션 로드맵 (승률 70% → 90%)

선발(050) 종료. **승률 개선** 레버 (우선순위):

1. **plan resilience** (`plan_is_stale` wiring + player 단 KO/miss 감지 → force_replan nudge). 사용자 의연 "확률 변수로 plan 깨짐 대처". 050c parse failures(위기 JSON→산문)도 이 영역. **가장 미구현 영역**.
2. **게임 phase 노드** (early/mid/late 결정론 → phase별 전략 전환).
3. **역할횟수 + tera/hazard 자원 ledger** (HP→체크횟수, 자원 추적).
4. **opp stats 추정** (bayesian prediction — opp EV/ability/nature 추정; own 회수는 050d 완료).

의존성: 050d ability/EV 회수(own)는 완료. opp 추정은 별도(bayesian). phase/자원은 독립.

---

## 시작 지점 (다음 세션 첫 액션)

1. 본 handoff + `experiment-context.md` §5 읽기.
2. **첫 EXP 추천: plan resilience** (가장 미구현, 사용자 의연 직결).
   - `plan_is_stale`(`battle_memory.py:299`) wiring — `react_agent.build_context`에서 호출, stale 시 brief "replan" 마커.
   - player 단 `_detect_plan_disruption`(KO/miss/tera) → `force_replan`.
3. §0-4 단일 변경, smoke(N=1) 게이트(§0-9).

---

## 컨텍스트 복원 가이드 (읽을 파일)

- **`experiment-context.md`** §0(규칙) · §5(실험 이력 — 소스 오브 트루스).
- **분석**: `docs/analysis/exp-050a-react-glm51-analysis.md`(050a 상세).
- **memory**: `team-preview-050-series`(본 요약) · `oracle-stats-ev-zero`(EV=0 왜곡) · `own-team-info-recovery`(pack 회수) · `oracle-impl-technique`.
- **codex 피드백**(matrix — 050c/050e로 기각됐지만 참고): `.temp/codex_feedback/lead-selection-feedback.md`.
- **plan**: `/root/.claude/plans/misty-orbiting-brooks.md`.

---

## 코드 위치 (참고)

- **own pack 회수(050d, 유지)**: `poke_env/player/team_util.py`(`_load`/`team_sets_at`) · `poke_env/environment/pokemon.py`(`__slots__` `_own_pack_set`) · `pokechamp/langchain_player.py`(`set_own_pack`/`_overlay_own_pack`) · `pokechamp/llm_player.py`(`_format_lead_selection_data`) · `pokechamp/battle_state_mapper.py`(`_pack_pokemon`).
- **matrix(050c, 제거됨)**: `pokechamp/battle_memory.py`(`build_lead_payoff_matrix`/`classify_lead_mode` — 정의 잔존, teampreview 호출 제거) · `pokechamp/langchain_player.py`(`_render_lead_matrix` — 잔존, 미사용).
- **plan resilience(050f 후보)**: `pokechamp/battle_memory.py:plan_is_stale`(사문) · `pokechamp/langchain_player.py:604`(plan 갱신 지점) · `pokechamp/agents/react_agent.py:_format_memory_brief`/`STRATEGY_SYSTEM_PROMPT`.
