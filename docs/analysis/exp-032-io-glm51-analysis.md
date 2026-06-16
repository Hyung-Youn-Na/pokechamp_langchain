# EXP-032 (io / GLM-5.1) 실험 분석

> 분석 일시: 2026-06-15
> EXP-032: 2026-06-12, `ollama/glm-5.1:cloud`, **io**, **30전** vs abyssal (휴리스틱 `AbyssalPlayer`)
> 비교 1차: EXP-033 (minimax, GLM-5.1, 30전) — 동일 모델·상대·시드, **알고리즘만 io↔minimax** 다른 단일변수 ablation
> 비교 2차: EXP-011 (io, GLM-5.1, 30전, 2026-06-05) — 동일 설정 재실행 (재현성 검증)

> ⚠️ **데이터 무결성 경고 (본 보고서 전체에 영향)**: `experiment_*.json` 의 `summary.avg_turns`(39.0) 와 `battles[].won`/`battles[].turns` 필드가 **손상**되어 있다. 원인은 `scripts/battles/local_1v1.py:347-350` 의 per-battle 기록 버그(방금 끝난 배틀이 아닌 `b.turn` 최댓값 배틀을 "latest"로 선택). 본 보고서의 **승률·턴 수·구간 승률은 모두 30개 HTML 리플레이를 직접 파싱(`|faint|`/`|turn|` 마커)한 ground truth**를 사용한다. 단, `summary.win_rate`/`summary.wins` 는 `player.n_won_battles` 카운터 기반이라 **정확**하다(검증 완료). 상세는 3.x P1-2.
>
> ⚠️ **상대 정체 정정**: `config.opponent_backend=gemini-2.5-pro`, `opponent_algorithm=io` 는 **사용되지 않는 CLI 기본값의 echo**다. `get_llm_player`(`poke_env/player/team_util.py:307`) 에서 `name=="abyssal"` 분기는 `AbyssalPlayer`(휴리스틱, LLM 없음)을 반환하며 backend/algo 인자를 무시한다. llm_log(937건 ≈ 31.2×30)이 pokechamp 호출만 기록하는 것이 이를 확인한다. (EXP-031 보고서의 "vs abyssal (gemini-2.5-pro, io)" 표기는 config echo를 실제 동작으로 오독한 것.)

---

## 1. 실험 결과 비교

### 1.1 승률

출처: 30개 HTML 리플레이 파싱(ground truth) + `experiment_*.json summary`. 모든 구간값은 리플레이의 실제 `|turn|` 최댓값 기준.

| 구간 | EXP-032 (io, 본) | EXP-033 (minimax) | EXP-011 (io) | 변화 (vs EXP-033) |
|------|------------------|--------------------|--------------|-------------------|
| **전체** | **53.3% (16/30)** | **80.0% (24/30)** | 53.3% (16/30) | ⬇ −26.7pp |
| 짧은 배틀 (<15턴) | — (0전) | 80.0% (4/5) | — (0전) | — |
| 중간 배틀 (15-24턴) | 64.3% (9/14) | 78.9% (15/19) | 62.5% (10/16) | ⬇ −14.6pp |
| 긴 배틀 (25+턴) | 🔴 **43.8% (7/16)** | 83.3% (5/6) | 42.9% (6/14) | ⬇ −39.5pp |
| 실제 평균 턴 | 26.5 (min16/max41) | 19.9 (min9/max30) | 28.6 (min16/max117) | ⬇ +6.6턴 더 김 |

> io+GLM-5.1 은 **장기전(25+턴)에서만 붕괴**(43.8%)하며, 중간 구간(64.3%)에서는 양호하다. EXP-011 도 동일 시그니처(long 42.9%)로, 이는 io+GLM-5.1 의 **안정적 약점 패턴**이다. 반면 minimax 는 구간 무관 78~83%로 붕괴가 없다. 이 격차(long −39.5pp)가 io→minimax 전체 승률 격차(−26.7pp)의 주원인이다.
> `summary.avg_turns` 는 EXP-032=39.0, EXP-033=28.9 로 **둘 다 손상**. 실제값은 위 표(26.5 / 19.9).

### 1.2 리소스 사용량

출처: `summary.avg_*` (llm_calls/tokens 필드는 delta 기반이라 정확) + 실제 턴(리플레이). 턴당 호출 = avg_llm_calls ÷ 실제 평균 턴.

| 항목 | EXP-032 (io) | EXP-033 (minimax) | 변화율 |
|------|--------------|--------------------|--------|
| 배틀당 LLM 호출 | 31.2건 | 61.0건 | ⬇ io 가 −49% |
| 턴당 LLM 호출 | ~1.18건 | ~3.07건 | ⬇ io 가 −61% |
| 배틀당 prompt 토큰 | 65,221 | 116,837 | ⬇ −44% |
| 배틀당 completion 토큰 | 2,777 | 9,558 | ⬇ −71% |
| 배틀당 총 토큰 | ~68,000 | ~126,400 | ⬇ −46% |
| **JSON 파싱 실패** | **0건 / 937 (0.00%)** | (해당 없음*) | — |

*minimax 는 leaf evaluation 이라 별도 파싱 실패 메트릭 없음. io 의 0% 파싱 실패는 **강점**이다 (EXP-027 react 69% → EXP-031 react 4건 대비). 단, 파싱 안정성이 곧 승률로 이어지지는 않는다.

### 1.3 (io 전용) 액션 분포

출처: `llm_log.jsonl` 937건의 `parsed_action` (JSON 문자열) 파싱. minimax 의 move/switch 비율은 leaf evaluation 이라 최종 결정이 아니어서 비교에서 제외.

| 항목 | EXP-032 (io) | 비율 |
|------|--------------|------|
| 공격(move) | 608건 | 65.0% |
| 교체(switch) | 328건 | 35.0% |
| 파싱 실패/기타 | 0건 | 0.0% |

> 교체율 35% 는 다소 높으나, **승패를 구분하지는 않는다** (승리 배틀 683: 37%, 663: 30% vs 패배 681: 27%, 690: 32%). 차별점은 교체 빈도가 아니라 **무브 선택의 결정성**(3.x P0-1).
> 상위 교체 대상: tinglu(40), gliscor(28), zamazenta(25), gholdengo(16), clefable(16) — 방어형 벽 포켓몬으로의 회피적 교체가 주도.
> 상위 무브: earthquake(66), flipturn(29), moonblast(29), knockoff(28), shadowball(20), **painsplit(19), ruination 반복 사용**, uturn(19), whirlwind(16) — 비율/고정 데미지기(ruination, painsplit)와 피벗(flipturn/uturn)·페이즈(whirlwind) 비중이 높다.

---

## 2. 핵심 발견

### 2.1 결정적 차이: io 는 장기전에서만 붕괴한다 (모델이 아니라 알고리즘이 병목)

EXP-032(io) 와 EXP-033(minimax) 는 **모델(GLM-5.1)·상대(abyssal 휴리스틱)·시드(42)·N(30)·temperature(0.3)·모든 `enable_*` 플래그(OFF)** 가 동일하고, **프롬프트 알고리즘만 다르다** (규칙 6.2 만족 단일변수 ablation). 결과:

- 전체 승률 53.3% → 80.0% (**+26.7pp**)
- 장기전 승률 43.8% → 83.3% (**+39.5pp**, 격차의 핵)
- 평균 턴 26.5 → 19.9 (더 빠른 승리)

동일 모델이 io 로는 53%에 머물고 minimax 로는 80%에 도달한다. 즉 **GLM-5.1 의 능력 한계가 아니라 io 알고리즘의 한계**다. io 의 붕괴는 구간에 국한된다 — 중간 구간(64.3%)에서는 minimax(78.9%)와 14.6pp 차이로 비교적 근접하지만, 장기전(25+턴)에서만 39.5pp 로 벌어진다.

### 2.2 가설 / 인과 추론: io 는 "턴 단위 최적"에 갇혀 win-condition 을 계획하지 못한다

정성 분석(뷰어 + `llm_log` reasoning)이 장기전 붕괴의 기전을 명확히 보여준다:

| 배틀 | 결과 | late-game 행동 | reasoning 핵심 |
|------|------|----------------|----------------|
| **681** | 패 (41턴, opp 5KO 후 전멸) | t35-38: `tickle→tickle→wish→protect` (무공격 스톨), t39 에서야 `flipturn` 킬각 인식 | t35: *"Wish heals Alomomola next turn and pairs well with Protect, while Tickle lowers Vigoroth's Attack"* — 버티기만 추구 |
| **690** | 패 (36턴, opp 5KO 후 전멸) | t13-t19: **`painsplit` 7턴 연속** | t18: *"Garchomp is trapped... Pain Split a safe option to drain its HP while it slowly dies to burn"* — 유리함을 전환하지 못하고 7턴 방치 |
| **683** (대조) | 승 (16턴) | t1: `ivycudgel` (리드 킬), t15: `flamethrower`/`icespinner` (킬각 커밋) | t1: *"knocking out the opponent's lead is more valuable"* / t15: *"Flamethrower will cleanly KO it for the win"* |
| **663** | 승 (37턴) | calm-mond blissey 셋업 + shadowball 로 스톨 압승 | 긴 배틀도 셋업→스윕이 있으면 승리 (장기전이 100% 패가 아닌 이유) |

**기전**: io+GLM-5.1 은 각 턴의 "가장 안전한 수"(Wish/Protect, Pain Split, 페이즈)에 최적화된다. 초반·유리한 매치업에서는 공격적으로 커밋해 빠른 승리(683)로 이어지지만, 중후반 그라인드 상황에서는 **안전한 per-turn 수가 승리로 수렴하지 않는 함정**에 빠진다. Pain Split 7턴 루프(690), Wish/Protect/Tickle 스톨(681) 은 "잃지 않는 수"의 국소 최적에 갇힌 사례다. 상대가 회복·피벗·상태이상으로 버티거나 마비·급소 한 방이 터지면 방어적 라인이 붕괴해 전멸한다.

**왜 minimax 는 이걸 해결하는가**: minimax 는 leaf evaluation 으로 **결과 트리**를 평가한다. 수동 라인이 승리로 수렴하지 않음(또는 상대 회복에 갇힘)을 트리에서 인식하고, 킬로 수렴하는 가지를 선택한다. 이것이 구간 무관 78~83% 의 원인으로 추정된다. (io→minimax 가 단일 변수이므로, 위 추론은 강한 인과에 가깝다 — 단, 프롬프트 본문도 algo 별로 달라 완전한 통제는 아님.)

### 2.3 미해결 문제

- **데이터 무결성 버그**(3.x P1-2): `summary.avg_turns` 가 체계적으로 손상되어, 이 지표에 의존하는 모든 과거 분석/비교(EXP 인덱스의 턴 수 포함)가 재검증 대상이다.
- **특수 데미지기 의존**(3.x P2-1): ruination/painsplit/seismictoss 를 회복·회피 목적으로 반복 사용하는 패턴이 승률을 깎는 주범은 아니나, win-con 부재와 시너지해 장기전을 유발한다.

---

## 3. 문제점 분석

### 🔴 P0-1: 장기전(25+턴) 붕괴 — win-condition 인식·커밋 부재

| 항목 | EXP-032 (io) | EXP-033 (minimax) |
|------|--------------|--------------------|
| long(25+) 승률 | 🔴 43.8% (7/16) | 83.3% (5/6) |
| mid(15-24) 승률 | 64.3% (9/14) | 78.9% (15/19) |
| 평균 턴 | 26.5 | 19.9 |
| 패배 14전 패턴 | 전원 전멸(my_faint=6), opp 평균 **3.79** KO 달성 후 탈락 | — |

패배 14전은 **전부 my_faint=6**(완전 전멸)이며, 평균 3.79마리(최대 5)만 잡고 6마리가 쓰러진다. 즉 "거의 이기 직전"까지 가고도 마지막 1~2킬을 마무리하지 못한다. reasoning 증거:
- 681 t35-38: 무공격 스톨(tickle/wish/protect), t39 에서야 킬각 인식 → 시점 지연.
- 690 t13-19: Pain Split 7턴 루프 — *"slowly dies to burn"* 전략이 상대 회복/피벗에 무력화.

**근본 원인:** io 알고리즘은 단일 턴의 안전성만 최적화하고, 다수 턴에 걸친 **승리 수렴(win-condition) 계획**이 없다. 안전한 per-turn 수가 승리로 이어지지 않는 함정을 탐지할 lookahead 가 부재하다.

**개선 방안 (범용, 6.1 준수):**
- io 시스템 프롬프트(`pokechamp/prompts.py` L1054-1076)에 **win-condition 가이드** 추가: "현재 라인이 KO 로 수렴하는가? 회복·피벗 루프에 갇혀 있지 않은가?" 자문 단계. 단순 "안전한 수" 선택 지양.
- 근본 해법은 **minimax 로의 전환**(이미 +26.7pp 검증). io 유지 시엔 프롬프트 수준의 완화만 가능.

### 🟡 P1-1: 반복 수 루프 탈출 불가 (Pain Split ×7)

| 항목 | EXP-032 |
|------|---------|
| 동일 무드 연속 사용 | battle 690: `painsplit` t13-t19 (7턴), battle 663: `shadowball` t16-19 (4턴) |

io 가 동일 수를 연속 선택하며 국소 최적(stall)에서 빠져나오지 못한다. 턴 단위 평가에서는 같은 상황이 같은 수를 내기 때문이다.

**근본 원인:** 상태 전이(history) 없는 마르코프적 턴 평가. 이전 턴에 같은 수를 써도 진전이 없었으면 대안을 시도하는 메커니즘 부재.
**개선 방안 (범용):** 직근 N턴의 행동 이력을 프롬프트에 포함해 "같은 수 반복 시 진전 부족" 인지 유도; 또는 동일 수 3회 연속 시 대안 강제(heuristic fallback). — 모든 gen9ou 상대에 전이되는 회피 반복 개선.

### 🟡 P1-2: 실험 데이터 무결성 버그 (avg_turns / battles[].won 체계적 손상)

| 항목 | JSON 값 | 실제값(리플레이) |
|------|--------|------------------|
| EXP-032 `summary.avg_turns` | 39.0 | **26.5** |
| EXP-032 `battles[].turns` | {37,39,41} 단조 | 16~41 (19종) |
| EXP-032 `battles[].won` 합 | 18 | **16** (= summary.wins, 정확) |
| EXP-033 `summary.avg_turns` | 28.9 | **19.9** |

**근본 원인:** `scripts/battles/local_1v1.py:347-350`
```python
for tag, b in player.battles.items():
    if b.turn > latest_turn:   # ← 방금 끝난 배틀이 아니라 turn 최댓값 배틀을 "latest"로 선택
        latest_turn = b.turn; latest_battle = b
won = ... latest_battle.won ...
turns = latest_battle.turn ...
```
"방금 종료된 배틀"이 아니라 `player.battles` 전체 중 `b.turn` 이 가장 큰 배틀을 선택한다. 누적 최대 턴이 갱신될 때만 `turns`/`won` 이 바뀌므로, `turns` 는 단조 증가(37→39→41)하고 `won` 은 max-turn 배틀의 결과가 복사된다. 반면 `summary.wins`/`win_rate`(`local_1v1.py:384-386`)는 `player.n_won_battles`/`n_finished_battles` 카운터 기반이라 정확하고, `llm_calls`/`prompt_tokens`/`completion_tokens`(L354-356 delta)도 정확하다.

**개선 방안:** L344-353 을 `battle_against` 직후 종료된 배틀 tag 로 추적하도록 수정 (예: 루프 진입 전 `known_tags = set(player.battles)`, 종료 후 차집합으로 신규 tag 식별, 또는 `player.battles` 의 가장 최근 삽입 key 사용). 모든 향후 실험의 `avg_turns` 신뢰성 회복.

### 🟢 P2-1: 특수 데미지기의 회피·회복 용도 남용

ruination(50% HP), painsplit, seismictoss 가 킬이 아닌 **chip·회복·시간벌기** 목적으로 반복 선택된다(690 의 Pain Split 루프). EXP-031 분석에서 `calculate_damage` 가 이들을 "status move" 로 오분류하는 에러(react P0-1)로 지적된 바 있으나, io 모드에서는 도구 호출 없이 직접 선택되므로 에러는 없다 — 문제는 **선택 동기**(안전한 chip) 쪽이다.

**개선 방안 (범용):** win-condition 가이드(P0-1)와 동일선상. 비데미지기를 chip 용도로 과사용하지 않도록, "현재 라인이 KO 로 수렴하는가" 자문에서 점검.

---

## 4. 이전 실험 대비 개선 현황

| 이슈 | EXP-031 (react) | EXP-032 (io) | 상태 |
|------|-----------------|--------------|------|
| JSON 파싱 실패 | 🟡 4건 (json_parse_failures) | ✅ **0건/937 (0.00%)** | 해결 (io 파싱 안정) |
| 도구 호출 과다/무한루프 | 🔴 stopping-criteria 코드로 해결 | — (io 는 도구 미사용) | 해당 없음 |
| 특수 데미지기 처리 | 🔴 calculate_damage 158건 에러 | 🟢 에러 0건 (io 직접 선택) | 우회 (근본 미해결) |
| switch 토큰 파싱(`switch*`) | 🟡 18건 | ✅ 0건 (정상 switch 파싱) | 해결 |
| 장기전 결정력 | 🟡 미해결(패 7전 전멸) | 🔴 long 43.8%, 패 14전 전멸 | **미해결 (io 공통 약점)** |
| 승률 수준 | 76.7% | 53.3% | io < react |

출처: 본 EXP 데이터 + `docs/analysis/exp-031-react-glm51-analysis.md`. io 는 react 의 도구/파싱 계열 이슈가 전무하나, **승률은 react(76.7%)·minimax(80.0%) 에 크게 미달**한다. io 의 파싱 안정성은 장점이지만 알고리즘 한계(2.2절)가 더 크다.

---

## 5. 권장 개선 우선순위

| 순위 | 문제 | 근거 | 난이도 | 예상 효과 |
|------|------|------|--------|-----------|
| 1 | **minimax 채택** (P0-1 근본 해법) | 동일 모델에서 io 53.3% → minimax 80.0% (단일변수 +26.7pp 검증) | 낮 (설정 변경만) | 승률 53%→80%, 장기전 44%→83% |
| 2 | io 시스템 프롬프트 win-condition 가이드 (P0-1) | 장기전 43.8%, 690 Pain Split×7 / 681 스톨 루프 증거 | 중 | io 유지 시 장기전 승률 소폭 ↑, 반복 루프 감소 |
| 3 | 데이터 무결성 버그 수정 `local_1v1.py:347` (P1-2) | avg_turns 체계적 손상, 과거 비교 신뢰성 훼손 | 낮 | 모든 향후 실험 avg_turns 신뢰성 회복 |
| 4 | 반복 수 탈출(행동 이력 prompt) (P1-1) | 동일 수 7턴 루프 | 중 | stall 루프 빈도 ↓ |

> 모든 권고는 범용 gen9ou 전략 관점(ANALYSIS_MANUAL.md 6.1·6.5절). abyssal 특화 공략 없음. win-condition 계획·반복 탈출·데이터 신뢰성은 LLM agent·human·ladder 모든 상대에 동일 적용된다.

---

## 6. 다음 단계

### 즉시
- [ ] (사용자 실행) io 대신 **minimax** 로 동일 조건 재검증은 EXP-033 이미 완료 — 본 권고1 은 "EXP-033 결과로 io 한계 확인됨"의 정리. 새 실행 불필요.
- [ ] `scripts/battles/local_1v1.py:344-353` 종료 배틀 tag 추적 로직으로 수정 (P1-2) [EXP-032]
- [ ] (선택) io 시스템 프롬프트(`pokechamp/prompts.py:1054-1076`)에 win-condition 자문 단계 추가 후 io 단독 ablation 준비

### 코드 수정 후
- [ ] `local_1v1.py` 수정 후 임의 실험 1개 재실행 → `avg_turns` 가 리플레이 `|turn|` 최댓값과 일치하는지 검증 (회귀 테스트)

### 후속 실험
- [ ] win-condition 프롬프트 추가한 **io** ablation (baseline=EXP-032, 변수 1개) — 목표: 장기전 승률 43.8% → 55%+, 반복 수 루프 감소
- [ ] (규칙 6.2) 위 실험은 프롬프트만 변경, 알고리즘·모델·상대·시드·N 동일 유지
- [ ] 장기 목표: minimax 기반 90%+ (EXP-033 80% 에서 추가 개선), `avg_turns` 신뢰성 확보 후 구간별 재추적
