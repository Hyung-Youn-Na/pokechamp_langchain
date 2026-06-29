# PokéChamp LangGraph Tool 아키텍처

> `scripts/battles/local_1v1_langchain.py`를 시작점으로 하는 LangGraph 기반 배틀 에이전트 시스템의 전체 아키텍처 문서입니다.

---

## 1. 시스템 개요

### 1.1 전체 아키텍처

```
┌─────────────────────────────────────────────────────────────────────┐
│  scripts/battles/local_1v1_langchain.py  (엔트리포인트)            │
│  ├── LANGCHAIN_PROMPT_ALGOS = ["react", "io_langchain", "cot_langchain"]
│  ├── _get_langchain_player() → LangChainPlayer 인스턴스 생성       │
│  └── main() → 배틀 루프, 메트릭 수집                               │
└───────────────────────────┬─────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│  pokechamp/langchain_player.py  (LangChainPlayer)                  │
│  ├── LLMPlayer 상속 → 기존 알고리즘은 super().choose_move()로 위임 │
│  ├── _get_chat_model() → LangChain BaseChatModel 획득             │
│  ├── _get_graph(algo) → 알고리즘별 CompiledStateGraph 캐싱/생성    │
│  ├── choose_move(battle) → 알고리즘 분기 라우팅                     │
│  └── _run_langgraph_agent(battle, algo) → 핵심 실행 로직           │
└───────────────────────────┬─────────────────────────────────────────┘
                            │
              ┌─────────────┼─────────────┐
              ▼             ▼             ▼
┌──────────────────┐ ┌────────────┐ ┌──────────────────┐
│  ReAct Agent     │ │  IO Agent  │ │  CoT Agent       │
│  (react_agent.py)│ │(io_agent.py)│ │(cot_agent.py)    │
│                  │ │            │ │                   │
│  build_context   │ │build_prompt│ │ build_prompt      │
│       ↓          │ │     ↓      │ │     ↓             │
│  tool_agent ←──→ │ │ call_llm   │ │ think (CoT)       │
│  tool_execution  │ │     ↓      │ │     ↓             │
│       ↓          │ │parse_action│ │ decide            │
│  parse_action    │ │            │ │                   │
└──────┬───────────┘ └────────────┘ └───────────────────┘
       │
       ▼  (ReAct만 Tool 사용)
┌─────────────────────────────────────────────────────────────────────┐
│  pokechamp/battle_tools.py  (9개 @tool 함수)                       │
│                                                                     │
│  ┌─────────────────────┐  ┌──────────────────────────┐             │
│  │ calculate_damage    │  │ check_type_effectiveness │             │
│  │ analyze_matchup     │  │ get_team_analysis        │             │
│  │ simulate_turn       │  │ get_move_details         │             │
│  │ predict_opponent_   │  │ evaluate_position        │             │
│  │ moves               │  │                          │             │
│  └─────────────────────┘  └──────────────────────────┘             │
│                                                                     │
│  BattleContext (module-level 전역 상태)                              │
│  set_battle_context() / get_battle_context()                        │
└─────────────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│  pokechamp/langchain_backend.py  (LangChainBackend)                 │
│  ├── init_chat_model() → 50+ 프로바이더 지원                       │
│  ├── OllamaChatModel → Ollama Cloud / Local 커스텀 구현            │
│  ├── get_LLM_action() → (output, json_flag, raw) 튜플 반환        │
│  └── get_LLM_query() → (message, json_flag) 튜플 반환             │
└─────────────────────────────────────────────────────────────────────┘
```

### 1.2 모듈 의존 관계

```
agents/state.py          ← 모든 에이전트가 공유하는 BattleAgentState TypedDict
     │
     ▼
agents/common.py         ← build_battle_state(), action_to_battle_order()
     │
     ├──────────────────────────────────────┐
     ▼                  ▼                   ▼
agents/react_agent.py  agents/io_agent.py  agents/cot_agent.py
     │
     ▼
battle_tools.py         ← 9개 LangChain @tool 함수
```

### 1.3 핵심 설계 원칙

- **비침투적(Non-invasive)**: 기존 파일(`llm_player.py`, `prompts.py` 등)은 수정하지 않음
- **순수 추가(Purely additive)**: `agents/`, `battle_tools.py`, `langchain_player.py`, `langchain_backend.py`가 전부 새로 추가된 모듈
- **기존 알고리즘 호환**: `io`, `sc`, `cot`, `tot`, `minimax` 등 기존 prompt_algo는 `super().choose_move()`로 그대로 동작

---

## 2. Battle Tools 상세

`pokechamp/battle_tools.py`에 정의된 9개의 LangChain `@tool` 함수. ReAct 에이전트가 배틀 분석을 위해 호출합니다.

### 2.1 컨텍스트 주입 패턴: BattleContext

```python
@dataclass
class BattleContext:
    sim: Any                    # LocalSim 인스턴스
    battle: Any                 # AbstractBattle 인스턴스
    active_pokemon: Pokemon     # 플레이어 활성 포켓몬
    opponent_pokemon: Pokemon   # 상대 활성 포켓몬
    weather: str | None         # 현재 날씨
    terrain: str | None         # 현재 필드
```

**주입 메커니즘**:

1. `LangChainPlayer._run_langgraph_agent()`에서 매 턴 `BattleContext` 인스턴스 생성
2. `set_battle_context(ctx)` → 모듈 전역 변수 `_current_context`에 저장
3. 각 Tool 함수 내부에서 `get_battle_context()`로 가져와 사용
4. Tool은 상태가 없는(stateless) 순수 함수로 설계

```
LangChainPlayer._run_langgraph_agent()
    │
    ├── ctx = BattleContext(sim, battle, active_pokemon, ...)
    ├── set_battle_context(ctx)        ← 전역 컨텍스트 설정
    │
    └── graph.invoke(state)
            │
            ├── tool_agent → tool_calls
            │       │
            │       ▼
            │   tool_execution 노드
            │       │
            │       ▼
            │   calculate_damage()
            │       └── ctx = get_battle_context()   ← 전역 컨텍스트 읽기
            │
            ├── strategy_synthesis → clean rebuild 결정 (EXP-049b)
            │
            └── parse_action → 결과 반환
```

### 2.2 Tool 목록

#### 2.2.1 `calculate_damage`

| 항목 | 내용 |
|------|------|
| **목적** | 특정 기술의 예상 데미지, KO 턴수 계산 |
| **선언** | `@tool(parse_docstring=True)` |
| **입력** | `move_name: str` (기술명), `target_species: Optional[str]` (상대 종류, 기본값=활성 상대) |
| **출력** | JSON 문자열: `{move, attacker, defender, defender_hp_after, hp_lost, turns_to_ko, estimated_remaining_hp}` |
| **내부 로직** | `sim.calculate_remaining_hp()` → `get_number_turns_faint()` |
| **제약** | 변화기술(category=STATUS)은 거부 → `"error": "...not a damaging move"` |
| **의존** | `prompts.get_number_turns_faint`, `LocalSim.calculate_remaining_hp` |

#### 2.2.2 `check_type_effectiveness`

| 항목 | 내용 |
|------|------|
| **목적** | 특정 타입이 상대 포켓몬에 대해 갖는 상성 배율 조회 |
| **입력** | `attacking_type: str` (예: "fire"), `defender_species: Optional[str]` |
| **출력** | JSON: `{attacking_type, defender, defender_types, multiplier, description}` |
| **내부 로직** | `calculate_move_type_damage_multipier()` → 0x/0.25x/0.5x/1x/2x/4x 매핑 |
| **의존** | `poke_env.player.local_simulation.calculate_move_type_damage_multipier` |

#### 2.2.3 `analyze_matchup`

| 항목 | 내용 |
|------|------|
| **목적** | 두 포켓몬 간 매치업 종합 분석 (스피드, 타입 이점, 최적 기술) |
| **입력** | `attacker_species: Optional[str]`, `defender_species: Optional[str]` |
| **출력** | JSON: `{attacker, defender, speed{ratio, outspeed}, type_advantage, best_move, best_move_turns_to_ko, hp}` |
| **내부 로직** | 스피드 비교 → 양측 타입 이점 분석 → 모든 기술 KO 턴수 테스트 → 최적 기술 선정 |
| **의존** | `prompts.get_number_turns_faint` |

#### 2.2.4 `get_team_analysis`

| 항목 | 내용 |
|------|------|
| **목적** | 팀 전체의 타입 커버리지, 공통 약점/내성 분석 |
| **입력** | `side: str` ("player" 또는 "opponent") |
| **출력** | JSON: `{side, alive, fainted, members[], shared_weaknesses{}, shared_resistances{}}` |
| **내부 로직** | 18개 타입 전부 순회 → 각 포켓몬에 대한 배율 계산 → 2마리 이상 공통 약점/내성 추출 |
| **의존** | 18개 타입 상수 목록 (`ALL_TYPES`) |

#### 2.2.5 `predict_opponent_moves`

| 항목 | 내용 |
|------|------|
| **목적** | 상대 포켓몬의 기술배 예측 (확인된 기술 + 통계적 예측) |
| **입력** | `species: Optional[str]` (상대 포켓몬 종류) |
| **출력** | JSON: `{species, confirmed_moves[], predicted_moves[]}` |
| **내부 로직** | `sim.get_opponent_current_moves(return_separate=True)` → 폴백: `get_cached_pokemon_move_dict()` |
| **의존** | `data_cache.get_cached_pokemon_move_dict`, `LocalSim.get_opponent_current_moves` |

#### 2.2.6 `simulate_turn`

| 항목 | 내용 |
|------|------|
| **목적** | 양측 기술을 지정하여 1턴 시뮬레이션 |
| **입력** | `player_move: str`, `estimated_opponent_move: str` |
| **출력** | JSON: `{player_move, opponent_move, player_hp_before, player_hp_after, opponent_hp_before, opponent_hp_after, player_move_success, opponent_move_success}` |
| **내부 로직** | `_find_move()`로 Move 객체 생성 → `sim.calculate_remaining_hp()` 실행 |
| **의존** | `LocalSim.calculate_remaining_hp` |

#### 2.2.7 `get_move_details`

| 항목 | 내용 |
|------|------|
| **목적** | 기술의 정적 속성 + 동적 속성(날씨/필드/테라/아이템 반영) 상세 조회 |
| **입력** | `move_name: str` |
| **출력** | JSON: `{name, base_type, base_power, accuracy, pp, category, priority, dynamic_type, effective_type, dynamic_power, effective_power, dynamic_priority, effective_priority, effect}` |
| **내부 로직** | `_find_move()` → `resolve_dynamic_type()`, `resolve_dynamic_power()`, `resolve_dynamic_priority()` |
| **의존** | `dynamic_move.resolve_dynamic_type/power/priority`, `data_cache.get_cached_move_effect` |

#### 2.2.8 `evaluate_position`

| 항목 | 내용 |
|------|------|
| **목적** | 현재 포지션의 승리 확률 휴리스틱 평가 (0~100점) |
| **입력** | 없음 |
| **출력** | JSON: `{score, interpretation, breakdown{player_active_hp, opponent_active_hp, player_team_alive, opponent_team_alive, turn}}` |
| **내부 로직** | `fast_battle_evaluation()` → 팀 수 차이 보정 (마싱 포켓몬당 -25, 라스트 포켓몬 -35) |
| **의존** | `minimax_optimizer.fast_battle_evaluation` |

#### 2.2.9 `get_strategy_insight` (EXP-049c)

| 항목 | 내용 |
|------|------|
| **목적** | Smogon 커뮤니티 전략(역할/견제/약점/승리 경로) 자연어 조회 |
| **입력** | `species: str`, `aspect: str = "overview"` ("overview" 또는 "moveset") |
| **출력** | JSON `{species, home_tier, overview/moveset}` 또는 `{no_data: true}` (데이터 결함 시) |
| **내부 로직** | `get_cached_smogon_strategies()`에서 종족 키 조회 → overview/moveset 캡(2000자, bloat guard) |
| **제약** | overview 빈 시 `no_data` 플래그 → tool-call 예산에서 제외(대안 도구 예산 확보) |
| **의존** | `data_cache.get_cached_smogon_strategies`, `battle_memory.to_species_key` |

### 2.3 Tool 내보내기

```python
ALL_BATTLE_TOOLS = [
    calculate_damage,
    check_type_effectiveness,
    analyze_matchup,
    get_team_analysis,
    predict_opponent_moves,
    simulate_turn,
    get_move_details,
    evaluate_position,
    get_strategy_insight,   # EXP-049c (Smogon method 1)
]
```

에이전트 생성 시 `ALL_BATTLE_TOOLS` 리스트를 통째로 전달하거나, 서브셋을 선택할 수 있습니다.

### 2.4 보조 함수

| 함수 | 위치 | 목적 |
|------|------|------|
| `_get_pokemon_types(pokemon)` | `battle_tools.py:86` | Pokemon 타입을 `["WATER", "FAIRY"]` 형태의 깨끗한 문자열 리스트로 반환 |
| `_get_type_multiplier(type, defender, chart)` | `battle_tools.py:100` | 타입 상성 배율 숫자 반환 (0.0~4.0) |
| `_find_move(move_name, ctx)` | `battle_tools.py:150` | 기술명으로 Move 객체 찾기 (활성 포켓몬 기술 → 전체 기술 풀) |
| `_find_opponent_pokemon(species, ctx)` | `battle_tools.py:166` | 상대 포켓몬을 종류명으로 검색 (활성 → 팀 전체) |
| `_pokemon_to_dict(pokemon)` | `battle_tools.py:194` | Pokemon 객체를 직렬화 가능한 dict로 변환 |

---

## 3. 에이전트 그래프 아키텍처

`pokechamp/agents/` 디렉토리에 3종류의 LangGraph 에이전트가 구현되어 있습니다.

### 3.1 ReAct 에이전트 (`react_agent.py`)

가장 정교한 에이전트. Tool Calling을 활용한 ReAct(Reasoning + Acting) 루프를 실행합니다.

> **EXP-049b 구조 (5노드):** `build_context → tool_agent ⇄ tool_execution → strategy_synthesis → parse_action`.
> 과거 `agent_loop`(툴 호출 + 강제종료 통합)가 `tool_agent`(툴 호출만)와 `strategy_synthesis`(clean rebuild)로
> 분리되었습니다. 아래 단순화 다이어그램은 4박스 요약이며, 노드 표가 정확합니다.

```
┌──────────────┐     ┌─────────────────────┐     ┌──────────────────┐
│ build_context│────→│     tool_agent      │────→│   parse_action   │
│              │     │  ┌───────────────┐  │     │                  │
│ messages 초기│     │  │ LLM 호출      │  │     │ JSON에서 action  │
│ 시스템/유저  │     │  │ tool_calls?   │  │     │ 추출             │
│ 프롬프트 구성│     │  └───────┬───────┘  │     └──────────────────┘
└──────────────┘     │     yes  │  no     │
                     │         ▼          │
                     │ ┌──────────────┐   │
                     │ │tool_execution│   │
                     │ │              │   │
                     │ │Tool 호출     │   │
                     │ │→ ToolMessage │   │
                     │ └──────┬───────┘   │
                     │        │           │
                     └────────┘           │
                     (루프 반복, 최대 5회) │
```

**그래프 노드**:

| 노드 | 함수 | 역할 |
|------|------|------|
| `build_context` | `build_context(state)` | 시스템 프롬프트 + 배틀 상태를 messages에 구성 |
| `tool_agent` | `tool_agent(state, llm, tools)` | LLM에 메시지 전송 → 도구 호출 여부 판단. **강제종료 안 함**(EXP-049b 분리) |
| `tool_execution` | `tool_execution(state, tools_by_name)` | AIMessage.tool_calls에서 도구명/인자 추출 → 실행 → ToolMessage 생성 |
| `strategy_synthesis` | `strategy_synthesis(state, llm)` | 툴 루프 종료 후 **clean rebuild**로 전략 결정 + `my_plan` 장기화 (EXP-049b) |
| `parse_action` | `parse_action(state)` | 대화 히스토리에서 최종 JSON 액션 추출 |

**라우팅 로직** (`should_continue`, EXP-049b):
- AIMessage에 `tool_calls`가 있고 예산 남았으면 → `"tools"` (tool_execution)
- 그 외(툴 호출 없음 / 예산 도달) → `"strategy_synthesis"` (clean rebuild)
- 카운터는 state의 `tool_call_count`(Annotated) 기반 (`"parse"` 라우팅은 더 이상 사용 안 함)

**제약사항**:
- 최대 5회 Tool 호출/턴
- 변화기술에 대해 `calculate_damage` 호출 시 에러 메시지로 안내
- 도구 호출 실패 시 graceful degradation

### 3.2 IO 에이전트 (`io_agent.py`)

가장 단순한 베이스라인 에이전트. 단일 LLM 호출로 결과를 생성합니다.

```
┌──────────────┐     ┌──────────┐     ┌──────────────┐
│ build_prompt │────→│ call_llm │────→│ parse_action │
│              │     │          │     │              │
│시스템+유저   │     │1회 LLM   │     │JSON 파싱     │
│프롬프트 구성 │     │호출      │     │              │
└──────────────┘     └──────────┘     └──────────────┘
```

**그래프 노드**:

| 노드 | 역할 |
|------|------|
| `build_prompt` | 시스템 프롬프트 + 배틀 상태를 메시지로 구성 |
| `call_llm` | LLM 단일 호출 → AIMessage 추가 |
| `parse_action` | 응답에서 JSON 액션 추출 |

**특징**: Tool 없이 프롬프트만으로 행동 결정. 가장 빠르지만 정확도는 낮음.

### 3.3 CoT 에이전트 (`cot_agent.py`)

Chain-of-Thought 방식. 추론 단계와 의사결정 단계를 분리합니다.

```
┌──────────────┐     ┌──────────┐     ┌──────────┐
│ build_prompt │────→│  think   │────→│  decide  │
│              │     │          │     │          │
│프롬프트 구성 │     │CoT 추론  │     │최종 결정 │
│              │     │(최대 4문)│     │          │
└──────────────┘     └──────────┘     └──────────┘
```

**그래프 노드**:

| 노드 | 역할 |
|------|------|
| `build_prompt` | 초기 프롬프트 구성 |
| `think` | "think step by step" 지시 → 최대 4문장 추론 → reasoning 필드에 저장 |
| `decide` | 추론 내용에서 최종 액션 파싱 |

**특징**: IO보다 나은 추론 품질, ReAct보다 빠름 (Tool 호출 없음).

---

## 4. State Schema

`pokechamp/agents/state.py`에 정의된 `BattleAgentState` TypedDict. 모든 에이전트 그래프가 공유합니다.

```python
class BattleAgentState(TypedDict):
    # -- LangChain 메시지 채널 --
    messages: List[AnyMessage]

    # -- 배틀 컨텍스트 (턴당 1회 설정) --
    battle_tag: str
    turn: int
    battle_format: str

    # -- 사용 가능한 액션 --
    available_moves: List[Dict[str, Any]]
    available_switches: List[Dict[str, Any]]
    can_dynamax: bool
    can_tera: bool

    # -- 배틀 상태 요약 --
    active_pokemon: Optional[Dict[str, Any]]
    opponent_pokemon: Optional[Dict[str, Any]]
    team_summary: str
    opponent_summary: str
    weather: Optional[str]
    terrain: Optional[str]

    # -- state_translate 프롬프트 --
    system_prompt: str
    state_prompt: str
    state_action_prompt: str
    constraint_prompt: str

    # -- 추론 상태 --
    reasoning: str
    evaluation_scores: Dict[str, float]

    # -- 배틀 메모리 (EXP-049a, design D — 턴 간 누적) --
    opp_role_balance: Dict[str, int]
    opp_team_roles: Dict[str, List[Dict]]
    opp_revealed: Dict[str, Dict]
    opp_win_condition: str
    my_plan: str
    plan_turn: int
    tool_call_count: Annotated[int, _add_int]      # success만 누적 (EXP-049b)

    # -- LLM 사용량 추적 (reducer로 누적) --
    total_prompt_tokens: Annotated[int, _add_int]      # 노드 간 합산
    total_completion_tokens: Annotated[int, _add_int]   # 노드 간 합산
    llm_call_count: Annotated[int, _add_int]            # 노드 간 합산

    # -- 최종 출력 --
    chosen_action: Optional[Dict[str, Any]]
    chosen_dynamax: bool
    chosen_tera: bool
```

**Reducer 패턴**: `Annotated[int, _add_int]` 필드는 여러 노드에서 값을 반환할 때 자동으로 합산됩니다. 이를 통해 여러 LLM 호출에 걸쳐 토큰 사용량을 누적할 수 있습니다.

```python
def _add_int(a: int, b: int) -> int:
    """Reducer that sums integer values across graph nodes."""
    return a + b
```

---

## 5. 실행 흐름

### 5.1 진입점에서 그래프 실행까지

```
local_1v1_langchain.py main()
    │
    ├── _get_langchain_player()
    │       └── LangChainBackend(model_spec) 생성
    │       └── LangChainPlayer(backend, llm_backend, prompt_algo="react") 생성
    │
    └── await player.battle_against(opponent, n_battles=1)
            │
            └── LangChainPlayer.choose_move(battle)    [매 턴 호출]
                    │
                    ├── 알고리즘 라우팅
                    │   ├── "react" / "io_langchain" / "cot_langchain" → _run_langgraph_agent()
                    │   └── 그 외 → super().choose_move() (기존 코드 경로)
                    │
                    └── _run_langgraph_agent(battle, algo)
                            │
                            ├── LocalSim 생성 (기존과 동일)
                            ├── 조기 종료 체크 (기절/1선택지)
                            ├── 전략 프롬프트 업데이트 (턴 1)
                            ├── 제약 프롬프트 생성 (JSON 출력 형식)
                            │
                            ├── BattleContext 생성 + set_battle_context()
                            ├── build_battle_state(battle, sim, constraint)
                            │
                            ├── LLMLoggingCallback 설정 (log_dir 있을 시)
                            │
                            └── graph.invoke(state, config=callbacks)
                                    │
                                    └── [에이전트 그래프 실행]
                                    │
                                    └── result = {chosen_action, reasoning,
                                                   total_prompt_tokens, ...}
                            │
                            ├── 토큰/LLM 호출 메트릭 누적
                            │
                            └── action_to_battle_order(result["chosen_action"], battle)
                                    │
                                    └── BattleOrder 반환
```

### 5.2 State 생성: `build_battle_state()`

`pokechamp/agents/common.py`에 정의. `AbstractBattle` + `LocalSim` → `BattleAgentState` dict 변환.

```python
def build_battle_state(battle, sim, constraint_prompt) -> dict:
    """AbstractBattle + LocalSim → BattleAgentState dict"""
    # 1. 기존 프롬프트 재사용: sim.state_translate()
    # 2. 구조화된 데이터 추출: available_moves, switches, pokemon info
    # 3. BattleAgentState의 모든 필드를 dict로 반환
```

### 5.3 액션 파싱: `action_to_battle_order()`

`pokechamp/agents/common.py`에 정의. 그래프 결과 → `BattleOrder` 변환.

```python
def action_to_battle_order(action: dict, battle: AbstractBattle) -> BattleOrder:
    """parsed action dict → BattleOrder for poke-env"""
    # 1. action["move"] → battle.available_moves에서 매칭
    # 2. action["switch"] → battle.available_switches에서 매칭
    # 3. dynamax/terastallize 플래그 처리
```

**지원 액션 형식**:

```json
{"move": "thunderbolt"}
{"move": "thunderbolt", "dynamax": true}
{"move": "thunderbolt", "terastallize": true}
{"switch": "pikachu"}
```

---

## 6. LLM Backend

### 6.1 LangChainBackend (`langchain_backend.py`)

50+ 프로바이더를 지원하는 통합 백엔드. LangChain의 `init_chat_model()`을 활용합니다.

```python
class LangChainBackend:
    def __init__(self, model_spec: str):
        # "provider:model" 형식
        if model_spec.startswith("ollama:"):
            self.chat_model = OllamaChatModel(model=...)
        else:
            self.chat_model = init_chat_model(model_spec)
```

**지원 프로바이더 명명 규칙**:

| model_spec | 프로바이더 |
|-----------|-----------|
| `openai:gpt-4o` | OpenAI |
| `google_genai:gemini-2.5-flash` | Google Gemini |
| `ollama:glm-5.1:cloud` | Ollama Cloud / Local |
| `openrouter:anthropic/claude-sonnet-4-5` | OpenRouter |

### 6.2 OllamaChatModel (`langchain_backend.py`)

LangChain `BaseChatModel`을 상속한 커스텀 구현. `langchain-ollama` 의존성 없이 `ollama` 라이브러리만 사용합니다.

```python
class OllamaChatModel(BaseChatModel):
    model: str = "llama3.1"
    temperature: float = 0.7

    def bind_tools(self, tools) -> "OllamaChatModel":
        """도구 바인딩 (ReAct 에이전트에서 사용)"""
        return self.bind(tools=list(tools))

    def _generate(self, messages, ...) -> ChatResult:
        """Ollama API 호출 → AIMessage 반환"""
        # Cloud: OLLAMA_API_KEY → https://ollama.com
        # Local: http://localhost:11434
```

**Tool Calling 지원**:
- `bind_tools()` → 도구 스키마를 kwargs에 저장
- `_generate()` → `_lc_tools_to_ollama()`로 Ollama 형식 변환 → API 호출
- 응답의 `tool_calls`를 LangChain `AIMessage.tool_calls` 형식으로 변환

### 6.3 백엔드 매핑 (엔트리포인트)

`local_1v1_langchain.py`에서 백엔드 문자열 → LangChain 프로바이더 spec 변환:

```python
if "gpt" in backend:     → f"openai:{backend}"
elif "gemini" in backend: → f"google_genai:{backend}"
elif "ollama/" in backend: → f"ollama:{...}"
else:                     → f"openrouter:{backend}"
```

---

## 7. 로깅: LLMLoggingCallback

`pokechamp/agents/llm_logging.py`에 정의. LangChain `BaseCallbackHandler`를 상속합니다.

### 7.1 구조

```python
class LLMLoggingCallback(BaseCallbackHandler):
    """LangChain 콜백으로 LLM 호출/도구 호출을 JSONL 파일에 기록"""

    def on_llm_start(self, serialized, prompts, **kwargs):  # LLM 호출 시작
    def on_llm_end(self, response, **kwargs):                # LLM 호출 완료
    def on_llm_error(self, error, **kwargs):                 # 에러
    def on_tool_start(self, serialized, input_str, **kwargs): # 도구 호출 시작
    def on_tool_end(self, output, **kwargs):                  # 도구 호출 완료
```

### 7.2 로그 포맷

**LLM 로그** (`langgraph_llm_log.jsonl`):

```json
{
  "timestamp": "2025-01-15T10:30:00",
  "battle_tag": "battle-gen9ou-12345",
  "turn": 5,
  "llm_call_in_turn": 1,
  "system_prompt": "...",
  "user_prompt": "...",
  "llm_response": "...",
  "tool_calls": [{"name": "calculate_damage", "args": {"move_name": "thunderbolt"}}],
  "token_usage": {"input_tokens": 500, "output_tokens": 100}
}
```

**Tool 로그** (`langgraph_tool_log.jsonl`):

```json
{
  "timestamp": "2025-01-15T10:30:01",
  "battle_tag": "battle-gen9ou-12345",
  "turn": 5,
  "tool_name": "calculate_damage",
  "tool_input": {"move_name": "thunderbolt"},
  "tool_output": "{\"move\": \"thunderbolt\", ...}"
}
```

### 7.3 스레드 안전성

- `threading.Lock`을 사용하여 동시 파일 쓰기를 보호
- 각 배틀/턴 조합에 대해 독립적인 로그 파일 생성

---

## 8. 사용법 요약

### 8.1 실행 명령

```bash
# ReAct 에이전트 (Tool Calling)
uv run python scripts/battles/local_1v1_langchain.py \
    --player_prompt_algo react \
    --player_backend gemini-2.5-flash \
    --opponent_name abyssal

# IO 에이전트 (베이스라인)
uv run python scripts/battles/local_1v1_langchain.py \
    --player_prompt_algo io_langchain \
    --player_backend openai:gpt-4o

# CoT 에이전트
uv run python scripts/battles/local_1v1_langchain.py \
    --player_prompt_algo cot_langchain \
    --player_backend gemini-2.5-pro
```

### 8.2 프롬프트 알고리즘 선택

| 알고리즘 | 클래스 | Tool 사용 | 특징 |
|----------|--------|----------|------|
| `react` | ReAct | O (9개) | Tool Calling 기반 정량 분석 |
| `io_langchain` | IO | X | 단일 LLM 호출 베이스라인 |
| `cot_langchain` | CoT | X | Chain-of-Thought 추론 |
| 그 외 (io, sc, cot, tot, minimax...) | LLMPlayer | X | 기존 코드 경로 (변경 없음) |

### 8.3 새 Tool 추가 방법

1. `pokechamp/battle_tools.py`에 `@tool(parse_docstring=True)` 함수 추가
2. `ALL_BATTLE_TOOLS` 리스트에 추가
3. `react_agent.py`의 `REACT_SYSTEM_PROMPT`에 도구 설명 업데이트
4. 별도의 설정 없이 ReAct 에이전트가 자동으로 새 도구를 사용

### 8.4 새 에이전트 추가 방법

1. `pokechamp/agents/`에 새 에이전트 파일 생성 (예: `tot_agent.py`)
2. `BattleAgentState`를 공유 State로 사용
3. `StateGraph(BattleAgentState)`로 그래프 구성
4. `create_xxx_agent(llm)` 팩토리 함수 구현
5. `LangChainPlayer._get_graph()`에 새 알고리즘 분기 추가
6. `local_1v1_langchain.py`의 `LANGCHAIN_PROMPT_ALGOS`에 추가

---

## 9. 파일 인덱스

| 파일 경로 | 줄수 | 역할 |
|-----------|------|------|
| `scripts/battles/local_1v1_langchain.py` | 431 | 엔트리포인트, 배틀 루프, 메트릭 |
| `pokechamp/langchain_player.py` | 262 | LangChainPlayer (choose_move 오버라이드) |
| `pokechamp/langchain_backend.py` | 367 | LangChainBackend + OllamaChatModel |
| `pokechamp/battle_tools.py` | 796 | 9개 @tool 함수 + BattleContext |
| `pokechamp/agents/state.py` | 69 | BattleAgentState TypedDict |
| `pokechamp/agents/common.py` | — | build_battle_state, action_to_battle_order |
| `pokechamp/agents/react_agent.py` | — | ReAct 에이전트 그래프 |
| `pokechamp/agents/io_agent.py` | — | IO 에이전트 그래프 |
| `pokechamp/agents/cot_agent.py` | — | CoT 에이전트 그래프 |
| `pokechamp/agents/llm_logging.py` | — | LLMLoggingCallback |
| `pokechamp/agents/__init__.py` | 18 | 패키지 익스포트 |
