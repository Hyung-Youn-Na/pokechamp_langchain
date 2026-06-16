# EXP-033 (minimax / GLM-5.1) 실험 분석

> 분석 일시: 2026-06-15
> EXP-033: 2026-06-12, `ollama/glm-5.1:cloud`, **minimax** (depth=2), **30전** vs abyssal (휴리스틱 `AbyssalPlayer`)
> 비교 1차: EXP-032 (io, GLM-5.1, 30전) — 동일 모델·상대·시드, **알고리즘만 io↔minimax** 다른 단일변수 ablation
> 비교 2차: EXP-001 (minimax, deepseek-v4-flash, 30전) — 동일 알고리즘, **모델만** 다른 단일변수 ablation

> ⚠️ **데이터 무결성 경고**: `summary.avg_turns`(28.9) 와 `battles[].won`(전부 1로 기록, sum=30)/`battles[].turns`({27,30}만) 가 손상. 원인은 `scripts/battles/local_1v1.py:347-350` 의 per-battle 기록 버그 (EXP-032 분석에서 동일 규명). 본 보고서의 **승률·턴 수·구간값은 30개 HTML 리플레이 파싱(`|faint|`/`|turn|`) ground truth** 사용. `summary.win_rate`/`summary.wins`(24/30=80.0%) 은 `player.n_won_battles` 카운터 기반이라 **정확** (검증 완료).
>
> ⚠️ **상대 정체**: `config.opponent_backend=gemini-2.5-pro`/`opponent_algorithm=io` 는 **사용되지 않는 CLI 기본값 echo** (`team_util.py:307` 의 `abyssal` 분기 → `AbyssalPlayer` 휴리스틱 반환, backend/algo 무시). llm_log(1,751건)이 pokechamp 호출만 기록하는 것이 확인.

---

## 1. 실험 결과 비교

### 1.1 승률

출처: 30개 HTML 리플레이 ground truth + `summary`. 구간값은 실제 `|turn|` 최댓값 기준.

| 구간 | EXP-033 (minimax, 본) | EXP-032 (io) | EXP-001 (minimax+deepseek) | 변화 (vs io) |
|------|------------------------|--------------|----------------------------|--------------|
| **전체** | **80.0% (24/30)** | 53.3% (16/30) | 83.3% (25/30) | ⬆ +26.7pp |
| 짧은 배틀 (<15턴) | 80.0% (4/5) | — (0전) | 100.0% (2/2) | — |
| 중간 배틀 (15-24턴) | 78.9% (15/19) | 64.3% (9/14) | 94.4% (17/18) | ⬆ +14.6pp |
| 긴 배틀 (25+턴) | **83.3% (5/6)** | 🔴 43.8% (7/16) | 60.0% (6/10) | ⬆ +39.5pp |
| 실제 평균 턴 | 19.9 (min9/max30) | 26.5 (min16/max41) | 21.5 (min10/max32) | ⬇ -6.6턴 |

> **minimax 는 구간 무관 78~83% 로 붕괴가 없다.** io 가 장기전(25+턴)에서 43.8%로 무너진 것과 대조적. 이것이 io→minimax 전체 승률 격차(+26.7pp)의 핵심이며, 장기전 구간에서만 +39.5pp 로 집중된다.
> 모델 비교(EXP-001 vs 본): 동일 minimax 알고리즘에서 glm-5.1(80.0%) ≈ deepseek-v4-flash(83.3%), **-3.3pp(노이즈 내)**. 단 deepseek-flash 는 mid(94.4%)에서 강하지만 long(60.0%)에서 약하다 — 단 long 표본이 작아(6/10, 5/6) 참고용. 결론: **알고리즘이 승률을 지배하고, 모델 선택은 부차적**이다.
> `summary.avg_turns` 는 EXP-033=28.9, EXP-032=39.0, EXP-001 도 추정 손상 — 모두 리플레이 실제값(19.9/26.5/21.5)로 대체.

### 1.2 리소스 사용량

출처: `summary.avg_*` (llm_calls/tokens delta 기반, 정확) + 실제 턴.

| 항목 | EXP-033 (minimax) | EXP-032 (io) | 변화율 |
|------|--------------------|--------------|--------|
| 배틀당 LLM 호출 | 61.0건 (min15/max120) | 31.2건 (min19/max49) | ⬆ +96% |
| 턴당 LLM 호출 | ~3.07건 (트리 탐색) | ~1.18건 | ⬆ +160% |
| 배틀당 prompt 토큰 | 116,837 | 65,221 | ⬆ +79% |
| 배틀당 completion 토큰 | 9,558 | 2,777 | ⬆ +244% |
| 배틀당 총 토큰 | ~126,400 | ~68,000 | ⬆ +86% |
| JSON 파싱 실패 | 0건 (json_decode 실패 11건=0.63%) | 0건 | — |

> minimax 는 턴당 ~3회(leaf evaluation 포함 트리 탐색)로 io(~1.18)의 2.6배 탐색한다. 이 추가 탐색이 **장기전 의사결정 품질 유지**(붕괴 없음)의 직접 원인. 비용은 io 대비 토큰 +86%, 호출 +96%.
> 호출 분산이 크다(min 15 / max 120): 결정적 승리는 15회로 충분(698 배틀), 구조적 열세 포지션은 120회까지 깊이 탐색(719 배틀). 2.2절 참조.

### 1.3 (minimax 전용) 탐색 메트릭

출처: `llm_log.jsonl` 1,751건. minimax 호출은 (a) 상대 액션 예측(system_prompt: "predicting the action that the opposing battler will use") 과 (b) 우리 액션 선택("You can choose to take a move or switch") 이 교대·누적된 트리 탐색 로그.

| 항목 | EXP-033 |
|------|---------|
| 총 LLM 호출 | 1,751건 / 30배틀 (평균 60.4) |
| 턴당 평균 호출 | ~3.07건 |
| 호출 범위(배틀당) | 15 ~ 120 |
| leaf action 제안(move/switch) | move 326 / switch 208 (61% / 39%) |
| 메타 결정(`choice`) | `{choice:"minimax"}` / `{choice:"damage calculator"}` — 평가 방법 선택 단계 존재 |
| 파싱 실패 | 0건 / 1,751 (0.00%) |

> leaf action 분포의 move/switch 비율(61/39)은 탐색 트리 전체의 가지 비율이지 최종 결정이 아님(io 보고서 1.3 의 최종 결정 65/35 와 직접 비교 불가).
> `{choice: minimax/damage calculator}` 메타 단계: 각 턴 시작에 전체 minimax 트리 탐색 vs 단순 데미지 계산 중 어느 쪽으로 평가할지 결정한다. 이는 비용·정확도 트레이드오프를 런타임에 조절하는 메커니즘.

---

## 2. 핵심 발견

### 2.1 결정적 차이: 승률은 "알고리즘"이 지배한다

두 개의 단일변수 ablation 이 승률 결정 인자를 분리한다 (규칙 6.2):

| 비교 | 변수 | 결과 | 해석 |
|------|------|------|------|
| EXP-033(minimax) vs EXP-032(io) | **알고리즘** (모델=GLM-5.1 동일) | 80.0% vs 53.3% (**+26.7pp**) | 알고리즘이 결정적 |
| EXP-033(glm-5.1) vs EXP-001(deepseek-flash) | **모델** (알고리즘=minimax 동일) | 80.0% vs 83.3% (**-3.3pp**) | 모델은 부차적(노이즈 내) |

동일 GLM-5.1 이 io 로는 53%, minimax 로는 80% 에 도달 → **GLM-5.1 능력 한계가 아니라 io 알고리즘의 한계**. 반대로, 동일 minimax 에서 모델을 바꾸면(glm-5.1↔deepseek-flash) ±3.3pp 내외로 거의 동일. 즉 현재 병목은 모델이 아니라 **프롬프트 알고리즘**이며, minimax 가 그 병목을 해소한다.

### 2.2 가설 / 인과 추론: minimax 의 트리 탐색이 장기전 붕괴를 없앤다

EXP-032(io) 의 핵심 약점은 장기전(25+턴) 43.8% 붕괴였고, 그 기전은 *"턴 단위 안전한 수에 갇혀 win-condition 을 계획하지 못하는 것"* (Pain Split 7턴 루프, Wish/Protect 스톨). EXP-033 은 동일 구간 **83.3%** 로 이 붕괴가 소멸한다. 인과 메커니즘:

1. **트리 탐색이 수동 라인의 비수렴을 탐지**: io 는 직전 턴만 보고 "가장 안전한 수"를 고른다. minimax 는 depth=2 로 결과를 펼쳐 평가하므로, *"이 수동 라인이 KO 로 수렴하지 않고 상대 회복/피벗에 갇힌다"* 는 것을 leaf evaluation 이 포착한다.
2. **결정적 승리의 효율성**: 단기 승리(698: 9턴, my_faint=0, **15 호출**)는 minimax 가 승선을 빠르게 식별함을 보여준다. t1 reasoning: *"Iron Valiant is a massive threat to Weavile with its 4x super-effective Fighting-type moves"* — 정확한 위협 평가 후 최소 탐색으로 수렴.
3. **탐색량이 포지션 난이도에 비례**: 승리 평균 54.2 calls, 패배 평균 75.0 calls. minimax 는 어려운 포지션에서 더 깊이 탐색한다 — 즉 패배는 "탐색 부족"이 아니라 "구조적으로 극복 불가한 포지션" (2.3절).

> 인과에 가까운 추론: io→minimax 가 단일 변수이므로 장기전 붕괴 소멸은 알고리즘 변경에 기인. 단, 알고리즘 변경이 프롬프트 본문(leaf evaluation system prompt) 변경을 수반하므로 완전한 통제는 아님.

### 2.3 미해결 문제: 6패는 "탐색 실패"가 아니라 "구조적 팀/매치업 드로우"

패배 6전 분석(전부 my_faint=6 전멸, opp 평균 3.50 KO):

| 배틀 | 턴 | opp KO | 탐색 | pokechamp 팀 | 진단 |
|------|----|--------|------|--------------|------|
| 699 | 21 | 🔴 **1** | 87 | Dondozo/Weezing/Toxapex/Iron Treads/Blissey/Alomomola (**순수 스톨**) | **스톨 미러**(상대 Quagsire=Unaware/Blissey/Toxapex) — 브레이커 없음 |
| 720 | 13 | 3 | 64 | Lokix/Pecharunt/Zamazenta/Ting-Lu/Latios/Gliscor | t1 리드 Zamazenta 가 Iron Jugulis Hurricane+Quark Drive 에 KO → 모멘텀 상실 |
| 719 | 29 | 5 | **120** | Ting-Lu/Weezing/Alomomola/Tornadus-T/Gholdengo/Zamazenta | 강공팀(Garchomp/Darkrai/Deoxys)에 5KO 접전패 (최대 탐색) |
| 697/711/712 | 19~23 | 3~5 | 59~76 | (스톨/밸런스) | 매치업·페이즈 누적 |

- **battle 699 (1 KO, 87 탐색)**: reasoning 에서 minimax 가 정확히 *"Quagsire has Unaware, setting up is useless. Seismic Toss does consistent damage that Unaware cannot ignore"* 라고 판단. 즉 **탐색 품질은 정상**이나, 순수 스톨 팀(브레이커 없음)이 동급 수비팀(Unaware Quagsire)을 만나 **구조적으로 승선이 존재하지 않는다**. 87회 탐색해도 답이 없는 것은 탐색 실패가 아니라 포지션 자체의 한계.
- **battle 720 (13턴 빠른 붕괴)**: 리드 매치업 불리(Zamazenta vs Iron Jugulis)로 t1 KO 후 회복 불가. `enable_llm_lead_selection=False` 로 리드가 무작위.

→ **대조 (EXP-032 io 패배)**: io 의 패배는 *결정적 의사결정 실패*(수동 스톨 루프·win-con 부재)였다. minimax 의 패배는 *팀/매치업 드로우 실패*다. minimax 는 의사결정 품질을 올렸지만, **팀 구성·리드 선택** 영역의 한계는 남아 있다. 이 한계는 다른 gen9ou 상대(LLM/human/ladder)에도 동일히 적용되므로 범용 개선 대상이다 (6.1 준수).

---

## 3. 문제점 분석

### 🔴 P0-1: 불리한 팀/매치업 드로우에서 자력 회복 불가 (6패의 원인)

| 항목 | EXP-033 (minimax) | EXP-032 (io) |
|------|--------------------|--------------|
| 패배 시 opp 평균 KO | 3.50 (1,3,3,4,5,5) | 3.79 |
| 패배 시 탐색량 | 75.0 calls (승리 54.2 대비 +38%) | — |
| 패배 유형 | 구조적 팀/매치업 드로우 | 결정적 의사결정 실패(수동 루프) |

패배 6전 중 스톨 미러(699), 리드 KO(720), 강공팀 상대 접전패(719) 등이 **탐색량(최대 120)에도 불구하고 발생**. minimax 가 의사결정을 향상시켰으나, 팀 로딩(`get_metamon_teams("gen9ou","competitive")`) 과 리드 선택이 무작위라 구조적 열세를 자력으로 뒤집지 못한다.

**근본 원인:** (a) `enable_llm_lead_selection=False` — 리드가 매치업을 고려하지 않음(720 의 t1 KO 직결). (b) 로드된 팀이 win-condition(브레이커/스위퍼)을 보장하지 않음(699 의 순수 스톨).
**개선 방안 (범용, 6.1 준수):**
- **LLM 리드 선택 활성화**(`enable_llm_lead_selection=True`): 팀 preview 에서 상대 예측 리드 대비 유리한 리드 선택. 모든 gen9ou 상대에 전이되는 t1 모멘텀 확보 (기존 EXP-017/019 는 io+gemma4 에서 혼합 결과 — minimax+GLM-5.1 조합에서 재검증 필요).
- 팀 소스 평가: metamon 팀이 win-condition(설정 스위퍼/Taunt+설정 브레이커)을 포함하는지 점검. 스톨 미러 회피.

### 🟡 P1-1: 실험 데이터 무결성 버그 (avg_turns / battles[].won 체계적 손상)

| 항목 | JSON 값 | 실제값(리플레이) |
|------|--------|------------------|
| `summary.avg_turns` | 28.9 | **19.9** |
| `battles[].turns` | {27,30} | 9~30 (다양) |
| `battles[].won` 합 | 30 (전부 1) | **24** (= summary.wins, 정확) |

**근본 원인:** `scripts/battles/local_1v1.py:347-350` — `b.turn` 최댓값 배틀을 "latest" 로 잘못 선택 (EXP-032 분석 P1-2 와 동일). `summary.wins/win_rate`(`player.n_won_battles` 카운터, L384-386)·`llm_calls`/tokens(delta)는 정확.
**개선 방안:** L344-353 을 `battle_against` 종료 후 신규 tag 추적 로직으로 수정. 이 지표에 의존하는 모든 과거/향후 실험의 `avg_turns` 신뢰성에 영향.

### 🟢 P2-1: 탐색 비용 분산 및 json_decode 실패

| 항목 | EXP-033 |
|------|---------|
| 호출 범위(배틀당) | 15 ~ 120 (8배 차이) |
| json_decode 실패 | 11건 / 1,751 (0.63%) |

max 120 calls 배틀(719) 은 깊이 탐색해도 패배 — 비용 대비 효과가 낮은 극단 포지션. 비용 상한(budget cap) 도입 시 이런 포지션의 탐색이 조기 절단되어 자원 절약 가능하나, 동시에 희망적 포지션의 깊이 탐색도 잘릴 수 있어 트레이드오프. json_decode 11건은 io(0) 대비 미세 증가이나 탐색량 2배를 고려하면 무시 가능 수준.

**개선 방안 (범용):** 턴/포지션 기반 적응적 탐색 깊이(리드 차이·HP 차이가 크면 얕게, 밸런스 포지션은 깊게). 영향 미미.

---

## 4. 이전 실험 대비 개선 현황

| 이슈 | EXP-032 (io) | EXP-031 (react) | EXP-033 (minimax, 본) | 상태 |
|------|--------------|-----------------|------------------------|------|
| 장기전(25+) 붕괴 | 🔴 43.8% | (패 7전 전멸) | ✅ **83.3%** | **해결** (트리 탐색) |
| win-condition 계획 | 🔴 부재 (수동 루프) | 🟡 부분 | ✅ 트리 기반 수렴 탐지 | 해결 |
| JSON 파싱 실패 | ✅ 0건 | 🟡 4건 | ✅ 0건 (json_fail 11=0.63%) | 해결 |
| 전체 승률 | 53.3% | 76.7% | **80.0%** | 최고 (EXP-001 minimax 83.3% 에 근접) |
| 단기 결정적 승리 | — | — | ✅ 698: 9턴/0손실/15호출 | 강점 |
| 팀/매치업 드로우 대응 | — | — | 🔴 6패 = 구조적 열세 | 미해결 (P0-1) |
| 데이터 무결성(avg_turns) | 🔴 손상 | — | 🔴 손상 (동일 버그) | 미해결 (P1-1) |

출처: 본 EXP 데이터 + `docs/analysis/exp-032-io-glm51-analysis.md` + `docs/analysis/exp-031-react-glm51-analysis.md`. minimax 는 io·react 의 의사결정 계열 약점을 해결하고 최고 승률(80%)을 기록했으나, 팀/리드 선택 계열 한계는 미해결로 남았다.

---

## 5. 권장 개선 우선순위

| 순위 | 문제 | 근거 | 난이도 | 예상 효과 |
|------|------|------|--------|-----------|
| 1 | **LLM 리드 선택 활성화** (P0-1) | 720 의 t1 리드 KO, 6패 중 매치업 불리 다수; 모든 상대에 전이 | 낮 (기존 flag ON) | t1 모멘텀 확보, 단기 승률 ↑ |
| 2 | 팀 win-condition 점검 (P0-1) | 699 스톨 미러(브레이커 부재), 1KO 패 | 중 | 불리 드로우 회피, 최악 패 감소 |
| 3 | 데이터 무결성 버그 수정 `local_1v1.py:347` (P1-1) | avg_turns 체계적 손상, 3개 실험(EXP-001/032/033) 확인 | 낮 | 향후 avg_turns 신뢰성 회복 |
| 4 | 적응적 탐색 깊이 (P2-1) | max 120 calls 포지션, 비용 분산 8배 | 중 | 비용 절감(효과 미미) |

> 모든 권고는 범용 gen9ou 전략 관점(ANALYSIS_MANUAL.md 6.1·6.5절). LLM 리드 선택·팀 밸런스·데이터 신뢰성은 LLM agent/human/ladder 모든 상대에 동일 적용. abyssal 특화 공략 없음.

---

## 6. 다음 단계

### 즉시
- [ ] (사용자 실행) minimax + GLM-5.1 + **`enable_llm_lead_selection=True`** ablation 실행 (baseline=EXP-033, 변수 1개=리드 선택) — seed 42, N=30, 동일 opponent
- [ ] `scripts/battles/local_1v1.py:344-353` 종료 배틀 tag 추적 로직으로 수정 (P1-1) [EXP-033]

### 코드 수정 후
- [ ] `local_1v1.py` 수정 후 임의 실험 1개 재실행 → `avg_turns` 가 리플레이 `|turn|` 최댓값과 일치 검증 (회귀 테스트)

### 후속 실험
- [ ] **리드 선택 ablation** (위 즉시 항목) — 목표: 승률 80%→85%+, 단기/중간 구간 승률 80%→85%+, t1 KO 유발 패 감소
- [ ] (규칙 6.2) 알고리즘·모델·상대·시드·N 동일, 리드 선택만 ON
- [ ] 장기 목표: minimax 기반 90%+ 도달 가능성 확인 (현재 80%, 병목이 팀/리드로 이동했으므로 해당 영역 개선이 다음 열쇠)
