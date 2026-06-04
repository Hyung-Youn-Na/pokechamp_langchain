# EXP-009: io flags-only (deepseek-v4-flash)

## 목적
`io` 프롬프트 알고리즘에 `--enable_dynamic_flags` 플래그를 추가했을 때의 성능을 측정합니다. minimax 알고리즘 기반 EXP-005 (flags-only, 70.0%)와 비교하여, 동적 flags가 io 프롬프트 알고리즘에 미치는 영향을 평가합니다.

## 가설
`--enable_dynamic_flags`는 무브 정보에 동적 플래그(STAB, 효과성 등)를 추가하여 프롬프트 품질을 향상시킵니다. minimax에서는 flags가 성능을 저하시켰지만(EXP-005: -20pp vs EXP-004), io 알고리즘에서는 트리 탐색이 없으므로 flags가 추가 정보로서 도움이 될 수 있습니다. 다만 EXP-008(io baseline, 20.0%)과 비교하여 어느 정도 개선이 있을 것으로 예상합니다.

## 설정 (EXP-005 대비 변경점만 명시)
- Prompt algorithm: `io` (EXP-005는 `minimax`)
- 동적 플래그: `--enable_dynamic_flags` (EXP-005와 동일)
- 코드 변경: 없음

### 전체 설정
| 항목 | 값 |
|------|-----|
| Player | pokechamp |
| Prompt algo | `io` |
| Backend | ollama/deepseek-v4-flash:cloud |
| Opponent | abyssal |
| Battle format | gen9ou |
| Temperature | 0.3 |
| Seed | 42 |
| N | 30 |
| Dynamic flags | `--enable_dynamic_flags` |

## 결과
- **승률**: 14/30 (46.7%)
- **평균 턴 수**: 44.6
- **JSON 파싱 실패**: 0회
- **평균 LLM 호출 수/배틀**: 29.3
- **평균 Prompt Tokens**: 61,212
- **평균 Completion Tokens**: 489
- **총 소요 시간**: 37분 48초

### EXP-005 (minimax flags-only) 대비 비교

| 지표 | EXP-005 (minimax flags) | EXP-009 (io flags) | Delta |
|------|------------------------|---------------------|-------|
| 승률 | 70.0% (21/30) | 46.7% (14/30) | **-23.33pp** |
| 평균 턴 수 | N/A | 44.6 | — |
| LLM 호출/배틀 | ~8 | 29.3 | +21.3 |
| Prompt Tokens/배틀 | N/A | 61,212 | — |
| Completion Tokens/배틀 | N/A | 489 | — |

### EXP-008 (io baseline) 대비 비교

| 지표 | EXP-008 (io baseline) | EXP-009 (io flags) | Delta |
|------|----------------------|---------------------|-------|
| 승률 | 20.0% (6/30) | 46.7% (14/30) | **+26.67pp** |
| 평균 턴 수 | 58.6 | 44.6 | -14.0 |
| LLM 호출/배틀 | 33.0 | 29.3 | -3.7 |
| Prompt Tokens/배틀 | 70,590 | 61,212 | -9,378 |

## 분석

### 핵심 발견
`io` 프롬프트 알고리즘에 `--enable_dynamic_flags`를 추가하면 EXP-008(io baseline) 대비 **+26.67pp**의 상당한 승률 향상이 관찰됩니다. 그러나 동일 flags 조건의 minimax(EXP-005, 70.0%)에는 여전히 **-23.33pp** 부족합니다.

### 원인 분석
1. **Flags의 긍정적 효과**: `io` 알고리즘에서는 flags가 무브 정보를 풍부하게 하여 LLM의 의사결정 품질을 향상시킵니다. EXP-008(20.0%) → EXP-009(46.7%)로 +26.67pp 개선은 flags가 io 알고리즘에 큰 도움이 됨을 보여줍니다.
2. **minimax와의 차이**: minimax(EXP-005)에서는 flags가 baseline(EXP-004, 90.0%) 대비 -20pp 저하를 유발했지만, io에서는 flags가 +26.67pp 향상을 가져왔습니다. 이는 두 알고리즘의 구조적 차이 때문으로 보입니다: minimax는 트리 탐색 중 flags 정보가 노이즈로 작용할 수 있지만, io는 flags를 직접적인 의사결정 정보로 활용합니다.
3. **평균 턴 수 감소**: EXP-008(58.6턴) → EXP-009(44.6턴)로 감소했습니다. 이는 flags 추가로 더 효율적인 무브 선택이 이루어짐을 시사합니다.
4. **토큰 효율 향상**: 평균 prompt tokens가 70,590 → 61,212로 감소했습니다. 짧은 배틀로 인한 것이 주원인입니다.

### 다음 단계
- EXP-010에서 `--enable_dynamic_calcs` 추가 효과 측정
- EXP-011에서 모든 flags 조합 효과 측정
- io+flags 조합이 minimax 대비 어느 정도 격차가 있는지 종합 평가
