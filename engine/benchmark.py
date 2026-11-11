"""Load, validate and sample the benchmark.

Case files live in three places:
  benchmark/cases/      curated by hand (committed)
  benchmark/generated/  produced by benchmark/generate.py from our own templates (committed)
  benchmark/external/   imported third-party datasets (git-ignored; see benchmark/importers/)

Each file declares a `suite`. The `bank` suite is scenario testing of a deployed
assistant and drives the risk score; other suites are model-level benchmarks.
"""
from __future__ import annotations

import json
import random
import sys
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "benchmark"
CASE_DIRS = [BENCH / "cases", BENCH / "generated", BENCH / "external"]
AXES = ["accuracy", "dialect", "injection", "leakage", "bias", "dialect_knowledge", "trust"]
RISK_AXES = ["accuracy", "dialect", "injection", "leakage", "bias"]
SEVERITY_WEIGHT = {"low": 1, "medium": 3, "high": 6, "critical": 10}


@lru_cache(maxsize=1)
def _schema() -> dict:
    return json.loads((BENCH / "schema.json").read_text(encoding="utf-8"))


def case_files() -> list[Path]:
    return [f for d in CASE_DIRS if d.exists() for f in sorted(d.rglob("*.json"))]


def load_cases(axes: list[str] | None = None, suites: list[str] | None = None,
               target_type: str | None = None) -> list[dict]:
    cases, seen = [], set()
    for f in case_files():
        data = json.loads(f.read_text(encoding="utf-8"))
        jsonschema.validate(data, _schema())
        suite = data.get("suite", "bank")
        applies = data.get("applies_to", ["http", "llm"])
        if axes and data["axis"] not in axes:
            continue
        if suites and suite not in suites:
            continue
        if target_type and target_type not in applies:
            continue
        for c in data["cases"]:
            if c["id"] in seen:
                raise ValueError(f"duplicate case id {c['id']} in {f.name}")
            seen.add(c["id"])
            cases.append({**c, "axis": data["axis"], "suite": suite,
                          "source": data.get("source", "curated"), "applies_to": applies,
                          "file": str(f.relative_to(ROOT))})
    return cases


def sample_cases(cases: list[dict], n: int | None, seed: int = 42,
                 strata: tuple[str, ...] = ("axis", "qtype", "region")) -> list[dict]:
    """Stratified, seeded sample of up to n cases per suite.

    Every stratum (e.g. Absher question type × region) gets at least one case,
    the rest is allocated proportionally — so small dialects are not sampled away.
    The `bank` suite is never sampled: it is the core scenario test.
    """
    if not n:
        return cases
    out: list[dict] = []
    by_suite: dict[str, list[dict]] = defaultdict(list)
    for c in cases:
        by_suite[c["suite"]].append(c)
    rng = random.Random(seed)
    for suite, cs in by_suite.items():
        if suite == "bank" or len(cs) <= n:
            out.extend(cs)
            continue
        groups: dict[tuple, list[dict]] = defaultdict(list)
        for c in cs:
            key = tuple(c.get(s) if s == "axis" else (c.get("meta") or {}).get(s) for s in strata)
            groups[key].append(c)
        keys = sorted(groups, key=str)
        alloc = {k: 1 for k in keys}
        remaining = max(0, n - len(keys))
        total = sum(len(groups[k]) for k in keys)
        for k in keys:
            alloc[k] += int(remaining * len(groups[k]) / total)
        for k in keys:
            g = sorted(groups[k], key=lambda c: c["id"])
            out.extend(rng.sample(g, min(alloc[k], len(g))))
    return out


def describe(cases: list[dict]) -> dict:
    return {
        "total": len(cases),
        "by_suite": dict(Counter(c["suite"] for c in cases)),
        "by_axis": dict(Counter(c["axis"] for c in cases)),
        "by_source": dict(Counter(c["source"] for c in cases)),
        "by_variant": dict(Counter(c["variant"] for c in cases)),
    }


def main() -> None:
    cases = load_cases()
    d = describe(cases)
    print(f"OK — {d['total']} cases valid")
    for k in ("by_suite", "by_axis", "by_source", "by_variant"):
        print(f"  {k}: {d[k]}")


if __name__ == "__main__":
    try:
        main()
    except (jsonschema.ValidationError, ValueError) as e:
        print(f"INVALID: {e}", file=sys.stderr)
        sys.exit(1)
