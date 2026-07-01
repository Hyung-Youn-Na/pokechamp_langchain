"""Compare Oracle — Showdown oracle 와 damage-calc 백엔드를 병렬로 호출.

``--oracle_backend compare`` 일 때 ``oracle_backend.get_oracle("compare")`` 가
반환하는 싱글톤. 동일 payload 를 양쪽 백엔드에 보내 결과를 비교해 JSONL
로그로 남기고, **의사결정에는 showdown 결과를 반환**한다(승률 회귀 無, 관측만).

이 모드는 "damage-calc 이 기존 oracle 과 같은 Showdown 공식으로 동일한 데미지를
내는가" 를 검증하기 위한 것이다 — 두 백엔드는 동일 payload·동일 응답 스키마를
공유하므로 ``battle_tools.py``·``battle_state_mapper.py`` 수정 없이 drop-in 한다.

로그: 한 줄에 JSON 객체(``move_id``/양쪽 ``median_pct``/``type``/``delta``)를
``ORACLE_COMPARE_LOG`` 환경변수 경로(기본 ``.temp/oracle_compare.jsonl``)에 append.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any, Dict, Optional

from pokechamp.damage_calc_oracle import get_shared_damage_calc_oracle
from pokechamp.showdown_oracle import get_shared_oracle

logger = logging.getLogger("oracle_compare")

_DEFAULT_LOG = ".temp/oracle_compare.jsonl"


def _summary(result: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not result or not result.get("ok"):
        return None
    damage = result.get("damage") or {}
    resolved = result.get("resolved") or {}
    rtype = resolved.get("type")
    return {
        "median_pct": damage.get("median_pct"),
        "min_pct": damage.get("min_pct"),
        "max_pct": damage.get("max_pct"),
        "type": rtype.lower() if isinstance(rtype, str) and rtype else None,
        "base_power": resolved.get("base_power"),
    }


class CompareOracle:
    """Run both backends, log the diff, return the showdown result."""

    def __init__(self, log_path: Optional[str] = None) -> None:
        self._showdown = get_shared_oracle()
        self._damagecalc = get_shared_damage_calc_oracle()
        self._closed = False
        self._lock = threading.Lock()
        self._log_path = log_path or os.environ.get("ORACLE_COMPARE_LOG", _DEFAULT_LOG)
        log_dir = os.path.dirname(self._log_path)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
        # line-buffered append — 한 줄씩 flush 해 즉시 분석 가능.
        self._fh = open(self._log_path, "a", buffering=1)
        logger.info(
            "CompareOracle logging to %s (showdown=%s, damagecalc=%s)",
            self._log_path,
            self._showdown is not None,
            self._damagecalc is not None,
        )

    def query(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Return the showdown result; also query damage-calc and log the diff."""
        if self._closed:
            return None
        # 의사결정은 항상 showdown. damage-calc 실패해도 showdown 결과는 살린다.
        sd = self._showdown.query(payload) if self._showdown else None
        try:
            dc = self._damagecalc.query(payload) if self._damagecalc else None
        except Exception as exc:  # noqa: BLE001 — 관측용, 의사결정에 영향 無
            logger.debug("damage-calc query failed (logged as null): %s", exc)
            dc = None
        self._log_diff(payload, sd, dc)
        return sd

    def _log_diff(
        self,
        payload: Dict[str, Any],
        sd: Optional[Dict[str, Any]],
        dc: Optional[Dict[str, Any]],
    ) -> None:
        ss = _summary(sd)
        cs = _summary(dc)
        delta = None
        if (
            ss
            and cs
            and ss.get("median_pct") is not None
            and cs.get("median_pct") is not None
        ):
            delta = round(ss["median_pct"] - cs["median_pct"], 2)  # noqa: RUF100
        type_match = None
        if ss and cs and ss.get("type") and cs.get("type"):
            type_match = ss["type"] == cs["type"]
        # attacker/defender species — active_state 의 actor/target 첫째.
        actor = payload.get("actor_side")
        asx = (payload.get("active_state") or {}).get(actor) or []
        dsx = (payload.get("active_state") or {}).get(
            "p2" if actor == "p1" else "p1"
        ) or []
        rec = {
            "move_id": payload.get("move_id"),
            "atk": (asx[0].get("species_id") if asx else None),
            "defn": (dsx[0].get("species_id") if dsx else None),
            "showdown": ss,
            "damagecalc": cs,
            "delta_median_pct": delta,
            "type_match": type_match,
        }
        line = json.dumps(rec, separators=(",", ":")) + "\n"
        with self._lock:
            try:
                self._fh.write(line)
            except Exception as exc:  # noqa: BLE001
                logger.debug("compare log write failed: %s", exc)

    def close(self) -> None:
        self._closed = True
        try:
            self._fh.close()
        except Exception:  # noqa: BLE001
            pass


# ----------------------------------------------------------------------
# Process-wide shared singleton
# ----------------------------------------------------------------------

_shared_compare: Optional[CompareOracle] = None
_shared_compare_lock = threading.Lock()


def get_compare_oracle() -> Optional[CompareOracle]:
    """Return the process-wide singleton :class:`CompareOracle`."""
    global _shared_compare
    if _shared_compare is not None and not _shared_compare._closed:
        return _shared_compare
    with _shared_compare_lock:
        if _shared_compare is not None and not _shared_compare._closed:
            return _shared_compare
        try:
            _shared_compare = CompareOracle()
        except Exception as exc:  # noqa: BLE001 — never raise to callers
            logger.error("Failed to initialize compare oracle: %s", exc)
            _shared_compare = None
        return _shared_compare
