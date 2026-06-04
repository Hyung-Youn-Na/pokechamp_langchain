# EXP-010: io flags+calcs (deepseek-v4-flash)

## 목적
`io` 프롬프트 알고리즘에 `--enable_dynamic_flags`와 `--enable_dynamic_calcs`를 동시에 활성화했을 때의 성능을 측정합니다. minimax 알고리즘 기반 EXP-006 (flags+calcs, 40.0%)와 비교하여, 동적 flags+calcs가 io 프롬프트 알고리즘에 미치는 영향을 평가합니다.

## 가설
`--enable_dynamic_flags --enable_dynamic_calcs`를 동시에 활성화하면, io 알고리즘에서 flags와 calcs가 추가 정보로서 LLM의 의사결정 품질을 향상시킬 것입니다. EXP-009(io flags-only, 46.7%) 대비 calcs 추가로 승률이 추가 개선될 가능성이 있으며, EXP-006(minimax flags+calcs, 40.0%)와 비교하여 io 알고리즘에서의 flags+calcs 효과를 평가합니다.

## 설정 (EXP-006 대비 변경점만 명시)
- Prompt algorithm: `io` (EXP-006은 `minimax`)
- 동적 플래그: `--enable_dynamic_flags --enable_dynamic_calcs` (EXP-006과 동일)
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
| Dynamic flags | `--enable_dynamic_flags --enable_dynamic_calcs` |

## 결과
- **승률**: 18/30 (60.0%)
- **평균 턴 수**: 43.8
- **JSON 파싱 실패**: 0회
- **평균 LLM 호출 수/배틀**: 31.1
- **평균 Prompt Tokens**: 65,672
- **평균 Completion Tokens**: 504
- **총 소요 시간**: 39분 55초

### EXP-006 (minimax flags+calcs) 대비 비교

| 지표 | EXP-006 (minimax flags+calcs) | EXP-010 (io flags+calcs) | Delta |
|------|------------------------------|--------------------------|-------|
| 승률 | 40.0% (12/30) | 60.0% (18/30) | **+20.00pp** |
| 평균 턴 수 | 22.1 | 43.8 | +21.7 |
| LLM 호출/배틀 | 69.6 | 31.1 | -38.5 |
| Prompt Tokens/배틀 | ~144,562 | 65,672 | -78,890 |
| Completion Tokens/배틀 | ~4,358 | 504 | -3,854 |

### EXP-008 (io baseline) 대비 비교

| 지표 | EXP-008 (io baseline) | EXP-010 (io flags+calcs) | Delta |
|------|----------------------|--------------------------|-------|
| 승률 | 20.0% (6/30) | 60.0% (18/30) | **+40.00pp** |
| 평균 턴 수 | 58.6 | 43.8 | -14.8 |
| LLM 호출/배틀 | 33.0 | 31.1 | -1.9 |
| Prompt Tokens/배틀 | 70,590 | 65,672 | -4,918 |

### EXP-009 (io flags-only) 대비 비교

| 지표 | EXP-009 (io flags-only) | EXP-010 (io flags+calcs) | Delta |
|------|------------------------|--------------------------|-------|
| 승률 | 46.7% (14/30) | 60.0% (18/30) | **+13.33pp** |
| 평균 턴 수 | 44.6 | 43.8 | -0.8 |
| LLM 호출/배틀 | 29.3 | 31.1 | +1.8 |
| Prompt Tokens/배틀 | 61,212 | 65,672 | +4,460 |

## 분석

### 핵심 발견
`io` 프롬프트 알고리즘에 `--enable_dynamic_flags --enable_dynamic_calcs`를 동시에 추가하면 EXP-009(io flags-only, 46.7%) 대비 **+13.33pp**, EXP-008(io baseline, 20.0%) 대비 **+40.00pp**의 상당한 승률 향상이 관찰됩니다. 또한 동일 flags+calcs 조건의 minimax(EXP-006, 40.0%) 대비 **+20.00pp** 높은 승률을 기록했습니다.

### 원인 분석
1. **Calcs의 추가 기여**: EXP-009(io flags-only, 46.7%) → EXP-010(io flags+calcs, 60.0%)로 +13.33pp 개선은 dynamic calcs가 io 알고리즘에서 추가적인 의사결정 정보로 작동함을 보여줍니다. 이는 minimax에서 calcs 추가가 승률을 하락시킨 것(EXP-005→EXP-006, -30pp)과 대조적입니다.
2. **minimax vs io 구조 차이**: minimax에서는 flags+calcs가 트리 탐색 중 노이즈로 작용하여 EXP-004(90.0%) → EXP-006(40.0%)로 -50pp 하락을 유발했지만, io에서는 같은 정보가 직접적인 의사결정 보조로 활용되어 승률이 크게 향상되었습니다.
3. **토큰 효율**: 평균 prompt tokens(65,672)는 EXP-008(70,590) 대비 감소했으며, completion tokens(504)는 낮게 유지되었습니다. io 알고리즘의 낮은 completion tokens는 출력이 간결함을 의미합니다.
4. **LLM 호출 효율**: 평균 31.1 LLM 호출/배틀은 minimax(EXP-006, 69.6/판)의 절반 이하로, io 알고리즘의 효율성을 보여줍니다.

### 다음 단계
- EXP-011에서 `--enable_showdown_oracle` 추가 효과 측정 (모든 flags 활성화)
- io+flags+calcs 조합이 EXP-004(minimax baseline, 90.0%) 대비 어느 정도 격차가 있는지 종합 평가
- io 알고리즘에서 flags/calcs가 효과적이지만 minimax baseline에는 미치지 못하는 원인 심층 분석
