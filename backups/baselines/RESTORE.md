# Baseline 데이터셋 백업 · 복원 안내

> `.temp/experiments/baselines/` (gitignored) 의 **공식 baseline 3종**(io/react/minimax-glm51,
> 162파일)을 버전화된 tar.zst blob 으로 git 트랙 영역에 보존. 디스크 장애로 `.temp/` 를
> 잃어도 `git clone` 한 번으로 baseline 전체(90개의 비재생성 가능한 Showdown HTML replay 포함)를
> 바이트 단위로 복원할 수 있다.

---

## 산물

| 파일 | 크기 | 역할 |
|------|------|------|
| `baselines-full-v1.tar.zst` | 2,968,287 bytes (2.97 MB) | 전체 baseline 디렉토리 트리의 zstd 압축 blob |
| `baselines-full-v1.sha256manifest.json` | ~31 KB | blob 메타 + 파일별 `{path, sha256, bytes}` (162 엔트리) |

- **blob sha256**: `aba1f01ad5c728c9dfa0a3e7dbb90adbddaa70ce613cba0b94ecc31d4ea2aa1b`
- **codec**: zstd (시스템 `tar --zstd`). zstd 미가용 환경에선 자동 gzip 폴백.
- **파일 구성**: 152 html · 3 json(핵심 메트릭) · 4 jsonl(LLM 로그) · 3 md(README)

### 왜 tar.zst 인가
`.gitignore` 가 `*.html`(L27)·`*.jsonl`(L21) 을 **전역** 으로 무시한다. 따라서 90개 HTML
replay와 JSONL 로그는 어떤 경로에 둬도 git-add 할 수 없다. 반면 `.tar.zst` 와 매니페스트의
`.json` 은 추적 가능(검증됨). 디렉토리를 blob 하나로 묶어 이 제약을 우회한다.

### 왜 매니페스트가 `.json` 인가 (`.jsonl` 이 아님)
파일명에 공백(`pokechamp7493 - battle-gen9ou-635.html`)과 콜론
(`experiment_io_ollama_glm-5.1:cloud_...json`)이 섞여 있어 공백 구분 텍스트(sha256sum
스타일)는 파싱 불가하다. JSON 이 안전하다. **주의**: `.jsonl` 매니페스트는 `*.jsonl`
gitignore 규칙에 잡혀 커밋되지 않으므로 **반드시 `.json` 확장자를 써야 한다** (이것이
`.jsonl` → `.json` 으로 바뀐 이유).

---

## EXP 매핑 (출처: [experiment-context.md](../../experiment-context.md) §5)

> baseline은 io/minimax JSON에 `experiment_id` 키가 없다(react만 `EXP-031` 보유). 따라서
> EXP↔baseline 매핑의 정당한 출처는 본 파일이 아니라 `experiment-context.md` §5 이다.
> 아래는 편의를 위한 요약이며, 정합성은 항상 원본 §5를 기준으로 한다.

| EXP | baseline | algo | 승률 | 비고 |
|-----|----------|------|------|------|
| EXP-031 ★ | react-glm51 | react | 76.7% (23/30) | experiment_id=EXP-031 (JSON에 포함) |
| EXP-032 ★ | io-glm51 | io | 53.3% (16/30) | experiment_id 누락 |
| EXP-033 ★ | minimax-glm51 | minimax | 80.0% (24/30) | experiment_id 누락 |

---

## 계약: live-canonical vs recovery-snapshot ★

- **`.temp/experiments/baselines/`** = **canonical live copy**. ablation 비교가 실제로
  읽는 소스. 언제나 최우선.
- **`backups/baselines/`** = **recovery-only snapshot**. 디스크 장애 복원용. **편집 금지.**
  이 디렉토리의 파일을 직접 손대지 말 것. baseline을 갱신하려면 [유지보수](#유지보수) 절차.

source-of-truth 가 둘로 쪼개지지 않도록: canonical은 `.temp/`, snapshot은 여기. snapshot이
canonical과 어긋나면(누군가 `.temp/` baseline을 직접 수정) `verify` 가 감지한다.

---

## 복원 절차

### 재난 복원 (`.temp/` 전체 손실 시)

```sh
# 1. (git repo 자체가 살아있거나 clone) 최신 blob/매니페스트가 있는지 확인
ls backups/baselines/

# 2. canonical 위치에 전체 복원 — 90개 HTML replay · 로그 · 메트릭 모두 포함
uv run python scripts/backup/backup_baselines.py restore --dest .temp/experiments/baselines
#   → OK (162/162 files verified, 0 mismatches) 가 떠야 성공

# 3. (선택) viewer 재생성 — react는 원래 viewer가 없었으므로 이 단계에서 채워짐
uv run python tools/battle_viewer.py .temp/experiments/baselines/io-glm51
uv run python tools/battle_viewer.py .temp/experiments/baselines/react-glm51
uv run python tools/battle_viewer.py .temp/experiments/baselines/minimax-glm51
```

복원 직후 battle_viewer.py가 정상 작동한다(`battle_log/*.html` 의존성이 충족되므로) —
즉 [ANALYSIS_MANUAL.md](../../exp_analysis/ANALYSIS_MANUAL.md) 의 정성 분석 파이프라인
(viewer step, IO/minimax·react 로그 분석 step) 도 완전히 복구된다.

### 복원 드릴 (정기 점검 · live 트리 건드리지 않음)

```sh
uv run python scripts/backup/backup_baselines.py restore --dest /tmp/restore-drill
```

---

## 검증 (4단계 · backup is theater 인지 증명)

```sh
# (A) 빌드 시 무결성 — blob 재추출 + per-file sha256 재계산 + 매니페스트 diff
uv run python scripts/backup/backup_baselines.py verify
#   기대: [v1] OK (162/162 files verified, 0 mismatches), exit 0

# (B) 복원 드릴 — /tmp 복원 후 메트릭 앵커 확인 (정성적으로 복원 가능함을 증명)
uv run python scripts/backup/backup_baselines.py restore --dest /tmp/restore-drill
python -c "import json; d=json.load(open('/tmp/restore-drill/react-glm51/battle_log/experiment_react_glm-5.1_cloud.json')); print('react', d['summary']['win_rate'], d.get('experiment_id'))"
#   기대: react 76.7 EXP-031
# (io 53.3, minimax 80.0 도 동일하게 확인)
rm -rf /tmp/restore-drill

# (C) 재난 복원 — 위 "재난 복원" 절차. 복원 트리 == 원본 임을 diff 로 확인 가능.

# (D) 오프디스크 내구성 ★ — blob 가 GitHub 원격에 실제로 존재하는지 확인
#     (commit 만 하고 push 안 하면 로컬 단일 복사 = 백업이 아님)
git ls-remote origin refs/heads/main          # remote HEAD 가 local 과 일치?
git cat-file -s $(git rev-parse origin/main:backups/baselines/baselines-full-v1.tar.zst)
#   기대: 2968287 (0 이면 원격에 blob 없음 = 백업 미완료)
```

> **(D) 가 핵심이다.** 로컬 `.git` 은 `.temp/` 와 같은 디스크에 있어, 디스크 장애에
> 함께 죽는다. `git push origin main` 이 blob 를 GitHub 로 옮기는 **유일한** 내구성
> 메커니즘이다. (D) 가 0 이 아닌 크기를 출력해야 백업이 완료된 것이다.

---

## 유지보수

### 새 baseline 추가 시 (예: `baselines/minimax-qwen3/`)
1. `scripts/backup/backup_baselines.py` 의 `BASELINE_NAMES` 리스트에 이름 추가.
2. `uv run python scripts/backup/backup_baselines.py backup` → 새 버전(`-v2`) blob 생성.
3. `verify` 실행 확인.
4. `git add backups/baselines/ scripts/backup/backup_baselines.py && git commit && git push`.
5. (D) 원격 확인.

### 백업 갱신 (baseline이 의도적으로 수정된 경우 — §4상 거의 일어나지 않음)
- `backup` 은 per-file sha256 이 동일하면 재아카이브를 생략(idempotent).
- 강제 재생성은 `backup --force`. 새 버전 번호로 새 blob 생성(이전 blob 는 히스토리에 잔류).

### 주기적 점검
- `verify` 를 정기(예: 월 1회) 실행해 bit-rot / silent corruption 을 감지.
- `.temp/` baseline 이 직접 수정됐는지 확인하려면 `restore --dest /tmp/x` 후 `diff -rq .temp/experiments/baselines /tmp/x`.
