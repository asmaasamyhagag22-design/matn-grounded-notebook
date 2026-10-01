"""Make checks/ modules importable from their tests (checks/ is a directory of repository guards, not a package)."""
import sys
from pathlib import Path

CHECKS_DIR = Path(__file__).resolve().parent
if str(CHECKS_DIR) not in sys.path:
    sys.path.insert(0, str(CHECKS_DIR))
