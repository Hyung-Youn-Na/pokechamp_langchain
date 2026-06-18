# Performance Improvement Experiment Context

> LLM agent(pokechamp)가 abyssal player 상대 **승률 90%+ 달성**을 위한 실험의 세션 간 컨텍스트 문서.
> 새 세션 시작 시 이 파일을 먼저 읽어 context를 복원하고, 섹션 0의 행동 규칙을 따르세요.

---

## 0. Agent 행동 규칙 (READ FIRST)

1. **범용 전략 우선 (★)**: abyssal의 특정 규칙 허점(matchup score 임계값, Tera 미고려 등)을 *직접 공략*하는 실험·코드 변경은 **금지**. 모든 개선안은 "이 변경이 다른 gen9ou 상대(다른 LLM agent, human, ladder)에게도 동일하게 도움이 되는가?"를 만족해야 함. 승률 90%는 **범용 gen9ou 전략 능력 향상의 결과**여야 함.
2. **EXP 번호 확인**: 새 실험 시작 전 반드시 [섹션 5](#5-실험-인덱스)에서 다음 EXP 순번을 확인.
3. **Baseline 우선**: EXP-001 baseline 미측정 상태면 어떤 ablation도 시작하지 않음.
4. **변경 1개 원칙**: ablation 시 baseline 대비 변수 1개만 변경. 다른 모든 조건은 baseline과 동일. **자동 검증**: [§8.4](#84-변경-1개-원칙-자동-검증-0-4) `scripts/exp/verify_single_change.py`.
5. **재현성**: 모든 실험에서 `--seed 42`, `--N 30` 이상. **ablation 비교 시 고정 팀 모드(`--team_mode fixed`) 우선** ★ — `--seed`는 첫 배틀만 재현한다(전역 RNG를 매 배틀마다 가변 소비하므로 2번째 배틀부터 팀이 달라짐). 고정 팀 모드는 player/opponent 매치업까지 완전 격리해 **승률 변화 = 코드 변경 효과**만 남긴다. 상세는 [§9](#9-고정-팀-모드-ablation-격리) · [`docs/architecture/fixed-team-mode.md`](docs/architecture/fixed-team-mode.md). 랜덤 팀 baseline(`baselines/`)은 최종 평균 성능 비교용으로 보존.
6. **코드 변경 동반 시**:
   - 커밋 메시지에 EXP-ID 포함 (예: `feat(prompt): macro_prompt to user [EXP-002]`)
   - 코드 상태(commit·argv·dirty patch)는 배틀 로그 `meta` 블록에 **자동 기록**됨 ([§8](#8-실험-코드파라미터-변경-자동-추적)). README 수동 해시 기록은 폐지(준수율 0%로 실패).
7. **로그 분리**: `--log_dir`로 실험 전용 디렉토리 지정. `./battle_log/one_vs_one` (기본값) 사용 금지.
8. **배틀 실행 금지 (★)**: `--N` 배틀 실행은 **에이전트가 직접 하지 않음**. 에이전트는 (a) 코드 변경, (b) 디렉토리/README 준비, (c) **실행 명령어 안내**까지만 담당. 사용자가 명령어를 직접 실행 후 결과를 알려주면 분석 진행.

---

## 1. 프로젝트 목표

- **Player**: `pokechamp` (LLM-backed minimax agent)
- **Opponent**: `abyssal` (heuristic baseline, LLM 없음)
- **Target**: 승률 ≥ 90% (battle_format: `gen9ou`)
- **달성 방식**: **범용 gen9ou 전략 능력 향상** (abyssal 특화 공략 금지 — 섹션 0-1 참조)

---

## 2. Abyssal Player 요약

**위치**: [poke_env/player/baselines.py](poke_env/player/baselines.py) — `AbyssalPlayer` 클래스

**결정 로직**:
1. `_estimate_matchup`: 타입 상성 + 스피드 + HP 비율 → 점수. 점수 `< -2`면 스위치.
2. 엔트리 해저드: 상대 필드 미설치면 setup, 내 필드 설치되어 있으면 제거.
3. 부스트 무브: HP 100% + 매치업 > 0 + 부스트 합 ≥ 2 + self 대상이면 setup.
4. 공격 선택: `base_power × STAB × 명중률 × 예상 타수 × 타입상성` 최대값.
5. Dynamax: 마지막 완전 HP 포켓몬 또는 (남은 1마리 + HP ≤ 25%).

**결정 특성** (참고용 — *직접 공략 금지*, 섹션 0-1 참조):
- 반응형 의사결정 (현재 매치업·HP 기반, 미래 턴 예측 없음)
- Terastallize / 팀 시너지 / 장기 전략 미고려
- 1턴 EV 최적화에 집중

→ 위 특성을 직접 공략하지 말고, **범용 gen9ou 강화를 통해 자연스럽게 우위 확보**. 다른 상대(LLM agent, ladder)에 전이되지 않는 abyssal 특화 변경은 거부.

---

## 3. Baseline 실행

> ⚠️ **실험 실행 정책**: 배틀 실험(`--N 30` 등)은 **에이전트가 직접 실행하지 않고 명령어만 안내**. 사용자가 터미널에서 직접 실행. 에이전트는 실험 준비(디렉토리 생성, README 템플릿 작성, 코드 변경)까지만 수행.

### 명령어 안내 (사용자 직접 실행)

```sh
uv run python scripts/battles/local_1v1.py \
  --player_name pokechamp \
  --player_prompt_algo minimax \
  --player_backend ollama/glm-5.1:cloud \
  --opponent_name abyssal \
  --N 30 \
  --battle_format gen9ou \
  --temperature 0.3 \
  --seed 42 \
  --log_dir .temp/experiments/EXP-001-baseline/battle_log
```

**사전 조건**:
- Pokémon Showdown 서버가 `localhost:8000`에서 실행 중
- Ollama Cloud 인증 설정 완료 (default 모델: `glm-5.1:cloud`, 별도 지정 없으면 이 모델 사용)
- `uv sync` 완료

> **모델 정책**: `--player_backend`는 Ollama Cloud의 자유 모델 중 선택. 별도 지정이 없으면 `ollama/glm-5.1:cloud`를 기본값으로 사용. 다른 Ollama Cloud 모델로 교체해 ablation 가능 (예: `ollama/qwen3-coder:cloud`, `ollama/nemotron-3-super:cloud`, `ollama/deepseek-v4-flash:cloud`).

### 핵심 설정

| 항목 | 값 | 비고 |
|------|-----|------|
| Prompt algo | `minimax` | LLM leaf evaluation 사용 |
| K (depth) | `2` | [LLMPlayer.__init__](pokechamp/llm_player.py) |
| 턴당 LLM 호출 | ~8회 | depth=2 기준 |
| Temperature | `0.3` | CLI에서 전달, 백엔드 기본값 0.7 무시 |
| `--enable_*` 플래그 | 전부 OFF | 정적 무브 정보만 사용 |
| Player 팀 | `get_metamon_teams("gen9ou", "competitive")` | 실패시 static teams |
| Opponent 팀 | `get_metamon_teams("gen9ou", "modern_replays")` | 실패시 static teams |

### 측정 항목 (ablation 비교용)

| 항목 | 단위 | 출처 |
|------|------|------|
| 승률 | % (X/Y판) | 배틀 결과 카운트 |
| 평균 턴 수 | 턴/판 | 배틀 로그 |
| LLM 호출 수 | calls/판 | `LLMPlayer.llm_call_count` |
| JSON 파싱 실패 | 회/판 | `retries=10` 도달 빈도 |
| 토큰 사용량 | prompt + completion | `LLMPlayer.prompt_tokens`, `completion_tokens` |
| 평균 응답 시간 | ms/call | 총 시간 ÷ 호출 수 |

> ✅ **baseline 측정 완료** — io/react/minimax 3종 baseline(`baselines/`)이 EXP-031~033으로 측정됨. [섹션 5](#5-실험-인덱스) 상단 "현재 baseline 전경" 참조. 새 ablation은 위 baseline 중 하나를 기준으로 변수 1개만 변경.

---

## 4. 실험 규칙

### 디렉토리 구조 (3분할)

```
.temp/experiments/
├── baselines/                 # ★ 공식 baseline (랜덤 팀, 수정 금지) — 평균 성능 비교 기준
│   ├── io-glm51/              #   ← EXP-032 (io, 53.3%)
│   ├── react-glm51/           #   ← EXP-031 (react, 76.7%)
│   └── minimax-glm51/         #   ← EXP-033 (minimax, 80.0%)
├── fixed-baselines/           # ★ 고정 팀 baseline (신규) — ablation 격리 비교 기준 (§9)
│   ├── manifests/v1.json      #   공통 고정 팀 manifest (player competitive × opponent modern_replays)
│   ├── io-glm51/              #   고정 팀 io baseline (측정 후)
│   ├── react-glm51/           #   고정 팀 react baseline (측정 후)
│   └── minimax-glm51/         #   고정 팀 minimax baseline (측정 후)
├── active/                    # 현재/다음 실험 (번호는 new_experiment.py 가 자동 할당)
│   └── EXP-NNN-name/
├── archive/                   # 종료된 실험 (EXP-001~030, EXP-TEST)
│   └── EXP-NNN-name/
└── model-timing/              # 모델별 응답속도 벤치마크
```

**이동 규칙**: 새 실험은 `active/`에서 시작 → 분석 완료 후 `archive/`로 이동. baseline은 `baselines/`에 영구 보관.

### 네이밍

- baseline: `baselines/{algo}-{model}/` (예: `minimax-glm51`)
- 실험: `EXP-{NNN}-{kebab-case-name}` — NNN은 3자리 순번. **다음 순번**은 `scripts/exp/new_experiment.py` 가 자동 할당.

### baseline 보존 규칙 ★

- `baselines/` 3종(io/react/minimax)은 **동일 조건**(glm-5.1, temp 0.3, seed 42, N=30, 상대 abyssal)으로 공정 비교 가능한 공식 baseline.
- **임의 수정·재실행 금지**. ablation의 "변경 1개 원칙"(섹션 0-4) 비교 기준이므로 고정.
- `fixed-baselines/` 3종도 동일 보존 규칙 적용 — 고정 팀 manifest(`manifests/v1.json`)와 함께 **ablation 격리 비교**의 기준(§9). 랜덤 팀 `baselines/`와는 별개 체계.
- 재측정 필요 시 `active/EXP-0NN` 신규 번호로 새 실험 생성, baseline은 그대로 유지.

### README.md 템플릿

```markdown
# EXP-{NNN}: {제목}

## 목적
{검증하려는 것}

## 가설
{변경 → 기대 효과}

## 설정 (baseline 대비 변경점만 명시)
- 변경: ...
- 코드 커밋: <hash> (있는 경우)

## 결과
- 승률: X/Y (Z%)
- 평균 턴 수: ...
- JSON 파싱 실패: N회
- (그 외 측정 항목)

## 분석
{해석, 다음 단계}
```

### 완료 체크리스트

- [ ] `battle_log/`에 잔여 파일 정리 완료
- [ ] README.md에 결과/분석 작성
- [ ] [섹션 5 실험 인덱스](#5-실험-인덱스)에 한 줄 추가
- [ ] 코드 변경 있으면 커밋 해시 README에 기록

---

## 5. 실험 인덱스

### 현재 baseline 전경 (★ 동일 조건 공정 비교)

> 조건: glm-5.1, temp 0.3, seed 42, N=30, 상대 abyssal (gemini-2.5-pro, io). 경로: `.temp/experiments/baselines/`.

| Baseline ★ | algo | 승률 | 평균 턴 | LLM 호출/판 | prompt tok | completion tok | 비고 |
|-------------|------|------|---------|------------|------------|----------------|------|
| io-glm51 | io | 53.3% (16/30) | 39.0 | 31.2 | 65,221 | 2,777 | 장기전 붕괴 |
| react-glm51 | react | 76.7% (23/30) | 24.4 | 119.1 | 357,737 | 11,610 | 426s/판, 토큰 다소 |
| minimax-glm51 | minimax | 80.0% (24/30) | 28.9 | 61.0 | 116,837 | 9,558 | 최고, 성능/비용 양호 |

> ablation은 위 3종 중 하나를 기준으로 변수 1개만 변경. **다음 EXP 번호**는 `scripts/exp/new_experiment.py` 가 자동 할당한다 (§8.3).

> **opponent 필드 기록 안내 (abyssal).** `--opponent_name abyssal`일 때 config의 `opponent_backend`/`opponent_algorithm`은 argparse 원값(기본 `gemini-2.5-pro`/`io`)의 직렬화일 뿐, abyssal 동작과 무관한 **노이즈 필드**. `AbyssalPlayer`(`poke_env/player/baselines.py:559`)은 LLM 미사용 순수 휴리스틱(`Player` 서브클래스)이며, `get_llm_player`(`poke_env/player/team_util.py:307-314`)의 abyssal 분기가 `backend`/`algo` 인자를 무시한다. ablation 공정성을 위해 baseline/EXP 모두 동일값(`abyssal`/`gemini-2.5-pro`/`io`) 유지 — `verify_single_change.py`가 값 변경을 §0-4 위반(FAIL)으로 잡는다.

### 전체 실험 이력

| ID | 이름 | 날짜 | 상태 | 승률 | 비고 |
|----|------|------|------|------|------|
| EXP-001 | Baseline 측정 | 2026-06-04 | ✅ 완료 | 83.3% (25/30) | minimax + deepseek-v4-flash:cloud, 변경 없음 |
| EXP-002 | 전술 원칙 프롬프트 | 2026-06-04 | ✅ 완료 | 73.3% (22/30) | 장황한 프롬프트 역효과, -10pp |
| EXP-003 | 최소 프롬프트 추가 | 2026-06-04 | ✅ 완료 | 66.7% (20/30) | 1문장 추가도 역효과, -16.6pp |
| EXP-004 | Value Function 수정 | 2026-06-04 | ✅ 완료 | 70.0% (21/30) | 리프 평가 변경도 역효과, -13.3pp |
| EXP-005 | Dynamic Flags (KAG) | 2026-06-04 | ✅ 완료 | 73.3% (22/30) | 데이터 증강도 역효과, 턴수 81.8 |
| EXP-006 | IO + Nemotron-3-Super | 2026-06-05 | ✅ 완료 | 6.7% (2/30) | io+nemotron 치명적, -76.6pp, 스위칭 루프 |
| EXP-007 | Verbose Prompt + IO+Ne | 2026-06-05 | ✅ 완료 | 13.3% (4/30) | 장문 프롬프트 약간 개선, 턴수 98.7 |
| EXP-008 | Minimal Prompt + IO+Ne | 2026-06-05 | ✅ 완료 | 23.3% (7/30) | 1줄 추가 최고성능(io+ne), 턴수 110 |
| EXP-009 | Value Func + IO+Ne | 2026-06-05 | ⏭️ SKIP | — | value_func은 io 알고리즘 미사용 |
| EXP-010 | Dynamic Flags + IO+Ne | 2026-06-05 | ✅ 완료 | 13.3% (4/30) | 데이터증강 효과미미, 턴수 62.1 |
| EXP-011 | IO Baseline + glm-5.1 | 2026-06-05 | ✅ 완료 | 53.3% (16/30) | io+glm-5.1, 118s/판, 턴수 55.4 |
| EXP-012 | IO Baseline + deepseek-v4-pro | 2026-06-05 | ✅ 완료 | 20.0% (6/30) | io+deepseek-pro, 105s/판, 턴수 94.6, 스위칭 루프 의심 |
| EXP-013 | IO Baseline + nemotron-3-s | 2026-06-05 | ✅ 완료 | 23.3% (7/30) | io+nemotron3s, 턴수 132.5, 스위칭 루프 심각 |
| EXP-014 | IO Baseline + deepseek-v4-flash | 2026-06-05 | ✅ 완료 | 53.3% (16/30) | io+deepseek-flash, 턴수 51.2, minimax 대비 -30pp |
| EXP-015 | IO Baseline + gemma4:31b | 2026-06-05 | ✅ 완료 | 70.0% (21/30) | io+gemma4 최고성능, 턴수 36.1, 효율적 전투 |
| EXP-016 | IO Baseline + kimi-k2.6 | 2026-06-05 | ✅ 완료 | 56.7% (17/30) | io+kimi-k2.6, 648s/판(매우느림), 턴수 51.6, completion 28k |
| EXP-017 | IO + gemma4 + LLM Lead | 2026-06-08 | ✅ 완료 | 50.0% (15/30) | io+gemma4+llm_lead, 턴수 34.4, JSON실패 394회, -20pp vs EXP-015 |
| EXP-018 | IO + GLM-5.1 속도 측정 | 2026-06-08 | ✅ 완료 | 60.0% (3/5) | io+glm-5.1, 190s/판, 턴수 30.0, 속도 측정 목적 (N=5) |
| EXP-019 | IO+Gemma4+LLM Lead+Temp0 | 2026-06-08 | ✅ 완료 | 50.0% (15/30) | EXP-017 대비 승률 변화없음, JSON실패 143회, temp0 효과미미 |
| EXP-020 | — | — | ⏭️ SKIP | — | 번호 스킵 (실험 미진행) |
| EXP-021~030 | ReAct 중간 산물 (10건) | 2026-06-09~11 | 📦 archive | — | stopping-criteria 개선 전 비효율 실행. 30판 배틀 수행됐으나 metrics 산출·README 누락. `archive/EXP-021~030` (약 250MB, EXP-030 단일 jsonl=177MB). 최종 성공은 EXP-031, 비교 근거는 `docs/archive/exp-030-react-glm51-analysis.md` |
| EXP-031 ★ | Baseline: ReAct + glm-5.1 | 2026-06-12 | ✅ baseline | 76.7% (23/30) | **react baseline** → `baselines/react-glm51`. 24.4턴, 119.1 LLM호출, 426s/판 |
| EXP-032 ★ | Baseline: IO + glm-5.1 | 2026-06-12 | ✅ baseline | 53.3% (16/30) | **io baseline** → `baselines/io-glm51`. 39.0턴, 31.2 LLM호출. 장기전 붕괴 |
| EXP-033 ★ | Baseline: Minimax + glm-5.1 | 2026-06-12 | ✅ baseline | 80.0% (24/30) | **minimax baseline** → `baselines/minimax-glm51`. 28.9턴, 61.0 LLM호출. 최고 성능 |
| EXP-034 | ReAct BUDGET 힌트 정밀화(안 A) | 2026-06-16 | ✅ 완료 | 76.7% (23/30) | 승률 유지 + 비용절감(토큰 −42%, LLM호출 −38.5%, 시간 −43%). 조기종료율 34→80%. `react_agent.py` 단일 변경(§0-4 PASS). ⚠️ 메트릭 수집 버그(turns/won) 발견·fix. 분석 `docs/analysis/exp-034-react-glm51-analysis.md` |
| EXP-035 | ReAct 동적 타입/위력 리졸브(안 B B-1) | 2026-06-17 | ❌ 기각 | 56.7% (17/30) | −20pp 역효과(단 n=30 비유의, z≈1.64 p≈0.10). 기술 결함: 동적 위력 override가 sim `modify_base_power`와 중복 보정(acrobatics no-item 110→×2=220 BP, 2× 과대평가). ivycudgel 거짓 OHKO는 sim 본연 버그라 미해결. `battle_tools.py` 단일 변경이나 §0-4에서 smogon 메타 3개 섞여 런타임 무영향 확인. B-1 기각, 안 A 최선. 분석 `docs/analysis/exp-035-react-glm51-analysis.md` |
| EXP-036 | sim 행동순서 정확도(fix1) | 2026-06-17 | ✅ 완료 | 80.0% (24/30) | **+3.3pp vs react baseline**(비유의 z≈0.31 p≈0.75, 하락 아닌 상승). 시뮬레이터 코어 버그 시리즈 1/3. `local_simulation.py calculate_remaining_hp` priority 전 범위 정렬(기존 `==1`만 → protect/Extreme Speed/Sucker Punch 등 전 범위 + p2 priority) + protosynthesis p2 인자 복붙 fix. 비용 213k/76.5 LLM 유지. 단위 테스트 5/5 PASS. 패배 808(111턴)은 ivycudgel 거짓 OHKO 매몰(EXP-038 영역). 분석 `docs/analysis/exp-036-react-glm51-analysis.md`. →EXP-037(protect/item), EXP-038(ivycudgel/tera) |
| EXP-037 | sim protect/item(fix2) | 2026-06-17 | ⚠️ 보류 | 66.7% (20/30) | −13.3pp vs EXP-036(80%)(비유의 z≈−1.17 p≈0.24, 인과 불명). protect 계열 0데미지(early return, 최소1데미지규칙 우회) + LifeOrb명 정규화(`"LifeOrb"`→`"lifeorb"`). fix1 누적. fix2는 **올바른 동작**(단위테스트 3/3, showdown 스펙)이라 기각 아닌 **보류**. LifeOrb는 metamon 팀 빈도 낮아 효과 미미; protect tool_result 71→15·LLM언급 161→100 감소, ohko언급 323→371 증가, 보수화 지표(setup/heal)는 변화 없음. long구간 62.5%→45.5%. 분석 `docs/analysis/exp-037-react-glm51-analysis.md`. EXP-038(fix3) 누적 후 fix2 순효과 재평가 |
| EXP-038 | sim tera/ivycudgel(fix3) | 2026-06-18 | ⚠️ 무효(시리즈 완결) | 66.7% (20/30) | 승률·거짓OHKO(16.7%) 변화 없음. **z(037 vs 038)=0.00** → fix3 단독 효과 이론상 0 확인. tera 언급 **0.7%**(16/2254턴)·ivycudgel/ogerpon 등장 3배틀로 fix3 영향 범위 0(abyssal 휴리스틱이라 tera·Ogerpon 극히 드묾). **시리즈 종합**: fix1(80%) > fix1+2(66.7%)=fix1+2+3(66.7%). fix2가 시리즈 하락 원인(037=038 일관, 비유의 z≈−1.17), fix3 무효. 단위테스트 12/12 PASS. **핵심 교훈: "sim 정확도≠승률"** — fix1(매턴 영향)만 전이, fix2/3(조건부/희귀 기믹)는 비전이·역효과. 근본 병목은 agent 맹신(EXP-034 P0-1) → 다음 레버는 sim이 아닌 **agent self-verification + 팀분석**. 분석 `docs/analysis/exp-038-react-glm51-analysis.md`. 시리즈 권고: fix1 단독 채택(80%), fix2 기각/재검토, fix3는 코드 유지(tera 빈번 매칭서 재검증) |

---

## 6. 핵심 코드 위치

| 위치 | 역할 |
|------|------|
| [pokechamp/prompts.py](pokechamp/prompts.py) L1054-1076 | 시스템 프롬프트 (Active/Fainted 두 분기) |
| [pokechamp/prompts.py](pokechamp/prompts.py) `_apply_dynamic_calcs_to_move` L170-256 | 동적 무브 증강 (flags/calcs/oracle) |
| [pokechamp/llm_player.py](pokechamp/llm_player.py) L429-490 | 프롬프트 조합 (system + state + state_action + constraint) |
| [pokechamp/minimax_optimizer.py](pokechamp/minimax_optimizer.py) | Minimax tree search |
| [poke_env/player/local_simulation.py](poke_env/player/local_simulation.py) | `LocalSim` 턴 시뮬레이션 |
| [poke_env/player/baselines.py](poke_env/player/baselines.py) | `AbyssalPlayer` 등 휴리스틱 baseline |
| [bayesian/pokemon_predictor.py](bayesian/pokemon_predictor.py) | 베이지안 예측 프로덕션 인터페이스 |

---

## 7. Baseline 백업 ★

> `baselines/` 3종은 `.temp/` (gitignore)에만 존재해 디스크 장애 시 **복구 불가**. 이를
> git-tracked blob 으로 보존해 `git clone` 한 번에 복원 가능하게 한다.

- **도구**: [`scripts/backup/backup_baselines.py`](scripts/backup/backup_baselines.py) — `backup` / `verify` / `restore` 서브커맨드. stdlib only.
- **산물**: [`backups/baselines/`](backups/baselines/) — `baselines-full-vN.tar.zst` (전체 162파일, ~2.97MB zstd) + `.sha256manifest.json` (파일별 sha256). `RESTORE.md` 참조.
- **왜 tar.zst**: `.gitignore` 가 `*.html`·`*.jsonl` 을 전역 무시 → blob 으로 우회. 매니페스트는 `.json` (`.jsonl` 은 ignore됨).
- **내구성 = push ★**: blob 가 로컬 `.git` (`.temp/` 와 동일 디스크) 에 있으므로, **`git push` 해야만** GitHub 원격에 복제본이 생겨 디스크 장애에서 살아남음. commit 후 반드시 push + 원격 확인(`git cat-file -s`, RESTORE.md 검증 D).
- **canonical vs snapshot**: `.temp/experiments/baselines/` 가 canonical live copy, `backups/baselines/` 는 recovery-only snapshot (편집 금지).
- **범위**: 현재 baseline 3종만. `active/`·`archive/` 백업은 별도 결정 (archive는 `experiment_*.json` 이 없어 별도 접근 필요).
- **갱신**: `BASELINE_NAMES` 에 baseline 추가 후 `backup` 재실행 → 새 버전 blob. 상세는 [`backups/baselines/RESTORE.md`](backups/baselines/RESTORE.md).
- **코드 상태 한계 ★**: baseline 3종은 2026-06-12 에 **더티(커밋 전) 작업트리**에서 실행됐다. 당시 `experiment_*.json` 의 `meta` 로깅 코드는 커밋되지 않은 채 이후 덮어쓰기돼 **코드 상태가 영영 소실** 됐다. 따라서 baseline의 *정확한 코드 커밋을 역추론하거나 태그로 고정하는 것은 불가능*. baseline은 **데이터**(JSON·replay·로그) 만 공식이며, 코드 비교 기준은 JSON `config`(파라미터) 한정. 상세 한계는 [§8.5](#85-baseline-코드-상태-한계-선언).

---

## 8. 실험 코드·파라미터 변경 자동 추적

> [§0-6](#0-agent-행동-규칙-read-first) 수동 기록(commit 해시를 README에 적으라)은
> 준수율 0%로 실패했다. 대신 배틀 스크립트가 JSON `meta` 블록에 **자동** 으로 기록한다.
> §7 백업과 동일 철학("수동 규칙은 실패 → 자동화로 마찰 제거, 결론은 git에").

### 8.1 자동 meta 기록 ★

배틀 스크립트(`scripts/battles/local_1v1.py`, `local_1v1_langchain.py`)가 각 실험
`experiment_*.json` 최상위에 `meta` 블록을 자동 추가한다. 공통 헬퍼:
[`scripts/battles/_experiment_meta.py`](scripts/battles/_experiment_meta.py) (stdlib only,
git 호출 전부 예외 방어 — git 없는 환경에서도 배틀은 죽지 않음).

| 필드 | 의미 |
|------|------|
| `git_commit` / `git_commit_short` | 실험 실행 시점 HEAD 커밋 |
| `git_branch` | 브랜치명 |
| `git_dirty` | 작업트리 더티(커밋 전 변경) 여부 |
| `git_dirty_files` | 변경된 파일 목록 (tracked 수정 + untracked 신규) |
| `git_dirty_stat` | `git diff HEAD --stat` 요약 줄 (tracked 수정만) |
| `git_error` | git 호출 실패/비-repo 시 메시지 (정상 `null`) |
| `dirty_patch_file` | 더티 diff patch 파일명 (log_dir 내; clean tree면 `null`) |
| `argv` | `sys.argv` 전체 = 실행 명령 100% 재현 |
| `python_version`, `repo_root` | 실행 환경 |

구 baseline JSON(`meta` 없음)과 호환 — 분석 스크립트는 `.get("meta", {})` 로 읽는다.

### 8.2 더티 코드 보존 ★

실험은 보통 코드 수정 후 커밋 전(더티 트리)에 돈다. 더티 diff는 log_dir에 patch로
남지만 `.temp/` 전체가 gitignore라 **push 하면 소실**. 배틀 후 보존:

```sh
uv run python scripts/exp/preserve_code_state.py EXP-NNN-name
#   → backups/code_state/EXP-NNN-name/ 에 patch + meta.json 복사 (tracked, .temp/ 바깥)
git add backups/code_state/ && git commit -m "exp: preserve code state [EXP-NNN]" && git push
```

`backups/code_state/` 는 `.temp/` 바깥이라 tracked. push = 오프디스크 내구성
([§7](#7-baseline-백업-) RESTORE.md 검증 D 와 동일 원칙).

- **untracked 새 파일**은 `git diff HEAD` patch 에 내용이 없으므로, preserve 가
  `backups/code_state/EXP-NNN/untracked/` 로 파일을 직접 복사해 보존한다.
- **clean tree**(코드를 이미 커밋한 뒤 배틀)는 더티 patch 가 없다. preserve 가 그
  커밋이 origin 에 도달했는지(`git branch -r --contains`) 확인하고 미push 면 경고한다
  (커밋만 있고 push 안 하면 디스크 장애에 소실).

### 8.3 실험 시작 도우미

```sh
uv run python scripts/exp/new_experiment.py --name {kebab-name} --baseline {io|react|minimax}
```

다음 EXP 번호 자동 할당(`active/`+`archive/`+§5 이력표 스캔) → 디렉토리 + README(§4
템플릿) 생성 + baseline 맞춤 실행 명령 안내 + 더티 경고. §0-2(번호 확인)·§0-7(로그
분리) 자동 준수.

### 8.4 "변경 1개 원칙" 자동 검증 (§0-4)

```sh
uv run python scripts/exp/verify_single_change.py EXP-NNN-name --baseline {io|react|minimax}
```

실험 `config` 와 baseline `config` 비교 → **파라미터 diff 수 + 코드 파일 수 = 총 변경**.
1 이면 ✅ PASS, 아니면 ❌ FAIL + 변경 내역. 도구 자체(`scripts/exp/`,
`_experiment_meta.py`) 변경은 노이즈로 자동 제외.

### 8.5 Baseline 코드 상태 한계 선언 ★

baseline 3종의 정확한 **코드 커밋은 소실** 됐다 (§7 "코드 상태 한계" 참조). 따라서:
- baseline 코드 상태를 재현하거나 태그로 고정하는 것은 **불가능**.
- §8.4 코드 변경 검증은 "실험 시점 더티 파일" 기준이지, baseline 코드와의 직접 diff가 아님.
- 파라미터 diff 는 baseline JSON `config`(canonical) 와 정확히 비교.
- **§8 자동 추적은 본 시스템 도입 이후 신규 실험부터 유효**. 이전 실험(archive)은 `meta`가 없어 코드 변경 검증 불가.

### 8.6 예시 walkthrough

> 한 사이클(`new_experiment` → 배틀 → `preserve` → `verify`)을 구체적 예시로.
> 시나리오: minimax baseline(80%)에서 시스템 프롬프트에 "상대 어빌리티 추론"
> 범용 지침 1줄을 추가하는 ablation (§0-1 범용 원칙, abyssal 특화 아님).

| # | 액션 | 산출물 / 결과 | 누가 |
|---|------|---------------|------|
| 1 | `new_experiment.py --name infer-ability-prompt --baseline minimax` | `EXP-034` 자동 할당 · dir/README + 실행 명령 안내 | 도구 |
| 2 | `prompts.py` 시스템 프롬프트 1줄 추가 (커밋 X) | 작업트리 더티 | 도구(수정) |
| 3 | 안내 명령으로 **배틀 실행** | `experiment_*.json`에 `meta`(`git_commit`, `git_dirty:true`, `git_dirty_files:["prompts.py"]`, `argv`…) 자동 기록 + `log_dir/*_dirty.patch`(gitignored) | **사용자** (§0-8) |
| 4 | `preserve_code_state.py EXP-034-infer-ability-prompt` | `backups/code_state/EXP-034-…/` ← patch(tracked) + `meta.json` | 도구 |
| 5 | `git add … && commit && git push origin main` | GitHub 도달 = 오프디스크 내구성 | 커밋(도구)/push(사용자) |
| 6 | `verify_single_change.py EXP-034 --baseline minimax` | 파라미터 0 + 코드 1 = **PASS** (§0-4). `temperature`까지 바꿨으면 2 → FAIL | 도구 |
| 7 | `ANALYSIS_MANUAL.md` → `docs/analysis/exp-034-minimax-glm51-analysis.md` | 분석 보고서 + README 결과 | 도구 |
| 8 | `active/` → `archive/`, §5 한 줄 추가 | 이력 갱신 | 도구 |

**변형 케이스**:
- **untracked 새 파일**(예: `ability_inference.py`) 추가 시 — patch는 기존 파일만 담지만 `preserve`가 untracked를 식별해 `backups/…/untracked/`로 직접 복사 (§8.2).
- **clean tree**(코드 커밋 후 배틀) — `preserve`가 그 커밋의 origin 도달을 `git branch -r --contains`로 검사, 미push면 경고 (§8.2).

**예전 vs 지금**: 예전엔 단계 3의 `meta`가 없어 "이 승률이 어느 코드에서 나왔나"를 재현 불가(README 해시 수동 기록, 준수율 0%). 지금은 ③에서 `meta` 자동 + ④⑤에서 patch 오프디스크 → 디스크 장애 후에도 `git clone` + patch 적용으로 코드 상태 100% 복원.

---

## 9. 고정 팀 모드 (ablation 격리)

> [§0-5](#0-agent-행동-규칙-read-first) 재현성 규칙의 실행 체계. 상세 설계는
> [`docs/architecture/fixed-team-mode.md`](docs/architecture/fixed-team-mode.md).

### 9.1 배경: 왜 `--seed`만으로는 부족한가

`--seed 42`는 프로세스 시작 시 전역 RNG를 **한 번만** 초기화한다. 매 배틀마다
`TeamSet.yield_team()`이 `random.choice`로 팀을 뽑아 전역 RNG를 소비하고, 배틀
진행 중에도 `random.shuffle`/`random.random`/`np.random.randint`가 가변 개수로
난수를 소비한다. 결과: **첫 배틀만 재현되고 2번째부터는 직전 배틀의 턴 수·LLM
응답에 따라 팀이 달라진다.** 같은 seed여도 ablation 간 매치업이 달라져 승률 변화의
인과(코드 변경 vs 팀 구성)를 분리할 수 없다.

### 9.2 해결: 고정 팀 모드

`--team_mode fixed --team_manifest <path>` 로 **미리 선별된 팀 매치업 N개**를
manifest에서 인덱스로 결정적 로드한다(player+opponent 양쪽). `random.choice`를
쓰지 않으므로 전역 RNG에 영향을 주지 않고, 매 배틀마다 같은 팀 쌍이 주입된다.
→ **ablation 간 동일 매치업 → 승률 변화 = 코드 변경 효과.**

manifest(`fixed-baselines/manifests/v1.json`, 공통 세트):

- player: metamon `competitive`(16팀) modulo 순환
- opponent: metamon `modern_replays`(25192팀)에서 30개 균등 간격 유일 추출
- → 30판 매치업 쌍 모두 유일 (player 팀은 반복되나 opponent가 매번 달라 다른 배틀)

맞춤 세트(stall matchup 등 검증 목적)는 동일 스키마 + `custom_purpose` 로 별도 manifest 작성 가능.

### 9.3 워크플로우

**0. 고정 팀 baseline 1회 측정**(각 algo, 사용자 실행 — §0-8):

```sh
uv run python scripts/battles/local_1v1_langchain.py \
  --player_name pokechamp --player_prompt_algo minimax \
  --player_backend ollama/glm-5.1:cloud --opponent_name abyssal \
  --N 30 --battle_format gen9ou --temperature 0.3 --seed 42 \
  --team_mode fixed \
  --team_manifest .temp/experiments/fixed-baselines/manifests/v1.json \
  --log_dir .temp/experiments/fixed-baselines/minimax-glm51/battle_log
# (react/langchain, io/local_1v1 도 동일 — algo·script·log_dir 만 교체)
```

**1. ablation 시작**:

```sh
uv run python scripts/exp/new_experiment.py --name <change> --team_mode fixed
# → active/EXP-NNN/ 스캐폴드 + --team_mode fixed 안내 명령
# (맞춤 세트면 --team_manifest <custom.json> 추가)
```

**2. 코드 1개 변경 → 3. 안내 명령으로 배틀(사용자) → 4. 검증**:

```sh
uv run python scripts/exp/verify_single_change.py EXP-NNN --baseline minimax --zone fixed-baselines
# 같은 manifest → team_manifest_hash 값 동일 → 팀 키 변경 0 + 코드 1 = PASS (§0-4)
```

**5. 분석**: `ANALYSIS_MANUAL.md` 절차 + `template.md` "0. 실험 조건"(팀 모드·manifest hash).

### 9.4 verify 정합성 (§0-4 "변경 1개 원칙")

`verify_single_change.py` 의 `config_diff` 는 **양쪽 공통 키만 값 비교**한다.
`team_manifest_hash` 는 IGNORE 가 아니므로:

| 비교 (fixed-baseline → ablation) | manifest | 코드 | 결과 |
|---|---|---|---|
| **같은 manifest** (일반적) | same | 1파일 | 팀 키 0 + 코드 1 = **1 → PASS** |
| 다른 manifest (맞춤 세트) | diff | 0파일 | hash diff 1 = **1 → PASS** (manifest 자체가 ablation) |
| 다른 manifest + 코드 | diff | 1파일 | **2 → FAIL** (의도) |

`--zone fixed-baselines` 로 fixed-baseline config 를 비교 기준으로 지정. (지정
안 하면 랜덤 `baselines/` 기준이 되는데, 이때 `team_*` 키가 스키마 차이로 제외돼
여전히 PASS 이긴 하나, 의미상 fixed-baseline 비교가 정확.)

### 9.5 한계 ★

- **LLM 응답 비결정성**(temp 0.3): 팀을 고정해도 동일 ablation 2회 실행이 완전히
  일치하지는 않는다. 고정 팀 모드가 보장하는 것은 **ablation 간 매치업 공정성**이지,
  실행 간 완전 재현이 아니다. 분석은 N판 평균 ± 표준편차로.
- **competitive 풀 16개 vs N=30**: player 팀 modulo 순환 (opponent 30개 유일이
  매치업 유일성을 보장). 매치업 다양성을 더 원하면 N=16 또는 player 풀 확장 검토.
- **archive(EXP-001~038)와의 단절**: 과거는 랜덤 팀. `baselines/`(랜덤)는 과거
  archive 비교 기준, `fixed-baselines/`(고정)는 신규 비교 기준 — 두 체계 병존.
  중요 결론은 고정 팀 모드로 재검증(신규 EXP 번호) 가능.
- manifest(`fixed-baselines/manifests/`)는 git 추적 권장 — 재현성은 hash 로 검증.
