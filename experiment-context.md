# Performance Improvement Experiment Context

> LLM agent(pokechamp)가 abyssal player 상대 **승률 90%+ 달성**을 위한 실험의 세션 간 컨텍스트 문서.
> 새 세션 시작 시 이 파일을 먼저 읽어 context를 복원하고, 섹션 0의 행동 규칙을 따르세요.

---

## 0. Agent 행동 규칙 (READ FIRST)

1. **범용 전략 우선 (★)**: abyssal의 특정 규칙 허점(matchup score 임계값, Tera 미고려 등)을 *직접 공략*하는 실험·코드 변경은 **금지**. 모든 개선안은 "이 변경이 다른 gen9ou 상대(다른 LLM agent, human, ladder)에게도 동일하게 도움이 되는가?"를 만족해야 함. 승률 90%는 **범용 gen9ou 전략 능력 향상의 결과**여야 함.
2. **EXP 번호 확인**: 새 실험 시작 전 반드시 [섹션 5](#5-실험-인덱스)에서 다음 EXP 순번을 확인.
3. **Baseline 우선**: EXP-001 baseline 미측정 상태면 어떤 ablation도 시작하지 않음.
4. **변경 1개 원칙**: ablation 시 baseline 대비 변수 1개만 변경. 다른 모든 조건은 baseline과 동일.
5. **재현성**: 모든 실험에서 `--seed 42`, `--N 30` 이상.
6. **코드 변경 동반 시**:
   - 커밋 메시지에 EXP-ID 포함 (예: `feat(prompt): macro_prompt to user [EXP-002]`)
   - 해당 실험 README.md에 커밋 해시 기록
7. **로그 분리**: `--log_dir`로 실험 전용 디렉토리 지정. `./battle_log/one_vs_one` (기본값) 사용 금지.
8. **상세 정보 필요시**:
   - `--enable_*` 플래그 사양 → [flags-reference.md](flags-reference.md)
   - 개선 우선순위/진단 → [improvement-plan/](improvement-plan/)
   - 과거 세션 작업 → [SESSIONS.md](SESSIONS.md)

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

```sh
uv run python scripts/battles/local_1v1.py \
  --player_name pokechamp \
  --player_prompt_algo minimax \
  --player_backend ollama/deepseek-v4-flash:cloud \
  --opponent_name abyssal \
  --N 30 \
  --battle_format gen9ou \
  --temperature 0.3 \
  --seed 42 \
  --log_dir .temp/experiments/EXP-001-baseline/battle_log
```

**사전 조건**:
- Pokémon Showdown 서버가 `localhost:8000`에서 실행 중
- Ollama Cloud 인증 설정 완료 (default 모델: `deepseek-v4-flash:cloud`, 별도 지정 없으면 이 모델 사용)
- `uv sync` 완료

> **모델 정책**: `--player_backend`는 Ollama Cloud의 자유 모델 중 선택. 별도 지정이 없으면 `ollama/deepseek-v4-flash:cloud`를 기본값으로 사용. 다른 Ollama Cloud 모델로 교체해 ablation 가능 (예: `ollama/qwen3-coder:cloud`).

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

> ⚠️ **현재 baseline 미측정**. EXP-001 실행 후 결과를 [섹션 5](#5-실험-인덱스)에 기록.

---

## 4. 실험 규칙

### 디렉토리 구조

```
.temp/experiments/
├── EXP-001-baseline/
│   ├── README.md
│   └── battle_log/
├── EXP-002-prompt-p0/
│   ├── README.md
│   └── battle_log/
└── ...
```

### 네이밍

`EXP-{NNN}-{kebab-case-name}` — NNN은 3자리 순번 (001, 002, ...)

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
- [ ] [SESSIONS.md](SESSIONS.md)에 세션 요약 추가

---

## 5. 실험 인덱스

| ID | 이름 | 날짜 | 상태 | 승률 | 비고 |
|----|------|------|------|------|------|
| EXP-001 | baseline | 2026-05-26 | completed | 63.33% (19/30) | 기준점, 코드 변경 없음 |
| EXP-002 | flags-only | 2026-05-26 | completed | 66.67% (20/30) | +3.33pp vs baseline |
| EXP-003 | flags-calcs | 2026-05-26 | completed | 73.33% (22/30) | +10.00pp vs baseline, +6.67pp vs EXP-002 |
| EXP-004 | baseline (deepseek-v4-flash) | 2026-06-02 | completed | 90.0% (27/30) | deepseek-v4-flash:cloud 기준점, dynamic flags 없음 |
| EXP-005 | flags-only (deepseek-v4-flash) | 2026-06-03 | completed | 70.0% (21/30) | --enable_dynamic_flags, -20.00pp vs EXP-004 |
| EXP-006 | flags+calcs (deepseek-v4-flash) | 2026-06-03 | completed | 40.0% (12/30) | --enable_dynamic_flags --enable_dynamic_calcs, -50.00pp vs EXP-004, -30.00pp vs EXP-005 |
| EXP-007 | all flags (deepseek-v4-flash) | 2026-06-03 | completed | 60.0% (18/30) | --enable_dynamic_flags --enable_dynamic_calcs --enable_showdown_oracle, -30.00pp vs EXP-004, +20.00pp vs EXP-006 |
| EXP-008 | io baseline (deepseek-v4-flash) | 2026-06-03 | completed | 20.0% (6/30) | io prompt, no dynamic flags, -70.00pp vs EXP-004 |

### 미측정 코드 변경 (실험 인덱스에 없음)

다음 코드 변경은 Phase 1 이후 main에 merge되었으나, 공식 실험으로 측정되지 않았습니다.
후속 실험(EXP-004+)에서 baseline 대비 효과를 검증해야 합니다.

| 변경 | 커밋 | 내용 | 비고 |
|------|------|------|------|
| switch prompt 보강 | `b97f81d` | switch pokemon prompt에 full move/ability info 추가 | EXP-001 이전 적용, baseline에 포함됨 |
| 확장 dynamic type resolver | `8806a5a`, `c1f1044` | species/form/property/terrain/item 기반 동적 타입 해석 추가 | EXP-003 이후 추가, 미측정 |
| oracle integration | `c0bc155`, `95be5e0`, `b564023` | ShowdownOracle: 정확한 데미지/KO 확률 계산 → prompt 주입 | `--enable_showdown_oracle`, 미측정 |

### 개선 계획 (미구현)

improvement-plan에 정리된 P0~P4 항목. 코드 변경 전 실험 계획 필요.

| 우선순위 | 항목 | 상태 |
|----------|------|------|
| P0 | macro_prompt를 system → user로 이동 | 계획 |
| P1 | 영문 문법/오타 수정 + 두 분기 공통화 | 계획 |
| P2 | Gen 9 OU 특화 휴리스틱 추가 | 계획 |
| P3 | 출력 계약을 system 최상단 통합 | 계획 |
| P4 | "sacrifice" 휴리스틱 재검토 | 계획 |

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
