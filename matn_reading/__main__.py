"""``python -m matn_reading read <pdf> --out <folder>``: see matn_reading/cli.py."""
import sys

from .cli import main

sys.exit(main())
