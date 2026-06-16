# Battle Viewer (`tools/battle_viewer.py`) 문제점 분석서

> 분석 일자: 2026-06-11
> 대상 실험: `EXP-028-react-glm51` (LangGraph ReAct 에이전트)
> 대상 파일: `tools/battle_viewer.py` (1,965 lines)

---

## 목차

1. [심각한 버그 (Critical)](#1-심각한-버그-critical)
2. [데이터 손실/잘림 문제 (High)](#2-데이터-손실잘림-문제-high)
3. [UI/UX 문제 (Medium)](#3-uiux-문제-medium)
4. [코드 품질 문제 (Low)](#4-코드-품질-문제-low)
5. [개선 제안 요약](#5-개선-제안-요약)

---

## 1. 심각한 버그 (Critical)

### 1.1 🔴 데드 코드 — 잔여 엔트리 처리 불가

**위치:** `match_entries_to_turns()` 818–827행

```python
    return matched          # ← line 816: 항상 여기서 반환됨

    # Handle remaining entries (shouldn't happen normally, but just in case)
    remaining = entry_idx   # ← entry_idx가 정의되지 않음 (NameError 발생)
    if remaining < len(entries) and matched:
        for extra in entries[remaining:]:
            matched[-1]["retries"].append(
                {"reasoning": extra.reasoning, "action": extra.action}
            )

    return matched          # ← line 827: 도달 불가능한 두 번째 return
```

**문제:**
- 816행의 `return matched` 이후 코드는 **절대 실행되지 않음**
- `entry_idx` 변수가 함수 내에 존재하지 않아, 실행되더라도 `NameError` 발생
- 모든 배틀 턴이 소진된 이후의 LLM 엔트리가 **잘려서 손실**됨
- 실제로는 774–815행의 루프에서 `turn_idx >= len(turns)`인 경우 마지막 턴의 retries에 추가하는 처리가 있으나, 이는 임시방편

**영향:** 긴 배틀에서 마지막 턴 이후의 LLM 재시도 로그가 누락될 수 있음

---

### 1.2 🔴 툴 결과 매칭 버그 — 잘못된 결과 연결

**위치:** `parse_langgraph_logs()` 444–453행

```python
if (
    tr["tool"] == tc_info.tool_name
    or tool_result_idx < len(tool_calls_raw)  # ← 항상 True!
):
    tc_info.result = tr.get("result", "")
    tc_info.is_error = tr.get("is_error", False)
    tool_result_idx += 1
```

**문제:**
- `tool_result_idx < len(tool_calls_raw)` 조건이 **정상 반복 중에는 항상 True**
- `or` 연산자로 인해 툴 이름이 일치하지 않아도 결과가 매핑됨
- 결과적으로 `calculate_damage` 툴의 결과가 `simulate_turn` 툴에 연결되는 등 **잘못된 결과 표시**

**예시:**
```
LLM이 calculate_damage, simulate_turn을 순차 호출
→ tool_log에 [calculate_damage 결과, simulate_turn 결과] 기록
→ 매칭 로직이 이름 무시하고 순서대로 매핑
→ 올바른 결과가 표시될 수도 있지만, 비동기/재시도 시나리오에서 오매칭 발생
```

---

### 1.3 🔴 중첩 JSON 파싱 실패

**위치:** `_extract_reasoning()` 286행, `_parse_entry_block()` 212행

```python
# _extract_reasoning (line 286)
json_match = re.search(r'\{[^}]*\}', message_content)
# [^}]* → "}"가 아닌 문자만 매칭 → 중첩 JSON에서 첫 "}"에서 중단

# _parse_entry_block (line 212)
output_match = re.search(r"output: (\{[^}]+\})", full_text)
# 동일한 문제
```

**문제:**
- 중첩 JSON이 포함된 응답(예: `{"move": "earthquake", "tera": {"type": "fire"}}`)을 제대로 파싱하지 못함
- `[^}]*` 패턴이 첫 번째 `}`에서 멈추어 불완전한 JSON 조각만 매칭
- **실제 영향:** Terastallize, Dynamax 등 복합 액션이 포함된 턴에서 액션 파싱 실패

---

### 1.4 🔴 XSS 취약점 — JSON 데이터 비이스케이프 삽입

**위치:** `generate_battle_viewer()` 933행

```python
turn_data_json = json.dumps(battle.matched_turns, ensure_ascii=False)
# 이후 HTML에 직접 삽입 (실제로는 JS 내에 삽입되지 않으나, 향후 변경 시 위험)
```

**문제:**
- `_html_escape()` 처리 없이 사용자 제어 문자열이 JSON으로 직렬화되어 HTML에 삽입
- LLM 응답에 `</script>` 또는 HTML 태그가 포함되면 스크립트 컨텍스트 탈출 가능
- 현재는 JSON 데이터가 JS에 직접 삽입되지 않아 즉각적 위험은 없으나, 향후 리팩토링 시 취약점 유발 가능

**영향:** 로컬 파일이므로 실제 공격 벡터는 제한적이나, 웹 서버로 서비스할 경우 XSS 위험

---

## 2. 데이터 손실/잘림 문제 (High)

### 2.1 🟠 ReAct 뷰어 — reasoning 텍스트 1,000자 잘림

**위치:** `generate_react_viewer()` 1446행

```python
<div class="reasoning-text">{_html_escape(_truncate(step.reasoning, 1000))}</div>
```

**문제:**
- LLM reasoning이 1,000자에서 강제 잘림
- ReAct 에이전트의 긴 분석(타입 상성, 데미지 계산, 전략적 고민 등)이 **중간에 끊겨서 표시**
- 사용자가 "왜 이 행동을 선택했는지" 핵심 논리를 놓칠 수 있음

**실제 사례 (EXP-028):**
- 평균 LLM 응답 길이가 1,500–3,000자인 경우가 빈번
- 1,000자 제한으로 reasoning의 약 30–70%가 손실

---

### 2.2 🟠 ReAct 뷰어 — 툴 결과 300자 잘림

**위치:** `generate_react_viewer()` 1397행

```python
result_display = _truncate(tc.result, 300) if tc.result else ""
```

**문제:**
- 툴 호출 결과(데미지 계산, 턴 시뮬레이션 등)가 300자에서 잘림
- `calculate_damage` 결과는 보통 200–500자, `simulate_turn` 결과는 500–2,000자
- 중요한 계산 결과(효과적/비효과적 표시, KO 확률 등)가 누락될 수 있음

**실제 사례 (EXP-028):**
- `calculate_damage`: 82회 호출, 대부분 300자 초과
- `simulate_turn`: 31회 호출, 대부분 300자 초과

---

### 2.3 🟠 배틀 이벤트 20개 제한

**위치:** `generate_battle_viewer()` 983행

```python
for e in t["events"][:20]:  # Limit to 20 events per turn
```

**문제:**
- 턴당 이벤트를 최대 20개까지만 표시
- 복잡한 턴(더블 배틀, 날씨 효과, 상태이상, 아이템 발동 등)에서 이벤트가 20개를 쉽게 초과
- 20개 초과 시 "... and N more" 메시지만 표시

---

### 2.4 🟠 ReAct 뷰어 — system_prompt / user_prompt 미표시

**위치:** `generate_react_viewer()` 전체 (1334–1587행)

**문제:**
- `ReActTurn.system_prompt`와 `ReActTurn.battle_state`는 파싱되어 저장되지만 **HTML에 렌더링되지 않음**
- 반면 표준 뷰어(`generate_battle_viewer`)에서는 system_prompt/user_prompt가 접이식 섹션으로 표시됨
- 에이전트의 "어떤 프롬프트를 받았는지" 확인 불가

**관련 CSS/JS가 준비되어 있으나 사용되지 않음:**
- `.battle-section`, `.battle-section-header`, `.battle-section-body` CSS 클래스 정의됨
- `showTurn()` JS 함수에서 `battle-group-{turnNum}` 요소를 찾으려 하지만 **HTML에 존재하지 않음**
- `#battlePlaceholder` 요소를 숨기려 하지만 **HTML에 존재하지 않음**

---

### 2.5 🟠 `_extract_battle_state` / `_extract_historical_turns` — 불안정한 정규식

**위치:** 479–509행

```python
def _extract_battle_state(user_prompt: str) -> str:
    match = re.search(
        r"Turn \d+: (Current battle state:.*?)(?:\n\nYour current pokemon:|$)",
        user_prompt, re.DOTALL,
    )
```

**문제:**
- 프롬프트 구조가 조금이라도 변경되면 빈 문자열 반환
- `"Your current pokemon:"` 구분자가 프롬프트에 없으면 전체 매칭 실패
- `.*?` (non-greedy) 매칭으로 의도보다 적은 텍스트가 캡처될 수 있음

---

### 2.6 🟠 `_parse_entry_block` — 중첩 따옴표 처리 실패

**위치:** 189–196행

```python
msg_match = re.search(
    r'Message content: "(.*?)"\noutput:', full_text, re.DOTALL
)
```

**문제:**
- `.*?` (non-greedy)가 첫 번째 `"`에서 멈춤
- 메시지 내용에 따옴표가 포함되면 내용이 잘림
- 예: `Message content: "He said "use earthquake" then"` → `He said `만 매칭

---

## 3. UI/UX 문제 (Medium)

### 3.1 🟡 턴 네비게이션 — 34개 턴 시 스크롤 불편

**위치:** CSS `.turn-nav` (1242행)

```css
.turn-nav {
    max-height: 80px;
    overflow-y: auto;
}
```

**문제:**
- 34개 턴의 버튼이 80px 높이에 압축 → 가로/세로 스크롤 필요
- 턴 번호가 작아서 특정 턴을 찾기 어려움
- 50턴 이상 배틀에서는 사실상 사용 불가

---

### 3.2 🟡 반응형 레이아웃 — 존재하지 않는 패널 참조

**위치:** CSS media query (1293–1297행)

```css
@media (max-width: 900px) {
    .battle-panel { width: 100%; height: 40vh; ... }
}
```

**문제:**
- `.battle-panel` 클래스가 HTML에 존재하지 않음 (ReAct 뷰어가 replay iframe을 사용하는 경우)
- CSS만 정의되고 실제 요소가 없어 불필요한 스타일

---

### 3.3 🟡 초기 로드 — 첫 턴 자동 선택은 되나 배틀 상태는 안 보임

**위치:** JS (1577–1579행)

```javascript
if (document.querySelectorAll('.turn-btn').length > 0) {
    showTurn(document.querySelectorAll('.turn-btn')[0].dataset.turn);
}
```

**문제:**
- 첫 턴이 자동으로 선택되지만, `showTurn()`이 `battle-group-*` 요소를 찾지 못해 배틀 상태 패널이 비어 있음
- 사용자가 페이지를 열면 왼쪽은 iframe, 오른쪽은 첫 턴의 reasoning만 보임
- "배틀이 어떤 상황인지" 한눈에 파악하기 어려움

---

### 3.4 🟡 툴 결과 — CSS max-height 120px로 스크롤 필요

**위치:** CSS `.tool-result` (1275행)

```css
.tool-result {
    max-height: 120px;
    overflow-y: auto;
}
```

**문제:**
- 120px면 약 8줄 정도만 표시 가능
- 긴 툴 결과(데미지 계산, 턴 시뮬레이션 등)를 보려면 스크롤해야 함
- 300자 Python 단계 잘림 + 120px CSS 잘림의 이중 제한

---

### 3.5 🟡 승패 결과 표시 없음 — ReAct 뷰어

**위치:** `generate_react_viewer()` 헤더 영역

**문제:**
- 표준 뷰어는 승/패/무 배지(Win/Loss/Tie)를 표시하지만
- ReAct 뷰어는 승패 정보를 전혀 표시하지 않음
- `LangGraphBattle` 데이터 구조에 `winner` 필드가 없음

---

### 3.6 🟡 인덱스 페이지 — ReAct 형식에 승패 통계 없음

**위치:** `generate_react_index()` (1590–1679행)

**문제:**
- 표준 인덱스는 "5W / 3L / 0T (62.5%)" 승률을 표시
- ReAct 인덱스는 승률 정보 없이 툴 사용량, 토큰 수만 표시
- HTML 리플레이에서 승패를 추출하는 로직이 ReAct 경로에서 호출되지 않음

---

## 4. 코드 품질 문제 (Low)

### 4.1 🟢 `_extract_final_action` — 죽은 코드

**위치:** 538행

```python
key = pattern.split(r"\\")[-1].split('"')[0]  # 항상 빈 문자열 반환
```

- `r"\\"`은 리터럴 `\\`로 분할 → 패턴 문자열에 `\\` 없음 → 전체 문자열 반환
- `.split('"')[0]` → 빈 문자열
- 하지만 540–543행에서 하드코딩된 if/elif로 실제 처리 → `key` 변수는 사용되지 않음

---

### 4.2 🟢 `match_entries_to_turns` — future_match 로직의 한계

**위치:** 797–813행

```python
for ahead in range(turn_idx + 1, min(turn_idx + 4, len(turns))):
    if _action_matches(entry.action, turns[ahead]):
        future_match = True
        break
```

**문제:**
- 앞으로 최대 3턴까지만 확인 → 4턴 이상 격차가 나면 미매칭
- `future_match`가 True여도 실제로 턴 인덱스를 전진시키지 않음 → 모든 엔트리가 현재 턴의 retry로 들어감

---

### 4.3 🟢 `_action_matches` — 빈 액션 자동 매칭

**위치:** 832–833행

```python
if not turn_info.player_action:
    return True  # Can't verify, assume match
```

**문제:**
- 빈 액션을 항상 매칭으로 간주 → false positive 가능
- 강제 교체(drag), 기절 후 교체 등의 상황에서 `player_action`이 비어있을 수 있음

---

### 4.4 🟢 출력 디렉토리 중복 생성

**문제:**
- `process_experiment()`에서 `exp_path / "viewer"` 생성
- `_process_langgraph_experiment()`에서도 동일 경로 생성
- `battle_log/` 아래에도 `viewer/`가 생성될 수 있어 혼란
- EXP-028에서 두 개의 viewer 디렉토리가 존재:
  - `.temp/experiments/archive/EXP-028-react-glm51/viewer/` (180KB)
  - `.temp/experiments/archive/EXP-028-react-glm51/battle_log/viewer/` (342KB)

---

## 5. 개선 제안 요약

| 우선순위 | 문제 | 제안 |
|----------|------|------|
| **P0** | 툴 결과 매칭 버그 | `or` 조건 제거, 툴 이름 기반 매칭으로 수정 |
| **P0** | 중첩 JSON 파싱 | `json.JSONDecoder.raw_decode()` 사용 또는 마지막 `}` 찾기 |
| **P0** | 데드 코드 제거 | 818–827행 삭제 |
| **P1** | reasoning 1,000자 잘림 | 접이식(accordion)으로 전체 텍스트 표시 |
| **P1** | 툴 결과 300자 잘림 | 접이식 + "더 보기" 버튼으로 전체 결과 표시 |
| **P1** | system/user prompt 미표시 | ReAct 뷰어에도 접이식 프롬프트 섹션 추가 |
| **P1** | 배틀 상태 미표시 | `battle-group-*` HTML 요소 생성 |
| **P2** | 승패 정보 누락 | ReAct 경로에서도 HTML 리플레이 파싱하여 승패 추출 |
| **P2** | 턴 네비게이션 개선 | 슬라이더 + 현재 턴 하이라이트 개선 |
| **P2** | XSS 방어 | JSON → JS 삽입 시 `</script>` 이스케이프 |
| **P3** | 출력 디렉토리 통일 | viewer 출력 위치 단일화 |
| **P3** | 반응형 CSS 정리 | 존재하지 않는 패널 참조 제거 |
