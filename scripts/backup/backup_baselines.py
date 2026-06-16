#!/usr/bin/env python3
"""백업·검증·복원 도구 for 공식 baseline 데이터셋.

`.temp/experiments/baselines/` (gitignored) 의 3개 baseline(io/react/minimax-glm51)을
`backups/baselines/` (git-tracked) 에 **버전화된 tar.zst blob** 으로 백업한다.

왜 tar.zst 인가
--------------
`.gitignore` 가 `*.html`(L27)·`*.jsonl`(L21) 을 **전역** 으로 무시하므로, 90개의 raw
Showdown HTML replay와 JSONL 로그는 어떤 경로에 두어도 git-add 할 수 없다. 반면
`.tar.zst` 는 추적 가능하다(검증됨). 따라서 디렉토리 통째로 하나의 blob에 담아
gitignore를 우회한다. 전체 baseline 162파일(73MB)은 zstd 로 **~2.97MB** 로 압축되며,
이 정도 크기면 git 히스토리에 직접 넣어도 기존 learnset.json(3.9MB) 선례에 부합한다.

결정적으로, blob이 git에 들어가면 **사용자의 기존 `git push` 가 곧 오프디스크 내구성
메커니즘** 이 된다 — 같은 디스크에만 존재하는 로컬 미러(단일장애점)와 달리, push 한
번이면 GitHub 원격에 복제본이 생긴다.

매니페스트는 JSON (sha256sum 텍스트가 아님)
-------------------------------------------
파일명에 공백(`pokechamp7493 - battle-gen9ou-635.html`)과 콜론
(`experiment_io_ollama_glm-5.1:cloud_...json`)이 섞여 있어, 공백 구분 텍스트 포맷은
파싱 불가하다. 매니페스트를 JSON 객체로 안전하게 직렬화한다.

주의: 매니페스트 확장자는 `.json` 이다 (`.jsonl` 가 아님). `.gitignore` 가 `*.jsonl`
(L21) 을 전역으로 무시하므로 `.jsonl` 매니페스트는 커밋되지 않는다. `.json` 은 추적
가능하다(검증됨). 매니페스트는 로그 스트림이 아니라 단일 문서(blob 메타 + 파일 목록)
이므로 JSON 이 의미적으로도 더 적합하다.

서브커맨드
----------
  backup            blob + 매니페스트 생성. 변경이 없으면 재아카이브 생략(idempotent).
  verify            blob 재추출 + per-file sha256 재계산 + 매니페스트 diff.
  restore --dest    blob을 dest에 복원한 뒤 복원 트리를 매니페스트와 검증.

의존성: Python stdlib only. zstd 는 시스템 `tar --zstd` 우선, 실패 시 gzip 폴백.

행동 규칙 (experiment-context.md §0-8): 본 도구는 배틀을 실행하지 않는다.
`.temp/` 를 **읽고** `backups/` 에 **쓰기** 만 한다. baseline은 읽기 전용 복사이므로
§4 "수정 금지" 규칙을 위반하지 않는다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# /workspace
REPO = Path(__file__).resolve().parents[2]
SOURCE = REPO / ".temp" / "experiments" / "baselines"
BACKUP_DIR = REPO / "backups" / "baselines"

# 공식 baseline 3종. 새 baseline이 추가되면 여기에 이름을 추가한다.
# (experiment-context.md §4: baselines/ 은 영구, 임의 수정·재실행 금지)
BASELINE_NAMES = ["io-glm51", "react-glm51", "minimax-glm51"]

BLOB_PREFIX = "baselines-full-v"  # baselines-full-v1.tar.zst / .sha256manifest.jsonl

CHUNK = 1024 * 1024  # 1 MiB


# --------------------------------------------------------------------------- #
# 기본 유틸
# --------------------------------------------------------------------------- #
def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def hash_tree(root: Path) -> dict[str, str]:
    """root 아래 모든 파일의 {relative_posix_path: sha256}."""
    out: dict[str, str] = {}
    for p in root.rglob("*"):
        if p.is_file():
            out[p.relative_to(root).as_posix()] = sha256_file(p)
    return out


def git_commit_short() -> str:
    try:
        r = subprocess.run(
            ["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
        )
        return r.stdout.strip() if r.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


# --------------------------------------------------------------------------- #
# tar codec 감지·생성·추출
# --------------------------------------------------------------------------- #
def detect_codec() -> str:
    """시스템 tar 가 --zstd 를 지원하면 'zstd', 아니면 'gzip'."""
    try:
        r = subprocess.run(
            ["tar", "--zstd", "-cf", os.devnull, os.devnull],
            capture_output=True,
        )
        if r.returncode == 0:
            return "zstd"
    except FileNotFoundError:
        pass
    return "gzip"


def create_blob(src_root: Path, names: list[str], dest: Path, codec: str) -> None:
    if codec == "zstd":
        cmd = ["tar", "-C", str(src_root), "--zstd", "-cf", str(dest), *names]
    else:
        cmd = ["tar", "-C", str(src_root), "-czf", str(dest), *names]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"tar 생성 실패 (codec={codec}):\n{r.stderr}")


def extract_blob(blob: Path, dest_dir: Path, codec: str) -> None:
    if codec == "zstd":
        cmd = ["tar", "--zstd", "-xf", str(blob), "-C", str(dest_dir)]
    else:
        cmd = ["tar", "-xzf", str(blob), "-C", str(dest_dir)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"tar 추출 실패 (codec={codec}):\n{r.stderr}")


# --------------------------------------------------------------------------- #
# 버전 관리·매니페스트 I/O
# --------------------------------------------------------------------------- #
def list_versions() -> list[tuple[int, Path]]:
    """(version, blob_path) 오름차순."""
    vers: list[tuple[int, Path]] = []
    for p in BACKUP_DIR.glob(f"{BLOB_PREFIX}*.tar.zst"):
        m = re.search(r"-v(\d+)\.tar\.zst$", p.name)
        if m:
            vers.append((int(m.group(1)), p))
    return sorted(vers)


def manifest_path_for(version: int) -> Path:
    return BACKUP_DIR / f"{BLOB_PREFIX}{version}.sha256manifest.json"


def load_manifest(mf: Path) -> tuple[dict, dict[str, str]]:
    """(blob_meta, {path: sha256})."""
    data = json.loads(mf.read_text())
    blob_meta = data["blob"]
    files = {f["path"]: f["sha256"] for f in data["files"]}
    return blob_meta, files


# --------------------------------------------------------------------------- #
# 검증 코어
# --------------------------------------------------------------------------- #
def diff_hashes(expected: dict[str, str], actual: dict[str, str]) -> tuple[bool, str]:
    exp, act = set(expected), set(actual)
    missing = sorted(exp - act)
    extra = sorted(act - exp)
    mismatched = sorted(p for p in (exp & act) if expected[p] != actual[p])
    if missing or extra or mismatched:
        parts = []
        if missing:
            parts.append(f"MISSING {len(missing)}: {missing[:3]}")
        if extra:
            parts.append(f"EXTRA {len(extra)}: {extra[:3]}")
        if mismatched:
            parts.append(f"MISMATCH {len(mismatched)}: {mismatched[:3]}")
        return False, "; ".join(parts)
    return True, f"OK ({len(expected)}/{len(expected)} files verified, 0 mismatches)"


def verify_blob(blob: Path, mf: Path) -> tuple[bool, str]:
    """blob 자체 해시 + 추출 후 per-file 해시를 매니페스트와 비교."""
    blob_meta, files = load_manifest(mf)
    actual = sha256_file(blob)
    if actual != blob_meta["sha256"]:
        return False, (
            f"blob sha256 불일치: manifest={blob_meta['sha256'][:12]} "
            f"actual={actual[:12]}"
        )
    with tempfile.TemporaryDirectory() as td:
        extract_blob(blob, Path(td), blob_meta["codec"])
        return diff_hashes(files, hash_tree(Path(td)))


def verify_tree(tree_root: Path, mf: Path) -> tuple[bool, str]:
    """이미 추출된 트리를 매니페스트와 비교 (restore 검증용)."""
    _, files = load_manifest(mf)
    return diff_hashes(files, hash_tree(tree_root))


# --------------------------------------------------------------------------- #
# 서브커맨드
# --------------------------------------------------------------------------- #
def cmd_backup(force: bool) -> int:
    # 가드: backups/ 가 .temp/ 내부면 거부 (gitignored 트랩 방지)
    if str(BACKUP_DIR).startswith(str(REPO / ".temp")):
        print("오류: 백업 대상이 .temp/ 내부입니다.", file=sys.stderr)
        return 2

    # 소스 검증 + 해시 계산
    src_hashes: dict[str, str] = {}
    src_sizes: dict[str, int] = {}
    for name in BASELINE_NAMES:
        d = SOURCE / name
        if not d.is_dir():
            print(f"오류: baseline 디렉토리 없음: {d}", file=sys.stderr)
            return 2
        for p in d.rglob("*"):
            if p.is_file():
                rel = p.relative_to(SOURCE).as_posix()
                src_hashes[rel] = sha256_file(p)
                src_sizes[rel] = p.stat().st_size

    # idempotency: 최신 매니페스트와 per-file 해시가 같으면 생략
    vers = list_versions()
    if vers and not force:
        latest_n = vers[-1][0]
        try:
            _, prev_files = load_manifest(manifest_path_for(latest_n))
        except Exception:
            prev_files = None
        if prev_files is not None and prev_files == src_hashes:
            print(
                f"변경 없음 — 재아카이브 생략 (현재 최신: v{latest_n}). "
                f"--force 로 강제 재생성."
            )
            return 0

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    n = (vers[-1][0] + 1) if vers else 1
    codec = detect_codec()
    blob = BACKUP_DIR / f"{BLOB_PREFIX}{n}.tar.zst"
    mf = manifest_path_for(n)

    create_blob(SOURCE, BASELINE_NAMES, blob, codec)
    blob_meta = {
        "file": blob.name,
        "sha256": sha256_file(blob),
        "bytes": blob.stat().st_size,
        "codec": codec,
        "file_count": len(src_hashes),
        "git_commit": git_commit_short(),
        "source_root": SOURCE.relative_to(REPO).as_posix(),
        "baselines": list(BASELINE_NAMES),
    }
    data = {
        "blob": blob_meta,
        "files": [
            {"path": rel, "sha256": src_hashes[rel], "bytes": src_sizes[rel]}
            for rel in sorted(src_hashes)
        ],
    }
    mf.write_text(json.dumps(data, indent=2) + "\n")

    # anti-theater: 생성 즉시 self-verify. 실패하면 롤백.
    ok, msg = verify_blob(blob, mf)
    if not ok:
        blob.unlink(missing_ok=True)
        mf.unlink(missing_ok=True)
        print(f"오류: self-verify 실패, 롤백 — {msg}", file=sys.stderr)
        return 1

    print(f"✓ backup 완료: {blob.name}")
    print(f"    크기      : {blob_meta['bytes']:,} bytes ({codec})")
    print(f"    파일 수   : {blob_meta['file_count']}")
    print(f"    매니페스트: {mf.name}")
    print(f"    git commit: {blob_meta['git_commit']}")
    print(f"    검증      : {msg}")
    return 0


def cmd_verify() -> int:
    vers = list_versions()
    if not vers:
        print("백업이 없습니다. 먼저 `backup` 을 실행하세요.", file=sys.stderr)
        return 1
    n, blob = vers[-1]
    mf = manifest_path_for(n)
    ok, msg = verify_blob(blob, mf)
    print(f"[v{n}] {msg}")
    return 0 if ok else 1


def cmd_restore(dest: Path, force: bool) -> int:
    vers = list_versions()
    if not vers:
        print("복원할 백업이 없습니다.", file=sys.stderr)
        return 1
    n, blob = vers[-1]
    mf = manifest_path_for(n)
    blob_meta, _ = load_manifest(mf)

    dest = dest.resolve()
    if dest.exists() and any(dest.iterdir()):
        if not force:
            print(
                f"오류: 대상이 비어있지 않음: {dest} (덮어쓰려면 --force)",
                file=sys.stderr,
            )
            return 1
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)

    extract_blob(blob, dest, blob_meta["codec"])
    ok, msg = verify_tree(dest, mf)
    print(f"restore[v{n}] → {dest}")
    print(f"    {msg}")
    return 0 if ok else 1


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_bak = sub.add_parser("backup", help="blob + 매니페스트 생성")
    p_bak.add_argument("--force", action="store_true", help="변경 없어도 강제 재아카이브")

    sub.add_parser("verify", help="최신 blob 무결성 검증")

    p_res = sub.add_parser("restore", help="blob을 dest에 복원")
    p_res.add_argument("--dest", required=True, help="복원 대상 디렉토리")
    p_res.add_argument("--force", action="store_true", help="비어있지 않은 dest 덮어쓰기")

    args = ap.parse_args()

    if args.cmd == "backup":
        return cmd_backup(args.force)
    if args.cmd == "verify":
        return cmd_verify()
    if args.cmd == "restore":
        return cmd_restore(Path(args.dest), args.force)
    return 2


if __name__ == "__main__":
    sys.exit(main())
