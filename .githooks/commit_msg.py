"""Public owner publication convention: Conventional Commits, why-body, no agent trailers."""
import re
import sys
from pathlib import Path


def agent_problems(message):
    return ['Public commits must not carry Agent or Co-authored-by trailers'] if re.search(r'^(Agent:|Co-authored-by:)', message, re.I | re.M) else []


def problems(message):
    lines = message.strip().splitlines()
    issues = agent_problems(message)
    if not lines or not re.match(r'^(feat|fix|docs|test|ci|build|chore|refactor|perf|style)(\([^)]+\))?!?: ', lines[0]):
        issues.append('Use a Conventional Commit subject')
    if len(lines) < 3 or not any(x.strip() for x in lines[2:]):
        issues.append('Add a body explaining why')
    return issues


if __name__ == '__main__':
    issues = problems(Path(sys.argv[1]).read_text())
    for issue in issues:
        print(issue, file=sys.stderr)
    raise SystemExit(bool(issues))
