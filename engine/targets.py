"""Load targets from config/targets.yaml with ${VAR:-default} expansion."""
from __future__ import annotations

import os
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
_VAR = re.compile(r"\$\{([A-Z0-9_]+)(?::-([^}]*))?\}")


def _expand(value):
    if isinstance(value, str):
        return _VAR.sub(lambda m: os.getenv(m.group(1)) or (m.group(2) or ""), value)
    if isinstance(value, list):
        return [_expand(v) for v in value]
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    return value


def load_targets(only_available: bool = False) -> list[dict]:
    raw = yaml.safe_load((ROOT / "config" / "targets.yaml").read_text(encoding="utf-8"))["targets"]
    out = []
    for t in raw:
        t = _expand(t)
        missing = [v for v in t.get("requires_env", []) if not os.getenv(v)]
        t["available"] = not missing
        t["missing_env"] = missing
        if only_available and missing:
            continue
        out.append(t)
    return out
