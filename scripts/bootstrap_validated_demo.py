from __future__ import annotations

from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from matn_presentation.demo import SOURCE_PDF, prepare_validated_demo


def main() -> int:
    if not SOURCE_PDF.is_file():
        print(
            "Missing local prerequisite: documents/2601.14525v1.pdf. "
            "Obtain the source PDF under its applicable license and place it at that exact path. "
            "The repository intentionally does not redistribute the paper or its extracted Figure 2.",
            file=sys.stderr,
        )
        return 2
    result = prepare_validated_demo()
    print(f"Validated demo ready: {result['pptx_path']}")
    print(f"Deck plan: {result['plan_path']}")
    print("Model generation calls: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
