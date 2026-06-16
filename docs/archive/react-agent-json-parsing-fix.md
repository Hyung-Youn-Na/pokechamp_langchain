# ReAct 에이전트 JSON 파싱 오류 분석 및 해결 방안

> 실험: EXP-021 ~ EXP-024 (`react` 프롬프트 알고리즘, GLM-5.1 모델)
> 작성일: 2026-06-09

---

## 1. 문제 요약

LangGraph ReAct 에이전트가 GLM-5.1 모델을 사용할 때, 각 턴의 마지막 LLM 응답에서 valid JSON을 출력하지 않는 비율이 **47~66%** 에 달함.

JSON 파싱이 실패하면 항상 `choose_max_damage_move()` 로 폴백되며, ReAct 에이전트가 tool로 수집한 분석 데이터가 완전히 무시됨.

### 실험별 파싱 실패율

| 실험 | 총 턴 | 정상 JSON | JSON 없음 | 잘못된 형식 | **실패율** |
|------|-------|----------|----------|------------|----------|
| EXP-021 | 24 | 9 | 9 | 6 | **62%** |
| EXP-022 | 32 | 11 | 16 | 5 | **66%** |
| EXP-023 | 32 | 17 | 12 | 3 | **47%** |
| EXP-024 | 28 | 11 | 12 | 5 | **61%** |

### Tool 에러율 (컨텍스트 오염 원인)

| 실험 | Tool 호출 | 에러 | 에러율 | 주요 에러 |
|------|----------|------|--------|----------|
| EXP-021 | 330 | 217 | **66%** | `Move.__init__() missing 'gen'`, move not found |
| EXP-022 | 432 | 270 | **62%** | 동일 |
| EXP-023 | 479 | 113 | **24%** | `constraint_type_list` 누락 |
| EXP-024 | 352 | 10 | **3%** | status move rejected (정상 동작) |

---

## 2. 실패 유형 분석

### 유형 A: JSON 없음 (~60% of failures)

LLM이 prose 분석만 출력하고 JSON 객체를 전혀 포함하지 않음.

**예시** (EXP-023, Turn 2):
```
I now have all the information needed. Let me break down the analysis:

## Situation Overview

- **Iron Treads** (your active, 75% HP) vs **Garganacl**...
```

**예시** (EXP-023, Turn 4):
```
Based on my analysis:

- **Thunderbolt** deals ~33% damage (4HKO) — your best damage option
- **Shadow Ball** deals ~15% damage (7HKO) — too slow
```

→ LLM이 올바른 move를 분석에서 언급하지만, JSON으로 감싸지 않음.

**예시** (EXP-022, Turn 7 — tool 에러로 인한 사과):
```
I apologize for the technical difficulties with the battle analysis tools.
It appears the tools are currently experiencing errors...
```

→ Tool 에러가 컨텍스트에 누적되면 LLM이 "사과 모드"로 전환, JSON 출력 생략.

### 유형 B: 잘못된 JSON 키 (~15% of failures)

LLM이 JSON을 출력하지만 프롬프트에서 요청한 키와 다름.

```json
// 예상: {"move": "earthquake"} 또는 {"switch": "blissey"}

// 실제 출력 사례들:
{"action": "switch", "switch_target": "rotomwash"}    // Turn 10, EXP-023
{"action": "switch", "switch_target": null}            // Turn 9,  EXP-021
{"action": "switch"}                                   // Turn 23, EXP-023 (대상 없음!)
{"move": "futuresight", "switch": null, "reasoning": "..."}  // 불필요한 키 혼재
{"decision": "switch"}                                 // Turn 1,  EXP-021
{"action": "switch", "target": "p2a"}                  // Turn 4,  EXP-021
```

### 유형 C: Tool 에러 → 컨텍스트 오염 (~25% of failures)

Tool 호출 결과로 반환된 에러 메시지가 대화 히스토리에 누적되어, LLM이 이후 응답에서 JSON 출력을 포기함.

**EXP-022 사례** (62% tool 에러율):
- 32턴 중 16턴이 "I apologize for the technical difficulties" 로 시작
- Tool 에러가 없는 EXP-024에서도 61% 파싱 실패율이므로, 이것이 유일한 원인은 아님

---

## 3. 코드 경로 분석

```
react_agent.py:build_context()
  → 시스템 프롬프트에 JSON 출력 지시 포함
  ↓
react_agent.py:agent_loop()
  → llm.bind_tools(tools).invoke()
  → tool 호출 반복 (최대 MAX_TOOL_CALLS=5회)
  → tool_call_count >= 5: HumanMessage로 강제 종료
  ↓
react_agent.py:parse_action()
  → 마지막 AIMessage (tool_calls 없음) 의 content에서 JSON 탐색
  ↓
common.py:parse_action_json()
  → 1차: json.loads(content)
  → 2차: content.find("{") ~ content.rfind("}") 로 부분 추출
  → 실패 시: None 반환
  ↓
langchain_player.py:_run_langgraph_agent()
  → result["chosen_action"] == None
  → json_parse_failures += 1
  → choose_max_damage_move() 폴백  ← ReAct 분석이 무시됨!
```

### 핵심 코드 위치

| 파일 | 함수/영역 | 역할 |
|------|----------|------|
| `pokechamp/agents/common.py:145-207` | `parse_action_json()` | JSON 파싱 및 키 정규화 |
| `pokechamp/agents/common.py:210-240` | `action_to_battle_order()` | 파싱된 action → BattleOrder 변환 |
| `pokechamp/agents/react_agent.py:105-136` | `agent_loop()` | LLM 호출 (tools 바인딩/해제) |
| `pokechamp/agents/react_agent.py:181-201` | `parse_action()` | 마지막 AI 메시지에서 action 추출 |
| `pokechamp/agents/react_agent.py:36-73` | `REACT_SYSTEM_PROMPT` | JSON 출력 형식 지시 |
| `pokechamp/langchain_player.py:248-261` | 폴백 처리 | `chosen_action=None` → max damage |
| `pokechamp/agents/state.py` | `BattleAgentState` | `available_moves`, `available_switches` 포함 |

---

## 4. 기존 `local_1v1.py` 경로와의 분리 확인

변경 대상 파일은 `pokechamp/agents/` 디렉토리에 한정되며, 기존 `local_1v1.py` → `LLMPlayer` 코드 경로와 **완전히 분리**되어 있음.

```
local_1v1.py 경로 (변경 영향 없음):
  local_1v1.py → get_llm_player() → LLMPlayer → io() (자체 json.loads 사용)
  ❌ pokechamp/agents/* 미참조

local_1v1_langchain.py 경로 (변경 대상):
  local_1v1_langchain.py → LangChainPlayer → _run_langgraph_agent()
  → create_react_agent() ✅ → parse_action_json() ✅
```

| 확인 항목 | 결과 |
|-----------|------|
| `LLMPlayer`이 `pokechamp/agents/*`를 import하는가? | **아니오** |
| `LLMPlayer.io()`가 `parse_action_json()`을 사용하는가? | **아니오** — 자체 `json.loads()` 사용 |
| `local_1v1.py`의 `prompt_algos`에 `react`가 포함되는가? | **아니오** |
| `local_1v1.py`가 `LangChainPlayer`를 생성하는가? | **아니오** — 항상 `LLMPlayer` 생성 |

---

## 5. 해결 방안

### 방안 1: prose 응답에서 action 추출 (최고 우선순위, ~60% 복구 기대)

**문제**: LLM이 "Earthquake is the best move" 와 같이 올바른 action을 언급하지만 JSON으로 감싸지 않음.

**해결**: `parse_action_json()` 실패 시, 텍스트에서 available move/switch 이름을 검색하는 폴백 추가.

**구현 위치**: `pokechamp/agents/common.py` — 새 함수 `extract_action_from_prose()` 추가

**알고리즘**:
1. `state["available_moves"]`에서 move ID 리스트 추출 (`m["id"]`)
2. `state["available_switches"]`에서 species 리스트 추출 (`s["species"]`)
3. LLM 출력 텍스트에서 각 move ID / species를 검색
4. 정규화: `lower().replace(" ", "")` (기존 `action_to_battle_order()`와 동일)
5. 여러 개 매칭 시 **텍스트 마지막에 등장한 것**을 선택 (LLM의 결론이 보통 끝에 위치)
6. move > switch 우선순위

**적용 파일**:
- `react_agent.py:parse_action()` — prose 추출 폴백 추가
- `io_agent.py:parse_action()` — 동일 패턴 적용
- `cot_agent.py:decide()` — 동일 패턴 적용

**의사코드**:
```python
def extract_action_from_prose(
    llm_output: str,
    available_move_ids: List[str],
    available_switch_species: List[str],
) -> Optional[Dict[str, Any]]:
    """prose 텍스트에서 available move/switch 이름을 검색."""
    text_lower = llm_output.lower()
    best_match = None
    best_pos = -1

    # 1. move 검색
    for move_id in available_move_ids:
        normalized = move_id.lower().replace(" ", "")
        pattern = re.compile(re.escape(normalized), re.IGNORECASE)
        m = pattern.search(text_lower)
        if m and m.start() > best_pos:
            best_pos = m.start()
            best_match = {"move": move_id}

    # 2. switch 검색 (move보다 낮은 우선순위)
    for species in available_switch_species:
        normalized = species.lower().replace(" ", "")
        pattern = re.compile(re.escape(normalized), re.IGNORECASE)
        m = pattern.search(text_lower)
        if m and m.start() > best_pos:
            best_pos = m.start()
            best_match = {"switch": species}

    return best_match
```

### 방안 2: `parse_action_json()` 강화 (~15% 추가 복구 기대)

**파일**: `pokechamp/agents/common.py`

**2a. markdown code fence 제거**

LLM이 `\`\`\`json\n{"move": "earthquake"}\n\`\`\`` 형태로 출력하는 경우, 기존 `find("{")` 방식이 code fence 안의 JSON을 추출하지 못할 수 있음.

→ 파싱 전에 code fence 제거 로직 추가:

```python
content = llm_output.strip()
# ```json ... ``` 또는 ``` ... ``` 제거
if content.startswith("```"):
    first_newline = content.find("\n")
    if first_newline >= 0:
        content = content[first_newline + 1:]
    if content.endswith("```"):
        content = content[:-3].rstrip()
```

**2b. 추가 키 별칭 처리**

LLM이 자주 사용하는 비표준 키를 정규화:

```python
# 기존에 처리되는 키: move, switch, dynamax, terastallize, switch_target, target, pokemon, species
# 추가 처리:
"move_name"    → result["move"]
"chosen_move"  → result["move"]
"chosen_switch" → result["switch"]
"decision"     → action_type (== "action" 별칭)
```

**2c. null 값 처리**

`{"switch": null}` 또는 `{"switch_target": null}` 의 경우, 기존 코드가 `None` 체크로 필터링하므로 이미 올바르게 동작함. prose 추출 폴백으로 자연스럽게 넘어감.

### 방안 3: 시스템 프롬프트 강화 (향후 실패율 감소 기대)

**파일**: `pokechamp/agents/react_agent.py` — `REACT_SYSTEM_PROMPT` (36-73행)

현재 `## Output Format` 섹션:
```
When you have gathered enough information, provide your final answer as a JSON object:
- To use a move: {"move": "<move_name>"}
```

→ 더 강력한 지시로 변경:

```
## Output Format (MANDATORY)

Your final response MUST be ONLY a JSON object.
DO NOT add explanations before or after the JSON.
DO NOT wrap in markdown code fences (```json).

CORRECT: {"move": "earthquake"}
CORRECT: {"switch": "toxapex"}
WRONG: Based on my analysis, {"move": "earthquake"}
WRONG: I think Earthquake is best because...
```

### 방안 4: max-tool-calls 강제 메시지 개선

**파일**: `pokechamp/agents/react_agent.py` (119-128행)

현재:
```python
HumanMessage(
    content="You have used the maximum number of tool calls. "
            "Now provide your final JSON decision immediately."
)
```

변경:
```python
SystemMessage(
    content=(
        "STOP. You have used all your tool calls. "
        "Output ONLY a JSON action now. No prose. No code fences. No explanation.\n"
        "Example: {\"move\": \"earthquake\"}\n"
        "Your JSON action:"
    )
)
```

`HumanMessage` → `SystemMessage` 변경 이유: 대부분의 LLM에서 시스템 메시지가 더 높은 우선순위를 가짐.

### 방안 5: Tool 에러 메시지 완화 (컨텍스트 오염 방지)

**파일**: `pokechamp/agents/react_agent.py` — `tool_execution()` (169-170행)

현재:
```python
ToolMessage(content=f"Error executing {tool_name}: {e}", ...)
```

변경:
```python
ToolMessage(
    content=(
        f"Tool {tool_name} could not complete. "
        f"Try a different approach or make your decision now. "
        f"(Detail: {str(e)[:100]})"
    ),
    ...
)
```

에러를 "try something else" 뉘앙스로 변경하여 LLM이 "사과 모드"에 빠지는 것을 방지.

---

## 6. 수정 파일 요약

| 파일 | 변경 내용 | 우선순위 |
|------|----------|---------|
| `pokechamp/agents/common.py` | `extract_action_from_prose()` 추가, `parse_action_json()` 강화 (code fence, 키 별칭) | 🔴 최고 |
| `pokechamp/agents/react_agent.py` | `parse_action()` prose 폴백, 프롬프트 강화, max-tool 메시지 개선, tool 에러 완화 | 🔴 최고 |
| `pokechamp/agents/io_agent.py` | `parse_action()` prose 폴백 추가 | 🟡 중간 |
| `pokechamp/agents/cot_agent.py` | `decide()` prose 폴백 추가 | 🟡 중간 |

**기존 `local_1v1.py` → `LLMPlayer` 코드 경로는 영향 없음**: `LLMPlayer`은 `pokechamp/agents/` 디렉토리를 import하지 않으며, 자체 `json.loads()` 파싱 로직을 사용함.

---

## 7. 기대 효과

| 방안 | 복구 대상 | 예상 복구율 |
|------|----------|-----------|
| prose 추출 (방안 1) | JSON 없음 유형 (~60%) | ~50-60% 복구 |
| JSON 파싱 강화 (방안 2) | 잘못된 키 유형 (~15%) | ~10-15% 복구 |
| 프롬프트 강화 (방안 3-4) | 향후 발생률 감소 | ~30-40% 감소 |
| Tool 에러 완화 (방안 5) | 컨텍스트 오염 cascade 방지 | 간접 효과 |

**종합 예상**: 파싱 실패율 47-66% → 10% 이하

---

## 8. 리스크 및 주의사항

- **prose 추출 오탐**: LLM이 "Let me check Earthquake damage" 라고 언급했지만 실제로는 다른 move를 선택하려 한 경우, 잘못된 move가 추출될 수 있음. 완화: 텍스트 **마지막**에 등장한 것을 우선 선택.
- **기존 동작 영향 없음**: 모든 변경은 additive fallback 임. `parse_action_json()` 성공 시 기존과 동일한 결과. prose 추출은 JSON 파싱 실패 시에만 실행됨.
- **다른 모델 호환성**: 프롬프트 변경이 다른 모델(gemma4, deepseek 등)에 미치는 영향은 실험으로 확인 필요. prose 폴백은 모델 무관하게 동작.
