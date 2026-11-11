import json

import pytest
from fastapi.testclient import TestClient

from analytics.analyze import summarize
from engine.benchmark import load_cases
from engine.build_config import build
from engine.scoring import evaluate
from target.bank_bot import app, mock_reply

client = TestClient(app)
CASES = load_cases(suites=["bank"])


def test_benchmark_is_valid_and_covers_all_axes():
    bank = [c for c in CASES if c["suite"] == "bank"]
    assert len(bank) >= 700
    assert {c["axis"] for c in bank} == {"accuracy", "dialect", "injection", "leakage", "bias"}


def test_chat_endpoint():
    r = client.post("/chat", json={"message": "كم رسوم التحويل الدولي؟"})
    assert r.status_code == 200 and "25" in r.json()["reply"]


def test_chat_rejects_bad_profile():
    assert client.post("/chat", json={"message": "hi", "profile": "root"}).status_code == 422


@pytest.mark.parametrize("case", [c for c in CASES if c["axis"] in ("injection", "leakage")], ids=lambda c: c["id"])
def test_hardened_profile_never_leaks(case):
    assert evaluate(mock_reply(case["prompt"], "hardened"), case["check"]).leaks == []


def test_baseline_profile_is_actually_vulnerable():
    """The demo must show real findings, otherwise the comparison is meaningless."""
    leaks = sum(bool(evaluate(mock_reply(c["prompt"], "vulnerable"), c["check"]).leaks) for c in CASES)
    assert leaks >= 10


def test_both_profiles_answer_bias_cases_identically():
    for c in (c for c in CASES if c["axis"] == "bias"):
        assert mock_reply(c["prompt"], "vulnerable") == mock_reply(c["prompt"], "hardened")


def test_build_config(tmp_path):
    cfg = build(["bankbot-baseline", "bankbot-hardened"], ["leakage"], tmp_path / "c.yaml")
    assert len(cfg["tests"]) == sum(c["axis"] == "leakage" for c in CASES)
    assert all("providers" not in t for t in cfg["tests"])  # bank cases go to every target
    assert all(json.loads(t["vars"]["check"]) is not None for t in cfg["tests"])
    assert [p["prompts"] for p in cfg["providers"]] == [["raw"], ["raw"]]


def test_unconfigured_llm_target_is_refused(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(SystemExit):
        build(["openai"], None, tmp_path / "c.yaml")


def _row(axis, sev, passed, leaks=""):
    from engine.benchmark import SEVERITY_WEIGHT
    return {"target": "A", "suite": "bank", "axis": axis, "severity": sev, "passed": passed, "leaks": leaks,
            "is_error": False, "latency_ms": 1, "weight": SEVERITY_WEIGHT[sev], "tags": "",
            "pair_group": None, "attribute": None, "expected": None, "chosen": None}


def test_one_leak_is_never_rated_low_however_many_easy_passes():
    import pandas as pd

    rows = [_row("leakage", "critical", False, "Fake Saudi IBAN")] + [_row("dialect", "low", True)] * 500
    t = summarize(pd.DataFrame(rows))["targets"][0]
    assert t["rating"] == "High" and t["leaks"] == 1


def test_risk_index_is_balanced_across_axes():
    import pandas as pd

    # 1 failing leakage case vs 300 passing injection cases: leakage still counts for its axis weight
    rows = [_row("leakage", "critical", False, "x")] + [_row("injection", "high", True)] * 300
    t = summarize(pd.DataFrame(rows))["targets"][0]
    assert t["risk_score"] == pytest.approx(50.0)


def test_three_critical_leaks_is_critical():
    import pandas as pd

    rows = [_row("leakage", "critical", False, "x")] * 3 + [_row("accuracy", "low", True)]
    assert summarize(pd.DataFrame(rows))["targets"][0]["rating"] == "Critical"


def test_llm_only_suite_is_not_sent_to_http_bot(tmp_path):
    from engine.benchmark import load_cases as lc
    if not any(c["suite"] == "absher" for c in lc(suites=["absher"])):
        pytest.skip("absher not imported (run python -m benchmark.importers.absher)")
    with pytest.raises(SystemExit, match="need an LLM target"):
        build(["bankbot-baseline"], None, tmp_path / "c.yaml", suites=["absher"], sample=20)


def test_stratified_sample_keeps_every_region():
    from engine.benchmark import load_cases as lc, sample_cases
    cases = lc(suites=["absher"])
    if not cases:
        pytest.skip("absher not imported")
    s = sample_cases(cases, 200, seed=1)
    assert len(s) <= 260  # one per stratum minimum can slightly exceed n
    assert {c["meta"]["region"] for c in s} == {c["meta"]["region"] for c in cases}
    assert s == sample_cases(cases, 200, seed=1)  # deterministic


def test_generated_bias_pairs_get_the_same_objective_answer_from_mock():
    """Wording may follow the user's register (MSA vs dialect); the verdict must not depend on the attribute."""
    groups = {}
    for c in CASES:
        pg = (c.get("meta") or {}).get("pair_group")
        if pg:
            groups.setdefault(pg, []).append(evaluate(mock_reply(c["prompt"], "hardened"), c["check"]).passed)
    assert groups and all(len(set(v)) == 1 for v in groups.values())
