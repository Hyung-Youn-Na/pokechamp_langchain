#!/usr/bin/env python3
"""샘플링 풀(modern_replays + competitive)의 모든 포켓몬 종 → slug 리스트.

랜덤 배틀이 샘플링하는 팀 풀 전체에서 중복 없이 종을 추출해, Smogon 크롤러가
그 종들만 스크랩하도록 ``--only`` 인자용 dex alias(slug) 리스트를 출력한다.

배경 (EXP-049c 데이터 복구, 2026-06-25): overview 복구 재스크랩을 gen9ou 전체
(108종)가 아니라 실제 배틀 풀에 쓰이는 종들만으로 한정. 샘플링 원천 풀 =
modern_replays(25192팀) + competitive(16팀) 합집합 ≈ 431종.

사용::

    python extract_pool_species.py --out species.txt
    # 크롤러가 그 종들만 스크랩 (Draft overview fallback 자동 적용)
    python ../../.temp/script/smogon_live_crawler.py --gen sv \\
        --only $(cat species.txt) --format OU \\
        --out ../../.temp/script/smogon_ou_strategies.json --delay 0.8

재사용: ``get_metamon_teams`` / ``_numeric_team_sort`` (select_dynamic_teams.py
패턴), ``slugify`` 규칙 (smogon_live_crawler.py:21 — kebab-case dex alias).
"""
from __future__ import annotations

import argparse
import re
import sys

from poke_env.player.team_util import _numeric_team_sort, get_metamon_teams


def slugify(name: str) -> str:
    """display name -> dex alias 슬러그 (smogon_live_crawler.py:21 과 동일 규칙).

    'Great Tusk'->'great-tusk', "Farfetch'd"->'farfetchd', 'Mr. Mime'->'mr-mime'.
    """
    s = name.strip().lower()
    s = s.replace("♀", "-f").replace("♂", "-m")
    s = s.replace("'", "").replace("’", "")
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def species_of(team_files) -> set[str]:
    """정렬된 team_files 전체에서 포켓몬 species 집합 추출.

    각 팀 파일(showdown 텍스트)의 블록 첫 줄에서 species 추출. 세 가지 형식:
      - "Nickname (Species) @ Item" → 괄호 안 Species (competitive 풀 닉네임)
      - "Species (M) @ Item"        → 괄호 안 M/F 는 gender, Species 는 괄호 앞
      - "Species @ Item"            → 괄호/앳 앞 Species
    """
    sp: set[str] = set()
    for f in team_files:
        try:
            text = open(f).read()
        except OSError:
            continue
        for block in re.split(r"\n\n+", text.strip()):
            lines = [ln for ln in block.strip().split("\n") if ln.strip()]
            if not lines:
                continue
            line0 = lines[0].strip()
            m = re.match(r"[^(]*\(([^)]+)\)", line0)
            if m and m.group(1).strip() not in ("M", "F"):
                # Nickname (Species) 형식 → 괄호 안이 실제 species
                name = m.group(1).strip()
            else:
                # Species @ Item 또는 Species (M/F) → 괄호/앳 앞
                name = re.split(r"\s*[@(]", line0)[0].strip()
            if name:
                sp.add(name)
    return sp


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--sets",
        default="modern_replays,competitive",
        help="샘플링 풀 metamon 셋 (콤마 구분, 기본 modern_replays,competitive)",
    )
    ap.add_argument("--format", default="gen9ou")
    ap.add_argument(
        "--out", default=None, help="출력 파일 (기본 stdout, 한 줄에 한 slug)"
    )
    args = ap.parse_args()

    all_species: set[str] = set()
    for set_name in [s.strip() for s in args.sets.split(",") if s.strip()]:
        try:
            ts = get_metamon_teams(args.format, set_name)
            files = _numeric_team_sort(ts.team_files)
            sp = species_of(files)
            print(
                "[*] %s: %d팀 → %d종" % (set_name, len(files), len(sp)),
                file=sys.stderr,
            )
            all_species |= sp
        except Exception as e:  # noqa: BLE001
            print("[!] %s 로드 실패: %s" % (set_name, e), file=sys.stderr)

    slugs = sorted({slugify(s) for s in all_species if slugify(s)})
    print(
        "[*] 합집합: %d종 → dex alias(slug) %d개" % (len(all_species), len(slugs)),
        file=sys.stderr,
    )

    out = "\n".join(slugs) + "\n"
    if args.out:
        with open(args.out, "w") as f:
            f.write(out)
        print("[*] 저장 → %s" % args.out, file=sys.stderr)
    else:
        sys.stdout.write(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
