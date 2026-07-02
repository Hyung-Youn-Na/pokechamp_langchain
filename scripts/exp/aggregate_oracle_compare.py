#!/usr/bin/env python3
"""``oracle_compare.jsonl`` 집계 — calc vs Showdown oracle 데미지 차이 요약.

``--oracle_backend compare`` 실배틀이 남긴 ``.temp/oracle_compare.jsonl`` (한 줄에
JSON 레코드)을 읽어 데미지 정확도 metric을 표로 산출한다. 배틀을 실행하지 않는다
(§0-8 읽기 전용).

레코드 스키마(``pokechamp/oracle_compare.py:_log_diff``)::
    {"move_id","atk","defn",
     "showdown":{"median_pct","min_pct","max_pct","type","base_power"} | null,
     "damagecalc":{...} | null,
     "delta_median_pct": <showdown − damagecalc> | null,
     "type_match": bool | null}

사용법::
    .venv/bin/python scripts/exp/aggregate_oracle_compare.py <exp-dir|jsonl-path> [--log PATH]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO = Path(__file__).resolve().parents[2]

# 동적 위력/타입 무브 — 카테고리 분류용(결정적이지 않아도 됨, 발산 그룹화 목적).
DYNAMIC_MOVES = {
    "facade", "knockoff", "hex", "acrobatics", "terablast", "weatherball",
    "ivycudgel", "terrainpulse", "revelationdance", "pursuit", "stompingtantrum",
    "brine", "assurance", "ragefist", "revenge", "magnitude", "magnitude10",
    "round", "echoedvoice", "storedpower", "trumpcard", "fling", "naturalgift",
    "terastarstorm", "hiddenpower", "grassknot", "lowkick", "heavyslam",
    "gyroball", "electroball",
}


def resolve_log(path: str, log_override: Optional[str]) -> Path:
    p = Path(path)
    if p.is_file():
        return p
    if p.is_dir():
        return Path(log_override) if log_override else REPO / ".temp" / "oracle_compare.jsonl"
    # 도움말: 존재 않는 경로면 기본 로그로 간주해 에러 메시지 통일
    return Path(log_override) if log_override else REPO / ".temp" / "oracle_compare.jsonl"


def load_records(log: Path) -> List[Dict[str, Any]]:
    recs: List[Dict[str, Any]] = []
    with log.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                recs.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return recs


def _med(s: Optional[Dict[str, Any]]) -> Optional[float]:
    if not s:
        return None
    v = s.get("median_pct")
    return v if isinstance(v, (int, float)) else None


def categorize(rec: Dict[str, Any]) -> str:
    # 동적 무브 우선: 차이 원인이 동적 처리(knockoff/facade/terablast/weatherball…)
    # 인 것이 명확하므로 KO clamp 보다 먼저 분류한다.
    if str(rec.get("move_id", "")).lower() in DYNAMIC_MOVES:
        return "dynamic-move"
    sm, dm = _med(rec.get("showdown")), _med(rec.get("damagecalc"))
    vals = [v for v in (sm, dm) if v is not None]
    # KO clamp: 한쪽이 KO(≥100%)인데 다른 쪽과 차이 — 측정방식(clamp vs overkill) 차이
    if vals and max(vals) >= 100:
        return "ko-clamp"
    return "normal"


def pct(q: float, data: List[float]) -> float:
    """간단 백분위수(정렬 후 인덱스)."""
    if not data:
        return 0.0
    s = sorted(data)
    k = max(0, min(len(s) - 1, int(round(q * (len(s) - 1)))))
    return s[k]


def aggregate(recs: List[Dict[str, Any]]) -> None:
    n = len(recs)
    print(f"=== oracle_compare 집계 ({n} 레코드) ===\n")

    # --- (1) 전체 요약 ---
    both_ok = [r for r in recs if r.get("showdown") and r.get("damagecalc")]
    sd_only = [r for r in recs if r.get("showdown") and not r.get("damagecalc")]
    dc_only = [r for r in recs if r.get("damagecalc") and not r.get("showdown")]
    neither = [r for r in recs if not r.get("showdown") and not r.get("damagecalc")]
    tm = [r for r in recs if r.get("type_match") is True]
    tm_false = [r for r in recs if r.get("type_match") is False]
    tm_avail = len(tm) + len(tm_false)
    deltas = [r["delta_median_pct"] for r in recs if isinstance(r.get("delta_median_pct"), (int, float))]
    abs_deltas = [abs(d) for d in deltas]

    print("## (1) 전체 요약")
    print(f"  총 레코드          : {n}")
    print(f"  양쪽 ok (가용)     : {len(both_ok)} ({len(both_ok)/n*100:.1f}%)" if n else "  양쪽 ok: 0")
    print(f"  showdown 전용(null): {len(sd_only)}   | damagecalc 전용: {len(dc_only)}   | 둘 다 null: {len(neither)}")
    if tm_avail:
        print(f"  type 일치율        : {len(tm)}/{tm_avail} = {len(tm)/tm_avail*100:.2f}%  (불일치 {len(tm_false)})")
    if deltas:
        print(
            f"  delta_median_pct   : mean={statistics.mean(deltas):+.2f}  "
            f"median={statistics.median(deltas):+.2f}  p90|Δ|={pct(0.9, abs_deltas):.1f}  "
            f"max|Δ|={max(abs_deltas):.1f}"
        )
    sd_gt = sum(1 for d in deltas if d > 0)  # showdown > damagecalc = oracle 과대
    dc_gt = sum(1 for d in deltas if d < 0)  # calc 과대
    if deltas:
        print(f"  방향성             : oracle 과대(sd>dc) {sd_gt} | calc 과대(dc>sd) {dc_gt} | 동일 {len(deltas)-sd_gt-dc_gt}")
    print()

    # --- (2) 카테고리별 ---
    cats: Dict[str, List[Dict[str, Any]]] = {"ko-clamp": [], "dynamic-move": [], "normal": []}
    for r in recs:
        cats[categorize(r)].append(r)
    print("## (2) 카테고리별 차이")
    print(f"  {'category':14} {'count':>6} {'avg|Δ|':>8} {'oracle과대':>10} {'calc과대':>9}")
    for cat in ("ko-clamp", "dynamic-move", "normal"):
        rs = cats[cat]
        if not rs:
            continue
        ds = [abs(r["delta_median_pct"]) for r in rs if isinstance(r.get("delta_median_pct"), (int, float))]
        ovr = sum(1 for r in rs if isinstance(r.get("delta_median_pct"), (int, float)) and r["delta_median_pct"] > 0)
        cvr = sum(1 for r in rs if isinstance(r.get("delta_median_pct"), (int, float)) and r["delta_median_pct"] < 0)
        avg = statistics.mean(ds) if ds else 0.0
        print(f"  {cat:14} {len(rs):>6} {avg:>8.1f} {ovr:>10} {cvr:>9}")
    print()

    # --- (3) top-K move/매치업 (|delta| 큰 순) ---
    ranked = sorted(
        [r for r in recs if isinstance(r.get("delta_median_pct"), (int, float))],
        key=lambda r: abs(r["delta_median_pct"]),
        reverse=True,
    )
    k = min(15, len(ranked))
    print(f"## (3) |Δ| top-{k} move/매치업")
    print(f"  {'move':16} {'atk':18} {'defn':18} {'sd med':>7} {'dc med':>7} {'Δ':>7} {'cat':12}")
    for r in ranked[:k]:
        sm, dm = _med(r.get("showdown")), _med(r.get("damagecalc"))
        print(
            f"  {str(r.get('move_id'))[:15]:16} {str(r.get('atk'))[:17]:18} "
            f"{str(r.get('defn'))[:17]:18} {(f'{sm:.0f}' if sm is not None else '-'):>7} "
            f"{(f'{dm:.0f}' if dm is not None else '-'):>7} "
            f"{r['delta_median_pct']:+7.1f} {categorize(r):12}"
        )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("path", help="exp-dir 또는 oracle_compare.jsonl 경로")
    ap.add_argument("--log", default=None, help="jsonl 경로(exp-dir 지정 시; 기본 .temp/oracle_compare.jsonl)")
    args = ap.parse_args()

    log = resolve_log(args.path, args.log)
    if not log.exists():
        print(f"오류: 로그 파일 없음 — {log}", file=sys.stderr)
        print("  compare 모드 실배틀이 먼저 실행되어야 jsonl 이 생성됩니다.", file=sys.stderr)
        return 2
    recs = load_records(log)
    if not recs:
        print(f"오류: 레코드 없음 — {log}", file=sys.stderr)
        return 2
    aggregate(recs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
