"""Generate a promptfooconfig.yaml from the benchmark + selected targets.

The JSON benchmark is the source of truth; the Promptfoo config is a build
artifact, regenerated per run (stored in the run folder for reproducibility).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import yaml

from engine.benchmark import load_cases, sample_cases
from engine.targets import load_targets

ROOT = Path(__file__).resolve().parent.parent
SYSTEM_PROMPT = (ROOT / "target" / "system_prompt.txt").read_text(encoding="utf-8")

# A chat prompt for raw LLM targets. `| dump` JSON-escapes the user text so
# quotes/newlines in Arabic test prompts cannot break the message array.
BANK_CHAT_PROMPT = (
    '[{"role": "system", "content": ' + json.dumps(SYSTEM_PROMPT, ensure_ascii=False) + "},"
    ' {"role": "user", "content": {{ prompt | dump }}}]'
)


def _provider(t: dict) -> dict:
    if t["type"] == "http":
        return {
            "id": "http",
            "label": t["label"],
            "prompts": ["raw"],
            "config": {
                "url": t["url"],
                "method": "POST",
                "headers": {"Content-Type": "application/json"},
                "body": {"message": "{{prompt}}", "profile": t.get("profile", "vulnerable")},
                "transformResponse": "json.reply",
            },
        }
    cfg: dict = {"temperature": 0}
    if t.get("api_base_url"):
        cfg["apiBaseUrl"] = t["api_base_url"]
    if t.get("api_key_env"):
        cfg["apiKeyEnvar"] = t["api_key_env"]
    # bank_chat: the model plays the bank assistant (bank suite); plain: no persona (model-level suites)
    return {"id": t["provider"], "label": t["label"], "prompts": ["bank_chat", "plain"], "config": cfg}


META_KEYS = ("technique", "goal", "obfuscation", "fact", "region", "qtype", "unit",
             "question", "attribute", "pair_group")


def build(target_ids: list[str], axes: list[str] | None, out_path: Path,
          suites: list[str] | None = None, sample: int | None = None, seed: int = 42) -> dict:
    targets = {t["id"]: t for t in load_targets()}
    unknown = [i for i in target_ids if i not in targets]
    if unknown:
        raise SystemExit(f"unknown target(s): {unknown}. Known: {list(targets)}")
    unavailable = [f"{i} (needs {targets[i]['missing_env']})" for i in target_ids if not targets[i]["available"]]
    if unavailable:
        raise SystemExit(f"target(s) not configured: {unavailable}")

    labels_by_type: dict[str, list[str]] = {"http": [], "llm": []}
    for i in target_ids:
        labels_by_type[targets[i]["type"]].append(targets[i]["label"])

    judge = os.getenv("JUDGE_PROVIDER")
    assertion_file = f"file://{(ROOT / 'engine' / 'assertions.py').as_posix()}"

    cases = sample_cases(load_cases(axes, suites or ["bank"]), sample, seed)
    tests, skipped = [], 0
    for c in cases:
        allowed = [lbl for typ in c["applies_to"] for lbl in labels_by_type.get(typ, [])]
        if not allowed:
            skipped += 1  # e.g. an LLM-only suite when only the HTTP bot is selected
            continue
        asserts = [{"type": "python", "value": assertion_file, "metric": c["axis"]}]
        if judge and c.get("rubric"):
            asserts.append({"type": "llm-rubric", "value": c["rubric"], "metric": f"{c['axis']}_judge"})
        meta = {k: v for k, v in (c.get("meta") or {}).items() if k in META_KEYS}
        test = {
            "description": f"{c['id']} · {c.get('title', '')}",
            "vars": {
                "prompt": c["prompt"],
                "case_id": c["id"],
                "check": json.dumps(c.get("check", {}), ensure_ascii=False),
            },
            "assert": asserts,
            "metadata": {
                "case_id": c["id"], "axis": c["axis"], "severity": c["severity"],
                "variant": c["variant"], "title": c.get("title", ""), "suite": c["suite"],
                "source": c["source"], **meta,
            },
            # bank scenarios: HTTP bots get the raw message, LLMs play the bank via bank_chat.
            # model-level suites: plain prompt, no bank persona (it would refuse off-topic questions).
            "prompts": ["raw", "bank_chat"] if c["suite"] == "bank" else ["plain"],
        }
        if len(allowed) != len(target_ids):
            test["providers"] = allowed
        tests.append(test)
    if not tests:
        raise SystemExit("no applicable test cases for the selected targets/suites "
                         "(model-level suites such as absher need an LLM target)")

    config = {
        "description": "CyberNext — Arabic AI reliability & security benchmark",
        "prompts": [
            {"id": "raw", "label": "raw", "raw": "{{prompt}}"},
            {"id": "bank_chat", "label": "bank_chat", "raw": BANK_CHAT_PROMPT},
            {"id": "plain", "label": "plain", "raw": "{{prompt}}"},
        ],
        "providers": [_provider(targets[i]) for i in target_ids],
        "tests": tests,
        "evaluateOptions": {"maxConcurrency": int(os.getenv("EVAL_CONCURRENCY", "4"))},
    }
    if judge:
        config["defaultTest"] = {"options": {"provider": judge}}

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
    config["_skipped"] = skipped
    return config


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--targets", nargs="+", default=["bankbot-baseline", "bankbot-hardened"])
    ap.add_argument("--axes", nargs="*")
    ap.add_argument("--suites", nargs="*", default=["bank"])
    ap.add_argument("--sample", type=int)
    ap.add_argument("--out", default="promptfooconfig.yaml")
    a = ap.parse_args()
    cfg = build(a.targets, a.axes, Path(a.out), a.suites, a.sample)
    print(f"wrote {a.out}: {len(cfg['tests'])} tests × {len(cfg['providers'])} targets")
