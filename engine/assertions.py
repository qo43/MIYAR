"""Promptfoo python assertion hook: `type: python, value: file://engine/assertions.py`."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.scoring import evaluate  # noqa: E402


def get_assert(output, context):
    v = evaluate(output if isinstance(output, str) else str(output), context["vars"].get("check"))
    return {"pass": v.passed, "score": v.score, "reason": v.reason}
