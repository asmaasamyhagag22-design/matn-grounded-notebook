"""Enforce Conventional Commits with a reason in the body."""
import re
import subprocess
import sys
from pathlib import Path


def trailer_problems(message):
    trailers = subprocess.run(
        ['git', 'interpret-trailers', '--parse'],
        input=message,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return ['Use a plain commit message without trailers'] if trailers.strip() else []


def problems(message):
    lines = message.strip().splitlines()
    issues = trailer_problems(message)
    if not lines or not re.match(r'^(feat|fix|docs|test|ci|build|chore|refactor|perf|style)(\([^)]+\))?!?: ', lines[0]):
        issues.append('Use a Conventional Commit subject')
    if len(lines) < 3 or not any(line.strip() for line in lines[2:]):
        issues.append('Add a body explaining why')
    return issues


if __name__ == '__main__':
    issues = problems(Path(sys.argv[1]).read_text())
    for issue in issues:
        print(issue, file=sys.stderr)
    raise SystemExit(bool(issues))
