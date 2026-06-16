# PokéChamp Minimax Prompt Algorithm 작동 방식

> PokéChamp에서 `--player_prompt_algo minimax` 선택 시 LLM 기반 minimax tree search가 어떻게 동작하는지 정리한 문서.

---

## 1. 개요

Minimax 알고리즘은 **LLM이 행동 생성(action generation)과 리프 노드 평가(leaf evaluation)** 모두에 관여하는 하이브리드 검색 방식입니다. 순수 휴리스틱이 아닌 LLM의 판단력을 트리 탐색의 핵심에 배치하여, 복잡한 배틀 상황에서 장기적 최적 행동을 선택합니다.

### 핵심 구성요소

| 구성요소 | 파일 | 역할 |
|----------|------|------|
| `LLMPlayer` | `pokechamp/llm_player.py` | 오케스트레이터: 트리 생성, LLM 호출, minimax 역추적 |
| `LocalSim` | `poke_env/player/local_simulation.py` | 턴 시뮬레이터: 실제 배틀 규칙에 따라 상태 전이 |
| `SimNode` | `poke_env/player/local_simulation.py` | 트리 노드: 액션 쌍(player/opp)에 따른 상태와 자식 노드 보관 |
| `MinimaxOptimizer` | `pokechamp/minimax_optimizer.py` | 성능 최적화: 객체 풀링, 상태 캐싱 |
| `OptimizedSimNode` | `pokechamp/minimax_optimizer.py` | 풀링 기반 최적화 노드 |

---

## 2. 진입 경로

```
choose_move(battle)
  └─ prompt_algo == "minimax"
      ├─ use_optimized_minimax == True  → tree_search_optimized()
      └─ use_optimized_minimax == False → tree_search()
```

- `use_optimized_minimax` 기본값: `True`
- 예외 발생 시 `choose_max_damage_move()`로 폴백

---

## 3. 최적화 버전 (`tree_search_optimized`) 상세 흐름

### 3.1 초기화 및 Early Decision

```
tree_search_optimized(retries, battle)
│
├─ 1. MinimaxOptimizer 초기화 (최초 1회)
│     └─ LocalSimPool 생성, MinimaxCache(max_size=2000) 생성
│
├─ 2. OptimizedSimNode 루트 노드 생성
│     └─ battle 상태 deepcopy → LocalSim 인스턴스에 할당
│
├─ 3. get_player_prompt(return_actions=True)
│     └─ system_prompt, state_prompt, action_prompt_* 생성
│
└─ 4. LLM 사전 판단: "damage calculator vs minimax"
      ├─ LLM 호출 → {"choice": "damage calculator"} → dmg_calc_move() 즉시 반환
      └─ {"choice": "minimax"} 또는 예외 → 트리 탐색 계속
```

**LLM 사전 판단 프롬프트 요약**:
- damage calculator가 유리한 경우: 명확한 타입 우위, 상대 교체 없음, 빠른 KO 가능
- minimax가 유리한 경우: 복잡한 상황, 장기 전략 필요, 다수 유효 옵션 존재

### 3.2 BFS 트리 확장

```
BFS 큐: [root]
│
├─ 노드 pop
│   │
│   ├─ [종료 조건] is_terminal() 또는 depth == K (기본값 2)
│   │   └─ 리프 평가 (→ 섹션 3.3)
│   │
│   ├─ [플레이어 액션 생성] (최대 2개)
│   │   ├─ dmg_calc_move() → 최대 데미지 무브
│   │   └─ io() LLM 호출 → LLM 추천 무브/스위치
│   │
│   ├─ [상대 액션 생성] (최대 2개)
│   │   ├─ estimate_matchup() → 휴리스틱 최적 무브
│   │   └─ io() LLM 호출 (get_opponent_prompt) → LLM 예측 상대 행동
│   │
│   └─ [자식 노드 생성] action_p × action_o 조합 (최대 2×2=4개)
│       ├─ battle deepcopy → LocalSim.step(action_p, action_o)
│       └─ 큐에 추가
│
└─ 큐 빌 때까지 반복
```

**depth=2 기준 노드 수**:
- 루트 → 최대 4개 자식 → 각각 최대 4개 자식 = 최대 **1 + 4 + 16 = 21개 노드**
- 실제로는 액션 중복 제거로 더 적음

### 3.3 리프 노드 평가 (LLM Value Function)

종료 조건(terminal 또는 depth==K)에 도달한 노드에서 LLM이 상태를 평가합니다.

**프롬프트 구성**:
```
state_prompt (현재 배틀 상태)
+ value_prompt: "Evaluate the score from 1-100 based on how likely the player is to win..."
+ cot_prompt: "Briefly justify your total score, up to 100 words..."
```

**평가 기준 (value_prompt)**:
- 기본점: 50점에서 시작
- **가산**: 사용 가능한 무브의 효과성, 남은 포켓몬 수(강도 가중), 버프된 스탯, 상대 엔트리 해저드
- **감산**: 상태 이상, 자신의 엔트리 해저드, 과도한 스위칭, 상대 무브의 효과성(특히 더 빠른 스피드), 상대 남은 포켓몬 수

**출력 형식**: `{"score": <1-100 정수>}`

**폴백 체인**:
```
LLM value 평가 실패
  → dmg_calc_move 기반 평가 (우위/동등/불리 → 75/50/25)
    → get_hp_diff() (HP 비율 차이)
      → 50 (중립값)
```

### 3.4 Minimax 역추적

```
get_tree_action(root_node):
│
├─ 리프 노드 → (action, hp_diff, action_opp) 반환
│
└─ 내부 노드 → 자식들에 대해 재귀 호출
    │
    ├─ 같은 player action 끼리 그룹화
    │   └─ 각 그룹의 점수 = max(자식들의 hp_diff)
    │
    └─ 최고 점수의 player action 선택
        └─ (best_action, best_score, best_opp_action) 반환
```

> **참고**: 최적화 버전(`tree_search_optimized`)은 `max()`를 사용하지만, 원본 버전(`tree_search`)은 `min()`을 사용합니다. 이는 각각 "최적의 상대 대응 시 최고 점수" vs "최악의 상대 대응 시 최소 점수"를 선택하는 차이입니다.

### 3.5 결과 반환 및 정리

```
action, _, action_opp = get_tree_action(root)
│
├─ OptimizedSimNode 트리 정리 (객체 풀 반환)
├─ 성능 통계 출력 (소요 시간, 평가 노드 수, 캐시 적중률)
└─ BattleOrder 반환
```

---

## 4. 원본 버전 (`tree_search`)과의 차이

| 항목 | `tree_search` (원본) | `tree_search_optimized` (최적화) |
|------|---------------------|----------------------------------|
| 노드 타입 | `SimNode` (copy 기반) | `OptimizedSimNode` (풀링 기반) |
| LLM 사전 판단 | 노드 확장 중에 수행 | 루트 노드에서 사전 수행 |
| 역추적 방식 | `min()` (엄밀 minimax) | `max()` (최적 응답 기준 최고 점수) |
| 플레이어 액션 | dmg_calc + LLM move + LLM switch | dmg_calc + 1개 LLM io 호출 |
| 상대 액션 | 휴리스틱 + LLM + 매치업 스위치 | 휴리스틱 + 1개 LLM io 호출 |
| 액션 제한 | 제한 없음 | player/opp 각각 최대 2개 |
| 리프 평가 | 동일한 LLM value function | 동일 + 다중 폴백 체인 |
| 메모리 관리 | 수동 copy | 객체 풀 자동 회수 |

---

## 5. 턴당 LLM 호출 분석

depth=2 기준, 최적화 버전의 LLM 호출 횟수:

| 단계 | 호출 수 | 비고 |
|------|---------|------|
| 사전 판단 (damage calc vs minimax) | 1 | 루트에서 1회 |
| 루트 노드 액션 생성 | 1~2 | dmg_calc + io (최대 1회) |
| 루트 노드 상대 예측 | 1 | io 1회 |
| 자식 노드 액션 생성 (최대 4개 노드) | 4 | 각 노드당 io 1회 |
| 자식 노드 상대 예측 (최대 4개) | 4 | 각 노드당 io 1회 |
| 리프 노드 평가 (최대 16개) | ~16 | 각 리프당 LLM value function |
| **총합** | **~27** | 실제로는 캐시/중복 제거로 ~8회 |

> 실험 컨텍스트(`experiment-context.md`)에서는 "턴당 ~8회"로 기록. 이는 실제 액션 중복 및 early exit로 인한 것.

---

## 6. 데이터 흐름도

```
                         choose_move(battle)
                                │
                    ┌───────────┴───────────┐
                    │  minimax 알고리즘 선택  │
                    └───────────┬───────────┘
                                │
                ┌───────────────┴───────────────┐
                │  LLM: "damage calc vs minimax?" │  ← 1 LLM call
                └───────┬───────────────┬───────┘
                   "damage calc"    "minimax"
                        │               │
                   dmg_calc_move()   BFS 트리 확장
                        │               │
                        │    ┌──────────┴──────────┐
                        │    │  각 내부 노드:        │
                        │    │  ├─ player 액션 생성  │  ← dmg_calc + io()
                        │    │  ├─ opponent 액션 생성│  ← 휴리스틱 + io()
                        │    │  └─ 자식 노드 생성    │  ← LocalSim.step()
                        │    └──────────┬──────────┘
                        │               │
                        │    ┌──────────┴──────────┐
                        │    │  각 리프 노드:        │
                        │    │  └─ LLM value 평가   │  ← 1 LLM call/리프
                        │    └──────────┬──────────┘
                        │               │
                        │    minimax 역추적 (get_tree_action)
                        │               │
                        └───────┬───────┘
                                │
                          BattleOrder 반환
```

---

## 7. 핵심 설정 파라미터

| 파라미터 | 기본값 | 위치 | 설명 |
|----------|--------|------|------|
| `K` (depth) | `2` | `LLMPlayer.__init__` | 트리 탐색 깊이 |
| `temperature` | CLI에서 전달 (권장 0.3) | `choose_move` | LLM 생성 온도 |
| `use_optimized_minimax` | `True` | `LLMPlayer.__init__` | 최적화 버전 사용 여부 |
| `use_llm_value_function` | `True` | `LLMPlayer.__init__` | 리프 평가에 LLM 사용 |
| `max_depth_for_llm_eval` | `2` | `LLMPlayer.__init__` | LLM 평가 사용 최대 깊이 |
| `max_size` (cache) | `2000` | `MinimaxCache.__init__` | 상태 평가 캐시 크기 |
| `initial_size` (pool) | `1` | `LocalSimPool.__init__` | 초기 LocalSim 풀 크기 |

---

## 8. 실패 처리 및 폴백 체인

```
tree_search_optimized 예외
  → dmg_calc_move(battle) 시도
    → choose_max_damage_move(battle) (최종 폴백)

리프 노드 LLM 평가 실패
  → dmg_calc_move 기반 점수 (75/50/25)
    → get_hp_diff() (HP 비율 차이)
      → 50 (중립값)

LLM 사전 판단 실패
  → minimax 트리 탐색 계속 (폴백하지 않음)
```

---

## 9. 성능 최적화 메커니즘

### LocalSimPool (객체 풀링)
- `LocalSim` 인스턴스를 재사용하여 매 노드마다 새 객체 생성 비용 절감
- `acquire_sim(battle)` → deepcopy(battle)로 상태만 교체
- `release_sim()` → 풀로 반환

### MinimaxCache (상태 캐싱)
- `(BattleStateHash, player_action, opp_action)` → 평가 점수 캐싱
- LRU 방식: 캐시 가득 차면 가장 오래된 25% 제거
- 동일 상태 재평가 방지

### fast_battle_evaluation (휴리스틱 평가)
- `@lru_cache(maxsize=500)` 적용
- HP 이점, 팀 크기 이점, 턴 패널티 기반 빠른 점수 계산
- LLM 호출 없이 즉시 평가 (폴백용)

---

## 10. 요약

Minimax prompt algo는 **LLM + 시뮬레이션 하이브리드** 접근입니다:

1. **LLM이 의사결정의 핵심**: 행동 생성, 상대 예측, 리프 평가 모두 LLM 담당
2. **LocalSim이 물리 엔진**: 실제 배틀 규칙(데미지 계산, 상태 이상, 날씨 등)에 따라 상태 전이
3. **트리 탐색으로 장기 계획**: depth=2로 현재 턴과 다음 턴까지 고려
4. **성능 최적화**: 객체 풀링, 상태 캐싱, 액션 수 제한으로 실시간 배틀 가능
5. **다중 폴백**: LLM 실패 시 damage calc → HP diff → 중립값으로 단계적 폴백
