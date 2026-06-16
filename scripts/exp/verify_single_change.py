#!/usr/bin/env python3
""""변경 1개 원칙" (experiment-context.md §0-4) 자동 검증.

주어진 실험이 baseline 대비 **정확히 1개** 만 변경했는지 검사한다. 변경은 두 종류:
1. **파라미터 변경** — ``config`` 블록의 키 값 차이 (temperature, seed, enable_* 등).
2. **코드 변경** — ``meta.git_dirty_files`` (커밋되지 않은 파일).

총 변경 = (파라미터 diff 수) + (코드 파일 수). 1 이면 PASS, 아니면 FAIL.

한계 (§8.5)
-----------
baseline 3종의 정확한 **코드 커밋** 은 소실됐다 (06-12 더티 트리에서 실행). 따라서
코드 변경 검증은 "실험 시점의 더티 파일" 기준이며, baseline 코드 상태와의 직접 비교가
아니다. 파라미터 diff 는 baseline JSON ``config`` (canonical) 와 정확히 비교한다.

사용법
------
::

    uv run python scripts/exp/verify_single_change.py EXP-034-foo --baseline minimax

행동 규칙 (§0-8): 읽기 전용. 배틀 실행·파일 수정 없음.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from _common import (
    EXPERIMENTS,
    BASELINE_DIR,
    REPO,
    resolve_exp_dir,
    find_latest_experiment_json,
    load_experiment_json,
)

# config 비교 시 무시 — 스키마/메타 키 (ablation 변수가 아님)
IGNORE_CONFIG_KEYS = {"script", "experiment_id"}

# 이 도구들 자신이 dirty_files 에 들어가면 노이즈 — 경고용
TOOL_PATH_PREFIXES = ("scripts/exp/", "scripts/battles/_experiment_meta.py")


def find_baseline_json(baseline: str) -> Path | None:
    bdir = EXPERIMENTS / "baselines" / BASELINE_DIR[baseline] / "battle_log"
    if not bdir.is_dir():
        return None
    cand = sorted(bdir.glob("experiment_*.json"), key=lambda p: p.stat().st_mtime)
    return cand[-1] if cand else None


def config_diff(base_cfg: dict, exp_cfg: dict) -> list[dict]:
    changes: list[dict] = []
    keys = (set(base_cfg) | set(exp_cfg)) - IGNORE_CONFIG_KEYS
    for k in sorted(keys):
        if base_cfg.get(k) != exp_cfg.get(k):
            changes.append(
                {
                    "key": k,
                    "baseline": base_cfg.get(k),
                    "experiment": exp_cfg.get(k),
                }
            )
    return changes


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("exp", help="실험 디렉토리 경로 또는 EXP-NNN-name")
    ap.add_argument(
        "--baseline",
        choices=list(BASELINE_DIR),
        required=True,
        help="비교 기준 baseline",
    )
    args = ap.parse_args()

    base_json = find_baseline_json(args.baseline)
    if base_json is None:
        print(
            f"오류: baseline JSON 없음 — baselines/{BASELINE_DIR[args.baseline]}/",
            file=sys.stderr,
        )
        return 2
    base_data = load_experiment_json(base_json)
    base_cfg = base_data.get("config", {})

    try:
        exp_dir = resolve_exp_dir(args.exp)
    except FileNotFoundError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 2
    exp_json = find_latest_experiment_json(exp_dir)
    if exp_json is None:
        print(f"오류: experiment_*.json 없음 — {exp_dir}/battle_log/", file=sys.stderr)
        return 2
    exp_data = load_experiment_json(exp_json)
    exp_cfg = exp_data.get("config", {})
    exp_meta = exp_data.get("meta") or {}

    cfg_changes = config_diff(base_cfg, exp_cfg)

    if exp_meta:
        dirty_files = exp_meta.get("git_dirty_files", [])
        meta_note = (
            f"commit {exp_meta.get('git_commit_short', '?')}, "
            f"dirty={exp_meta.get('git_dirty')}"
        )
    else:
        dirty_files = []
        meta_note = "메타 없음 (§8 이전 실험) — 코드 변경 검증 불가"

    # 도구 자체 노이즈 분리
    tool_noise = [f for f in dirty_files if f.startswith(TOOL_PATH_PREFIXES)]
    real_dirty = [f for f in dirty_files if not f.startswith(TOOL_PATH_PREFIXES)]

    total = len(cfg_changes) + len(real_dirty)
    passed = total == 1

    print(f"baseline : {args.baseline} ({BASELINE_DIR[args.baseline]})")
    print(f"  config : {base_json.relative_to(REPO)}")
    print(f"실험     : {exp_dir.name}")
    print(f"  config : {exp_json.relative_to(REPO)}")
    print(f"  meta   : {meta_note}")
    print()
    print(f"파라미터 변경 (config diff): {len(cfg_changes)}개")
    for c in cfg_changes:
        print(f"  - {c['key']}: {c['baseline']!r} → {c['experiment']!r}")
    if not cfg_changes:
        print("  (없음)")
    print()
    print(f"코드 변경 (dirty files): {len(real_dirty)}개")
    for f in real_dirty:
        print(f"  - {f}")
    if not real_dirty:
        print("  (없음)")
    print()

    if tool_noise:
        print(f"⚠️  자동 추적 도구 자체 변경({len(tool_noise)}개)은 카운트에서 제외:")
        for f in tool_noise:
            print(f"    - {f}")
        print("    (ablation 변경과 분리해 별도 커밋 권장)\n")

    print(f"총 변경: {len(cfg_changes)} + {len(real_dirty)} = {total}개")
    if not exp_meta:
        print("⚠️  메타가 없어 코드 변경은 미검증. 파라미터 diff 만 판정.")
    if passed:
        print("✅ PASS — 변경 1개 원칙(§0-4) 준수.")
        return 0
    if total == 0:
        print("ℹ️  변경 0개 — baseline 과 동일. ablation 변경을 추가했는지 확인.")
    else:
        print(f"❌ FAIL — {total}개 변경 (§0-4 위반). baseline 대비 변수 1개로 줄이세요.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
