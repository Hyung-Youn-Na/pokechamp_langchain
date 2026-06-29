# ReAct Agent: LLM 기반 도구 호출 종료 판단 설계

> 작성일: 2026-06-12
> 배경: EXP-030/031 실험 분석에서 도구 사용 종료 시점이 LLM에게 전적으로 위임되어 있으나,
> 시스템 프롬프트에 명확한 종료 가이드가 없어 비효율적 도구 사용(simulate_turn 과의존)이 발생.
> Rule-based 종료 조건 대신 LLM의 추론 능력을 활용하는 접근을 모색.

> ⚠️ **EXP-049b 업데이트 (2026-06-29)**: 아이디어 4(Reflection 노드로 LLM 메타인지를 그래프에 명시)의
> 핵심 방향이 **`strategy_synthesis` 노드**로 구현되었습니다 — clean rebuild로 툴 결과를 종합하고
> `STRATEGY_SYSTEM_PROMPT`가 `my_plan`(장기 승리 경로)을 명시 출력합니다. 단, confidence 기반 라우팅
> (아이디어4의 `should_continue` 개선)은 채택되지 않았고, `should_continue`는 여전히 rule-based
> (예산 + tool_calls 유무, `"tools"`/`"strategy_synthesis"`). 본 문서의 "현재 그래프" 다이어그램과
> `"parse"` 라우팅은 4노드 구버전입니다.

---

## 문제 정의

### 현재 상태

ReAct Agent의 도구 호출 종료는 다음 메커니즘에 의존:

1. **LLM 암시적 판단**: AIMessage에 `tool_calls`가 없으면 종료
2. **Hard limit**: `max_tool_calls` 도달 시 강제 종료
3. **프롬프트 가이드**: "When you have enough data, stop calling tools" (모호)

시스템 프롬프트의 Decision Process는 도구 사용 순서만 제시할 뿐,
**언제 충분한 정보를 얻었는지, 언제 도구 호출을 멈추고 결정해야 하는지에 대한 가이드가 없음.**

### Rule-based 한계

명시적 종료 조건을 프롬프트에 추가하는 것은 rule-based와 다를 바 없음:

```
❌ "3개 이상 도구를 호출했으면 중단"
❌ "모든 기술의 데미지를 계산했으면 중단"
❌ "OHKO 가능한 기술을 찾았으면 중단"
```

- 모든 상황을 예측한 규칙이 필요 → 불가능
- 상황에 따라 필요한 분석량이 다름 → 고정 규칙은 비효율
- LLM의 의미적 이해 능력을 활용하지 못함

---

## 설계 목표

| 목표 | 설명 |
|------|------|
| **상황 적응성** | 배틀 상황에 따라 분석 깊이를 자동 조절 |
| **LLM 강점 활용** | 도메인 지식과 추론 능력으로 "충분히 아는 상태" 판단 |
| **관찰 가능성** | 왜 도구를 더 호출했는지/왜 멈췄는지가 로그에 남음 |
| **구조적 개선** | 그래프 레벨에서 메커니즘을 명확히 정의 |
| **점진적 도입** | 기존 구조를 크게 변경하지 않고 추가 가능 |

---

## 아이디어 1: 자신도(Self-confidence) 기반 종료

### 개념

도구를 호출하기 전에 LLM에게 현재 판단의 확신도를 먼저 묻고,
확신도가 높으면 도구 호출 없이 바로 결정.

### 구현 방식

`agent_loop` 노드에서 도구 바인딩 전, 먼저 LLM에게 확신도를 평가:

```
프롬프트:
"지금 가장 좋은 행동은 무엇이라 생각하나요?
확신도를 0-100으로 평가하세요.
확신도가 높다면 바로 JSON 결정을 출력하세요.
확신도가 낮다면 어떤 정보가 부족한지 설명하세요."
```

### 장점

- 상황이 명확할 때(예: 1배 효과의 강력한 STAB기) → 도구 0회 호출로 즉시 결정
- 상황이 복잡할 때(예: 교체 vs 공격 선택) → 필요한 도구만 선택적 호출
- LLM이 자신의 지식 상태를 **메타인지**하는 방식

### 단점

- 확신도 평가 자체가 LLM 호출 1회 추가 (토큰 비용 증가)
- 작은 모델(GLM-5.1)이 자신의 지식 부족을 정확히 인지하지 못할 가능성
- 확신도 임계값 설정이 또 다른 rule이 될 위험

### 적용 난이도

- 낮음 — 프롬프트 수정 + `agent_loop` 내부 로직 일부 변경
- 별도 그래프 노드 불필요

---

## 아이디어 2: 가설-검증(Hypothesis-then-Verify) 패턴

### 개념

무방향 도구 호출 대신, LLM이 먼저 명시적 가설을 세우고
그 가설을 반증할 수 있는 최소한의 정보만 수집.

### 구현 방식

프롬프트에 가설-검증 프로세스를 명시:

```
## Decision Process

1. 배틀 상황을 분석하고 가설을 세우세요:
   "Earthquake가 최선일 것이다. 이유: STAB + 상대 약점"

2. 가설이 틀릴 수 있는 조건을 스스로 생각하세요:
   "상대가 풀타입이면 반감. 그럼 다른 기술이 낫다."

3. 가설이 틀릴 가능성이 있다면 그것만 검증하는 도구를 호출:
   → check_type_effectiveness("ground", opponent_species)

4. 검증 후 확신이 들면 JSON 결정 출력
```

### 장점

- LLM이 스스로 검증 필요성을 판단 → rule이 아닌 추론 기반
- "모든 기술의 데미지를 계산"이 아니라 **가설을 반증할 최소한의 정보만** 수집
- 불필요한 도구 호출이 자연스럽게 감소
- 로그에 가설과 검증 과정이 명시적으로 남음 (디버깅 용이)

### 단점

- 가설 자체가 틀린 경우(예: "Thunderbolt가 최선"인데 실제로는 Switch가 최선) 탐색이 좁아짐
- 작은 모델은 좋은 가설을 세우는 능력이 떨어질 수 있음
- 프롬프트 복잡도 증가

### 적용 난이도

- 낮음~중간 — 주로 프롬프트 수정
- 로그에 가설/검증 단계를 남기려면 `agent_loop` 수정 필요

---

## 아이디어 3: 정보 가치(Value of Information) 추론

### 개념

각 도구 호출 전에 LLM에게 "이 결과가 내 결정을 바꿀 가능성이 있는가?"를 추론.

### 구현 방식

프롬프트에 메타질문 추가:

```
## Before Each Tool Call

다음 도구를 호출하기 전에 스스로 물어보세요:
"이 도구의 결과가 내 최종 결정을 바꿀 가능성이 있는가?"

예시:
- 이미 Earthquake로 2배 데미지를 확인 → 다른 기술의 데미지는 확인 불필요
- 상대 타입을 모름 → check_type_effectiveness는 결정을 바꿀 수 있음
- 이미 충분한 정보 → 도구 호출 없이 JSON 결정 출력
```

### 장점

- LLM이 **결정의 민감도(sensitivity)**를 스스로 추론
- 상황 적응적 — 명확한 상황에서는 빠르게 종료, 복잡한 상황에서는 깊이 분석
- 프롬프트 수정만으로 적용 가능 (코드 변경 최소)

### 단점

- "결정을 바꿀 가능성" 평가 자체가 LLM의 추론 능력에 의존
- 작은 모델은 이 메타질문을 일관되게 수행하지 못할 수 있음
- 호출 전 매번 이 질문을 처리하는 것이 모델에 부담

### 적용 난이도

- 낮음 — 프롬프트 수정만으로 적용
- 효과 검증이 중요 (A/B 테스트 필요)

---

## 아이디어 4: Reflection 노드 추가 (그래프 구조적 접근)

### 개념

현재 그래프에 `reflect` 노드를 추가하여, LLM의 메타인지를
그래프 라우팅 결정에 명시적으로 활용.

### 현재 그래프

```
build_context → agent_loop ⇄ tool_execution → parse_action → END
                    ↓
              should_continue (rule-based)
              ├─ "tools" → tool_execution
              └─ "parse" → parse_action
```

### 개선 그래프

```
build_context → agent_loop → reflect → [should_continue] → tool_execution
                   ↑                      ├─ "tools"          ↓
                   └──────────────────────┘                parse_action → END
                                          └─ "parse"
```

### `reflect` 노드 동작

```python
def reflect(state: BattleAgentState, *, llm: BaseChatModel) -> dict:
    """LLM이 현재 정보 충분성을 명시적으로 평가."""
    reflect_prompt = (
        "지금까지 얻은 정보를 바탕으로:\n"
        "1. 현재 최선의 행동은 무엇인가요?\n"
        "2. 그 결정에 얼마나 자신 있나요? (확신/보통/불확실)\n"
        "3. 결정을 바꿀 수 있는 구체적인 정보가 무엇인가요?\n\n"
        "답변 형식:\n"
        '{"confidence": "high"|"medium"|"low", '
        '"missing_info": "..." | null, '
        '"best_action": {"move": "..."} | {"switch": "..."}}'
    )
    # LLM 호출 후 confidence에 따라 라우팅
```

### `should_continue` 개선

```python
def should_continue(state: BattleAgentState) -> str:
    reflection = state.get("reflection")
    confidence = reflection.get("confidence", "low") if reflection else "low"

    # Rule-based 하드 리밋 유지 (safety net)
    if state.get("tool_call_count", 0) >= max_tool_calls:
        return "parse"

    # LLM 기반 판단
    if confidence == "high":
        return "parse"  # 충분히 앎 → 결정
    elif confidence == "medium":
        # 보통이면 도구 1개 더 허용
        return "tools" if state.get("tool_call_count", 0) < max_tool_calls - 1 else "parse"
    else:  # low
        return "tools"  # 정보 부족 → 도구 계속
```

### 장점

- **구조적 개선** — 그래프에 노드 하나만 추가
- **LLM 강점 활용** — 상황 이해 기반의 유연한 판단
- **관찰 가능** — 로그에 LLM의 종료/계속 사유가 명시적으로 기록
- **점진적 개선** — reflection 프롬프트만 조정하면 됨
- **Safety net 유지** — max_tool_calls 하드 리밋은 그대로 작동
- **디버깅 용이** — "왜 5번이나 도구를 호출했나?" → reflection 로그에서 확인

### 단점

- reflect 노드 자체가 LLM 호출 1회 추가 (턴당 1~N회)
- 그래프 구조 변경 필요 (노드 + 에지 추가)
- `BattleAgentState`에 `reflection` 필드 추가 필요

### 적용 난이도

- 중간 — 그래프 구조 변경 + state 필드 추가 + 새 노드 구현
- 하지만 기존 노드는 수정 없이 유지 가능

---

## 비교 요약

| 기준 | 아이디어 1 (자신도) | 아이디어 2 (가설-검증) | 아이디어 3 (정보 가치) | 아이디어 4 (Reflection 노드) |
|------|---------------------|----------------------|----------------------|---------------------------|
| **구현 위치** | agent_loop 내부 | 프롬프트 | 프롬프트 | 그래프 구조 |
| **코드 변경** | 소폭 | 없음~소폭 | 없음 | 중간 (노드 추가) |
| **LLM 추가 호출** | 턴당 1회 | 없음 | 없음 | 턴당 1~N회 |
| **상황 적응성** | 중 | 높음 | 중 | 높음 |
| **관찰 가능성** | 낮음 | 중 | 낮음 | 높음 |
| **작은 모델 적합성** | 중 | 낮음 | 중 | 중~높음 |
| **안전망** | 없음 | 없음 | 없음 | max_tool_calls 유지 |

---

## 권장 접근

### 단기 (즉시 적용)

**아이디어 2 + 3 조합** — 프롬프트 수정만으로 빠르게 적용:

```
## Decision Process

1. 배틀 상황을 분석하고 가설을 세우세요:
   "어떤 행동이 최선일 것인가? 왜?"

2. 가설이 틀릴 수 있는 조건을 생각하고, 그것을 검증하는 도구만 호출하세요.
   각 도구 호출 전 스스로 물어보세요:
   "이 결과가 내 결정을 바꿀 가능성이 있는가?"
   그렇지 않다면 호출하지 마세요.

3. 검증 후 확신이 들면 JSON 결정을 출력하세요.
```

비용 없이 즉시 실험 가능. EXP-031 완료 후 A/B 비교.

### 중기 (구조적 개선)

**아이디어 4 (Reflection 노드)** — 그래프 구조에 메타인지 체계화:

- `reflect` 노드에서 confidence + missing_info를 구조화된 출력으로 획득
- `should_continue`가 rule-based + LLM 판단의 하이브리드로 동작
- 로그에 종료 사유가 명시적으로 남아 실험 분석 품질 향상

### 장기 (고급)

**아이디어 2 + 4 결합** — 가설-검증을 Reflection 노드에서 수행:

```
agent_loop → reflect(hypothesis + confidence) → should_continue → tool_execution → agent_loop
```

reflect 단계에서:
1. 현재 가설 생성 ("Earthquake가 최선")
2. 가설 검증 필요성 평가 (confidence: high/medium/low)
3. 필요시 검증 도구 제안

이 구조는 LLM의 추론 능력을 최대한 활용하면서도,
rule-based safety net(max_tool_calls)으로 안정성을 보장.
