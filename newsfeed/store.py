"""Small helpers for reading and writing JSON files safely."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def load_json(path: Path, default: Any) -> Any:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path: Path, data: Any) -> None:
    """Write to a temp file first, then swap it in, so readers never see half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
