# EXP-011: io all flags (deepseek-v4-flash)

## 목적
`io` 프롬프트 알고리즘에 모든 동적 플래그(`--enable_dynamic_flags --enable_dynamic_calcs --enable_showdown_oracle`)를 동시에 활성화했을 때의 성능을 측정합니다. minimax 알고리즘 기반 EXP-007 (all flags, 60.0%)와 비교하여, 전체 flags 활성화가 io 프롬프트 알고리즘에 미치는 영향을 평가합니다.

## 가설
`--enable_dynamic_flags --enable_dynamic_calcs --enable_showdown_oracle`를 모두 활성화하면, io 알고리즘에서 최대치의 동적 정보가 LLM의 의사결정 품질을 향상시킬 것입니다. EXP-010(io flags+calcs, 60.0%) 대비 oracle 추가로 승률이 추가 개선될 가능성이 있으며, EXP-007(minimax all flags, 60.0%)와 비교하여 io 알고리즘에서의 전체 flags 효과를 평가합니다.

## 설정 (EXP-007 대비 변경점만 명시)
- Prompt algorithm: `io` (EXP-007은 `minimax`)
- 동적 플래그: `--enable_dynamic_flags --enable_dynamic_calcs --enable_showdown_oracle` (EXP-007과 동일)
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
| Dynamic flags | `--enable_dynamic_flags --enable_dynamic_calcs --enable_showdown_oracle` |

## 결과
- **승률**: 14/30 (46.7%)
- **평균 턴 수**: 55.7
- **JSON 파싱 실패**: 0회
- **평균 LLM 호출 수/배틀**: 36.3
- **평균 Prompt Tokens**: 82,744
- **평균 Completion Tokens**: 505
- **총 소요 시간**: 59분 16초

### EXP-007 (minimax all flags) 대비 비교

| 지표 | EXP-007 (minimax all flags) | EXP-011 (io all flags) | Delta |
|------|----------------------------|------------------------|-------|
| 승률 | 60.0% (18/30) | 46.7% (14/30) | **-13.33pp** |
| 평균 턴 수 | 28.9 | 55.7 | +26.8 |
| LLM 호출/배틀 | 56.4 | 36.3 | -20.1 |
| Prompt Tokens/배틀 | ~132,790 | 82,744 | -50,046 |
| Completion Tokens/배틀 | ~3,510 | 505 | -3,005 |

### EXP-008 (io baseline) 대비 비교

| 지표 | EXP-008 (io baseline) | EXP-011 (io all flags) | Delta |
|------|----------------------|------------------------|-------|
| 승률 | 20.0% (6/30) | 46.7% (14/30) | **+26.67pp** |
| 평균 턴 수 | 58.6 | 55.7 | -2.9 |
| LLM 호출/배틀 | 33.0 | 36.3 | +3.3 |
| Prompt Tokens/배틀 | 70,590 | 82,744 | +12,154 |

### EXP-009 (io flags-only) 대비 비교

| 지표 | EXP-009 (io flags-only) | EXP-011 (io all flags) | Delta |
|------|------------------------|------------------------|-------|
| 승률 | 46.7% (14/30) | 46.7% (14/30) | **+0.00pp** |
| 평균 턴 수 | 44.6 | 55.7 | +11.1 |
| LLM 호출/배틀 | 29.3 | 36.3 | +7.0 |
| Prompt Tokens/배틀 | 61,212 | 82,744 | +21,532 |

### EXP-010 (io flags+calcs) 대비 비교

| 지표 | EXP-010 (io flags+calcs) | EXP-011 (io all flags) | Delta |
|------|--------------------------|------------------------|-------|
| 승률 | 60.0% (18/30) | 46.7% (14/30) | **-13.33pp** |
| 평균 턴 수 | 43.8 | 55.7 | +11.9 |
| LLM 호출/배틀 | 31.1 | 36.3 | +5.2 |
| Prompt Tokens/배틀 | 65,672 | 82,744 | +17,072 |

## 분석

### 핵심 발견
`io` 프롬프트 알고리즘에 모든 flags를 활성화한 결과, EXP-010(io flags+calcs, 60.0%) 대비 **-13.33pp 하락**한 46.7%를 기록했습니다. 이는 EXP-009(io flags-only, 46.7%)와 동일한 승률로, oracle 추가가 오히려 flags+calcs의 이점을 상쇄했습니다. minimax 기반 EXP-007(60.0%) 대비 **-13.33pp** 낮은 결과입니다.

### 원인 분석
1. **Oracle의 부정적 영향**: `--enable_showdown_oracle` 추가는 EXP-010(60.0%) → EXP-011(46.7%)로 -13.33pp 하락을 유발했습니다. Oracle이 제공하는 정확한 데미지/KO 확률 정보가 io 알고리즘의 프롬프트를 과도하게 복잡하게 만들어 LLM의 판단을 흐렸을 가능성이 있습니다.
2. **프롬프트 길이 증가**: 평균 prompt tokens(82,744)은 EXP-010(65,672) 대비 +17,072 증가했습니다. oracle 정보가 프롬프트를 길게 만들어 LLM이 핵심 정보에 집중하기 어려워졌을 수 있습니다.
3. **동일 승률의 의미**: EXP-011(46.7%) = EXP-009(46.7%)는 oracle+calcs의 추가 정보가 flags-only와 동등한 수준으로만 작동했음을 시사합니다. calcs의 긍정적 효과(EXP-009→EXP-010, +13.33pp)가 oracle에 의해 완전히 상쇄되었습니다.
4. **minimax vs io 구조 차이**: minimax에서는 모든 flags를 켰을 때 EXP-007(60.0%)이 EXP-006(40.0%) 대비 +20.00pp 개선을 보였으나, io에서는 oracle이 추가 정보로 작동하지 못하고 성능을 저하시켰습니다.

### 다음 단계
- io 알고리즘에서 oracle 정보의 프롬프트 통합 방식 개선 필요
- flags+calcs 조합이 io에서 최적이며, oracle은 추가 개선이 아닌 별도 튜닝이 필요할 수 있음
- io+flags+calcs(EXP-010, 60.0%)가 io 알고리즘의 최적 구성으로 판단됨
