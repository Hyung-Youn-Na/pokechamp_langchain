# PokéChamp 실험 분석 보고서 작성 메뉴얼

> **목적**: `.temp/experiments/<zone>/EXP-NNN-*/` (baseline은 `baselines/{algo}-{model}/`) 실험 결과를 일관된 방식으로 분석하여 `docs/exp-{NNN}-*-analysis.md` 형식의 분석 보고서를 작성하는 **표준 절차**를 정의한다.
> **대상 독자**: 분석을 수행하는 Claude (또는 사람). 새 세션에서 이 파일만 읽어도 분석 착수가 가능해야 한다.
> **관련 문서**:
> - 규칙 원본: [`experiment-context.md`](../experiment-context.md) — **반드시 먼저 읽을 것** (특히 섹션 0 "Agent 행동 규칙").
> - 보고서 뼈대: [`template.md`](template.md) — 이 메뉴얼의 8절 참조.

---

## 0. 빠른 시작 (Quick Start)

### 0.1 이 메뉴얼은 무엇인가

이 메뉴얼은 **"실험 결과가 이미 존재할 때, 어떻게 분석하고 보고서로 정리하는가"** 에 대한 절차서다. 실험을 실행하거나(배틀 돌리기) 코드를 변경하는 방법은 다루지 않는다 — 그것은 [`experiment-context.md`](../experiment-context.md) 의 영역이다.

### 0.2 새 세션에서의 활용 순서 (5단계 요약)

1. [`experiment-context.md`](../experiment-context.md) 섹션 0(행동 규칙) + 섹션 5(실험 인덱스) 읽기 → 비교 대상 EXP 파악.
2. 본 메뉴얼 **2절**(입력 구조)·**3절**(워크플로우) 통독.
3. 분석 대상 EXP 디렉토리(`.temp/experiments/<zone>/EXP-NNN-*/` — baseline은 `baselines/{algo}-{model}/`) 확인 → **4.1** 로 뷰어 생성.
4. **4.2~4.5** 스니펫으로 정량 데이터 추출.
5. [`template.md`](template.md) 복사 → **8절** 순서대로 채우기.

### 0.3 사전 필수 확인

분석 시작 전 아래가 모두 참이어야 한다:

- [ ] 분석 대상 `<zone>/EXP-NNN-*/battle_log/experiment_*.json` (baseline은 `baselines/{algo}-{model}/`) 이 존재한다.
- [ ] 로그 파일(`llm_log.jsonl` 또는 `langgraph_*.jsonl`)이 존재한다.
- [ ] 배틀 리플레이 HTML(`pokechamp* - battle-gen9ou-*.html`)이 N개 존재한다.

> ⚠️ **누락 시**: 절대 직접 배틀을 실행하지 말고 사용자에게 실행을 요청한다 (규칙: [6.4절](#64-배틀-실행-금지)).

---

## 1. 관련 문서 및 코드 맵핑

### 1.1 experiment-context.md (행동 규칙 원본)

모든 분석 규칙의 **단일 진실 원본(single source of truth)**. 본 메뉴얼 6절은 이것을 분석 맥락에서 재해설할 뿐, 규칙을 재정의하지 않는다. 규칙 충돌 시 **experiment-context.md 가 우선**.

| 참조 | 내용 |
|------|------|
| [섹션 0](../experiment-context.md#0-agent-행동-규칙-read-first) | Agent 행동 규칙 (범용 전략, 배틀 실행 금지 등) |
| [섹션 3](../experiment-context.md#3-baseline-실행) | 측정 항목 정의 + baseline 실행 명령어 |
| [섹션 5](../experiment-context.md#5-실험-인덱스) | 실험 인덱스 (비교 대상 EXP 검색용) |

### 1.2 핵심 코드 위치 (참조 테이블)

보고서에서 원인 분석 시 아래 파일을 인용한다.

| 위치 | 역할 |
|------|------|
| [`pokechamp/prompts.py`](../pokechamp/prompts.py) L1054-1076 | 시스템 프롬프트 (Active/Fainted 분기) |
| [`pokechamp/prompts.py`](../pokechamp/prompts.py) `_apply_dynamic_calcs_to_move` L170-256 | 동적 무브 증강 |
| [`pokechamp/llm_player.py`](../pokechamp/llm_player.py) L429-490 | 프롬프트 조합 (system + state + action + constraint) |
| [`poke_env/player/baselines.py`](../poke_env/player/baselines.py) | `AbyssalPlayer` 등 휴리스틱 baseline (상대) |
| [`tools/battle_viewer.py`](../tools/battle_viewer.py) | 분석용 뷰어 생성 도구 (4.1절) |

### 1.3 본 메뉴얼 vs template.md 의 관계

| 문서 | 역할 | 사용 방식 |
|------|------|-----------|
| **ANALYSIS_MANUAL.md** (본 문서) | 절차/방법론 (읽기 전용 참조서) | 새 세션 첫 1회 통독, 매 분석마다 3·4절 참조 |
| [`template.md`](template.md) | 보고서 뼈대 (복사해서 쓰는 입력 양식) | `cp` 후 플레이스홀더 채우기 (8절) |

참조 방향은 **단방향**: 본 메뉴얼만 template을 참조한다. template은 독립적 뼈대로 유지한다.

---

## 2. 실험 입력 구조 이해

### 2.1 표준 디렉토리 구조

실험 데이터는 `.temp/experiments/` 아래 **3분할 zone**에 저장된다 (상세: [`experiment-context.md`](../experiment-context.md) §4):
- `baselines/{algo}-{model}/` — 공식 baseline (io/react/minimax, ablation 비교 기준)
- `active/EXP-NNN-*/` — 현재/다음 실험 (EXP-034+)
- `archive/EXP-NNN-*/` — 종료된 실험

각 실험 디렉토리는 아래 표준 구조를 따른다 (네이밍: `EXP-{NNN}-{algo}-{model}`; baseline은 `{algo}-{model}`).

```
.temp/experiments/<zone>/<exp-dir>/     # baseline: <zone>=baselines, <exp-dir>={algo}-{model}
└── battle_log/
    ├── experiment_<algo>_<backend>_<timestamp>.json   # config + summary + battles[]
    ├── llm_log.jsonl                                   # IO / minimax 알고리즘
    │   또는 langgraph_llm_log.jsonl + langgraph_tool_log.jsonl  # react 알고리즘
    └── pokechamp<NNNN> - battle-gen9ou-<NNN>.html      # 배틀 리플레이 N개
    └── viewer/   # ← 4.1 실행 시 생성됨 (분석 시점 전에는 없을 수 있음)
        ├── index.html                # 요약 (승률, 평균 턴, 총 LLM 호출)
        └── battle-gen9ou-<NNN>.html  # 개별 배틀 (리플레이 + LLM reasoning 병합)
```

> **참고**: experiment-context.md 섹션 4에 README.md 템플릿이 정의되어 있으나, **최근 실험(EXP-030~033)은 README.md를 작성하지 않는다**. 따라서 `experiment_*.json` 이 단일 진실 원본으로 간주한다.

### 2.2 experiment JSON 스키마

최상위 키: `timestamp`, `script`, `config`, `summary`, `battles`.

**`config`** — 실험 설정:

| 키 | 예시값 (EXP-032) | 설명 |
|----|------------------|------|
| `algorithm` | `io` | 프롬프트 알고리즘 (`io`/`minimax`/`react`/...) |
| `backend` | `ollama/glm-5.1:cloud` | LLM 백엔드 |
| `player_name` | `pokechamp` | 분석 대상 플레이어 |
| `opponent_name` | `abyssal` | 상대 |
| `opponent_backend` | `gemini-2.5-pro` | 상대 백엔드 |
| `opponent_algorithm` | `io` | 상대 알고리즘 |
| `battle_format` | `gen9ou` | 배틀 포맷 |
| `n_battles` | `30` | 배틀 수 |
| `seed` | `42` | 랜덤 시드 (재현성) |
| `temperature` | `0.3` | LLM temperature |
| `enable_dynamic_flags` | `false` | 동적 플래그 |
| `enable_dynamic_calcs` | `false` | 동적 계산 |
| `enable_showdown_oracle` | `false` | 오라클 |
| `enable_llm_lead_selection` | `false` | LLM 리드 선택 |

**`summary`** — 집계 통계:

| 키 | 예시값 (EXP-032) | 설명 |
|----|------------------|------|
| `win_rate` | `53.3` | 승률 (%) |
| `wins` | `16` | 승리 수 |
| `n_battles` | `30` | 총 배틀 수 |
| `avg_turns` | `39.0` | 평균 턴 수 |
| `avg_llm_calls` | `31.2` | 배틀당 평균 LLM 호출 |
| `avg_prompt_tokens` | `65221` | 배틀당 평균 prompt 토큰 |
| `avg_completion_tokens` | `2777` | 배틀당 평균 completion 토큰 |

**`battles[]`** — 배틀별 상세 (★ **error/retry 키 없음**):

```json
{"won": 1, "turns": 37, "prompt_tokens": 94556, "completion_tokens": 3417, "llm_calls": 40}
```

> ⚠️ 에러/파싱 실패/retry 정보는 `battles[]`에 없다. 반드시 **로그 파일에서 별도 추출**해야 한다 (4.4·4.5절).

### 2.3 로그 종류별 스키마

#### 2.3.1 IO / minimax → `llm_log.jsonl` (8키)

각 줄 = 1회 LLM 호출:

| 키 | 설명 |
|----|------|
| `turn` | 턴 번호 |
| `battle_tag` | 배틀 식별자 (예: `battle-gen9ou-663`) |
| `system_prompt` | 시스템 프롬프트 전문 |
| `user_prompt` | 배틀 상태 프롬프트 |
| `llm_response` | LLM 원시 응답 |
| `parsed_action` | 파싱된 액션 (`{"move": "..."}` / `{"switch": "..."}` / 에러 시 `{"error": ...}`) |
| `llm_call_count` | 배틀 내 호출 누적 카운트 |
| `timestamp` | 호출 시각 |

#### 2.3.2 react → `langgraph_llm_log.jsonl` (12키) + `langgraph_tool_log.jsonl` (4키)

**`langgraph_llm_log.jsonl`** 키: `timestamp`, `start_time`, `battle_tag`, `turn`, `decision_index`, `llm_call_in_turn`, `system_prompt`, `user_prompt`, `llm_response`, `tool_calls`, `token_usage`, `messages_full`.

**`langgraph_tool_log.jsonl`** — **두 종류 줄이 교대로 기록**된다 (호출 1건당 call/result 2줄):
- **`tool_call` 줄**: 키 `timestamp`, `battle_tag`, `turn`, `tool_call`. `tool_call` = `{"tool": <도구명>, "input": <입력>}` (예: `{"tool": "calculate_damage", "input": "{'move_name': 'earthquake'}"}`).
- **`tool_result` 줄**: 키 `timestamp`, `battle_tag`, `turn`, `tool_result`. `tool_result` = 도구 실행 결과 (JSON 문자열; 에러 시 `{"error": ...}` 포함).

> 집계 시 `tool_call` 줄과 `tool_result` 줄을 키 존재 여부로 구분해야 한다 (4.5절 참조).

### 2.4 알고리즘 분기 판단법

분석 전 `config.algorithm` 로 로그 종류를 결정한다:

```
config.algorithm ∈ {io, minimax, ...} (react 제외)  →  llm_log.jsonl 사용 (4.4절)
config.algorithm == react                           →  langgraph_*.jsonl 사용 (4.5절)
```

파일 존재 여부로도 교차 검증: `llm_log.jsonl` 이 있으면 IO/minimax 계열, `langgraph_tool_log.jsonl` 이 있으면 react 계열.

### 2.5 README.md 미작성 실험 대응

EXP-030~033 처럼 README.md가 없는 경우, `experiment_*.json` 의 `config` 블록에서 설정을 그대로 읽는다. 실험 "목적/가설"은 experiment-context.md 섹션 5(실험 인덱스)의 비고 컬럼이나 이전 분석 보고서에서 추론한다.

---

## 3. 분석 워크플로우 (5단계)

### Step 1. 입력 확인
- **입력**: EXP 디렉토리 경로.
- **수행**: 0.3 체크리스트로 파일 무결성 확인, 2.4 로 알고리즘 분기 결정, experiment-context.md 섹션 5 에서 비교 대상 EXP 식별.
- **산출물**: 알고리즘 종류, 비교 대상 EXP 목록.

### Step 2. 정량 데이터 추출
- **입력**: `experiment_*.json`.
- **수행**: 4.2 스니펫으로 config/summary 출력, 4.3 으로 턴 구간별 승률 분할.
- **산출물**: 승률(전체/구간), 리소스 사용량, 토큰 통계 → template 섹션 1.1·1.2.

### Step 3. 뷰어 생성 + 정성 분석
- **입력**: 배틀 HTML + 로그.
- **수행**: 4.1 로 뷨어 생성(최초 1회). `viewer/index.html` 로 요약 확인, 흥미로운 배틀(battle_tag)은 `--battle` 옵션으로 개별 뷰어 열어 reasoning·액션·재시도·도구 호출 흐름을 읽는다.
- **산출물**: 핵심 발견, 문제점의 로그 증거 → template 섹션 2·3.

### Step 4. 비교 분석
- **입력**: 본 EXP 데이터 + 이전 EXP 데이터.
- **수행**: 비교 대상 EXP(Step 1 식별)의 동일 메트릭을 추출하여 표로 병렬 비교. 변화(⬆⬇)와 이슈 추적(해결/완화/미해결) 정리.
- **산출물**: 변화 컬럼, 이슈 추적표, 개선 우선순위 → template 섹션 1.1 변화·4·5.

### Step 5. 보고서 작성
- **입력**: Step 2~4 산출물.
- **수행**: [`template.md`](template.md) 를 `docs/exp-{NNN}-{algo}-{model}-analysis.md` 로 복사 후 8절 순서대로 채운다.
- **산출물**: 완성된 분석 보고서. 7절 품질 체크리스트로 최종 검토.

---

## 4. 단계별 명령어 & 코드 스니펫

> 실행은 모두 **repo root** (`/workspace`) 기준 상대경로. Python 인터프리터는 `.venv/bin/python` 또는 `uv run python`.

### 4.1 뷰어 생성 (Step 3)

```sh
# 전체 배틀 뷰어 생성 (최초 1회) → {exp_dir}/viewer/index.html + viewer/{battle_tag}.html
uv run python tools/battle_viewer.py .temp/experiments/baselines/io-glm51

# 특정 배틀만 정성 분석 (index.html 링크에서 battle_tag 확인 후)
uv run python tools/battle_viewer.py .temp/experiments/baselines/io-glm51 --battle battle-gen9ou-663 --open
```

> **트러블슈팅**: `uv` 가 PATH에 없으면 `.venv/bin/python tools/battle_viewer.py ...` 또는 `python3 tools/battle_viewer.py ...` 사용.

### 4.2 정량 메트릭 추출 (Step 2)

```python
import json, glob
exp = ".temp/experiments/baselines/io-glm51"
jf = glob.glob(f"{exp}/battle_log/experiment_*.json")[0]
d = json.load(open(jf))
cfg, summ = d["config"], d["summary"]
print(f"algorithm={cfg['algorithm']} backend={cfg['backend']} N={cfg['n_battles']} seed={cfg['seed']} temp={cfg['temperature']}")
print(f"win_rate={summ['win_rate']}% ({summ['wins']}/{summ['n_battles']}) avg_turns={summ['avg_turns']} avg_llm_calls={summ['avg_llm_calls']}")
print(f"avg_prompt_tokens={summ['avg_prompt_tokens']} avg_completion_tokens={summ['avg_completion_tokens']}")
```

### 4.3 턴 구간 분할 (승률 구간화 — Step 2)

exp-030 분석에서 사용한 구간 기준(short<15 / mid 15-24 / long 25+):

```python
import collections
bs = d["battles"]
def bucket(t): return "short(<15)" if t < 15 else "mid(15-24)" if t < 25 else "long(25+)"
agg = collections.defaultdict(lambda: [0, 0])  # [wins, total]
for b in bs:
    k = bucket(b["turns"]); agg[k][1] += 1; agg[k][0] += b["won"]
for k, (w, n) in agg.items():
    print(f"{k}: {w}/{n} = {100*w/n:.1f}%")
```

### 4.4 IO / minimax 로그 분석 (파싱 실패 / 액션 분포 — Step 2·3)

`battles[]`에 error 키가 없으므로, `llm_log.jsonl` 의 `parsed_action` 으로 파싱 실패를 추출한다:

```python
import json
from collections import Counter
parse_fail = 0; total = 0; actions = Counter()
with open(f"{exp}/battle_log/llm_log.jsonl") as f:
    for ln in f:
        e = json.loads(ln); total += 1
        pa = e.get("parsed_action")
        if pa is None or "error" in str(pa).lower():
            parse_fail += 1
        else:
            # 액션 타입별 집계 (move / switch)
            actions[str(pa)[:40]] += 1
print(f"parse_fail={parse_fail}/{total} ({100*parse_fail/total:.1f}%)")
for a, c in actions.most_common(10):
    print(f"  {a}: {c}")
```

### 4.5 react 로그 분석 (도구 분포 / 에러율 — Step 2·3)

도구 분포는 `langgraph_tool_log.jsonl` 의 **`tool_call` 줄만** 집계한다 (`tool_result` 줄은 제외):

```python
import json
from collections import Counter
tool_calls = Counter(); total = 0
with open(f"{exp}/battle_log/langgraph_tool_log.jsonl") as f:
    for ln in f:
        e = json.loads(ln)
        if "tool_call" not in e:   # tool_result 줄은 건너뜀
            continue
        total += 1
        tool_calls[e["tool_call"]["tool"]] += 1
for t, c in tool_calls.most_common():
    print(f"{t}: {c} ({100*c/total:.1f}%)")
# 배틀당/턴당 정규화는 summary.avg_turns, summary.n_battles 활용
```

에러율은 **`tool_result` 줄**에서 결과 JSON을 파싱해 `"error"` 포함 여부로 판단한다 (battle_viewer.py L367-378 휴리스틱과 동일):

```python
import json
errors = 0; results = 0
with open(f"{exp}/battle_log/langgraph_tool_log.jsonl") as f:
    for ln in f:
        e = json.loads(ln)
        if "tool_result" not in e:
            continue
        results += 1
        try:
            parsed = json.loads(e["tool_result"])
            if isinstance(parsed, dict) and "error" in parsed:
                errors += 1
        except json.JSONDecodeError:
            pass
print(f"tool_errors={errors}/{results} ({100*errors/results:.1f}%)")
```

> react 전용 메트릭(도구 분포/에러율)은 template 섹션 1.3 에, IO/minimax 전용 메트릭(파싱 실패/재시도)은 template 섹션 3 의 문제점으로 기재한다 (5절 차이표 참조).

---

## 5. 알고리즘별 데이터 차이 대응표

| 메트릭 | IO / minimax | react | 추출 소스 |
|--------|:---:|:---:|-----------|
| 승률 (전체/구간) | ✅ | ✅ | `summary` + `battles[]` (4.2·4.3) |
| 평균 턴 수 | ✅ | ✅ | `summary.avg_turns` |
| 배틀당 LLM 호출 | ✅ | ✅ | `summary.avg_llm_calls` |
| 토큰 사용량 | ✅ | ✅ | `summary.avg_*_tokens` |
| **JSON 파싱 실패** | ✅ | — | `llm_log.jsonl` `parsed_action` (4.4) |
| **재시도(retry)** | ✅ | — | `llm_log.jsonl` 중복 호출 패턴 |
| **도구 사용 분포** | — | ✅ | `langgraph_tool_log.jsonl` (4.5) |
| **도구 에러율** | — | ✅ | `langgraph_llm_log.jsonl` tool 결과 |

react 의 파싱 실패는 도구 호출 흐름 내에서 처리되므로 "도구 에러율" 로 대체한다.

---

## 6. 규칙 준수 가이드 (experiment-context.md 섹션 0 연동)

> 규칙 원본은 [`experiment-context.md` 섹션 0](../experiment-context.md#0-agent-행동-규칙-read-first). 본 절은 분석 맥락에서의 적용만 다룬다.

### 6.1 범용 gen9ou 전략 원칙
분석의 **개선 권고**는 "다른 gen9ou 상대(LLM agent, human, ladder)에게도 동일하게 도움이 되는가?" 를 만족해야 한다. abyssal 특정 허점을 직접 공략하는 권고는 작성하지 않는다 (6.5절).

### 6.2 EXP 번호 / Baseline / 변경 1개 원칙
비교 분석 시, 비교 대상 EXP가 baseline(EXP-001) 대비 **변수 1개**만 다른 ablation 인지 확인한다. 여러 변수가 동시에 바뀐 비교는 인과 해석을 피하고 "상관" 으로만 기술한다.

### 6.3 재현성 (seed 42 / N≥30)
보고서 메타 헤더에 `seed`, `temperature`, `N` 을 명시한다. **N<30 인 진행 중 실험**은 template 의 ⚠️ 경고 박스로 통계 유의성 낮음을 표기한다.

### 6.4 배틀 실행 금지
분석 단계에서 **결과 JSON/로그가 이미 존재해야** 한다. 데이터가 누락되었을 때 에이전트가 직접 `--N` 배틀을 실행하지 말고, 사용자에게 실험 실행 명령어를 안내한다 (명령어 템플릿은 experiment-context.md 섹션 3 참조).

### 6.5 abyssal 특화 공략 발견 시 거부 판정
분석 중 "abyssal 의 matchup 임계값/Tera 미고려 등을 직접 노리면 승률이 오른다" 는 발견이 나오면, 그것을 개선 권고로 올리지 않고 **"범용 전략 관점에서 재검토 필요"** 로 명시한다.

---

## 7. 보고서 품질 체크리스트

완성된 보고서가 아래를 모두 만족하는지 최종 확인:

- [ ] **검증성**: 모든 정량 주장에 출처(`summary.xxx` / `battles[]` / 로그) 명시, 정성 주장은 로그 증거(`battle_tag` + 턴) 또는 코드 위치(`file.py:L`) 를 동반.
- [ ] **표 현시**: 비교(본 EXP vs 이전 EXP, 구간별, 도구별)는 항상 표로. 산문만으로 숫자 나열 금지.
- [ ] **우선순위 표기**: 문제점은 🔴 P0(치명) / 🟡 P1(중요) / 🟢 P2(개선) 로 분류.
- [ ] **액션 아이템**: 다음 단계는 `[ ]` 체크박스, 가능하면 목표 수치(예: "승률 50%+") 포함.
- [ ] **규칙 준수**: 6절 규칙(특히 6.1 범용 전략, 6.5 abyssal 특화 거부) 위반 권고 없음.

---

## 8. template.md 사용 방법

### 8.1 복사 → 파일명 규칙

```sh
cp exp_analysis/template.md docs/exp-{NNN}-{algo}-{model}-analysis.md
```

예: `docs/exp-032-io-glm51-analysis.md`. 파일명은 기존 보고서(`docs/exp-030-react-glm51-analysis.md`) 패턴을 따른다.

### 8.2 플레이스홀더 채우기 순서

1. **메타 헤더**: `{NNN}`, `{algorithm}`, `{model}`, `{N}`, `{opponent}`, `{YYYY-MM-DD}` → 4.2 결과값.
2. **1.1 승률 / 1.2 리소스**: 4.2·4.3 결과.
3. **1.3 도구 분포** (react) 또는 **3.x 파싱 실패** (IO/minimax): 4.4·4.5 결과.
4. **2 핵심 발견 / 3 문제점**: 4.1 뷰어 정성 분석 + 로그 증거.
5. **4 개선 현황 / 5 우선순위**: Step 4 비교 분석.
6. **6 다음 단계**: 체크박스 + 목표 수치.

> `<!-- ... -->` HTML 주석(출처 표기·가이드)은 **작성 완료 후 제거**한다. 단, 알고리즘 분기 안내 주석은 해당 섹션을 채운 후 제거.

### 8.3 진행 중 실험 (N<30) 표기 규칙

`n_battles < 30` 이면 메타 헤더 하단과 1.1 승률 표 하단에 경고 박스 삽입:

```
> ⚠️ N<30 통계 유의성 낮음. 완료(N=30) 후 재분석 필요.
```

### 8.4 메뉴얼 섹션 ↔ template 섹션 매핑

| 워크플로우 Step | 채워지는 template 섹션 | 스니펫 |
|----------------|----------------------|--------|
| Step 2 정량 추출 | 메타 헤더 + 1.1 승률 + 1.2 리소스 | 4.2, 4.3 |
| Step 3 뷰어/정성 | 2 핵심 발견 + 3 문제점 (로그 증거) | 4.1, 4.4/4.5 |
| Step 4 비교 분석 | 1.1 변화 컬럼 + 4 개선 현황 + 5 우선순위 | — |
| Step 5 작성 | 6 다음 단계 | — |
