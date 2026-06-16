#!/usr/bin/env python3
"""새 실험(EXP-NNN) 스캐폴드 생성 도우미.

``experiment-context.md`` §0 규칙(다음 EXP 순번 확인 · README 템플릿 · 로그 분리)을
자동으로 준수한다. §0-6 "수동 기록" 의 실패(준수율 0%)를 자동화로 대체 — §8 참조.

무엇을 하는가
------------
1. 다음 EXP 번호를 자동 할당 — active/+archive/ 디렉토리와 §5 이력표에서 사용된
   최대 EXP-NNN + 1.
2. ``.temp/experiments/active/EXP-NNN-{name}/battle_log`` 디렉토리 생성.
3. §4 README 템플릿 전개 (목적·가설·설정(변경점)·결과·분석).
4. baseline algo 에 맞는 실행 명령 안내 출력 (``--log_dir`` 자동 채움).
5. 현재 작업트리가 더티면 경고 — "이것이 의도된 ablation 변경인가?".

행동 규칙 (§0-8): 본 도구는 배틀을 실행하지 않는다. 디렉토리·README 생성과
명령어 안내까지만. 배틀은 사용자가 안내된 명령을 직접 실행한다.

사용법
------
::

    uv run python scripts/exp/new_experiment.py --name better-prompt --baseline minimax
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# /workspace — scripts/exp/ 의 조부모. _experiment_meta 와 동일 계산.
REPO = Path(__file__).resolve().parents[2]
EXPERIMENTS = REPO / ".temp" / "experiments"
CONTEXT = REPO / "experiment-context.md"

# baseline → (algo, battle script, 승률). 승률은 §5 source-of-truth 의 요약(드리프트
# 시 §5 기준). 새 baseline 추가 시 여기와 §5·§8 갱신.
BASELINE_INFO = {
    "io": {"algo": "io", "script": "local_1v1.py", "win_rate": "53.3% (16/30)"},
    "minimax": {
        "algo": "minimax",
        "script": "local_1v1.py",
        "win_rate": "80.0% (24/30)",
    },
    "react": {
        "algo": "react",
        "script": "local_1v1_langchain.py",
        "win_rate": "76.7% (23/30)",
    },
}

KEBAB_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def scan_exp_numbers() -> set[int]:
    """active/+archive/ 디렉토리 + §5 이력표에서 사용된 EXP-NNN 번호 수집."""
    nums: set[int] = set()
    for zone in ("active", "archive"):
        zdir = EXPERIMENTS / zone
        if zdir.is_dir():
            for d in zdir.iterdir():
                m = re.match(r"EXP-(\d{3})-?", d.name)
                if m:
                    nums.add(int(m.group(1)))
    if CONTEXT.exists():
        for m in re.finditer(r"EXP-(\d{3})", CONTEXT.read_text(encoding="utf-8")):
            nums.add(int(m.group(1)))
    return nums


def next_exp_id() -> int:
    nums = scan_exp_numbers()
    return (max(nums) + 1) if nums else 1


def build_command(exp_dir_rel: str, info: dict) -> str:
    algo = info["algo"]
    script = info["script"]
    return (
        f"uv run python scripts/battles/{script} \\\n"
        f"  --player_name pokechamp \\\n"
        f"  --player_prompt_algo {algo} \\\n"
        f"  --player_backend ollama/glm-5.1:cloud \\\n"
        f"  --opponent_name abyssal \\\n"
        f"  --opponent_backend gemini-2.5-pro \\\n"
        f"  --opponent_algorithm io \\\n"
        f"  --N 30 \\\n"
        f"  --battle_format gen9ou \\\n"
        f"  --temperature 0.3 \\\n"
        f"  --seed 42 \\\n"
        f"  --log_dir {exp_dir_rel}/battle_log"
    )


def build_readme(exp_id: str, name: str, baseline: str, info: dict) -> str:
    return f"""# {exp_id}: {name}

## 목적
<!-- 검증하려는 것을 한두 문장으로 -->

## 가설
<!-- 변경 → 기대 효과 -->

## 설정 (baseline 대비 변경점만 명시)
- baseline: **{baseline}** ({info['algo']}, {info['win_rate']}) — `.temp/experiments/baselines/{baseline}-glm51`
- 변경: <!-- §0-4 변경 1개 원칙 — baseline 대비 딱 1개만. 예: prompts.py 시스템 프롬프트 수정 -->
- (배틀 후 자동 기록) `meta.git_commit` / `dirty_patch_file` — §8 자동 추적

## 실행 명령 (사용자 직접 실행 — §0-8)
<!-- 아래는 안내된 명령. 코드 변경 후 실행. -->

## 결과
- 승률: / (배틀 후 기록)
- 평균 턴 수: ...
- JSON 파싱 실패: N회

## 분석
<!-- 배틀 후 작성 — `exp_analysis/ANALYSIS_MANUAL.md` 절차 + `exp_analysis/template.md` 로 보고서 작성 -->
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--name", required=True, help="kebab-case 실험 이름 (예: better-prompt)"
    )
    ap.add_argument(
        "--baseline",
        choices=list(BASELINE_INFO),
        default="minimax",
        help="비교 기준 baseline (기본 minimax)",
    )
    args = ap.parse_args()

    if not KEBAB_RE.match(args.name):
        print(
            f"오류: --name 은 kebab-case 여야 함 (소문자/숫자/하이픈): {args.name!r}",
            file=sys.stderr,
        )
        return 2

    n = next_exp_id()
    info = BASELINE_INFO[args.baseline]
    exp_id = f"EXP-{n:03d}"
    exp_name = f"{exp_id}-{args.name}"
    exp_dir = EXPERIMENTS / "active" / exp_name

    if exp_dir.exists():
        print(f"오류: 이미 존재 — {exp_dir}", file=sys.stderr)
        return 2

    battle_log = exp_dir / "battle_log"
    battle_log.mkdir(parents=True, exist_ok=True)

    readme = build_readme(exp_id, args.name, args.baseline, info)
    (exp_dir / "README.md").write_text(readme, encoding="utf-8")

    exp_dir_rel = exp_dir.relative_to(REPO).as_posix()

    # 더티 경고 — 의도된 ablation 변경인지 확인 (§0-4)
    dirty_note = ""
    try:
        sys.path.insert(0, str(REPO / "scripts" / "battles"))
        from _experiment_meta import collect_git_state  # type: ignore

        st = collect_git_state(REPO)
        if st.get("git_dirty"):
            files = st.get("git_dirty_files", [])
            dirty_note = (
                f"\n\n⚠️  작업트리가 더티({len(files)}개 파일 변경). "
                "이것이 본 실험의 의도된 ablation 변경인지 확인. "
                "배틀 로그에 자동으로 dirty patch 가 기록된다 (§8)."
            )
    except Exception:
        pass  # 경고는 부가 기능 — 실패해도 스캐폴드는 완료

    print(f"✓ 실험 스캐폴드 생성: {exp_dir_rel}/")
    print(f"    EXP-ID    : {exp_id} (다음 순번)")
    print(f"    baseline  : {args.baseline} ({info['algo']}, {info['win_rate']})")
    print(f"    README    : {exp_dir_rel}/README.md")
    print()
    print("▶ 실행 명령 (코드 변경 후 사용자 직접 실행 — §0-8):")
    print()
    print(build_command(exp_dir_rel, info))
    print()
    print("▶ 배틀 후:")
    print(
        "    1. 코드 변경 보존: uv run python scripts/exp/preserve_code_state.py "
        f"{exp_name}"
    )
    print(
        "    2. 변경 1개 검증 : uv run python scripts/exp/verify_single_change.py "
        f"{exp_id} --baseline {args.baseline}"
    )
    print(f"    3. 분석 보고서   : exp_analysis/ANALYSIS_MANUAL.md 절차")
    print(dirty_note)
    return 0


if __name__ == "__main__":
    sys.exit(main())
