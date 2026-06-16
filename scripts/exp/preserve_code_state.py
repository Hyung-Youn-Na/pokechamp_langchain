#!/usr/bin/env python3
"""실험의 더티 코드 상태를 git-tracked 영역으로 보존.

배틀이 끝난 **후** 실행한다. ``experiment_*.json`` 의 ``meta`` 블록에서
``dirty_patch_file`` 을 찾아 ``backups/code_state/{EXP-ID}/`` 로 복사한다.

왜 필요한가 (``experiment-context.md`` §8.2)
-------------------------------------------
배틀은 보통 코드 수정 후 커밋 전(더티 트리)에 돈다. 더티 diff 는 배틀 스크립트가
``.temp/.../battle_log/*_dirty.patch`` 에 남기지만, ``.temp/`` 전체가 ``.gitignore``
(무시됨)라 **push 하면 소실** 된다. 본 도구가 그 patch 를 ``.temp/`` 바깥
(``backups/``, tracked) 으로 옮긴다. 그 후 ``git commit && git push`` 하면 GitHub
원격에 코드 변경이 보존된다 (§7 baseline 백업과 동일 구조·동일 철학).

사용법
------
::

    uv run python scripts/exp/preserve_code_state.py EXP-034-foo
    uv run python scripts/exp/preserve_code_state.py .temp/experiments/active/EXP-034-foo

산물 (``backups/code_state/{EXP-ID}/``)
---------------------------------------
- ``{dirty_patch_file}`` — ``git diff HEAD`` 결과 (tracked 파일 수정분)
- ``meta.json`` — 실험 로그의 ``meta`` 블록 전체 (commit·argv·dirty_files 등)

clean tree 였으면 아무것도 복사하지 않고 메시지만 출력한다.

행동 규칙 (§0-8): 본 도구는 배틀을 실행하지 않는다. ``.temp/`` 를 **읽고**
``backups/`` 에 **쓰기** 만 한다. baseline은 건드리지 않는다.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from _common import (
    REPO,
    resolve_exp_dir,
    find_latest_experiment_json,
    load_experiment_json,
)

BACKUP_ROOT = REPO / "backups" / "code_state"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "exp",
        help="실험 디렉토리 경로 또는 EXP-NNN-name (active/→archive/ 순 탐색)",
    )
    args = ap.parse_args()

    try:
        exp_dir = resolve_exp_dir(args.exp)
    except FileNotFoundError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 2

    json_path = find_latest_experiment_json(exp_dir)
    if json_path is None:
        print(
            f"오류: experiment_*.json 없음 — {exp_dir}/battle_log/", file=sys.stderr
        )
        return 2

    data = load_experiment_json(json_path)
    meta = data.get("meta")
    if not meta:
        print(
            f"오류: meta 블록 없음 — §8 자동 추적 이전 실험({json_path.name}). "
            "코드 상태 보존 불가.",
            file=sys.stderr,
        )
        return 1

    if not meta.get("git_dirty"):
        commit = meta.get("git_commit_short", "?")
        print(f"clean tree (commit {commit}) — 보존할 더티 코드 없음.")
        return 0

    patch_name = meta.get("dirty_patch_file")
    if not patch_name:
        print(
            "오류: git_dirty=true 이나 dirty_patch_file 없음 (patch dump 실패했을 수 있음).",
            file=sys.stderr,
        )
        return 1

    src_patch = json_path.parent / patch_name
    if not src_patch.exists():
        print(f"오류: patch 파일 없음 — {src_patch}", file=sys.stderr)
        return 1

    exp_id = exp_dir.name
    dest_dir = BACKUP_ROOT / exp_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_patch = dest_dir / patch_name
    shutil.copy2(src_patch, dest_patch)
    (dest_dir / "meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    print(f"✓ 코드 상태 보존: {dest_dir.relative_to(REPO)}/")
    print(f"    patch     : {patch_name} ({dest_patch.stat().st_size:,} bytes)")
    print(f"    meta.json : commit {meta.get('git_commit_short', '?')}, "
          f"dirty_files {len(meta.get('git_dirty_files', []))}개")
    print(f"    원본 출처: {json_path.relative_to(REPO)}")
    print("    → git add backups/code_state/ && git commit && git push 로 보존 완료.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
