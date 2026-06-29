# Team Preview (050) 시리즈 인수인계 — 2026-06-29

> **다음 세션용 단일 문서**. 이 파일 하나로 050 시리즈 상태 + 다음 실험을 파악할 수 있다.
> 소스 오브 트루스: [`experiment-context.md`](../../experiment-context.md) §0/§5. 분석: [`docs/analysis/`](../analysis/).

---

## TL;DR

- **050 시리즈 최고: 050a 70.0%** (oracle 데미지 버그 수정 + teampreview 풀 정보). baseline.
- **050d**(own team pack 회수: ability/item/EV/nature/IV) 코드 완료(`commit 3640463`), **본측정 N=30 대기**(사용자 실행).
- **다음 세션 첫 EXP**: ① 050d 본측정 결과 도착 시 → 분석 + 보고서; ② 미도착 시 → **050e**(lead payoff matrix v2: preserve 모순 fix + ability 회수 위에서 재평가) 설계.

---

## 050 시리즈 결과

| EXP | 승률 | 상태 | 진단 |
|-----|------|------|------|
| **050a** | **70.0% (21/30)** | ✅ baseline | oracle 데미지 버그 2건 수정(`_pack_pokemon` 빈 pack → 랜덤 폴백, `active_state.max_hp`=opp% → dex maxhp 덮어쓰기) + teampreview 풀 정보(Smogon overview 12종 + 역할 + 선발 예측). EXP-044~049c는 전부 oracle 버그 오염下的 가짜 측정. |
| 050b | 53.3% (16/30) | ❌ archive | 매턴 자기 역할 주입 역효과 (−16.7pp, net −5). per-mon 라벨 장황 → brief 블로트 + 역할 라벨 오용. 050c에서 회수. |
| 050c | 60.0% (18/30) | ⚠️ 보류 | teampreview lead payoff matrix(codex 피드백). **자기모순**(preserve-mode mon을 rank1 추천 — `classify_lead_mode` worst-case vs ranking avg 충돌) + ability Unknown 제약. parse failures 5=matrix 무관. 050e에서 fix/재평가. |
| 050d | — (본측정 대기) | 🟡 코드 완료 | own team pack 회수(ability/item/EV/nature/IV). ability Unknown(teampreview) + EV=0 왜곡(oracle) 공통 근원 해소. smoke로 ability Unknown 소멸 확인. |

실행 조건 공통: react · ollama/glm-5.1:cloud · abyssal(io, gemini-2.5-pro) · N=30 · seed 42 · temp 0.3 · fixed-team `dynamic-v2.json` · oracle on · `--enable_llm_lead_selection` · max_tokens 65536.

---

## ★ 핵심 학습 6가지 (재발견 금지)

1. **oracle 정확성 = 승률**: 도구 결과가 틀리면 구조 개선이 무의미. 050a에서 53.3%(버그) → 70%(수정). EXP-048의 "정확성≠승률"은 oracle 버그 오염下的 **가짜 결론**.
2. **매턴 정보 주입 = 역효과**: 050b −16.7pp. brief 블로트 + LLM 주의 분산. **teampreview 1회성** 주입이 낫다(050a 시너지).
3. **matrix 자기모순**: 050c. mode 분류(`classify_lead_mode`, worst-case)와 행별 ranking(avg)이 다른 축 → preserve mon이 rank1 추천. **mode와 ranking 기준 통일** 필요(050e).
4. **ability Unknown + EV=0 왜곡 = 공통 근원 team pack**: teampreview own ability가 Unknown(poke_env가 teampreview request를 own team에 적용 안 함), oracle은 EV=0 neutral 폴백 → 절대 데미지 양방향 왜곡. 둘 다 **team pack**(`FixedTeamProvider._load` parsed `TeambuilderPokemon`)에서 회수(050d). 결정론(own은 pack 확정). opp는 별도 추정.
5. **teampreview 풀 정보 + 정확 oracle = 시너지**: 050a. 정보 주입이 oracle 정확 시에만 도움(이전엔 도구 결과 무작위라 무의미).
6. **로그 truncate 해제**: 분석 충실도 > 용량. `_log_preview`(user_prompt/response/error), `react_agent.reasoning` 전체 저장. battle_tools overview/moveset cap은 LLM 프롬프트 bloat guard라 유지.

---

## 다음 로드맵 (우선순위 + 의존성)

1. **050d 본측정 + 분석** (★ 우선, 사용자 실행 대기): N=30 → 050a 70% paired. 정성: weather setter 인식 plan(rain/sand 모순 소멸), oracle 데미지 절대값(1× 비현실 100% OHKO 감소). 보고서 `docs/analysis/exp-050d-*.md`.
2. **050e — lead payoff matrix v2**: 050c matrix preserve 모순 fix(preserve mon rank1 제외/penalty) + ranking avg→worst-case + **ability 회수(050d) 위에서 재평가**. codex 피드백(`.temp/codex_feedback/lead-selection-feedback.md`) 기반.
3. **050f — plan resilience**: `plan_is_stale` wiring(사문 코드 활성화) + player 단 KO/miss/tera 감지 → `force_replan` nudge. 050c parse failures(위기 JSON→산문 붕괴)도 이 영역. 사용자 의문 "확률 변수로 plan 깨짐 대처".
4. **이후 (별도 EXP, 의존성 명시)**: 게임 phase 노드 · 역할횟수 + tera/hazard 자원 ledger · opp stats 추정(bayesian, own과 별도).

의존성: 050d(ability/EV 회수) → 050e(matrix v2 평가) · 050f(resilience). phase/자원 ledger는 050e/f 위에서.

---

## 시작 지점 (다음 세션 첫 액션)

1. `experiment-context.md` §0/§5 + 본 handoff 읽기.
2. 050d 본측정 결과(`.temp/experiments/active/EXP-050d-own-pack-recovery/battle_log/experiment_*.json`) 확인:
   - **있으면**: 정량(050a paired) + 정성(weather plan / oracle 데미지) 분석 → `docs/analysis/exp-050d-*.md` 작성(ANALYSIS_MANUAL 절차) → §5/CLAUDE.md 갱신.
   - **없으면**: 사용자에게 본측정 실행 안내(README 명령). 또는 050e 설계로 전환.
3. 050d 결과에 따라 050e(matrix v2 preserve fix) 설계.

---

## 컨텍스트 복원 가이드 (읽을 파일)

- **`experiment-context.md`** §0(행동규칙) · §5(실험 인덱스/이력 — 소스 오브 트루스).
- **분석 보고서**: `docs/analysis/exp-050a-react-glm51-analysis.md`(050a 상세, oracle 버그/§2 정정). 050b/c/d 보고서는 §5 비고 참조.
- **memory**(`/root/.claude/projects/-workspace/memory/`): `oracle-stats-ev-zero`(EV=0 왜곡), `own-team-info-recovery`(pack 회수 레버), `team-preview-050-series`(본 학습 요약), `oracle-impl-technique`.
- **codex 피드백**: `.temp/codex_feedback/lead-selection-feedback.md`(050e matrix 설계 기반).
- **plan 파일**: `/root/.claude/plans/misty-orbiting-brooks.md`(최신 — 인수인계 plan).
- **react roadmap**: `docs/architecture/react-architecture-redesign.md`(구 로드맵, 049 설계 중심 — 050 시리즈로 부분 구식).

---

## 미해결 / 보류

- **050c matrix** (60%, 보류): 050e에서 preserve 모순 fix + ability 회수(050d) 위에서 재평가.
- **050d 본측정**: 사용자 실행 대기. 결과 미도착.
- **opp stats 추정**: 050d는 own pack 회수만(결정론). opp EV/ability는 bayesian prediction(`bayesian/pokemon_predictor.py`) 별도 EXP — 설계 논리 필요.
- **matrix ability 인식**(050d에서 미구현): weather setter ability → proactive 가산 등. 050e에서.

---

## 코드 위치 (회수/매트릭스)

- `poke_env/player/team_util.py`: `FixedTeamProvider._load`(pack sets 보존 + species 보정) · `team_sets_at` · `FixedTeamCombo.player_sets_at`.
- `poke_env/environment/pokemon.py`: `__slots__`에 `_own_pack_set` 추가(fork 전용).
- `pokechamp/langchain_player.py`: `set_own_pack` · `_overlay_own_pack`(teampreview·choose_move) · teampreview(matrix 주입) · `_log_preview`(truncate 해제).
- `pokechamp/battle_memory.py`: `build_lead_payoff_matrix` · `classify_lead_mode`(050e fix 대상) · `predict_opp_leads`.
- `pokechamp/battle_state_mapper.py`: `_pack_pokemon`(own EV/nature/IV 회수) · `_build_active_state`(max_hp 생략 — 050a 버그 수정).
- `pokechamp/llm_player.py`: `_format_lead_selection_data`(own ability/item 회수).
- `scripts/battles/local_1v1_langchain.py`: fixed 모드 `set_own_pack` 호출.
