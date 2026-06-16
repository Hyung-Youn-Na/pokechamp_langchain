# ReAct 에이전트 Final Step Valid Action 반환 실패 수정

> **날짜:** 2026-06-10

## 문제 요약

ReAct 에이전트가 툴 호출을 정상 수행한 후, 최종 단계에서 valid action을 반환하지 못하고 `choose_max_damage_move()`로 폴백되는 현상이 지속적으로 발생.

## 원인 분석

### 1. `_lc_messages_to_ollama` 변환 시 툴 호출 컨텍스트 손실

강제 종료(`MAX_TOOL_CALLS` 도달) 시 Ollama API에 전달되는 메시지가 구조적으로 깨져 있었음:

- 빈 `assistant` 메시지 (툴 호출 AIMessage의 content가 빈 문자열)
- `ToolMessage`에서 `tool_call_id` 참조 누락
- 다중 `system` 메시지 (Ollama 모델이 강제 종료 프롬프트를 무시할 수 있음)

### 2. `parse_action`이 `tool_calls`가 있는 AIMessage를 무조건 스킵

GLM-5.1이 `tools=None` 상태에서도 대화 맥락에 따라 `tool_calls`를 포함한 응답을 반환할 수 있음. 이 경우 `parse_action`이 해당 메시지를 스킵하여 모든 AIMessage가 파싱되지 못함.

### 3. `should_continue`의 무의미한 분기 (dead branch)

한계 초과 여부와 무관하게 양쪽 분기가 모두 `"tools"`를 반환하여, 실제로 툴 호출 제한이 작동하지 않았음.

## 적용 수정

| # | 파일 | 함수 | 수정 내용 |
|---|------|------|-----------|
| 1 | `react_agent.py` | `parse_action` | `tool_calls` 유무와 상관없이 AIMessage content 파싱 시도 + 각 메시지별 prose fallback |
| 2 | `react_agent.py` | `agent_loop` | 강제 종료 시 깨끗한 2-메시지(SystemMsg + HumanMsg)로 재구성, 툴 결과는 요약 포함 |
| 3 | `langchain_backend.py` | `_lc_messages_to_ollama` | ToolMessage에 `tool_call_id` 참조 추가, AIMessage에 `tool_calls` 정보 보존 |
| 4 | `react_agent.py` | `should_continue` | 한계 초과 시 `"tools"` 대신 `"parse"` 반환하도록 분기 수정 |

## 관련 파일

- `pokechamp/agents/react_agent.py` — 수정 1, 2, 4
- `pokechamp/langchain_backend.py` — 수정 3
- [LangGraph 아키텍처 문서](../architecture/langgraph-architecture.md)
