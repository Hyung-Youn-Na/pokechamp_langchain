# LangGraph ReAct 에이전트 아키텍처 문서

> 명령어: `uv run python scripts/battles/local_1v1_langchain.py --player_prompt_algo react --player_backend ollama/glm-5.1:cloud --opponent_name abyssal --N 1 --seed 42`

## 1. 전체 실행 흐름 개요

```
┌─────────────────────────────────────────────────────────────────────┐
│                    local_1v1_langchain.py (Entry Point)             │
│                                                                     │
│  1. 인자 파싱 (--player_prompt_algo=react, --player_backend=...)   │
│  2. LangChainBackend("ollama:glm-5.1:cloud") 생성                  │
│  3. LangChainPlayer(backend, prompt_algo="react") 생성             │
│  4. opponent = get_llm_player(...)  ← 기존 LLMPlayer              │
│  5. 팀 로드 (metamon / random)                                      │
│  6. await player.battle_against(opponent, n_battles=1)             │
│  7. 승률, 토큰 사용량, 소요 시간 집계                              │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
                           ▼ 매 턴마다 choose_move() 콜백
┌─────────────────────────────────────────────────────────────────────┐
│                  LangChainPlayer.choose_move(battle)                │
│                                                                     │
│  1. prompt_algo == "react" → _run_langgraph_agent() 라우팅         │
│  2. LocalSim 인스턴스 생성 (배틀 시뮬레이터)                        │
│  3. Early exit 체크 (기절 상태, 선택지 1개뿐인 경우)               │
│  4. BattleContext(sim, battle, pokemon...) 생성                     │
│  5. BattleAgentState 구성 (build_battle_state)                     │
│  6. graph.invoke(state) → LangGraph ReAct 그래프 실행              │
│  7. 결과 파싱 → BattleOrder 반환                                    │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│              LangGraph ReAct 에이전트 그래프                        │
│                                                                     │
│  build_context → tool_agent ⇄ tool_execution                       │
│      → strategy_synthesis → parse_action → END  (5노드, EXP-049b~) │
│                                                                     │
│  - 최대 5회 툴 호출 반복                                           │
│  - 9개의 배틀 분석 툴 사용 가능                                    │
│  - 최종 JSON 액션 반환                                              │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 2. 컴포넌트별 상세 설명

### 2.1 진입점: `local_1v1_langchain.py`

| 단계 | 동작 |
|------|------|
| 인자 파싱 | `--player_prompt_algo react` → `LANGCHAIN_PROMPT_ALGOS` 매칭 |
| 백엔드 매핑 | `ollama/glm-5.1:cloud` → `ollama:glm-5.1:cloud` (provider:model 형식) |
| 플레이어 생성 | `_get_langchain_player()` → `LangChainBackend` → `LangChainPlayer` |
| 배틀 실행 | `await player.battle_against(opponent, n_battles=N)` |

**백엔드 문자열 → LangChain provider 매핑 로직:**
```
"ollama/glm-5.1:cloud" → "ollama:glm-5.1:cloud"  → OllamaChatModel (Cloud)
"gpt-4o"               → "openai:gpt-4o"          → init_chat_model("openai:gpt-4o")
"gemini-2.5-flash"     → "google_genai:gemini-..." → init_chat_model("google_genai:...")
```

### 2.2 LLM 백엔드: `LangChainBackend` + `OllamaChatModel`

```
LangChainBackend
├── model_spec: "ollama:glm-5.1:cloud"
├── chat_model: OllamaChatModel
│   ├── OLLAMA_API_KEY 환경변수 확인
│   ├── 있으면 → https://ollama.com (Cloud, Bearer 인증)
│   └── 없으면 → http://localhost:11434 (Local)
├── get_LLM_action() → (output_str, json_flag, raw_message) 튜플 반환
└── 토큰 사용량 추적 (prompt_tokens, completion_tokens)
```

`OllamaChatModel`은 LangChain의 `BaseChatModel`을 상속하며:
- `.bind_tools()` → 툴 호출 지원
- `_generate()` → `ollama.Client.chat()` 호출
- 툴 호출 결과 → `AIMessage.tool_calls` 리스트로 파싱

### 2.3 플레이어: `LangChainPlayer`

`LLMPlayer`를 상속하며 `choose_move()`를 오버라이드합니다:

```python
class LangChainPlayer(LLMPlayer):
    def choose_move(self, battle):
        if algo in ("react", "io_langchain", "cot_langchain"):
            return self._run_langgraph_agent(battle, algo)  # ← 새 경로
        return super().choose_move(battle)                   # ← 기존 경로
```

**`_run_langgraph_agent()` 핵심 로직:**

1. **LocalSim 생성** — 배틀 시뮬레이터 (기존 코드와 동일)
2. **Early exit** — 기절한 포켓몬 + 교체 1개뿐, 또는 사용 가능 기술 1개뿐인 경우
3. **Strategy prompt** — 턴 1에 `sim.get_llm_system_prompt()` 호출
4. **Constraint prompt** — 출력 형식 JSON 스키마 생성
5. **BattleContext 주입** — `set_battle_context()`로 전역 컨텍스트 설정
6. **BattleAgentState 구성** — `build_battle_state()`로 그래프 입력 생성
7. **그래프 실행** — `graph.invoke(state)` 
8. **결과 처리** — `action_to_battle_order()` → `BattleOrder` 반환
9. **Fallback** — 파싱 실패 시 `choose_max_damage_move()` 사용

### 2.4 상태 스키마: `BattleAgentState`

LangGraph 그래프의 모든 노드가 공유하는 상태입니다:

```python
class BattleAgentState(TypedDict):
    # 메시지 채널 (대화 기록)
    messages: List[AnyMessage]

    # 배틀 컨텍스트 (턴당 1회 설정)
    battle_tag: str
    turn: int
    battle_format: str

    # 사용 가능한 액션
    available_moves: List[Dict]       # [{id, type, base_power, accuracy, category, priority}]
    available_switches: List[Dict]    # [{species, types, hp_fraction, level}]
    can_dynamax: bool
    can_tera: bool

    # 배틀 상태 요약
    active_pokemon: Optional[Dict]
    opponent_pokemon: Optional[Dict]
    team_summary: str
    opponent_summary: str
    weather: Optional[str]
    terrain: Optional[str]

    # 프롬프트 (state_translate()에서 생성)
    system_prompt: str
    state_prompt: str
    state_action_prompt: str
    constraint_prompt: str

    # 추론 상태
    reasoning: str
    evaluation_scores: Dict[str, float]

    # 배틀 메모리 (EXP-049a, design D — 턴 간 누적)
    opp_role_balance: Dict[str, int]      # 상대 팀 역할 분포
    opp_team_roles: Dict[str, List[Dict]]
    opp_revealed: Dict[str, Dict]          # 드러난 moves/item/tera
    opp_win_condition: str                 # LLM 추론 (다음 턴에 읽음)
    my_plan: str                           # LLM 추론 장기 승리 경로
    plan_turn: int
    tool_call_count: Annotated[int, _add_int]      # ← 노드 간 합산 (success만)

    # LLM 사용량 (reducer로 자동 누적)
    total_prompt_tokens: Annotated[int, _add_int]      # ← 노드 간 합산
    total_completion_tokens: Annotated[int, _add_int]   # ← 노드 간 합산
    llm_call_count: Annotated[int, _add_int]            # ← 노드 간 합산

    # 최종 출력
    chosen_action: Optional[Dict]
    chosen_dynamax: bool
    chosen_tera: bool
```

**핵심 설계:** `Annotated[int, _add_int]` 리듀서를 사용하여 각 노드에서 반환하는 토큰 값이 자동으로 합산됩니다.

---

## 3. LangGraph ReAct 에이전트 그래프

### 3.1 그래프 구조

```
                    ┌─────────────────┐
                    │  build_context  │ ← Entry Point
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
              ┌────▶│   tool_agent    │◀────────────────┐
              │     └────────┬────────┘                  │
              │              │                            │
              │   ┌──────────┴──────────┐                 │
              │   │ should_continue()?   │                 │
              │   └──┬──────────────┬───┘                 │
              │      │              │                      │
              │ "strategy_     "tools"                     │
              │ synthesis"        │                        │
              │      │              │                      │
              │      ▼              ▼                      │
              │  ┌──────────────┐ ┌──────────────────┐    │
              │  │ strategy_    │ │ tool_execution   │────┘
              │  │ synthesis    │ │ (툴 결과 반환)    │ (최대 5회 반복)
              │  │ (clean       │ └──────────────────┘
              │  │  rebuild)    │
              │  └──────┬───────┘
              │         │
              │         ▼
              │  ┌─────────────┐
              └─▶│ parse_action│
                 └──────┬──────┘
                        │
                        ▼
                     ┌──────┐
                     │ END  │
                     └──────┘

> **EXP-049b 구조 변경:** `agent_loop`(툴 호출 + 강제종료 통합)가 분리되어 —
> `tool_agent`(툴 호출 전담, 강제종료 안 함) ⇄ `tool_execution` 루프 후,
> `strategy_synthesis`(clean rebuild로 전략 결정 + my_plan 장기화) → `parse_action`.
> `should_continue`는 `"tools"` / `"strategy_synthesis"`로 라우팅(`"parse"` 아님).
```

### 3.2 그래프 노드 상세

#### `build_context` — 초기 컨텍스트 구성

```python
def build_context(state: BattleAgentState) -> dict:
    system_content = REACT_SYSTEM_PROMPT.format(max_tools=5)
    user_content = state["state_prompt"] + state["state_action_prompt"] + state["constraint_prompt"]
    messages = [SystemMessage(content=system_content), HumanMessage(content=user_content)]
    return {"messages": messages}
```

- 시스템 프롬프트: ReAct 전용 지시사항 (툴 목록, 의사결정 프로세스, 출력 형식)
- 유저 프롬프트: `state_translate()`가 생성한 배틀 상태 텍스트 + 제약 프롬프트
- IO/CoT 에이전트와 **동일한 배틀 상태 텍스트**를 사용하여 실험 비교 가능성 보장

#### `tool_agent` — 툴 호출 전담 (EXP-049b 분리)

> **구조 변경 (EXP-049b):** 과거의 `agent_loop`(툴 호출 + 강제종료 통합)가 둘로 분리되었습니다 —
> `tool_agent`(**툴 호출만**, 강제종료·최종 결정 안 함) ⇄ `tool_execution` 루프 후,
> `strategy_synthesis`(**clean rebuild**로 전략 결정 + `my_plan` 장기화) → `parse_action`.
> 아래는 개요용 의사코드; 실제 구현은 `react_agent.py`(`_make_tool_agent`, `_make_strategy_synthesis`) 참조.
> 툴 호출 횟수는 `sum(ToolMessage)`가 아닌 **state의 `tool_call_count`(Annotated) 카운터**로 추적합니다.

#### `strategy_synthesis` — 전략 종합 + clean rebuild (EXP-049b, design B)

> 툴 루프 종료(예산 도달·툴 호출 없음) 후 누적 메시지 히스토리에서 **툴 결과 + 마지막 추론만 추려
> clean rebuild**(`STRATEGY_SYSTEM_PROMPT` + `response_format=json_object`). per-turn 프롬프트 블로트를
> 방지하고, `my_plan`을 단기 행동이 아닌 **장기 승리 경로**로 강제(EXP-049a 95.4% 단기 재진술 교정).
> JSON 파싱 실패 시 1회 retry(`react_agent.py` `_make_strategy_synthesis`).

#### `tool_agent` — 툴 호출 (개요 의사코드)

```python
def agent_loop(state, *, llm, tools) -> dict:
    # 기존 툴 호출 횟수 카운트
    tool_call_count = sum(1 for m in state["messages"] if isinstance(m, ToolMessage))
    
    # 최대 5회 초과 시 강제로 최종 답변 요청
    if tool_call_count >= MAX_TOOL_CALLS:
        messages.append(HumanMessage(content="최대 툴 호출 도달. 최종 JSON 결정을 제공하세요."))
    
    # 툴 바인딩 후 LLM 호출
    llm_with_tools = llm.bind_tools(tools)
    response = llm_with_tools.invoke(messages)
    
    return {"messages": [response], ...usage_metadata}
```

- `llm.bind_tools(tools)`로 툴 스키마를 LLM에 전달
- LLM은 툴을 호출할지, 최종 답변을 생성할지 스스로 결정
- 토큰 사용량 자동 추적 (`extract_llm_usage`)

#### `should_continue` — 라우팅 로직 (EXP-049b: `"tools"` / `"strategy_synthesis"`)

> **변경:** 라우팅은 `"tools"` / `"strategy_synthesis"`입니다 (`"parse"` 아님). 예산
> (`tool_call_count >= max`) 도달 시 즉시 `strategy_synthesis`로 clean rebuild 결정.
> 카운터는 state의 Annotated 필드 기반. 실제 구현은 `react_agent.py` `_make_should_continue`.

#### `should_continue` — 라우팅 (개요 의사코드)

```python
def should_continue(state) -> str:
    last = state["messages"][-1]
    if isinstance(last, AIMessage) and last.tool_calls:
        return "tools"    # → tool_execution 노드로
    return "parse"         # → parse_action 노드로
```

- AI 메시지에 `tool_calls`가 있으면 → 툴 실행
- 없으면 (최종 텍스트 답변) → 액션 파싱

#### `tool_execution` — 툴 호출 실행

```python
def tool_execution(state, *, tools_by_name) -> dict:
    last_message = state["messages"][-1]
    tool_messages = []
    for tool_call in last_message.tool_calls:
        tool_fn = tools_by_name[tool_call["name"]]
        result = tool_fn.invoke(tool_call["args"])
        tool_messages.append(ToolMessage(content=result, tool_call_id=tool_call["id"]))
    return {"messages": tool_messages}
```

- AI의 `tool_calls`를 순회하며 각 툴 실행
- 결과를 `ToolMessage`로 반환하여 대화 기록에 추가
- 다시 `agent_loop`로 루프백

#### `parse_action` — 최종 액션 파싱

```python
def parse_action(state) -> dict:
    for msg in reversed(state["messages"]):
        if isinstance(msg, AIMessage) and not msg.tool_calls:
            action = parse_action_json(msg.content, None)
            if action is not None:
                return {"chosen_action": action}
    return {"chosen_action": None}
```

- 대화 기록을 역순으로 순회
- 툴 호출이 없는 AI 메시지에서 JSON 액션 추출
- `{"move": "thunderbolt"}`, `{"switch": "charizard"}` 등 파싱

### 3.3 반복 사이클 예시

```
[Turn 1] tool_agent → LLM: "calculate_damage(thunderbolt)" 호출
         ↓ should_continue → "tools"
[Turn 2] tool_execution → {"damage": "35%", "turns_to_ko": 3}
         ↓
[Turn 3] tool_agent → LLM: "check_type_effectiveness(fire)" 호출
         ↓ should_continue → "tools"  
[Turn 4] tool_execution → {"multiplier": 2.0, "description": "super effective"}
         ↓
[Turn 5] tool_agent → 툴 호출 없는 최종 추론
         ↓ should_continue → "strategy_synthesis"
[Turn 6] strategy_synthesis → clean rebuild → '{"move": "flamethrower", "my_plan": "..."}'
         ↓
[Turn 7] parse_action → {"chosen_action": {"move": "flamethrower"}}
         ↓
         END
```

---

## 4. 배틀 분석 툴 (9종)

`battle_tools.py`에 정의된 `@tool` 데코레이터 기반 LangChain 툴:

| 툴 | 기능 | 내부 호출 |
|-----|------|-----------|
| `calculate_damage` | 특정 기술의 데미지/턴킬 계산 | `LocalSim.calculate_remaining_hp()`, `get_number_turns_faint()` |
| `check_type_effectiveness` | 타입 상성 배수 확인 | `calculate_move_type_damage_multipier()` |
| `analyze_matchup` | 포켓몬 간 매치업 분석 (스피드, 타입, 최적 기술) | `get_number_turns_faint()` + 타입 배수 |
| `get_team_analysis` | 팀 전체 타입 커버리지/약점 분석 | 타입 차트 전수 검사 |
| `predict_opponent_moves` | 상대 기술 예측 (확정 + 예측) | `LocalSim.get_opponent_current_moves()` |
| `simulate_turn` | 특정 기술 조합으로 턴 시뮬레이션 | `LocalSim.calculate_remaining_hp()` |
| `get_move_details` | 기술 상세 정보 (동적 타입/위력/우선도) | `resolve_dynamic_type/power/priority()` |
| `evaluate_position` | 현재 포지션 점수 평가 (0-100) | `fast_battle_evaluation()` |
| `get_strategy_insight` | Smogon 커뮤니티 전략(역할/견제/약점/승리 경로) | `get_cached_smogon_strategies()` (EXP-049c) |

**모든 툴은 `BattleContext` 데이터클래스에서 현재 배틀 상태를 읽어옵니다:**

```python
@dataclass
class BattleContext:
    sim: LocalSim               # 배틀 시뮬레이터
    battle: AbstractBattle      # 배틀 객체
    active_pokemon: Pokemon     # 내 포켓몬
    opponent_pokemon: Pokemon   # 상대 포켓몬
    weather: Optional[str]      # 날씨
    terrain: Optional[str]      # 필드 효과
```

**컨텍스트 주입 방식:** `LangChainPlayer._run_langgraph_agent()`에서 `set_battle_context(ctx)`를 호출하여 모듈 레벨 전역 변수에 저장합니다. 각 툴 함수는 `get_battle_context()`로 접근합니다.

---

## 5. 전체 시퀀스 다이어그램

```
Showdown Server    local_1v1_langchain.py    LangChainPlayer    LangGraph ReAct    OllamaChatModel    BattleTools
      │                    │                       │                   │                   │                │
      │   battle_start     │                       │                   │                   │                │
      │───────────────────▶│                       │                   │                   │                │
      │                    │  battle_against()     │                   │                   │                │
      │                    │──────────────────────▶│                   │                   │                │
      │                    │                       │                   │                   │                │
      │   choose_move()    │                       │                   │                   │                │
      │───────────────────────────────────────────▶│                   │                   │                │
      │                    │                       │  build_battle_state()                 │                │
      │                    │                       │──────────────┐    │                   │                │
      │                    │                       │              │    │                   │                │
      │                    │                       │◀─────────────┘    │                   │                │
      │                    │                       │  set_battle_context()                  │                │
      │                    │                       │──────────────┐    │                   │                │
      │                    │                       │                   │                   │                │
      │                    │                       │  graph.invoke()   │                   │                │
      │                    │                       │──────────────────▶│                   │                │
      │                    │                       │                   │                   │                │
      │                    │                       │  [build_context]  │                   │                │
      │                    │                       │  시스템+유저 프롬프트 구성             │                │
      │                    │                       │                   │                   │                │
      │                    │                       │  [agent_loop]     │                   │                │
      │                    │                       │                   │  bind_tools + invoke()              │
      │                    │                       │                   │──────────────────▶│                │
      │                    │                       │                   │  AIMessage        │                │
      │                    │                       │                   │  (tool_calls)     │                │
      │                    │                       │                   │◀──────────────────│                │
      │                    │                       │                   │                   │                │
      │                    │                       │  [tool_execution] │                   │                │
      │                    │                       │                   │  tool_fn.invoke() │                │
      │                    │                       │                   │──────────────────────────────────▶│
      │                    │                       │                   │  ToolMessage      │                │
      │                    │                       │                   │◀──────────────────────────────────│
      │                    │                       │                   │                   │                │
      │                    │                       │                   │  ... (최대 5회 반복)                │
      │                    │                       │                   │                   │                │
      │                    │                       │  [parse_action]   │                   │                │
      │                    │                       │  chosen_action    │                   │                │
      │                    │                       │◀──────────────────│                   │                │
      │                    │                       │                   │                   │                │
      │                    │                       │  action_to_battle_order()             │                │
      │                    │                       │──────────────┐    │                   │                │
      │                    │                       │              │    │                   │                │
      │                    │                       │◀─────────────┘    │                   │                │
      │                    │                       │                   │                   │                │
      │  BattleOrder       │                       │                   │                   │                │
      │◀───────────────────────────────────────────│                   │                   │                │
      │                    │                       │                   │                   │                │
```

---

## 6. `ollama/glm-5.1:cloud` 모델 특화 동작

명령어에서 `--player_backend ollama/glm-5.1:cloud`를 지정한 경우:

1. **백엔드 문자열 변환:** `ollama/glm-5.1:cloud` → `ollama:glm-5.1:cloud`
2. **`LangChainBackend.__init__()`에서 `OllamaChatModel` 선택:** `_is_ollama_spec()`이 `True` 반환
3. **Cloud 모드 활성화:** `OLLAMA_API_KEY` 환경변수가 설정되어 있으면 `https://ollama.com`으로 Bearer 인증
4. **툴 호출 지원:** `OllamaChatModel.bind_tools()` → ollama 네이티브 툴 호출 포맷 변환
5. **`_generate()`에서 툴 결과 파싱:** `response.message.tool_calls` → LangChain `AIMessage.tool_calls` 변환

```
OllamaChatModel._generate()
├── _ollama_client_for_model("glm-5.1:cloud")
│   └── ollama.Client(host="https://ollama.com", headers={"Authorization": "Bearer ..."})
├── _lc_messages_to_ollama(messages)
│   └── [SystemMessage, HumanMessage, ...] → [{"role": "system", "content": ...}, ...]
├── _lc_tools_to_ollama(tools)
│   └── [BaseTool, ...] → [{"type": "function", "function": {"name": ..., "parameters": ...}}]
├── client.chat(model="glm-5.1:cloud", messages=..., tools=..., think=False, stream=False)
└── 응답 파싱 → AIMessage(content=..., tool_calls=[...])
```

---

## 7. 프롬프트 아키텍처 분석

### 7.1 프롬프트 생성 파이프라인

모든 LangGraph 에이전트는 **동일한 3단계 프롬프트 파이프라인**을 공유합니다:

```
                    state_translate(battle)
                    ┌─────────────────────────────┐
                    │ 1. system_prompt             │ ← sim.get_llm_system_prompt()
                    │ 2. state_prompt              │ ← 배틀 상태 텍스트 (HP, 타입, 날씨 등)
                    │ 3. state_action_prompt       │ ← 사용 가능한 기술/교체 목록
                    └──────────┬──────────────────┘
                               │
                               ▼
                    constraint_prompt (LangChainPlayer에서 생성)
                    ┌─────────────────────────────┐
                    │ 출력 형식 JSON 스키마        │
                    │ {"move":"..."} / {"switch":"..."}
                    │ + Dynamax/Tera 옵션          │
                    └──────────┬──────────────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
              ▼                ▼                ▼
         ReAct 에이전트    IO 에이전트     CoT 에이전트
    (별도 시스템 프롬프트)  (system_prompt  (system_prompt
                           그대로 사용)     그대로 사용)
```

**핵심:** `state_translate()`는 `LocalSim`의 기존 메서드로, `LLMPlayer`의 `io`/`cot`/`minimax` 알고리즘과 **동일한 배틀 상태 텍스트**를 생성합니다. 이를 통해 LangGraph 에이전트와 기존 에이전트 간의 **실험 비교 가능성**이 보장됩니다.

### 7.2 ReAct 에이전트 프롬프트 (`react_agent.py`)

#### 시스템 프롬프트: `REACT_SYSTEM_PROMPT`

ReAct 에이전트는 다른 에이전트와 달리 **전용 시스템 프롬프트**를 사용합니다. `build_context` 노드에서 `state["system_prompt"]`를 무시하고 `REACT_SYSTEM_PROMPT`로 대체합니다:

```python
def build_context(state: BattleAgentState) -> dict:
    system_content = REACT_SYSTEM_PROMPT.format(max_tools=MAX_TOOL_CALLS)
    user_content = state["state_prompt"] + state["state_action_prompt"] + state["constraint_prompt"]
    messages = [SystemMessage(content=system_content), HumanMessage(content=user_content)]
    return {"messages": messages}
```

**`REACT_SYSTEM_PROMPT` 구조 분석:**

| 섹션 | 내용 | 목적 |
|------|------|------|
| **역할 정의** | "You are a competitive Pokémon battle AI" | 에이전트 정체성 설정 |
| **Available Tools** | 9개 툴의 이름, 시그니처, 용도 설명 | LLM이 툴을 올바르게 호출하도록 안내 |
| **Decision Process** | 5단계 의사결정 플로우 (상태 읽기 → 데미지 계산 → 타입 확인 → 비교 → JSON 출력) | 체계적인 분석 유도 |
| **CRITICAL Rules** | 최대 5회 툴 호출, 보유 기술만 데미지 계산, 상태기술 제외, 에러 시 재시도 금지 | 환각/비효율적 툴 사용 방지 |
| **Output Format** | JSON 전용 출력, 마크다운 금지, 올바른/잘못된 예시 | 파싱 신뢰성 보장 |

**강제 종료 → clean rebuild (EXP-049b 변경):** 과거엔 예산 도달 시 강제종료 프롬프트로 LLM을
호출했으나, 현재는 `should_continue`가 예산 도달 시 **`strategy_synthesis` 노드로 라우팅**하여
clean rebuild로 최종 결정을 내립니다(§3.2 `strategy_synthesis` 참조). 툴 미바인딩 강제 호출은
더 이상 사용하지 않습니다.

#### 유저 프롬프트 구성

```
state_prompt           ← 배틀 상태 (HP, 타입, 능력치, 날씨, 필드 효과 등)
+ state_action_prompt  ← 사용 가능한 기술/교체 목록
+ constraint_prompt    ← 출력 JSON 형식 + Dynamax/Tera 옵션
```

`constraint_prompt`는 `LangChainPlayer._run_langgraph_agent()`에서 동적으로 생성됩니다:

```python
# 기절 상태
constraint = '{"switch":"<switch_pokemon_name>"}'
# 교체 불가
constraint = '{"move":"<move_name>"}{gimmick_output_format}'
# 일반
constraint = '{"move":"<move_name>"}{gimmick_output_format} or {"switch":"<switch_pokemon_name>"}'
```

### 7.3 IO 에이전트 프롬프트 (`io_agent.py`)

IO 에이전트는 **가장 단순한 프롬프트 구조**를 가집니다:

```python
def build_prompt(state: BattleAgentState) -> dict:
    system = state["system_prompt"]  # ← state_translate() 원본 시스템 프롬프트 그대로 사용

    cot_prompt = "In fewer than 3 sentences, let's think step by step:"
    user = (
        state["state_prompt"]
        + state["state_action_prompt"]
        + state["constraint_prompt"]
        + cot_prompt  # ← 간단한 CoT 트리거 추가
    )
    return {"messages": [SystemMessage(content=system), HumanMessage(content=user)]}
```

**특징:**
- `state_translate()`의 원본 `system_prompt`를 그대로 사용 (ReAct와 달리 대체하지 않음)
- 유저 프롬프트 끝에 `"In fewer than 3 sentences, let's think step by step:"` 추가
- LLM 1회 호출 → 바로 액션 파싱 (툴 없음)
- 기존 `LLMPlayer.io()`와 동일한 프롬프트 구조 재현

**그래프 흐름:** `build_prompt → call_llm → parse_action → END`

### 7.4 CoT 에이전트 프롬프트 (`cot_agent.py`)

CoT 에이전트는 **추론과 결정을 분리**하는 2단계 프롬프트를 사용합니다:

```python
# 1단계: build_prompt — 기본 프롬프트 구성
def build_prompt(state):
    system = state["system_prompt"]  # ← 원본 시스템 프롬프트
    user = state["state_prompt"] + state["state_action_prompt"] + state["constraint_prompt"]
    return {"messages": [SystemMessage(content=system), HumanMessage(content=user)]}

# 2단계: think — CoT 지시사항 추가 후 LLM 호출
cot_instruction = (
    "In fewer than 4 sentences, let's think step by step about "
    "the best action for this turn. Consider type matchups, HP "
    "advantage, and strategic implications. After reasoning, "
    "provide your final decision as a JSON object."
)
messages.append(HumanMessage(content=cot_instruction))
response = llm.invoke(messages)
```

**IO vs CoT 프롬프트 비교:**

| 측면 | IO 에이전트 | CoT 에이전트 |
|------|------------|-------------|
| CoT 트리거 위치 | 유저 프롬프트 끝에 인라인 | 별도 `HumanMessage`로 추가 |
| CoT 길이 | "fewer than 3 sentences" | "fewer than 4 sentences" |
| 분석 지시 | 없음 | 타입 상성, HP 이점, 전략적 고려 명시 |
| JSON 요구 | 제약 프롬프트에만 명시 | CoT 지시사항에도 명시 |
| 시스템 프롬프트 | 원본 그대로 | 원본 그대로 |

**그래프 흐름:** `build_prompt → think → decide → END`

### 7.5 공통 액션 파싱 체인

모든 에이전트는 동일한 2단계 파싱 폴백을 사용합니다:

```
parse_action_json()  →  JSON 파싱 시도
    ↓ 실패
extract_action_from_prose()  →  텍스트에서 move/switch 이름 검색
    ↓ 실패
chosen_action = None  →  LangChainPlayer에서 choose_max_damage_move() 폴백
```

`parse_action_json()`은 다양한 LLM 출력 형식을 처리합니다:
- 마크다운 코드 펜스 제거
- 키 정규화: `move_name`/`chosen_move` → `move`, `chosen_switch`/`switch_target` → `switch`
- 텍스트 내 JSON 객체 추출 (프롤로그가 있는 경우)

### 7.6 LLM Lead Selection 프롬프트 (`llm_player.py`)

팀 프리뷰 단계에서 LLM이 최적의 선봉 포켓몬을 선택하는 기능이 추가되었습니다 (`enable_llm_lead_selection` 플래그로 활성화).

#### 시스템 프롬프트: `_LEAD_SELECTION_SYSTEM_PROMPT`

```
구조:
├── 역할 정의: "expert competitive Pokemon gen9ou team analyst"
├── Lead 선택 기준 (6가지):
│   1. 타입 상성 이점
│   2. 스피드 티어 — 선공이 중요
│   3. 엔트리 해저드 설정 vs 안티리드
│   4. 리드 모멘텀 — 유리한 교체나 빠른 KO
│   5. 팀 순서 — 교체 필요 시점에 따른 예비 포켓몬 정렬
│   6. 시너지 — 리드가 팀 전체의 성공을 위한 기반
├── 정보 제한: 상대의 종족/타입/기본 스탯/가능 특성만, 기술/아이템/실제 특성은 불명
└── 출력 형식: 6자리 순열 (예: "421365" → 4번 포켓몬이 선봉)
```

#### 유저 프롬프트 구성 (`_create_lead_selection_prompt`):

```
아군 팀 (각 포켓몬):
  인덱스. 종족명 (타입)
  특성: ..., 아이템: ...
  기술: ..., ...
  스탯: HP:... Atk:... Def:... SpA:... SpD:... Spe:...

상대 팀 (종족/타입만):
  - 종족명 (타입)
    가능 특성: ...
    스탯: HP:... Atk:... Def:... SpA:... SpD:... Spe:...

지시: 6자리 순열로 응답
```

**파싱 로직** (`_parse_teampreview_response`):
1. 정규식으로 N자리 연속 순열 탐색
2. 실패 시 개별 숫자를 수집하여 유효한 순열 재구성
3. 모두 실패 시 `random_teampreview()` 폴백

---

## 8. LLM 로깅 아키텍처

### 8.1 기존 경로: `_log_llm_call()` (구조화 JSON 로깅)

`LLMPlayer.get_LLM_action()`에 추가된 구조화 로깅. `log_dir`이 설정된 경우 매 LLM 호출을 JSONL로 기록:

```python
log_entry = {
    "turn": battle.turn,
    "battle_tag": battle.battle_tag,
    "system_prompt": system_prompt,
    "user_prompt": user_prompt,
    "llm_response": raw_message,
    "parsed_action": output,
    "llm_call_count": self.llm_call_count,
    "timestamp": datetime.datetime.now().isoformat(),
}
# → {log_dir}/llm_log.jsonl
```

### 8.2 LangGraph 경로: `LLMLoggingCallback` (`agents/llm_logging.py`)

LangGraph 그래프 내부의 LLM 호출을 가로채는 LangChain `BaseCallbackHandler`:

```
LLMLoggingCallback
├── on_llm_start()  → 프롬프트/메시지 기록 (대기 큐에 저장)
├── on_llm_end()    → 최종 로그 작성 ({log_dir}/langgraph_llm_log.jsonl)
├── on_llm_error()  → 에러 로그 작성
├── on_tool_start() → 툴 호출 로그 ({log_dir}/langgraph_tool_log.jsonl)
└── on_tool_end()   → 툴 결과 로그
```

**로그 엔트리 구조:**
```json
{
  "timestamp": "...",
  "start_time": "...",
  "battle_tag": "...",
  "turn": 5,
  "llm_call_in_turn": 2,
  "system_prompt": "...",
  "user_prompt": "...",
  "llm_response": "...",
  "tool_calls": [{"name": "calculate_damage", "args": {...}, "id": "..."}],
  "token_usage": {"prompt_tokens": 500, "completion_tokens": 200, "total_tokens": 700},
  "messages_full": [{"role": "system", "content": "..."}, ...]
}
```

**활성화:** `LangChainPlayer._run_langgraph_agent()`에서 `self.log_dir`이 설정된 경우 자동으로 `LLMLoggingCallback`이 `config["callbacks"]`에 추가됩니다.

---

## 9. 파일 구조 요약

```
scripts/battles/
├── local_1v1.py                    ← 기존 진입점 (+ --enable_llm_lead_selection 인자 추가)
├── local_1v1_langchain.py          ← LangGraph 진입점 (인자 파싱, 플레이어 생성, 배틀 실행)
├── run_io_baselines.sh             ← IO 베이스라인 배치 스크립트
└── run_model_timing.sh             ← 모델 타이밍 측정 스크립트

pokechamp/
├── llm_player.py                   ← LLMPlayer (+ teampreview, _log_llm_call, lead selection 추가)
├── langchain_backend.py            ← 통합 LLM 백엔드 (OllamaChatModel 포함)
├── langchain_player.py             ← LangChainPlayer (choose_move 오버라이드)
├── battle_tools.py                 ← 9개 배틀 분석 툴 + BattleContext (EXP-049c get_strategy_insight)
└── agents/
    ├── __init__.py                 ← 패키지 초기화 (create_*_agent 익스포트)
    ├── state.py                    ← BattleAgentState TypedDict 정의
    ├── common.py                   ← 상태 구성, 액션 파싱, 토큰 추적 공통 유틸
    ├── react_agent.py              ← ReAct 그래프 정의 (+ REACT_SYSTEM_PROMPT)
    ├── io_agent.py                 ← IO 기본 에이전트
    ├── cot_agent.py                ← Chain-of-Thought 에이전트
    └── llm_logging.py              ← LLMLoggingCallback (LangGraph LLM/툴 로깅)
```

---

## 10. 기존 아키텍처와의 비교

| 측면 | 기존 `LLMPlayer` (io/cot/minimax) | `LangChainPlayer` (react) |
|------|-----------------------------------|--------------------------|
| 프롬프트 구성 | `prompts.py` → 단일 텍스트 | `state_translate()` + ReAct 전용 시스템 프롬프트 |
| 시스템 프롬프트 | `get_llm_system_prompt()` 원본 | `REACT_SYSTEM_PROMPT`로 대체 (툴/규칙 포함) |
| LLM 호출 | 1회 (또는 minimax 리프마다) | 1~6회 (에이전트 루프) |
| 배틀 데이터 | 프롬프트 텍스트에 직접 포함 | 툴 호출로 온디맨드 조회 |
| 팀 프리뷰 | `random_teampreview()` | LLM 기반 `teampreview()` (선택적) |
| 액션 파싱 | `io()` 내부에서 정규식/JSON | `parse_action_json()` + prose 폴백 |
| 로깅 | `_log_llm_call()` (JSONL) | `LLMLoggingCallback` (JSONL + 툴 로그) |
| 상태 관리 | `AbstractBattle` 객체 직접 접근 | `BattleAgentState` TypedDict |
| 백엔드 | `GPTPlayer`, `GeminiPlayer` 등 개별 클래스 | `LangChainBackend` 통합 (OllamaChatModel 포함) |
| 코드 경로 | `llm_player.py` 전체 | `langchain_player.py` + `agents/` 모듈 |

---

## 11. 의존성 (`pyproject.toml`)

LangGraph 에이전트는 `langchain` optional extra로 설치합니다:

```sh
uv sync --extra langchain    # LangChain + LangGraph 의존성 설치
uv sync                      # 기본 설치 (LangGraph 미포함)
```

**`[project.optional-dependencies].langchain`:**
```toml
langchain = [
    "langchain-core>=0.3.0",
    "langchain>=0.3.0",
    "langchain-openai>=0.3.0",
    "langchain-google-genai>=2.0.0",
    "langgraph>=0.4.0",
]
```

---

## 12. 핵심 설계 원칙

1. **비침투성:** 기존 파일(`llm_player.py`, `prompts.py` 등)은 수정 없이 그대로 동작. 단, `llm_player.py`에는 `_log_llm_call()`, `teampreview()` 등 **부가 기능이 추가**됨 (기존 동작에는 영향 없음)
2. **동일한 배틀 상태:** `state_translate()` 출력을 공유하여 모든 에이전트가 동일한 정보로 판단. ReAct만 시스템 프롬프트를 대체
3. **안전장치:** Early exit, MAX_TOOL_CALLS=5, 파싱 실패 시 max_damage 폴백, lead selection 실패 시 random_teampreview 폴백
4. **토큰 추적:** `_add_int` 리듀서로 그래프 전체의 토큰 사용량 자동 누적
5. **확장성:** 새로운 에이전트는 `agents/`에 파일 추가 + `LangChainPlayer._get_graph()`에 라우팅만 추가
6. **관측 가능성:** `_log_llm_call()` + `LLMLoggingCallback`으로 전체 LLM I/O와 툴 호출을 JSONL로 기록
