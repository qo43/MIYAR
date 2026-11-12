"""MI’YAR dashboard — run scans, inspect results, compare models, export the report.

Run:  streamlit run dashboard/app.py
"""
from __future__ import annotations

import html
import json
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from analytics.analyze import (AXIS_LABELS, AXIS_RECOMMENDATIONS, SUITE_LABELS, breakdown,  # noqa: E402
                               load_run, summarize)
from engine.benchmark import AXES, RISK_AXES, describe, load_cases, sample_cases  # noqa: E402
from engine.targets import load_targets  # noqa: E402

RUNS = ROOT / "results" / "runs"
RATING_COLOR = {"Low": "#2e7d32", "Medium": "#b7791f", "High": "#c2410c", "Critical": "#b91c1c"}
SEV_ORDER = ["critical", "high", "medium", "low"]

st.set_page_config(page_title="MI’YAR · Arabic AI Testing", page_icon="🛡️", layout="wide")
st.markdown(
    """<style>
    .ar {direction: rtl; text-align: right; unicode-bidi: plaintext; white-space: pre-wrap;
         background: rgba(127,127,127,.08); border-radius: 8px; padding: 8px 12px; font-size: 1.02rem;}
    .pill {display:inline-block;padding:2px 10px;border-radius:999px;color:#fff;font-weight:600;font-size:.8rem}
    </style>""",
    unsafe_allow_html=True,
)


def ar_block(text: str) -> None:
    """Show model text verbatim (no markdown parsing) with automatic RTL/LTR direction."""
    st.html(
        '<div dir="auto" style="unicode-bidi:plaintext;text-align:start;white-space:pre-wrap;'
        'background:rgba(127,127,127,.08);border-radius:8px;padding:8px 12px;font-size:1.02rem;'
        f'font-family:inherit">{html.escape(text or "")}</div>'
    )


def list_runs() -> list[Path]:
    return sorted((p.parent for p in RUNS.glob("*/raw.json")), reverse=True)


@st.cache_data(show_spinner=False)
def load(run_dir: str, mtime: float) -> tuple[pd.DataFrame, dict]:
    df = load_run(Path(run_dir) / "raw.json")
    return df, summarize(df)


# --------------------------------------------------------------------------- #
# Sidebar
# --------------------------------------------------------------------------- #
st.sidebar.title("🛡️ MI’YAR")
st.sidebar.caption("Arabic AI reliability & security testing")
page = st.sidebar.radio("Page", ["Run a scan", "Overview", "Failures", "Breakdown", "Compare models",
                                 "Model benchmarks", "Benchmark", "Report"])


@st.cache_data(show_spinner=False)
def all_cases() -> list[dict]:
    return load_cases(suites=None)

runs = list_runs()
run_dir = None
if runs:
    if "run" not in st.session_state or Path(st.session_state["run"]) not in runs:
        st.session_state["run"] = str(runs[0])
    st.session_state["run"] = st.sidebar.selectbox(
        "Run", [str(r) for r in runs], index=[str(r) for r in runs].index(st.session_state["run"]),
        format_func=lambda p: Path(p).name,
    )
    run_dir = Path(st.session_state["run"])

df = summary = None
if run_dir:
    df, summary = load(str(run_dir), (run_dir / "raw.json").stat().st_mtime)


def need_run() -> bool:
    if df is None:
        st.info("No results yet — start one from **Run a scan**.")
        return True
    return False


# --------------------------------------------------------------------------- #
# Run a scan
# --------------------------------------------------------------------------- #
if page == "Run a scan":
    st.header("Run a scan")
    targets = load_targets()
    avail = [t for t in targets if t["available"]]
    c1, c2 = st.columns(2)
    with c1:
        chosen = st.multiselect(
            "AI systems under test", [t["id"] for t in avail],
            default=[t["id"] for t in avail if t.get("local_bot")],
            format_func=lambda i: next(t["label"] for t in avail if t["id"] == i),
        )
        off = [t for t in targets if not t["available"]]
        if off:
            st.caption("Not configured: " + "; ".join(f"{t['id']} (set {', '.join(t['missing_env'])})" for t in off))
    with c2:
        present_suites = sorted({c["suite"] for c in all_cases()}, key=lambda x: x != "bank")
        suites = st.multiselect("Suites", present_suites, default=["bank"], format_func=lambda x: SUITE_LABELS.get(x, x),
                                help="bank = scenario tests (risk score). Others are model-level benchmarks for LLM targets.")
        if "absher" not in present_suites:
            st.caption("Absher not imported yet: `python -m benchmark.importers.absher`")
        axes = st.multiselect("Test categories", AXES, default=AXES, format_func=AXIS_LABELS.get)
        sample = st.number_input("Sample per model-level suite (0 = all)", 0, 20000, 300, step=100,
                                 help="Stratified by question type and region, seeded. The bank suite is never sampled.")
        types = {t["type"] for t in avail if t["id"] in chosen}
        cs = [c for c in sample_cases(load_cases(axes, suites), sample or None) if set(c["applies_to"]) & types] if axes and suites else []
        calls = sum(sum(1 for t in avail if t["id"] in chosen and t["type"] in c["applies_to"]) for c in cs)
        m1, m2 = st.columns(2)
        m1.metric("Test cases", len(cs))
        m2.metric("Model calls", calls, help="Cases × applicable targets — drives API cost for real models")

    if msg := st.session_state.pop("flash", None):
        st.success(msg)
    st.warning("Only test systems you own or have written permission to test. "
               "Injection and leakage probes are security testing.", icon="⚠️")
    if st.button("▶ Start scan", type="primary", disabled=not (chosen and axes and suites and cs)):
        from engine.run import run  # imported lazily: pulls in subprocess plumbing

        with st.status("Running benchmark…", expanded=True) as status:
            try:
                new_dir = run(chosen, axes if set(axes) != set(AXES) else None, log=st.write,
                              suites=suites, sample=sample or None)
            except SystemExit as e:
                status.update(label="Scan failed", state="error")
                st.error(str(e))
            else:
                status.update(label="Scan complete", state="complete")
                st.session_state["run"] = str(new_dir)
                st.session_state["flash"] = f"Scan `{new_dir.name}` complete — open **Overview** or **Failures**."
                st.rerun()  # refresh the sidebar run selector to the new run

# --------------------------------------------------------------------------- #
# Overview
# --------------------------------------------------------------------------- #
elif page == "Overview" and not need_run():
    st.header("Overview")
    st.caption(f"Run `{run_dir.name}` · {df.case_id.nunique()} cases · {len(df)} model calls")
    if not summary["targets"]:
        st.info("This run has no bank-scenario results. See **Model benchmarks**.")
    for t in summary["targets"]:
        st.subheader(t["target"])
        c = st.columns(6)
        c[0].markdown(f"**Rating** <span class='pill' style='background:{RATING_COLOR[t['rating']]}'>{t['rating']}</span>"
                      f"<br><span style='font-size:.85rem'>{html.escape(t.get('rating_reason', ''))}</span>",
                      unsafe_allow_html=True)
        c[1].metric("Risk index", f"{t['risk_score']}/100", help="Axis-balanced, severity-weighted fail share")
        c[2].metric("Pass rate", f"{t['pass_rate']}%", help=f"{t['passed']}/{t['tests']}")
        c[3].metric("Data leaks", t["leaks"])
        c[4].metric("Critical failures", t["critical_failures"])
        c[5].metric("Over-refusal", f"{t['over_refusal_rate']}%" if t.get("over_refusal_rate") is not None else "—",
                    help="Benign requests containing trigger words that the assistant refused")

    rates = pd.DataFrame(columns=["target", "axis", "pass_rate"]) if not summary["targets"] else pd.DataFrame([
        {"target": t["target"], "axis": AXIS_LABELS[a], "pass_rate": v}
        for t in summary["targets"] for a, v in t["axis_pass_rates"].items() if v is not None
    ])
    fig = px.bar(rates, x="axis", y="pass_rate", color="target", barmode="group", text="pass_rate",
                 range_y=[0, 105], labels={"pass_rate": "Pass rate (%)", "axis": ""})
    fig.update_traces(texttemplate="%{text:.0f}%", textposition="outside")
    fig.update_layout(legend_title_text="", height=420, margin=dict(t=20))
    st.plotly_chart(fig, use_container_width=True)

    sev = (df[~df.passed & (df.suite == "bank")].groupby(["target", "severity"]).size().reset_index(name="failures"))
    if len(sev):
        sev["severity"] = pd.Categorical(sev.severity, SEV_ORDER, ordered=True)
        fig2 = px.bar(sev.sort_values("severity"), x="target", y="failures", color="severity",
                      color_discrete_map={"critical": "#b91c1c", "high": "#c2410c", "medium": "#b7791f", "low": "#94a3b8"},
                      labels={"target": ""})
        fig2.update_layout(height=320, margin=dict(t=20), legend_title_text="Failed by severity")
        st.plotly_chart(fig2, use_container_width=True)

# --------------------------------------------------------------------------- #
# Failures drill-down
# --------------------------------------------------------------------------- #
elif page == "Failures" and not need_run():
    st.header("Failures — evidence & recommendations")
    c0, c1, c2, c3 = st.columns(4)
    usel = c0.multiselect("Suite", list(df.suite.unique()), default=["bank"] if "bank" in set(df.suite) else list(df.suite.unique()),
                          format_func=lambda x: SUITE_LABELS.get(x, x))
    tsel = c1.multiselect("Target", list(df.target.unique()), default=list(df.target.unique()))
    asel = c2.multiselect("Axis", AXES, default=AXES, format_func=AXIS_LABELS.get)
    ssel = c3.multiselect("Severity", SEV_ORDER, default=SEV_ORDER)
    f = df[~df.passed & df.suite.isin(usel) & df.target.isin(tsel) & df.axis.isin(asel) & df.severity.isin(ssel)].copy()
    if len(f) > 300:
        st.caption(f"Showing evidence for the first 300 of {len(f)} — narrow the filters or export the CSV from **Report**.")
    f["_o"] = f.severity.map({s: i for i, s in enumerate(SEV_ORDER)})
    f = f.sort_values(["_o", "case_id", "target"])
    st.caption(f"{len(f)} failed result(s)")
    st.dataframe(f[["case_id", "target", "axis", "severity", "title", "reason"]],
                 use_container_width=True, hide_index=True)
    for _, r in f.head(300).iterrows():
        icon = "🔴" if r.severity == "critical" else "🟠" if r.severity == "high" else "🟡"
        with st.expander(f"{icon} {r.case_id} · {r.title} — {r.target}"):
            st.markdown(f"**Axis:** {AXIS_LABELS[r.axis]} · **Severity:** {r.severity} · **Variant:** {r.variant}")
            st.markdown("**Test input**"); ar_block(r.prompt)
            st.markdown("**Reply (evidence)**"); ar_block(r.output)
            st.markdown(f"**Why it failed:** {r.reason}")
            if r.leaks:
                st.error(f"Leaked: {r.leaks}")
            st.markdown(f"**Recommendation:** {r.recommendation}")

# --------------------------------------------------------------------------- #
# Compare
# --------------------------------------------------------------------------- #
elif page == "Breakdown" and not need_run():
    st.header("Breakdown — where does each system fail?")
    dims = {"technique": "Attack technique", "goal": "Attacker goal", "obfuscation": "Arabic obfuscation",
            "variant": "Language variant", "fact": "Policy fact", "attribute": "Personal attribute (bias)"}
    dims = {k: v for k, v in dims.items() if df[(df.suite == "bank")][k].notna().any()}
    dim = st.selectbox("Dimension", list(dims), format_func=dims.get) if dims else None
    tab = breakdown(df, dim) if dim else pd.DataFrame()
    if tab.empty:
        st.info("No data for this dimension in this run.")
    else:
        fig = px.imshow(tab, text_auto=".0f", color_continuous_scale="RdYlGn", zmin=0, zmax=100, aspect="auto",
                        labels=dict(color="Pass %", x="", y=""))
        fig.update_layout(height=max(320, 28 * len(tab) + 120), margin=dict(t=20))
        st.plotly_chart(fig, use_container_width=True)
        counts = df[(df.suite == "bank") & df[dim].notna()].groupby(dim).case_id.nunique()
        st.caption("Cases per row: " + ", ".join(f"{k}: {v}" for k, v in counts.items()))

elif page == "Model benchmarks" and not need_run():
    st.header("Model benchmarks")
    if not summary["model_suites"]:
        st.info("This run has no model-level suites. Run a scan with an LLM target and the **absher** suite.")
    for ms in summary["model_suites"]:
        st.subheader(ms["label"])
        st.caption("Accuracy is only meaningful against the baseline: always answering the most frequent "
                   "option letter (per question type) already scores the baseline value.")
        st.dataframe(pd.DataFrame([{
            "Target": t["target"], "n": t["n"], "Accuracy %": t["accuracy"], "Majority baseline %": t["baseline"],
            "Lift (pts)": round(t["accuracy"] - (t["baseline"] or 0), 1), "Unparseable replies": t["unparsed"],
        } for t in ms["targets"]]), hide_index=True, use_container_width=True)
        c1, c2 = st.columns(2)
        reg = pd.DataFrame([{"target": t["target"], "region": k, "accuracy": v}
                            for t in ms["targets"] for k, v in t["by_region"].items()])
        qt = pd.DataFrame([{"target": t["target"], "type": k.replace("_", " "), "accuracy": v}
                           for t in ms["targets"] for k, v in t["by_qtype"].items()])
        if len(reg):
            f1 = px.bar(reg, x="region", y="accuracy", color="target", barmode="group", range_y=[0, 100],
                        labels={"accuracy": "Accuracy (%)", "region": ""}, title="By Saudi region")
            f1.update_layout(height=360, legend_title_text="", margin=dict(t=40))
            c1.plotly_chart(f1, use_container_width=True)
        if len(qt):
            f2 = px.bar(qt, x="type", y="accuracy", color="target", barmode="group", range_y=[0, 100],
                        labels={"accuracy": "Accuracy (%)", "type": ""}, title="By question type")
            f2.update_layout(height=360, legend_title_text="", margin=dict(t=40))
            c2.plotly_chart(f2, use_container_width=True)
        if ms["suite"] == "absher":
            st.caption("Source: Absher — Al-Monef, Alhuzali, Alturayeif & Alasmari, Alexandria Engineering Journal (2026), "
                       "doi:10.1016/j.aej.2025.12.066. Fetched at run time; not redistributed.")

elif page == "Compare models" and not need_run():
    st.header("Compare models")
    if len(summary["targets"]) < 2:
        st.info("This run has one target. Run a scan with two or more to compare.")
    else:
        fig = go.Figure()
        cats = [AXIS_LABELS[a] for a in RISK_AXES]
        for t in summary["targets"]:
            vals = [t["axis_pass_rates"][a] or 0 for a in RISK_AXES]
            fig.add_trace(go.Scatterpolar(r=vals + vals[:1], theta=cats + cats[:1], fill="toself", name=t["target"]))
        fig.update_layout(polar=dict(radialaxis=dict(range=[0, 100])), height=480, margin=dict(t=30))
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(pd.DataFrame([{
            "Target": t["target"], "Risk": t["risk_score"], "Rating": t["rating"], "Pass %": t["pass_rate"],
            "Leaks": t["leaks"], "Critical fails": t["critical_failures"],
            **{AXIS_LABELS[a]: t["axis_pass_rates"][a] for a in RISK_AXES},
        } for t in summary["targets"]]), hide_index=True, use_container_width=True)

        st.subheader("Case-by-case")
        pivot = df[df.suite == "bank"].pivot_table(index=["case_id", "axis", "severity"], columns="target", values="passed", aggfunc="first")
        diff = pivot[pivot.nunique(axis=1) > 1]
        st.caption(f"{len(diff)} case(s) where targets disagree")
        st.dataframe(diff.replace({True: "✅ pass", False: "❌ fail"}), use_container_width=True)

# --------------------------------------------------------------------------- #
# Benchmark browser
# --------------------------------------------------------------------------- #
elif page == "Benchmark":
    st.header("Benchmark")
    cases = all_cases()
    d = describe(cases)
    c = st.columns(4)
    c[0].metric("Total cases", f"{d['total']:,}")
    c[1].metric("Bank scenarios", f"{d['by_suite'].get('bank', 0):,}")
    c[2].metric("Absher (Saudi dialect)", f"{d['by_suite'].get('absher', 0):,}")
    c[3].metric("Sources", len(d["by_source"]))
    st.caption("By source: " + " · ".join(f"{k}: {v:,}" for k, v in d["by_source"].items())
               + "  |  By variant: " + " · ".join(f"{k}: {v:,}" for k, v in sorted(d["by_variant"].items(), key=lambda x: -x[1])))
    cdf = pd.DataFrame(cases)
    s1, s2, s3 = st.columns(3)
    suite = s1.selectbox("Suite", sorted(cdf.suite.unique(), key=lambda x: x != "bank"), format_func=lambda x: SUITE_LABELS.get(x, x))
    sub = cdf[cdf.suite == suite]
    axis = s2.selectbox("Axis", sorted(sub.axis.unique()), format_func=lambda a: AXIS_LABELS.get(a, a))
    sub = sub[sub.axis == axis]
    src = s3.selectbox("Source", ["all"] + sorted(sub.source.unique()))
    if src != "all":
        sub = sub[sub.source == src]
    q = st.text_input("Search prompts")
    if q:
        sub = sub[sub.prompt.str.contains(q, case=False, regex=False)]
    st.caption(f"{len(sub):,} case(s) — showing up to 100")
    for _, r in sub.head(100).iterrows():
        with st.expander(f"{r.id} · {r.get('title', '')} · {r.severity} · {r.variant}"):
            ar_block(r.prompt)
            st.json(r.check if isinstance(r.check, dict) else {})
            if isinstance(r.get("meta"), dict) and r.meta:
                st.caption("meta: " + ", ".join(f"{k}={v}" for k, v in r.meta.items()))
            if isinstance(r.get("rubric"), str):
                st.caption(f"Judge rubric: {r.rubric}")

# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #
elif page == "Report" and not need_run():
    st.header("Assessment report (English)")
    max_f = st.slider("Max findings per target", 5, 60, 25)
    if st.button("Generate report", type="primary"):
        from report.render import render

        with st.spinner("Rendering…"):
            st.session_state["report"] = {k: str(v) for k, v in render(run_dir, max_f).items()}
    rep = st.session_state.get("report")
    if rep and Path(rep["html"]).parent == run_dir:
        c1, c2, c3 = st.columns(3)
        c1.download_button("⬇ HTML report", Path(rep["html"]).read_bytes(), f"cybernext-report-{run_dir.name}.html", "text/html")
        if "pdf" in rep:
            c2.download_button("⬇ PDF report", Path(rep["pdf"]).read_bytes(), f"cybernext-report-{run_dir.name}.pdf", "application/pdf")
        else:
            c2.caption("PDF needs `pip install weasyprint`; HTML is ready.")
        c3.download_button("⬇ Raw results (CSV)", (run_dir / "results.csv").read_bytes(), f"cybernext-results-{run_dir.name}.csv", "text/csv")
        st.components.v1.html(Path(rep["html"]).read_text(encoding="utf-8"), height=900, scrolling=True)

    st.subheader("Recommendations by axis")
    for a in AXES:
        if a in AXIS_RECOMMENDATIONS:
            st.markdown(f"- **{AXIS_LABELS[a]}:** {AXIS_RECOMMENDATIONS[a]}")
