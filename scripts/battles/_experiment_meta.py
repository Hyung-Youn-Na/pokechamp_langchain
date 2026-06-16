#!/usr/bin/env python3
"""배틀 스크립트용 git-상태 메타 수집 헬퍼.

실험 로그(``experiment_*.json``)의 ``meta`` 블록을 조립해, 각 실험이 "정확히 어느
코드 상태에서, 어떤 명령으로, 어느 baseline 대비 무엇이 달라졌는지"를 재현
가능하게 한다. ``experiment-context.md`` §8 참조.

왜 필요한가
-----------
§0-6 은 "README 에 커밋 해시를 수동으로 기록" 하라고 했지만 실제 준수율 0%.
대신 배틀 스크립트가 JSON 에 git 상태를 **자동** 으로 기록한다. 수동 규칙은 이미
실패했으므로 자동화로 마찰을 없앤다 (§7 백업과 동일 철학).

설계 원칙
---------
- **stdlib 만** (subprocess). 배틀 의존성과 분리.
- **git 호출 전부 방어**. git 이 없거나 비-repo 여도 배틀은 죽지 않는다
  (실패 시 ``git_error`` 만 채우고 나머지는 null).
- **더티(uncommitted) 변경** 은 ``git diff HEAD`` patch 로 log_dir 에 덤프.
  untracked(새 파일)는 patch 에 미포함 — ``dirty_files`` 에만 상태와 함께 기록.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# /workspace — backup_baselines.py 와 동일 계산 (scripts/battles/ 의 조부모)
REPO = Path(__file__).resolve().parents[2]

_GIT_TIMEOUT = 10  # 초 — git 호출 하나당 상한


def _run_git(args: list[str], cwd: Path) -> tuple[int, str, str]:
    """git 서브커맨드 실행 → (returncode, stdout, stderr). 예외 시 (1, "", err)."""
    try:
        r = subprocess.run(
            ["git", "-C", str(cwd), *args],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT,
        )
        return r.returncode, r.stdout, r.stderr
    except Exception as exc:  # FileNotFoundError, TimeoutExpired, ...
        return 1, "", str(exc)


def collect_git_state(repo_root: Path) -> dict:
    """repo 의 git 상태를 수집. 실패 시 git_error 에 메시지, 나머지는 null/빈값."""
    state: dict = {
        "git_commit": None,
        "git_commit_short": None,
        "git_branch": None,
        "git_dirty": False,
        "git_dirty_files": [],
        "git_dirty_stat": None,
        "git_error": None,
    }

    rc, out, err = _run_git(["rev-parse", "--is-inside-work-tree"], repo_root)
    if rc != 0:
        state["git_error"] = f"not a git repo: {(err or out).strip()}"
        return state

    rc, out, _ = _run_git(["rev-parse", "HEAD"], repo_root)
    if rc != 0:
        state["git_error"] = "no HEAD (empty repo?)"
        return state
    state["git_commit"] = out.strip()

    rc, out, _ = _run_git(["rev-parse", "--short", "HEAD"], repo_root)
    state["git_commit_short"] = out.strip() or None

    rc, out, _ = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], repo_root)
    state["git_branch"] = out.strip() or "HEAD"

    rc, out, _ = _run_git(["status", "--porcelain=v1"], repo_root)
    if rc == 0:
        files = []
        for line in out.splitlines():
            if len(line) < 4:
                continue
            # porcelain v1: "XY path" 또는 rename 시 "XY orig -> dest"
            path = line[3:]
            if " -> " in path:
                path = path.split(" -> ", 1)[1]
            # git 은 공백/특수문자 경로를 C 스타일 quoting 함
            if len(path) >= 2 and path.startswith('"') and path.endswith('"'):
                path = path[1:-1].replace('\\"', '"').replace("\\\\", "\\")
            files.append(path)
        state["git_dirty_files"] = files
        state["git_dirty"] = len(files) > 0

    rc, out, _ = _run_git(["diff", "HEAD", "--stat"], repo_root)
    if rc == 0:
        lines = [ln for ln in out.strip().splitlines() if ln.strip()]
        # 마지막 요약 줄 ("N files changed, M insertions(+), K deletions(-)")
        state["git_dirty_stat"] = lines[-1] if lines else None

    return state


def dump_dirty_patch(repo_root: Path, out_path: Path) -> bool:
    """``git diff HEAD`` 를 out_path 에 쓴다. 변경이 없으면 False (파일 미생성).

    untracked(새 파일)는 포함되지 않는다 — 그것들은 ``dirty_files`` 에만 기록.
    """
    rc, out, _ = _run_git(["diff", "HEAD"], repo_root)
    if rc != 0 or not out.strip():
        return False
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(out, encoding="utf-8")
    return True


def build_meta(repo_root: Path, dirty_patch_file: str | None) -> dict:
    """meta 블록 조립: git 상태 + argv + python 버전 + repo root.

    ``dirty_patch_file`` 은 dump_dirty_patch 가 산출한 파일의 **이름만** (내용 X).
    None 이면 깨끗한 트리이거나 patch 생성 실패.
    """
    meta = collect_git_state(repo_root)
    meta["dirty_patch_file"] = dirty_patch_file
    meta["argv"] = list(sys.argv)
    meta["python_version"] = sys.version.split()[0]
    meta["repo_root"] = str(repo_root)
    return meta
