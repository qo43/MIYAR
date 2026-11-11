"""Load and validate the benchmark JSON files."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "benchmark"
AXES = ["accuracy", "dialect", "injection", "leakage", "bias"]
SEVERITY_WEIGHT = {"low": 1, "medium": 3, "high": 6, "critical": 10}


def load_cases(axes: list[str] | None = None) -> list[dict]:
    schema = json.loads((BENCH / "schema.json").read_text(encoding="utf-8"))
    cases, seen = [], set()
    for f in sorted((BENCH / "cases").glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        jsonschema.validate(data, schema)
        if axes and data["axis"] not in axes:
            continue
        for c in data["cases"]:
            if c["id"] in seen:
                raise ValueError(f"duplicate case id {c['id']} in {f.name}")
            seen.add(c["id"])
            cases.append({**c, "axis": data["axis"]})
    return cases


def main() -> None:
    cases = load_cases()
    by_axis = {a: sum(c["axis"] == a for c in cases) for a in AXES}
    print(f"OK — {len(cases)} cases valid: {by_axis}")


if __name__ == "__main__":
    try:
        main()
    except (jsonschema.ValidationError, ValueError) as e:
        print(f"INVALID: {e}", file=sys.stderr)
        sys.exit(1)
