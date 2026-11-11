"""One command to run a scan:  python -m engine.run --targets bankbot-baseline bankbot-hardened

1. validates the benchmark
2. writes a promptfoo config into results/runs/<timestamp>/
3. starts the local demo bot if a selected target needs it
4. runs promptfoo (pinned version from package.json)
5. computes results.csv + summary.json
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from analytics.analyze import analyze  # noqa: E402
from engine.build_config import build  # noqa: E402
from engine.targets import load_targets  # noqa: E402

RUNS = ROOT / "results" / "runs"


def _bot_base() -> str:
    return os.getenv("BOT_URL", "http://127.0.0.1:8000").rstrip("/")


def _bot_up() -> bool:
    try:
        return httpx.get(f"{_bot_base()}/health", timeout=2).status_code == 200
    except httpx.HTTPError:
        return False


def ensure_bot(log) -> subprocess.Popen | None:
    if _bot_up():
        return None
    port = _bot_base().rsplit(":", 1)[-1]
    log(f"starting demo bot on :{port}")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "target.bank_bot:app", "--port", port, "--log-level", "warning"],
        cwd=ROOT,
    )
    for _ in range(40):
        if _bot_up():
            return proc
        time.sleep(0.25)
    proc.terminate()
    raise SystemExit("demo bot did not start")


def promptfoo_cmd() -> list[str]:
    local = ROOT / "node_modules" / ".bin" / ("promptfoo.cmd" if os.name == "nt" else "promptfoo")
    if local.exists():
        return [str(local)]
    npx = shutil.which("npx")
    if not npx:
        raise SystemExit("promptfoo not found — run `npm install` first")
    return [npx, "promptfoo"]


def run(target_ids: list[str], axes: list[str] | None = None, log=print,
        suites: list[str] | None = None, sample: int | None = None, seed: int = 42) -> Path:
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = RUNS / stamp
    cfg_path = run_dir / "promptfooconfig.yaml"
    suites = suites or ["bank"]
    cfg = build(target_ids, axes, cfg_path, suites, sample, seed)
    n_calls = sum(len(t.get("providers", target_ids)) for t in cfg["tests"])
    log(f"run {stamp}: {len(cfg['tests'])} cases, {n_calls} model calls · suites {suites}"
        + (f" · sample {sample}/suite (seed {seed})" if sample else "")
        + (f" · {cfg['_skipped']} cases not applicable to selected targets" if cfg["_skipped"] else ""))

    targets = {t["id"]: t for t in load_targets()}
    needs_bot = any(targets[t].get("local_bot") or _bot_base() in (targets[t].get("api_base_url") or "")
                    for t in target_ids)
    bot = ensure_bot(log) if needs_bot else None

    env = {
        **os.environ,
        "PROMPTFOO_DISABLE_TELEMETRY": "1",
        "PROMPTFOO_DISABLE_UPDATE": "1",
        "PROMPTFOO_DISABLE_SHARING": "1",
        "PROMPTFOO_DISABLE_REMOTE_GENERATION": "true",
        "PROMPTFOO_SELF_HOSTED": "1",  # no calls to promptfoo cloud; works offline on stage
        "PROMPTFOO_PYTHON": sys.executable,
        "PROMPTFOO_CONFIG_DIR": str(ROOT / ".promptfoo"),
    }
    try:
        proc = subprocess.run(
            [*promptfoo_cmd(), "eval", "-c", str(cfg_path), "-o", str(run_dir / "raw.json"),
             "--no-cache", "--no-progress-bar"],
            cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8",
        )
    finally:
        if bot:
            bot.terminate()
    (run_dir / "promptfoo.log").write_text(proc.stdout + "\n" + proc.stderr, encoding="utf-8")
    # promptfoo exits 100 when some tests fail — that is a finding, not an error.
    if not (run_dir / "raw.json").exists():
        log(proc.stdout[-2000:] + proc.stderr[-2000:])
        raise SystemExit(f"promptfoo failed (exit {proc.returncode}); see {run_dir / 'promptfoo.log'}")

    summary = analyze(run_dir)
    meta = {"stamp": stamp, "targets": target_ids, "axes": axes or "all", "suites": suites,
            "sample": sample, "seed": seed, "n_calls": n_calls,
            "judge": os.getenv("JUDGE_PROVIDER") or None, "bot_mode": os.getenv("BOT_MODE", "mock")}
    (run_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    for t in summary["targets"]:
        log(f"  {t['target']}: risk {t['risk_score']}/100 ({t['rating']}) · "
            f"pass {t['pass_rate']}% · leaks {t['leaks']} · critical fails {t['critical_failures']}")
    for ms in summary["model_suites"]:
        for t in ms["targets"]:
            log(f"  [{ms['suite']}] {t['target']}: accuracy {t['accuracy']}% vs baseline {t['baseline']}% (n={t['n']})")
    log(f"results: {run_dir}")
    return run_dir


def main() -> None:
    ap = argparse.ArgumentParser(description="Run the CyberNext benchmark")
    ap.add_argument("--targets", nargs="+", default=["bankbot-baseline", "bankbot-hardened"])
    ap.add_argument("--axes", nargs="*", help="subset of: accuracy dialect injection leakage bias dialect_knowledge")
    ap.add_argument("--suites", nargs="*", default=["bank"], help="bank (default), absher, ...")
    ap.add_argument("--sample", type=int, help="max cases per model-level suite (stratified); bank is never sampled")
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    run(a.targets, a.axes, suites=a.suites, sample=a.sample, seed=a.seed)


if __name__ == "__main__":
    main()
