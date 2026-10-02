"""Matn commit-msg checks (see CLAUDE.md).

G3  a subject line plus a body that explains why (trailers alone do not count); merge and revert subjects are exempt.
G5  CLAUDE.md rule 15: the message ends with exactly one `Agent:` trailer, as the LAST trailer, whose value is in
    AGENTS. Merge and revert commits are held to G5 too. Trailers are parsed by git itself
    (`git interpret-trailers --parse`). agent_problems() is reused by the pre-push re-check (G4, pre_push.py).
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

TRAILER = re.compile(r"^[A-Za-z][A-Za-z-]*-[Bb]y:\s|^Co-Authored-By:\s|^Agent:\s", re.IGNORECASE)
AGENTS = ("claude-code", "codex", "human")


def agent_problems(message: str) -> list[str]:
    """Reasons the message breaks G5 (empty list when it complies)."""
    parsed = subprocess.run(["git", "interpret-trailers", "--parse"], input=message, capture_output=True, text=True,
                            check=True).stdout
    trailers = [line.split(":", 1) for line in parsed.splitlines() if ":" in line]
    agents = [value.strip() for key, value in trailers if key.strip().lower() == "agent"]
    accepted = ", ".join(AGENTS)
    if len(agents) != 1:
        return [f"[G5] the message must end with exactly one 'Agent:' trailer (found {len(agents)}); "
                f"accepted values: {accepted}"]
    if trailers[-1][0].strip().lower() != "agent":
        return [f"[G5] the 'Agent:' trailer must be the last trailer; accepted values: {accepted}"]
    if agents[0] not in AGENTS:
        return [f"[G5] unknown agent {agents[0]!r}; accepted values: {accepted}"]
    return []


def g3_problems(lines: list[str]) -> list[str]:
    subject, body = lines[0], lines[1:]
    if subject.startswith(("Merge ", "Revert ")):
        return []
    if len(subject) > 100:
        return [f"[G3] subject is {len(subject)} characters; keep it under 100"]
    explanation = [line for line in body if line.strip() and not TRAILER.match(line.strip())]
    if not explanation:
        return ["[G3] commit blocked: add a body after a blank line that says why the change was made"]
    return []


def main(path: str) -> int:
    lines = [line.rstrip() for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
             if not line.startswith("#")]
    while lines and not lines[0].strip():
        lines.pop(0)
    if not lines:
        sys.stderr.write("[G3] empty commit message\n")
        return 1
    problems = g3_problems(lines) + agent_problems("\n".join(lines) + "\n")
    for problem in problems:
        sys.stderr.write(problem + "\n")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
