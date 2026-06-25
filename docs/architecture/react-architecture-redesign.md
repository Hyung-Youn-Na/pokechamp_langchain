# ReAct Agent 구조 변환 설계: B(다단계 노드) + D(턴 간 메모리) + Smogon 메타

> 작성일: 2026-06-23 (갱신 2026-06-24) · 실험 시리즈: EXP-049+
> 상태: **설계 확정 → 구현 단계**. 결정 사항:
>   - Smogon 주입 = **방식 1(새 도구)** · EXP-049 범위 = **분할(049a/b/c)** · baseline = **EXP-048**
> 자매 문서: [`smogon-meta-design.md`](smogon-meta-design.md) (Smogon 데이터 정제 설계)

---

## 1. 배경 (Context)

**EXP-048 종결**: oracle damage 정확도/분산 영역은 한계 도달. 시리즈(044 56.7 → 045 53.3 → 046 43.3 → 047 **63.3** → 048 53.3)가 증명한 것은 **"정확한 damage ≠ 더 나은 결정"**. EXP-048 분석이 지목한 다음 병목:

> *"다음 레버 = langGraph/react 구조 (damage observation → 전략 변환)"*

**현재 react 구조의 한계** (원본 코드 분석, `pokechamp/agents/react_agent.py`):
- 단일 선형 루프 `build_context → agent ⇄ tool_execution → parse_action`. damage 관찰을 **전략적 결론으로 번역하는 노드 부재** → LLM 자유 추론에 전적 의존.
- 매 턴 **stateless** (`messages=[]` 재생성, `langchain_player.py:223`). 배틀은 멀티턴 게임인데 단턴 결정만 → 장기 전략(포지셔닝·세팅·스위치 타이밍) 누적 불가.
- `BattleAgentState`의 `reasoning`, `evaluation_scores` 필드가 **dead field**(정의만 있고 react graph는 write 안 함, `state.py:58-59`).
- observation이 절대값 중심(`hp_lost %`, `battle_tools.py:424-447`) → 무브 간 순위·KO 찬스·조건부성(rain 전후) 미제시.

**핵심 제약 ★**: 이 프로젝트에서 **데이터/프롬프트 주입은 일관되게 역효과** (EXP-002~004 프롬프트 블로트 −10~16pp, EXP-035 데이터 주입 −20pp). 단, react는 도구 기반이라 **도구 호출 경로가 안전**함이 검증됨(EXP-035 분석: "react에는 게이트로 미도달"). 이 제약이 모든 설계 결정을 가른다.

---

## 2. 개선안 후보 A~E (원래 제안 전체 + 선택 근거) ★

구조 분석 말미에서 식별한 5개 레버. 이 중 **B + D** 를 선택, 거기에 **Smogon 메타**를 결합.

| 레버 | 내용 | 선택 | 근거 |
|---|---|---|---|
| **A. 상태 활성화** | dead field(`reasoning`, `evaluation_scores`)를 살려 노드 간 전략적 기억 전달 | ◐ 흡수 | B의 strategy 노드 + D의 메모리가 state write하므로 자연스럽게 달성 — 독립 레버가 아닌 B·D의 일부 |
| **B. 다단계 노드 도입** | damage 관찰을 종합하는 "전략 평가/계획" 노드 분리 (plan→act→reflect 계열) | ✅ **선택** | EXP-048이 지목한 "observation→전략 변환" 병목의 직접 타격. 정량 도구 루프와 전략 종합을 구조적 단계로 분리 |
| **C. observation 재구성** | 절대값 → 순위/KO찬스/조건부성 강조 형태 (calculate_damage 반환 개조) | ✗ 미선택 | EXP-048이 "관측 정확도 영역 한계 도달" 선언. observation을 더 정제해도 승률 무관(047→048 교训). 구조적 접근(B/D) 우선 |
| **D. 턴 간 메모리** | 배틀 단위 전략/상대 모델링 누적 | ✅ **선택** | 멀티턴 게임인데 단턴 결정(stateless)이 핵심 결함. 장기 전략·상대 win condition 추적으로 단기 수렴(EXP-046/048) 방지 |
| **E. 도구 오케스트레이션 구조화** | LLM 자유 재량 → 구조적 도구 라우팅/필터링 | ✗ 보류 | glm-5.1의 도구 실사용 빈도 리스크(tera 발동 0% 교训) — 구조화 라우팅이 작은 모델에서 오히려 미사용 유발. 방식 1(도구 추가)의 사후 호출 빈도 데이터 먼저 확보 |

**선택 조합의 논리**: EXP-048 진단 "정확도 영역 한계 → 구조 영역으로 전환"에 부합. C(관측 정교화)는 명시적으로 기각한 영역, E는 데이터 부재로 보류. **B(구조) + D(기억)** 가 "damage→전략 변환" 병목의 양축(현재 턴 해석 + 턴 간 누적). 여기에 Smogon 자연어 전략을 **해석 자원**으로 결합.

---

## 3. Smogon 데이터 개요 (결합 대상)

- `poke_env/data/static/gen9/ou/smogon_strategies_gen9ou.json` — 108종 / 197 moveset. 종당 `overview`(평균 ~1.7k자) + moveset별 `description`(평균 ~3.8k자) = **풍부한 자연어**. `overview_links` = 메타 체크 관계 그래프. `moveslots`(조합) + `moves_flat`(평탄화).
- `poke_env/data/static/gen9/ou/smogon_roles_gen9ou.json` — 11 카테고리 / 58 역할 / 114 포켓몬. `by_role`(역할→포켓몬), `by_pokemon`(포켓몬→역할, main/niche tier).
- 캐시: `pokechamp/data_cache.py:get_cached_smogon_strategies/roles()` (`lru_cache` + `orjson`).
- 정제 설계: [`smogon-meta-design.md`](smogon-meta-design.md) (활용처 중립 — 기존 양적 `sets_1500.json`을 질적으로 보완).

**두 종류 자연어가 B/D 양축에 각각 결합**: `overview`/`description`(서술) → B의 전략 종합 해석 자원; `overview_links`/`roles`(구조적) → D의 상대 팀 모델링.

---

## 4. D (턴 간 메모리) — 확정 설계 ★ [4종 전부 누적]

배틀 단위 메모리. **저장**: `LangChainPlayer._battle_memory: dict[str, BattleMemory]` (`battle_tag` 키 — 기존 `_decision_counts`/`_last_battle_tag` 패턴 동일, `langchain_player.py:72-73,130`). **주입**: 매 턴 `build_battle_state`가 state 필드로 채움. **갱신**: ①② 관측 기반 자동, ③④ LLM 결정 출력에서 추출.

```python
@dataclass
class BattleMemory:
    # ① 상대 팀 역할 밸런스 — team preview 1회, 배틀 내내 불변
    opp_role_balance: dict           # {category: count} (예: {"Setup Sweepers": 2, "Walls": 1})
    opp_team_roles: dict             # {species_key: [roles]} (roles.by_pokemon)
    # ② 드러난 관측 — 매 choose_move 시작 시 갱신
    opp_revealed: dict               # {species_key: {moves, item, tera, last_move, seen_turns}}
    # ③④ LLM 갱신 — strategy 노드 출력에서 추출
    opp_win_condition: str           # 추론된 상대 승리 경로
    my_plan: str                     # 내 승리 계획 + 다음 세팅/KO찰 타이밍
    plan_turn: int                   # my_plan 마지막 갱신 턴 (stale 방지 게이트)
```

| 메모리 | 원천 | 갱신 시점 | 역할 |
|---|---|---|---|
| ① opp_role_balance | `roles.by_pokemon` + team preview(`_teampreview_opponent_team`/`opponent_team`) | 배틀 시작 1회 | 상대 win condition 후보 식별 (Setup Sweeper 2마리면 "스위퍼 세팅 경계") |
| ② opp_revealed | `opponent_active_pokemon.moves`/`.item`/`.terastallized` | 매 턴 관측 | `predict_opponent_moves` 관측 보정; "Earthquake 드러남 → 내 Gholdengo 안전" 판단 |
| ③ opp_win_condition | LLM (strategy 노드 JSON) | N턴마다/매 턴 | 장기 대응: "상대 Dragonite DD 세팅" → 견제 타이밍 |
| ④ my_plan | LLM (strategy 노드 JSON) | 매 턴 또는 변경 시 | **단기 damage 수렴 방지** (EXP-046/048 병목 직접 타격): "내 win condition = Ting-Lu 해저드 → Gholdengo 스윕, 지금은 해저드 우선" |

**③④ 갱신 메커니즘**: strategy 노드(049b) 또는 agent/decide 노드(049a)가 JSON에 `{"win_condition_opponent": ..., "my_plan": ...}` 키 추가 출력. `parse_action`이 추출해 `player._battle_memory[btag]` 갱신. 실패 시 이전값 유지(stale → `plan_turn` freshness 게이트).

---

## 5. B (다단계 노드) — 새 그래프 토폴로지 ★ (EXP-049b)

**현재**: `build_context → agent ⇄ tool_execution → parse_action` (`react_agent.py:493-520`)

**제안**: 정량 도구 루프와 전략 종합을 노드로 분리. dead field(`reasoning`, `evaluation_scores`) 활성화.

```
build_context ──► tool_agent ⇄ tool_execution      (정량 도구: damage/상성/sim/strategy_insight)
                       │
                       ▼ (도구 종료 or 예산)
                strategy_synthesis                  (★ 신설: 정량 결과 + Smogon 자연어 + D 메모리 종합)
                       │                             → reasoning 갱신, opp_win_condition/my_plan 갱신
                       ▼
                    decide                          (최종 JSON — force-termination clean-rebuild 이관)
                       │
                       ▼
                     END
```

| 노드 | 역할 | state 갱신 |
|---|---|---|
| `build_context` | 시스템 프롬프트 + state + **D 메모리 주입** | messages |
| `tool_agent` | 정량 도구 호출 루프 (현재 agent 노드 도구호출 부분 분리) | messages, tool_call_count |
| `tool_execution` | 기존 동일 (dedup, 예산, `react_agent.py:238-350`) | messages |
| `strategy_synthesis` ★ | 정량 결과 + 상대/내 포켓몬 Smogon 전략 + 메모리를 **종합**해 "이 턴의 전략적 결론" 도출 + win condition/plan 갱신 | **reasoning**, **opp_win_condition**, **my_plan** |
| `decide` | 최종 JSON 출력 (현재 agent 노드 force-termination clean-rebuild 로직 `react_agent.py:138-205` 이관) | chosen_action |

**분리 이유**: 현재 "도구호출 + 결정 + 강제종료"가 agent 노드에 매몰. 분리로 (a) 정량 관찰의 전략적 해석이 **구조적 단계**화 → LLM 자유 추론 의존도 감소, (b) win condition/plan이 노드 출력으로 명시 갱신 → D 메모리 ③④와 결합, (c) dead field 활성화.

---

## 6. Smogon 주입 — 3방식 비교 + 방식 1 채택 ★

### 비교표

| | **방식 1: 새 분석 도구** ✅채택 | 방식 2: 전략 노드 직접 주입 | 방식 3: 구조화 요약 사전 추출 |
|---|---|---|---|
| 메커니즘 | `get_strategy_insight(species)` 도구, LLM 자발 호출 | strategy 노드가 매 턴 active 양측 overview 직접 포함 | overview → 체크관계/역할/무브용도 요약 사전 생성 후 주입 |
| 발동 | on-demand | 매 턴 무조건 | 매 턴 (경량) |
| 토큰/턴 | 호출 시에만 (~5.5k자) | 고정 ~11k자(양측) | ~0.5k자 |
| 역효과 리스크 | **낮음** (도구=react 안전경로) | **중~높음** (EXP-002~004 블로트) | 낮음 |
| 미사용 리스크 | **있음** (LLM이 안 부르면 0) | 없음 | 없음 |

### 방식 1 채택 근거 (2026-06-23)

1. **EXP-035가 검증한 react 안전 경로** — 도구 호출은 프롬프트/데이터 주입(역효과 경로)이 아님. 가장 낮은 역효과 리스크로 baseline 확보.
2. **점진적 검증** — 방식 1(049c) → 방식 3 → 필요시 방식 2 순. 각각 동일 B+D 구조에서 Smogon 주입만 변수(§0-4 준수).
3. **데이터 획득** — glm-5.1의 "도구 실사용 빈도"를 049c에서 측정 → E(도구 오케스트레이션) 보류 결정에 재활용.

### 방식 1 구현 명세

> ⚠️ **데이터 의존성 (2026-06-25 발견)**: 방식 1은 `get_strategy_insight`가 반환하는 **overview 데이터 품질에 전적으로 의존**. EXP-049c 당시 Smogon dex API가 96/108종(88.9%)의 OU overview를 빈으로 반환 → 도구가 빈 overview만 주어 LLM이 안 부름 → "방식 1 기각"으로 **오평가됨**. crawler `normalize()`에 Draft format "Overview:" fallback을 추가해 복구(검증 완료). overview 복구 후에야 방식 1이 정당 평가됨. 상세 = `smogon-meta-design.md` §6.

- **신규 도구** `battle_tools.py:get_strategy_insight(species: str, aspect: str = "overview") -> str`:
  - `get_cached_smogon_strategies()[species_key]` 에서 `overview` (기본) 또는 현재 moveset 매칭 `description` 반환.
  - `species_key` 매핑: `lower()` + `string.punctuation` 제거 (기존 `parse_sets.py` 규칙, `smogon-meta-design.md` §5.3).
  - 종 미존재 시 폴백 메시지. never raises.
  - `ALL_BATTLE_TOOLS` 등록.
- **시스템 프롬프트**: `REACT_SYSTEM_PROMPT`의 "Available Tools" 목록에 `get_strategy_insight` 설명 **1줄 추가만**. **별도 지시문(스위치 시 조회 권장 등)은 추가하지 않음** — 새 프롬프트 지시(EXP-002~004 위험)가 되므로.
- **사후 측정(049c 핵심)**: `get_strategy_insight` 호출 빈도. **0에 가까우면 방식 1 기각** (glm-5.1이 가치를 인식 못함 → 방식 2/3 전환 근거).

---

## 7. 실험 로드맵 (EXP-049+) — 분할 방식 ★

모든 실험: 동일 `dynamic-v2.json` manifest, seed 42, N=30, react/glm-5.1, opponent io/gemini-2.5-pro. **baseline = EXP-048** (전무브 oracle 통일 + N-roll 난수 분산, 53.3%).

> **baseline 철학 (2026-06-24)**: oracle로 **정확한 damage 계산은 필수** + 난수 발생은 게임의 피할 수 없는 시스템이므로 **LLM이 핸들링할 수 있도록 정보(min/max)를 제공**해야 함 → EXP-048(oracle on + N-roll) 기반 위에서 구조 변환을 측정. 추후 승률 자체는 oracle off(EXP-044, 56.7%)와도 최종 비교.

| EXP | 변경 (vs 직전, 단일 변수) | 기대 | 핵심 측정 |
|---|---|---|---|
| **EXP-049a** | **D 메모리 도입** (현행 그래프 유지, 4종 메모리 + win_condition/my_plan 갱신) | 장기 전략·상대 모델링 → 단기 damage 수렴 완화 | 승률 vs 048; **my_plan/opp_win_condition 갱신 빈도**; 장기전(>20턴) 승률 |
| **EXP-049b** | **+ B 노드** (strategy_synthesis 분리) | 정량→전략 종합 구조화 → observation→전략 변환 병목 타격 | 승률 vs 049a; reasoning 노드 활성화; 노드 분리 효과 |
| **EXP-049c** | **+ Smogon 방식 1 도구** (`get_strategy_insight`) | 메타 지식(자연어 전략) 도구 제공 | 승률 vs 049b; **get_strategy_insight 호출 빈도**(0이면 방식 1 기각) |
| (후속) | oracle off(EXP-044 기준) 동일 구조 | oracle 의존도 / 구조의 oracle-독립 효과 | 승률 vs 044 기반 동일 구조 |

**§0-4 준수**: 각 EXP는 직전 EXP 대비 변수 1개만. 인과: 049a(메모리) → 049b(노드) → 049c(도구) 순차 분리. 각 EXP 후 `git checkout HEAD -- <변경파일>` 원복 권장(오염 방지), 다음 변수 누적.

---

## 8. 구현 계획 (파일/함수 단위)

### EXP-049a — D 메모리 (현행 그래프 유지)

**신규 `pokechamp/battle_memory.py`**: `BattleMemory` dataclass + `build_team_roles(battle)`(team preview roles 집계) + `update_opp_revealed(memory, battle)`(매 턴 관측 누적) + species_key 매핑 헬퍼.

**수정 `pokechamp/agents/state.py`** (`BattleAgentState`): 필드 추가 — `opp_role_balance`, `opp_team_roles`, `opp_revealed`, `opp_win_condition`, `my_plan`, `plan_turn`.

**수정 `pokechamp/agents/common.py:build_battle_state`**: `BattleMemory` 인자 추가 → state 필드 채움.

**수정 `pokechamp/langchain_player.py`**: `__init__`에 `_battle_memory` dict; `_run_langgraph_agent`에서 battle_tag 변경 시 `build_team_roles` 1회, 매 턴 `update_opp_revealed`, state 주입, 결과에서 win_condition/my_plan 추출 갱신.

**수정 `pokechamp/agents/react_agent.py`**: `build_context`에 메모리 경량 요약 주입; `REACT_SYSTEM_PROMPT`에 win_condition_opponent/my_plan JSON 키 출력 지시(최소); `parse_action`에서 키 추출.

### EXP-049b — B 노드 (049a 누적)

`react_agent.py:create_react_agent`: 현행 `agent` 노드 → `tool_agent` + `strategy_synthesis`(★신설) + `decide`(force-termination 이관) 분할. 엣지 재구성. dead field 활성화.

### EXP-049c — Smogon 방식 1 도구 (049b 누적)

`battle_tools.py`: `@tool get_strategy_insight` 추가 + `ALL_BATTLE_TOOLS` 등록. `REACT_SYSTEM_PROMPT` "Available Tools"에 설명 1줄(별도 지시문 없음).

### 검증

- **단위**: `BattleMemory` 갱신(team preview→role_balance, 매 턴→opp_revealed 누적); species_key 매핑(108종 조인); (049c) get_strategy_insight 스키마; (049b) strategy_synthesis 출력 추출.
- **회귀**: 기존 `tests/test_react_oracle_*.py`(57+ 단위), oracle 15개 유지.
- **통합**: fixed dynamic-v2 1판 샘플 → 메모리 턴 간 유지, my_plan 갱신 관측.
- **실행**: 배틀은 사용자 직접(§0-8). 에이전트는 코드 + 디렉토리/README + 명령 안내.
