from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .io import canonical_json, sha256_bytes


class MapCache:
    def __init__(self, root: Path):
        self.root = root

    @staticmethod
    def key(payload: dict[str, Any]) -> str:
        return sha256_bytes(canonical_json(payload).encode("utf-8"))

    def get(self, key: str) -> dict[str, Any] | None:
        path = self.root / f"{key}.json"
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) and value.get("cache_key") == key else None

    def put(self, key: str, payload: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        target = self.root / f"{key}.json"
        temporary = self.root / f".{key}.tmp"
        temporary.write_text(json.dumps({"cache_key": key, **payload}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, target)

