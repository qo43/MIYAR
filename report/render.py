"""Render the English assessment report for a run: HTML always, PDF if WeasyPrint is installed."""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import pandas as pd
from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from analytics.analyze import AXIS_RECOMMENDATIONS, load_run, summarize  # noqa: E402

SEV_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def _textdir(text: str) -> str:
    """rtl if Arabic letters dominate, else ltr (PDF engines ignore unicode-bidi: plaintext)."""
    ar = sum("\u0600" <= ch <= "\u06ff" for ch in text or "")
    lat = sum(ch.isascii() and ch.isalpha() for ch in text or "")
    return "rtl" if ar >= lat else "ltr"


def _headline(summary: dict) -> str:
    ts = sorted(summary["targets"], key=lambda t: t["risk_score"])
    if len(ts) == 1:
        t = ts[0]
        return (f"{t['target']} is rated {t['rating']} risk ({t['risk_score']}/100). "
                f"It passed {t['pass_rate']}% of cases with {t['leaks']} data-leak finding(s).")
    best, worst = ts[0], ts[-1]
    return (f"{best['target']} performed best ({best['risk_score']}/100, {best['rating']}); "
            f"{worst['target']} performed worst ({worst['risk_score']}/100, {worst['rating']}, "
            f"{worst['leaks']} leak(s), {worst['critical_failures']} critical failure(s)).")


def render(run_dir: Path, max_findings: int = 25) -> dict[str, Path]:
    run_dir = Path(run_dir)
    df = load_run(run_dir / "raw.json")
    summary = summarize(df)
    meta_p = run_dir / "meta.json"
    meta = json.loads(meta_p.read_text()) if meta_p.exists() else {}

    failures = {}
    for t in summary["targets"]:
        f = df[(df.target == t["target"]) & ~df.passed].copy()
        f["_o"] = f.severity.map(SEV_ORDER)
        failures[t["target"]] = f.sort_values(["_o", "case_id"]).to_dict("records")
    failing_axes = [a for a in summary["axes"] if (~df[df.axis == a].passed).any()]

    env = Environment(loader=FileSystemLoader(ROOT / "report"), autoescape=select_autoescape(["html", "j2"]))
    env.filters["textdir"] = _textdir
    html = env.get_template("template.html.j2").render(
        summary=summary, failures=failures, failing_axes=failing_axes, axis_recs=AXIS_RECOMMENDATIONS,
        meta=meta, stamp=run_dir.name, n_cases=df.case_id.nunique(), headline=_headline(summary),
        max_findings=max_findings, generated=dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
    )
    out = {"html": run_dir / "report.html"}
    out["html"].write_text(html, encoding="utf-8")
    try:
        from weasyprint import HTML  # optional dependency

        out["pdf"] = run_dir / "report.pdf"
        HTML(string=html, base_url=str(run_dir)).write_pdf(out["pdf"])
    except Exception as e:  # noqa: BLE001 — PDF is best-effort; HTML is the fallback deliverable
        print(f"PDF skipped ({type(e).__name__}): HTML report is at {out['html']}", file=sys.stderr)
    return out


if __name__ == "__main__":
    runs = sorted((ROOT / "results" / "runs").glob("*/raw.json"))
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else (runs[-1].parent if runs else None)
    if not target:
        raise SystemExit("no runs yet — run `python -m engine.run` first")
    for k, p in render(target).items():
        print(f"{k}: {p}")
