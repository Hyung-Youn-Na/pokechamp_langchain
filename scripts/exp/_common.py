#!/usr/bin/env python3
"""scripts/exp/ 스크립트 공통 유틸.

preserve_code_state.py · verify_single_change.py 가 공유하는 실험 디렉토리 해석·
JSON 탐색 로직. (``experiment-context.md`` §8 도구군)
"""

from __future__ import annotations

import json
from pathlib import Path

# /workspace
REPO = Path(__file__).resolve().parents[2]
EXPERIMENTS = REPO / ".temp" / "experiments"

# baseline 알고리즘 → baselines/ 디렉토리명 (§5)
BASELINE_DIR = {
    "io": "io-glm51",
    "react": "react-glm51",
    "minimax": "minimax-glm51",
}


def resolve_exp_dir(arg: str) -> Path:
    """인자를 실험 디렉토리로 해석. 경로면 그대로, 이름이면 active/→archive/ 탐색."""
    p = Path(arg)
    if p.is_absolute():
        return p
    if p.is_dir():
        return p.resolve()
    for zone in ("active", "archive"):
        cand = EXPERIMENTS / zone / arg
        if cand.is_dir():
            return cand
    name = p.parts[-1] if p.parts else arg
    for zone in ("active", "archive"):
        cand = EXPERIMENTS / zone / name
        if cand.is_dir():
            return cand
    raise FileNotFoundError(f"실험 디렉토리를 찾을 수 없음: {arg}")


def find_latest_experiment_json(exp_dir: Path) -> Path | None:
    """exp_dir/battle_log/experiment_*.json 중 mtime 최신. 없으면 None.

    mtime 동률(같은 초) 시 파일명(ts 접미사 포함)을 보조 정렬키로 써 결정성 확보.
    """
    bdir = exp_dir / "battle_log"
    if not bdir.is_dir():
        return None
    candidates = sorted(
        bdir.glob("experiment_*.json"), key=lambda p: (p.stat().st_mtime, p.name)
    )
    return candidates[-1] if candidates else None


def load_experiment_json(path: Path) -> dict:
    """experiment JSON 로드. 문법 오류 시 명확한 에러로 종료."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"오류: experiment JSON 파싱 실패 — {path}: {exc}") from exc
