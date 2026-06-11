# EXP-027 심층 분석: ReAct 에이전트 JSON 파싱 실패의 근본 원인

> 실험: EXP-027 (`react` 프롬프트 알고리즘, GLM-5.1 모델)
> 분석일: 2026-06-10
> 배틀: 1게임 (30턴, 217 LLM 호출)

---

## 1. 핵심 발견: `messages` 리듀서 누락이 근본 원인

### 문제 요약

EXP-027에서 JSON 파싱 성공률은 **31% (9/29)** 로, EXP-021~024 (47~66% 실패율) 대비 개선되지 않았습니다.

**근본 원인은 `BattleAgentState.messages` 필드에 LangGraph의 `add_messages` 리듀서가 누락되어 있기 때문입니다.**

```python
# 현재 (BUG)
class BattleAgentState(TypedDict):
    messages: List[AnyMessage]  # ← 리듀서 없음 → 매 노드마다 덮어씀

# 수정
from langgraph.graph import add_messages

class BattleAgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]  # ← 메시지 누적
```

### 영향

리듀서가 없으면 LangGraph의 각 노드가 `messages`를 **덮어쓰기** 합니다:

| 단계 | 노드 | state.messages | 문제 |
|------|------|---------------|------|
| 1 | `build_context` | `[SystemMsg, HumanMsg]` | ✅ 정상 |
| 2 | `agent` (call 1) | `[AIMsg(tool_calls)]` | ❌ 시스템 프롬프트 손실 |
| 3 | `tool_execution` | `[ToolMsg1, ToolMsg2, ...]` | ❌ AI 메시지 손실 |
| 4 | `agent` (call 2) | `[AIMsg(tool_calls)]` | ❌ 도구 결과 손실 |
| 5 | `should_continue` | `[AIMsg(tool_calls)]` | ❌ `tool_call_count = 0`! |
| ... | 무한 반복 | | ⚠️ MAX_TOOL_CALLS 미작동 |

### 실험 로그로 검증

Turn 25 (20 LLM 호출)의 로그에서 확인:

```
call 1: sys_in_user=True   ← 시스템 프롬프트 있음
call 2: sys_in_user=False  ← 시스템 프롬프트 손실!
call 3: sys_in_user=False  ← 계속 손실
...
call 20: {"move":"icebeam"} ← force 종료로 시스템 프롬프트 복원 후 JSON 출력
```

---

## 2. 파생 문제들

### 2a. MAX_TOOL_CALLS 미작동

`should_continue`에서 `tool_call_count`를 계산할 때, `state["messages"]`에 ToolMessage가 없습니다 (이미 AIMessage로 덮어씌워짐). 따라서 `tool_call_count`는 항상 0이고, "tools" 라우팅이 계속 발생합니다.

**결과**: Turn 25 = 20 calls, Turn 29 = 22 calls, Turn 13 = 23 calls. `MAX_TOOL_CALLS=5`가 완전히 무효화됨.

`agent_loop` 내부의 `tool_call_count`도 마지막 배치의 도구 수만 카운트합니다 (총 누적이 아님). 단일 배치가 ≥5개일 때만 force 종료가 발동합니다.

### 2b. 시스템 프롬프트 손실 → prose 출력

LLM은 call 2 이후 시스템 프롬프트를 받지 못합니다. "Your final response MUST be ONLY a JSON object" 지시가 손실되므로, LLM은 자연스럽게 분석 prose를 출력합니다.

**prose 응답 중 95% (19/20)이 올바른 move 추천을 포함**하고 있어, LLM의 분석 능력 자체는 정상입니다. 단지 포맷 지시가 손실될 뿐입니다.

### 2c. 비효율적 토큰 사용

리듀서 누락으로 인해:
- LLM이 매번 도구 결과만 받아 중복 도구 호출 반복
- 30턴에 571개의 도구 호출 (평균 19/턴)
- 동일한 `calculate_damage` 호출이 여러 번 반복됨

---

## 3. 정량적 분석

### JSON 파싱 성공/실패

| 지표 | 값 |
|------|-----|
| 총 턴 | 30 |
| 최종 응답 수 | 29 |
| JSON 포함 응답 | 9 (31.0%) |
| Prose만 포함 | 20 (69.0%) |

### Force 종료 vs 자연 종료

| 유형 | 응답 수 | JSON 성공 | 성공률 |
|------|---------|----------|--------|
| Force 종료 (단일 배치 ≥5) | 18 | 7 | 38.9% |
| 자연 종료 | 11 | 2 | 18.2% |

Force 종료가 더 높은 성공률을 보이는 이유: clean_messages 재구성 시 시스템 프롬프트가 포함되기 때문.

### 도구 호출 통계

| 지표 | 값 |
|------|-----|
| 총 도구 호출 | 571 |
| 에러 | 0 (0%) |
| 최다 호출 턴 | T29 (69회) |
| 최소 호출 턴 | T7, T9, T12 (2회) |

### Prose 응답의 추천 내용 분석

20개의 prose 응답 중 **19개 (95%)** 가 명확한 move/switch 추천을 포함:

```
T1:  "Use Earthquake" → ✅ 올바른 추천
T2:  "Go with Earthquake!" → ✅ 올바른 추천
T4:  "Switching is almost certainly the better play" → ✅ 전환 추천
T8:  "Use Shadow Ball" → ✅ 올바른 추천
T27: "Go with Sludge Bomb" → ✅ 올바른 추천
T30: "Go with Draco Meteor" → ✅ 올바른 추천
```

→ LLM이 올바른 분석을 하지만 JSON 포맷으로 출력하지 못함.

---

## 4. 해결 방안 (우선순위 순)

### 🔴 방안 1: `add_messages` 리듀서 추가 (필수, 최우선)

**파일**: `pokechamp/agents/state.py`

```python
from typing import Annotated
from langgraph.graph import add_messages

class BattleAgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]  # ← 수정
    # ... 나머지 필드 동일
```

**기대 효과**:
- 메시지가 누적되어 LLM이 항상 전체 컨텍스트를 유지
- `should_continue`에서 `tool_call_count`가 정확히 카운트
- `MAX_TOOL_CALLS=5`가 정상 작동
- 시스템 프롬프트 손실 방지 → JSON 출력률 대폭 향상
- 도구 호출 중복 방지 → 토큰 절약

### 🔴 방안 2: GLM-5.1 JSON 모드 활성화 (권장)

GLM-5.1은 `response_format={"type": "json_object"}`를 네이티브 지원합니다.

**파일**: `pokechamp/langchain_backend.py` 또는 `react_agent.py`

최종 응답 생성 시에만 JSON 모드 적용 (도구 호출 단계에서는 비활성화):

```python
# agent_loop에서 force 종료 시
from langchain_core.language_models import BaseChatModel

if tool_call_count >= MAX_TOOL_CALLS:
    # JSON 모드로 강제
    json_llm = llm.bind(response_format={"type": "json_object"})
    response = json_llm.invoke(clean_messages)
```

또는 LangChain의 `with_structured_output()` 사용:

```python
from pydantic import BaseModel

class BattleAction(BaseModel):
    move: Optional[str] = None
    switch: Optional[str] = None

structured_llm = llm.with_structured_output(BattleAction)
```

### 🟡 방안 3: `agent_loop` 수정 — 도구 바인딩 해제 로직 강화

리듀서 추가 후에도, force 종료 시 LLM이 도구 호출을 생성하지 못하도록 보장 필요.

**파일**: `pokechamp/agents/react_agent.py`

```python
if tool_call_count >= MAX_TOOL_CALLS:
    # tools를 바인딩하지 않은 LLM으로 호출
    # 추가: response_format으로 JSON 강제
    force_system = (
        REACT_SYSTEM_PROMPT.format(max_tools=MAX_TOOL_CALLS)
        + "\n\nSTOP. Output ONLY a JSON action."
    )
    clean_messages = [SystemMessage(content=force_system), HumanMessage(content=force_user)]
    response = llm.invoke(clean_messages)  # tools 미바인딩 확인
```

### 🟡 방안 4: prose 폴백 유지

현재 `extract_action_from_prose()`는 정상 동작하지만, 리듀서 수정 후에는 필요 빈도가 크게 줄어들 것입니다. 그럼에도 안전망으로 유지 권장.

**개선 제안**: prose에서 **마지막에 나타난 move** 대신 **"Recommendation" 섹션**의 move를 우선 추출:

```python
def extract_action_from_prose(llm_output, available_move_ids, available_switch_species):
    # 1. "Recommendation" 또는 "## Recommendation" 섹션 찾기
    rec_section = _find_recommendation_section(llm_output)
    if rec_section:
        action = _search_in_text(rec_section, available_move_ids, available_switch_species)
        if action:
            return action
    
    # 2. 기존 로직: 텍스트 전체에서 마지막 등장 검색
    ...
```

### 🟢 방안 5: 2단계 분리 (선택적, 장기 개선)

분석과 포맷팅을 분리하는 아키텍처:

```
ReAct 분석 단계 → prose 결론 생성
       ↓
포맷팅 단계 → "Output ONLY: {\"move\": \"<name>\"}" 프롬프트로 JSON 변환
```

이는 복잡도를 높이지만, JSON 성공률을 95%+로 올릴 수 있습니다.

---

## 5. 수정 파일 및 우선순위

| 파일 | 변경 내용 | 우선순위 |
|------|----------|---------|
| `pokechamp/agents/state.py` | `messages` 필드에 `add_messages` 리듀서 추가 | 🔴 필수 |
| `pokechamp/agents/react_agent.py` | force 종료 시 JSON 모드 적용 검토 | 🔴 권장 |
| `pokechamp/agents/io_agent.py` | 동일한 state.py 수정의 수혜 (별도 변경 불요) | — |
| `pokechamp/agents/cot_agent.py` | 동일 | — |
| `pokechamp/langchain_backend.py` | GLM-5.1 `response_format` 지원 추가 | 🟡 권장 |
| `pokechamp/agents/common.py` | prose 폴백 유지 (이미 구현됨) | 🟢 유지 |

---

## 6. 기대 효과

| 지표 | 현재 (EXP-027) | 리듀서 수정 후 예상 |
|------|---------------|-------------------|
| JSON 파싱 성공률 | 31% | **80~90%** |
| 평균 LLM 호출/턴 | 7.2 | **3~4** (MAX_TOOL_CALLS 정상 작동) |
| 평균 도구 호출/턴 | 19 | **5** (한도 내 실행) |
| Prose 폴백 필요률 | 69% | **10~20%** |
| 시스템 프롬프트 유지 | call 1 이후 손실 | **모든 call에서 유지** |

---

## 7. 리스크 및 주의사항

### 리듀서 추가 시 주의점

1. **메시지 누적으로 인한 컨텍스트 길이 증가**: `add_messages` 사용 시 모든 도구 결과가 누적됨. `MAX_TOOL_CALLS=5`가 정상 작동하므로 실제로는 큰 문제가 되지 않지만, 필요시 `trim_messages` 도입 검토.

2. **force 종료 경로의 clean_messages**: force 종료 시 새 메시지 리스트를 만드는데, 이것도 `add_messages` 리듀서에 의해 기존 메시지에 **추가**됨. parse_action이 올바른 메시지를 찾을 수 있도록, 마지막 AIMessage에서 JSON을 찾도록 보장 필요 (현재 로직이 이미 reverse 순회하므로 OK).

3. **다른 에이전트에 미치는 영향**: `io_agent.py`, `cot_agent.py`도 동일한 `BattleAgentState`를 사용하므로, 리듀서 수정이 모든 에이전트에 적용됨. 이들은 도구 호출이 없으므로 영향 없음.

### GLM-5.1 JSON 모드 주의점

- `response_format={"type": "json_object"}` 사용 시 시스템 프롬프트에 JSON 형식 설명이 반드시 포함되어야 함 (GLM API 요구사항)
- 도구 호출 단계에서는 JSON 모드를 비활성화해야 함 (도구 호출과 JSON 모드가 충돌할 수 있음)

---

## 8. 결론

EXP-027의 JSON 파싱 실패 (69%)의 **근본 원인은 LangGraph 상태 관리 버그**입니다. `BattleAgentState.messages`에 `add_messages` 리듀서가 누락되어:

1. 시스템 프롬프트가 첫 도구 호출 후 손실됨 → LLM이 JSON 출력 지시를 받지 못함
2. `MAX_TOOL_CALLS` 제한이 작동하지 않음 → 과도한 도구 호출
3. 대화 컨텍스트가 누적되지 않음 → 반복적이고 비효율적인 도구 사용

**`state.py` 한 줄 수정**으로 모든 파생 문제가 해결될 것으로 예상됩니다.
