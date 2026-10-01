"""Make the eval/ scripts importable as plain modules (eval/ is a script directory, not a package)."""
import sys
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parents[1]
if str(EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(EVAL_DIR))
