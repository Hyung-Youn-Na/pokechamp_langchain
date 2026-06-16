# ReAct Agent "should_continue" 결정 방식 분석

> 분석 대상: `scripts/battles/local_1v1_langchain.py`에서 사용하는 ReAct agent
> 분석 일시: 2026-06-11

---

## 결론: Rule-based + LLM 간접 판단의 하이브리드

ReAct agent의 continuation 결정은 **Rule-based 라우터**가 주도하며, LLM은 **간접적으로만** 영향을 줍니다.
LLM이 "계속하겠다"라고 명시적으로 판단하는 것은 **아닙니다.**

---

## 1. 그래프 구조

```
build_context → agent_loop ⇄ tool_execution → parse_action → END
                    ↓
              [should_continue]
              ├─ "tools" → tool_execution (루프 계속)
              └─ "parse" → parse_action (루프 종료)
```

- **그래프 빌더:** `create_react_agent()` (`react_agent.py:343-396`)
- **conditional edge:** `agent_loop` 이후 `should_continue` 함수가 "tools" 또는 "parse"로 라우팅

---

## 2. `should_continue` 함수 (Rule-based 라우터)

**파일:** `pokechamp/agents/react_agent.py:300-335`

`_make_should_continue(max_tool_calls)` 팩토리가 생성한 함수로, **순수하게 rule-based**입니다:

```python
def should_continue(state: BattleAgentState) -> str:
    # Rule 1: ToolMessage 개수 >= max_tool_calls → 강제 종료 ("parse")
    tool_call_count = sum(1 for m in state["messages"] if isinstance(m, ToolMessage))
    if tool_call_count >= max_tool_calls:
        return "parse"

    # Rule 2: 마지막 AI 메시지에 tool_calls가 있으면 → 계속 ("tools")
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        # Rule 3: pending tool_calls가 한도 초과면 → 종료 ("parse")
        if tool_call_count + pending > max_tool_calls:
            return "parse"
        return "tools"

    # Rule 4: tool_calls 없으면 → 종료 ("parse")
    return "parse"
```

### 확인하는 규칙 (4가지)

| # | 규칙 | 조건 | 결과 |
|---|------|------|------|
| 1 | Tool call count 한도 | `ToolMessage` 개수 >= `max_tool_calls` | `"parse"` (강제 종료) |
| 2 | Pending 초과 | 현재 count + pending > `max_tool_calls` | `"parse"` (강제 종료) |
| 3 | AI 메시지에 tool_calls 존재 | `last_message.tool_calls`가 비어있지 않음 | `"tools"` (루프 계속) |
| 4 | tool_calls 없음 | `last_message.tool_calls`가 없거나 비어있음 | `"parse"` (루프 종료) |

---

## 3. LLM의 간접적 역할

LLM은 "should continue"를 **명시적으로 결정하지 않습니다.** 대신 출력 형태로 간접적으로 영향을 줍니다:

| LLM 출력 | 라우터 해석 | 결과 |
|----------|------------|------|
| `tool_calls` 포함된 AIMessage | "tools" | 루프 계속 (도구 실행) |
| `tool_calls` 없는 AIMessage (텍스트만) | "parse" | 루프 종료 (액션 파싱) |

즉, **LLM의 출력 형식(tool_calls 유무)**이 간접적으로 continuation을 결정합니다.

---

## 4. 강제 종료 메커니즘 (Safety Net)

**파일:** `pokechamp/agents/react_agent.py:137-171`

`agent_loop` 노드에서 `tool_call_count >= max_tool_calls`일 때 작동:

1. 대화 기록을 깨끗하게 재구성 (2-message 구조: SystemMessage + HumanMessage)
2. 기존 tool 결과를 "Tool Results Summary"로 요약하여 포함
3. "STOP. You have used all your tool calls." 프롬프트 추가
4. JSON mode (`response_format={"type": "json_object"}`)로 강제 구조화 출력
5. 이후 `should_continue`가 "parse"로 라우팅하여 루프 종료

---

## 5. 관련 파일

| 파일 | 역할 |
|------|------|
| `pokechamp/agents/react_agent.py` | ReAct agent 그래프 정의 (should_continue, agent_loop, tool_execution, parse_action) |
| `pokechamp/langchain_player.py` | LangChainPlayer에서 ReAct agent 호출 |
| `scripts/battles/local_1v1_langchain.py` | 배틀 진입점 (`--player_prompt_algo react`) |

---

## 6. 요약

- **LLM이 직접 "should continue"를 판단하지 않음**
- **Rule-based 라우터**가 tool call count와 tool_calls 존재 여부로 결정
- LLM은 도구를 호출할지 말지를 결정할 뿐, continuation 여부는 라우터가 판단
- `max_tool_calls` 하드 리밋(기본 5)으로 무한 루프 방지
