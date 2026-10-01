"""Matn commit-msg check G3: a subject line plus a body that explains why (trailers alone do not count)."""
from __future__ import annotations

import re
import sys
from pathlib import Path

TRAILER = re.compile(r"^[A-Za-z][A-Za-z-]*-[Bb]y:\s|^Co-Authored-By:\s", re.IGNORECASE)


def main(path: str) -> int:
    lines = [line.rstrip() for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
             if not line.startswith("#")]
    while lines and not lines[0].strip():
        lines.pop(0)
    if not lines:
        sys.stderr.write("[G3] empty commit message\n")
        return 1
    subject, body = lines[0], lines[1:]
    if subject.startswith(("Merge ", "Revert ")):
        return 0
    if len(subject) > 100:
        sys.stderr.write(f"[G3] subject is {len(subject)} characters; keep it under 100\n")
        return 1
    explanation = [line for line in body if line.strip() and not TRAILER.match(line.strip())]
    if not explanation:
        sys.stderr.write("[G3] commit blocked: add a body after a blank line that says why the change was made\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
