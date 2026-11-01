"""Product identity, historical freeze checks and a zero-call replay smoke check."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time

from git_environment import git_environment

from .runtime import ORIGINAL, ROOT
from .store import read, write

PREFIXES = ("matn_", "checks/", "design/", "schemas/", "scripts/")
EXTENSIONS = {".py", ".json", ".svg", ".css", ".js", ".html", ".pptx", ".png", ".sh", ".ps1"}
EXTRA = {"eval/reranker_settings.json", "eval/reading/thresholds.json", "design/icons/heroicons/LICENSE"}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def identity(root=ROOT):
    root = Path(root)
    paths = subprocess.check_output(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=root, env=git_environment()).decode().splitlines()
    files = {p: sha(root / p) for p in sorted(set(paths)) if (p in EXTRA or
             (p.startswith(PREFIXES) and Path(p).suffix in EXTENSIONS) or
             (p.startswith("eval/") and Path(p).suffix == ".py") or
             ("/" not in p and (Path(p).suffix in {".py", ".sh", ".ps1"} or
                                (p.startswith("requirements") and p.endswith(".txt"))))) and (root / p).is_file()}
    digest = hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return dict(identity=digest, files=files, policy="All runtime source/config/assets plus pinned templates; no documents, out/, owner file or evaluation data")


def create(path):
    value = identity()
    value.update(commit=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, env=git_environment()).decode().strip(), at=time.time())
    write(path, value)
    return value


def verify(path):
    frozen = read(path)
    if not frozen:
        raise ValueError("PRODUCT_FREEZE_MISSING")
    actual = identity()
    if actual["identity"] != frozen["identity"] or actual["files"] != frozen["files"]:
        drift = sorted(p for p in set(actual["files"]) | set(frozen["files"]) if actual["files"].get(p) != frozen["files"].get(p))
        raise ValueError("PRODUCT_CODE_DRIFT: " + ", ".join(drift))
    return dict(status="PRODUCT_IDENTITY_MATCHES", identity=actual["identity"], files=len(actual["files"]))


def original_guard(baseline):
    baseline = read(baseline)
    problems = []
    for path, expected in baseline["original_files"].items():
        target = ORIGINAL / path
        if not target.is_file() or sha(target) != expected:
            problems.append("ORIGINAL_FILE_DRIFT:" + path)
    status = subprocess.check_output(["git", "status", "--porcelain=v1"], cwd=ORIGINAL, env=git_environment()).decode()
    if status != baseline["original_status"]:
        problems.append("ORIGINAL_STATUS_DRIFT")
    index = hashlib.sha256(subprocess.check_output(["git", "diff", "--cached", "--binary"], cwd=ORIGINAL, env=git_environment())).hexdigest()
    if index != baseline["original_index"]:
        problems.append("ORIGINAL_INDEX_DRIFT")
    for path, expected in baseline["ledgers"].items():
        if sha(ORIGINAL / path) != expected:
            problems.append("MEETING_LEDGER_DRIFT:" + path)
    for path, expected in baseline["frozen"].items():
        if sha(ROOT / path) != expected:
            problems.append("FROZEN_EVAL_DRIFT:" + path)
    tag = subprocess.check_output(["git", "rev-parse", "delivery-2026-10-30"], cwd=ROOT, env=git_environment()).decode().strip()
    if tag != baseline["delivery_tag"]:
        problems.append("DELIVERY_TAG_DRIFT")
    if problems:
        raise ValueError("; ".join(problems))
    return dict(status="ORIGINAL_PILE_OWNER_EVAL_TAG_LEDGERS_UNCHANGED", files=len(baseline["original_files"]))


def historical_candidate():
    """Retain the v5 batch-one identity check against its immutable Git commit.

    The final product intentionally changes the working-tree identity; old freeze
    expectations are neither overwritten nor passed off as the new candidate.
    """
    frozen = read(ORIGINAL / "out/research-v2/candidate-freeze.json")
    if not frozen:
        raise ValueError("BATCH1_FREEZE_MISSING")
    commit = "291d4c1"
    for path, expected in frozen["files"].items():
        raw = subprocess.check_output(["git", "show", commit + ":" + path], cwd=ROOT, env=git_environment())
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError("BATCH1_GIT_IDENTITY_DRIFT:" + path)
    return dict(status="BATCH1_HISTORICAL_FREEZE_MATCHES_GIT", commit=commit, files=len(frozen["files"]))


def smoke():
    from .smoke import run_replay_smoke
    return run_replay_smoke()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("create", "verify", "guard", "historical", "smoke"))
    parser.add_argument("--file", default=str(ORIGINAL / "out/product/final-freeze.json"))
    args = parser.parse_args()
    operation = {"create": create, "verify": verify, "guard": original_guard}
    value = operation[args.command](args.file) if args.command in operation else historical_candidate() if args.command == "historical" else smoke()
    print(json.dumps(value if args.command != "create" else {k: v for k, v in value.items() if k != "files"}, indent=2))


if __name__ == "__main__":
    main()
