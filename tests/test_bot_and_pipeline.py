import json

import pytest
from fastapi.testclient import TestClient

from analytics.analyze import summarize
from engine.benchmark import load_cases
from engine.build_config import build
from engine.scoring import evaluate
from target.bank_bot import app, mock_reply

client = TestClient(app)
CASES = load_cases()


def test_benchmark_is_valid_and_covers_all_axes():
    assert len(CASES) >= 60
    assert {c["axis"] for c in CASES} == {"accuracy", "dialect", "injection", "leakage", "bias"}


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
    assert all(json.loads(t["vars"]["check"]) is not None for t in cfg["tests"])
    assert [p["prompts"] for p in cfg["providers"]] == [["raw"], ["raw"]]


def test_unconfigured_llm_target_is_refused(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(SystemExit):
        build(["openai"], None, tmp_path / "c.yaml")


def test_risk_score_weighting():
    import pandas as pd

    df = pd.DataFrame([
        {"target": "A", "axis": "leakage", "severity": "critical", "passed": False, "leaks": "x",
         "is_error": False, "latency_ms": 1, "weight": 10},
        {"target": "A", "axis": "dialect", "severity": "low", "passed": True, "leaks": "",
         "is_error": False, "latency_ms": 1, "weight": 1},
    ])
    t = summarize(df)["targets"][0]
    assert t["risk_score"] == pytest.approx(90.9, abs=0.1) and t["rating"] == "Critical"
