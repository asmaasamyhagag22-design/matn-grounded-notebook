"""Matn pre-push G4: require the full test suite before publication."""
import sys
from pre_commit import run_tests

def main() -> int:
    sys.stdin.read()
    return run_tests("G4")

if __name__ == "__main__":
    sys.exit(main())
