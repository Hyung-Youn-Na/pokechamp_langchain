"""Oracle backend factory — damage-calc 백엔드를 런타임에 선택.

``battle_tools.py``(등 유일 소비자)가 ``get_shared_oracle()`` / ``get_oracle_cache()``
를 직접 호출하는 대신 ``get_oracle(backend)`` / ``get_cache(backend)`` 로 라우팅하도록
교체하기 위한 단일 진입점. 기존 ``showdown`` 백엔드(ShowdownOracle)와 새
``damagecalc`` 백엔드(DamageCalcOracle)는 동일 ``query()`` 인터페이스·동일 응답
스키마를 공유하므로 소비자 코드는 백엔드 무관하다.

Backends:
  - ``"showdown"``   (기본) — :class:`ShowdownOracle` (pokemon-showdown 엔진)
  - ``"damagecalc"``  — :class:`DamageCalcOracle` (Smogon ``@smogon/calc``)
  - ``"compare"``     — :class:`CompareOracle` (양쪽 동시 호출; 의사결정은 showdown)

전역 백엔드 선택자 ``DEFAULT_BACKEND`` 는 CLI(``--oracle_backend``)에서
``set_default_backend()`` 로 설정된다.
"""

from __future__ import annotations

from typing import Any

DEFAULT_BACKEND = "showdown"

VALID_BACKENDS = ("showdown", "damagecalc", "compare")


def set_default_backend(backend: str) -> None:
    """Set the process-wide default oracle backend (called from CLI parsing)."""
    global DEFAULT_BACKEND
    b = (backend or "showdown").lower()
    if b not in VALID_BACKENDS:
        raise ValueError(
            f"Unknown oracle backend {backend!r}; expected one of {VALID_BACKENDS}"
        )
    DEFAULT_BACKEND = b


def get_default_backend() -> str:
    return DEFAULT_BACKEND


def get_oracle(backend: str = "") -> Any:
    """Return the singleton oracle for the given backend (or the default).

    Returns the oracle instance, or ``None`` if it cannot be initialized.
    """
    b = (backend or DEFAULT_BACKEND).lower()
    if b == "damagecalc":
        from pokechamp.damage_calc_oracle import get_shared_damage_calc_oracle

        return get_shared_damage_calc_oracle()
    if b == "compare":
        from pokechamp.oracle_compare import get_compare_oracle

        return get_compare_oracle()
    # showdown (default)
    from pokechamp.showdown_oracle import get_shared_oracle

    return get_shared_oracle()


def get_cache(backend: str = "") -> Any:
    """Return the singleton result cache for the given backend (or the default).

    Each backend owns a separate cache so compare-mode results do not mix.
    """
    b = (backend or DEFAULT_BACKEND).lower()
    if b == "damagecalc":
        from pokechamp.damage_calc_oracle import get_damage_calc_cache

        return get_damage_calc_cache()
    # showdown / compare (compare reuses showdown's cache for the decision path)
    from pokechamp.showdown_oracle import get_oracle_cache

    return get_oracle_cache()
