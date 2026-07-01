"""Damage-Calc Oracle — ``@smogon/calc`` 백엔드 Python wrapper.

``ShowdownOracle``(``pokechamp/showdown_oracle.py``)와 동일한 stdin/stdout
JSON-line 프로토콜·동일 ``query()`` 인터페이스·동일 None-폴백/자동재시작/타임아웃
패턴을 갖되, Node 워커를 ``damage-calc/scripts/damage-calc-worker.js``
(Smogon ``@smogon/calc`` 라이브러리 사용)로 교체한다. 동일 응답 스키마
(``ok/resolved/damage/ko_estimate``)를 반환하므로 ``battle_tools.py``·
``battle_state_mapper.py`` 수정 없이 ``ShowdownOracle``과 병렬 비교 또는
교체 가능하다.

설계(fork additive 원칙): ``ShowdownOracle``을 **상속**해 ``_verify_dist``만
override → ``showdown_oracle.py`` 0행 수정. 캐시는 전역 공유 캐시와 분리해
compare 모드에서 두 백엔드 결과가 섞이지 않도록 별도 싱글톤으로 둔다.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any, Dict, Optional, Tuple

from pokechamp.showdown_oracle import OracleResultCache, ShowdownOracle

logger = logging.getLogger("damage_calc_oracle")


class DamageCalcOracle(ShowdownOracle):
    """``@smogon/calc`` Node 워커를 구동하는 oracle (``ShowdownOracle`` 호환).

    ``ShowdownOracle``의 모든 동작(query/재시작/타임아웃/cleanup)을 그대로
    상속하고, (1) 워커 경로 기본값, (2) ``_verify_dist`` 검증 대상만 교체한다.
    """

    def __init__(
        self,
        worker_path: str = "damage-calc/scripts/damage-calc-worker.js",
        node_path: str = "node",
        timeout_seconds: float = 5.0,
        max_restarts: int = 3,
    ) -> None:
        super().__init__(
            worker_path=worker_path,
            node_path=node_path,
            timeout_seconds=timeout_seconds,
            max_restarts=max_restarts,
        )

    def _verify_dist(self) -> None:
        """Raise FileNotFoundError if the ``@smogon/calc`` build is missing.

        worker 는 ``damage-calc/scripts/`` 에 있으므로, 상위
        ``damage-calc/calc/dist/index.js`` 가 빌드产物로 존재해야 한다.
        (oracle 의 ``pokemon-showdown/dist/sim/battle.js`` 검증과 대칭.)
        """
        worker_dir = os.path.dirname(os.path.abspath(self._worker_path))
        dc_root = os.path.dirname(worker_dir)  # damage-calc/
        index_js = os.path.join(dc_root, "calc", "dist", "index.js")
        if not os.path.isfile(index_js):
            raise FileNotFoundError(
                f"@smogon/calc build not found at {index_js}. "
                "Run 'cd damage-calc/calc && npm install --ignore-scripts && npm run compile' first."
            )


# ----------------------------------------------------------------------
# Process-wide shared singleton (showdown_oracle.get_shared_oracle 와 대칭)
# ----------------------------------------------------------------------

_shared_dc_oracle: Optional[DamageCalcOracle] = None
_shared_dc_oracle_lock = threading.Lock()


def get_shared_damage_calc_oracle() -> Optional[DamageCalcOracle]:
    """Return the process-wide singleton :class:`DamageCalcOracle`.

    Lazily spawns one Node worker (``damage-calc-worker.js``) on first call.
    Returns ``None`` (and logs) if it cannot be initialized (e.g. the
    ``@smogon/calc`` build is missing).  Callers must treat ``None`` as
    "damage-calc oracle unavailable".
    """
    global _shared_dc_oracle
    if _shared_dc_oracle is not None and not _shared_dc_oracle._closed:
        return _shared_dc_oracle
    with _shared_dc_oracle_lock:
        if _shared_dc_oracle is not None and not _shared_dc_oracle._closed:
            return _shared_dc_oracle
        try:
            _shared_dc_oracle = DamageCalcOracle()
        except Exception as exc:  # noqa: BLE001 — never raise to callers
            logger.error("Failed to initialize shared damage-calc oracle: %s", exc)
            _shared_dc_oracle = None
        return _shared_dc_oracle


# ----------------------------------------------------------------------
# Separate result cache (전역 oracle 캐시와 분리 — compare 시 결과 혼합 방지)
# ----------------------------------------------------------------------

_dc_cache: Optional[OracleResultCache] = None
_dc_cache_lock = threading.Lock()


def get_damage_calc_cache() -> OracleResultCache:
    """Return the process-wide :class:`OracleResultCache` for damage-calc."""
    global _dc_cache
    if _dc_cache is not None:
        return _dc_cache
    with _dc_cache_lock:
        if _dc_cache is None:
            _dc_cache = OracleResultCache()
        return _dc_cache
