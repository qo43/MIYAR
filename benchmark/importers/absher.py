"""Import Absher (Saudi dialect & culture benchmark) as the `absher` suite.

    python -m benchmark.importers.absher [--src PATH]

Absher: 18k+ multiple-choice questions about Saudi dialect words, phrases and
proverbs from five regions, by Al-Monef, Alhuzali, Alturayeif & Alasmari
(Alexandria Engineering Journal, 2026, doi:10.1016/j.aej.2025.12.066).

The upstream repository declares no licence, so this importer downloads it at
run time into benchmark/external/ (git-ignored) and nothing from it is committed
here. Cite the authors when you publish results.

Cleaning applied (and reported):
  * answers given as Latin A–D are mapped to أ–د
  * rows with an empty answer, or an answer that is not one of the parsed options, are dropped
  * region labels are trimmed ("Eastern " → "Eastern")
  * exact duplicate prompts are dropped
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from engine.arabic import normalize  # noqa: E402

REPO = "https://github.com/renad-01/Absher-Benchmark"
COMMIT = "692857e9adb56c70943718e7480b5c696d94af53"  # pinned for reproducibility
SRC = ROOT / "benchmark" / "external" / "_src" / "absher"
OUT = ROOT / "benchmark" / "external" / "absher.json"

LATIN = {"A": "أ", "B": "ب", "C": "ج", "D": "د"}
ARABIC = {"أ", "ب", "ج", "د", "ا"}
OPTION_LINE = re.compile(r"^\s*([أابجد]|[A-D])\s*[)\-.:]\s*(.+?)\s*$")
UNIT_CODE = {"Words": "W", "Phrases": "P", "Proverbs": "V"}
QTYPE_CODE = {"Meaning": "MEA", "True_False": "TF", "Fill_in_Blank": "FIB", "Contextual_Usage": "CTX",
              "Cultural_Interpretation": "CUL", "Location_Recognition": "LOC"}
INSTRUCTION_AR = "\n\nأجب بحرف الخيار الصحيح فقط (أ أو ب أو ج أو د)."
INSTRUCTION_LATIN = "\n\nأجب بحرف الخيار الصحيح فقط كما هو مكتوب في الخيارات (A أو B أو C أو D)."


def fetch(src: Path) -> Path:
    if (src / ".git").exists():
        subprocess.run(["git", "-C", str(src), "fetch", "-q", "--depth", "1", "origin", COMMIT], check=False)
    else:
        src.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-q", str(src)], check=True)
        subprocess.run(["git", "-C", str(src), "remote", "add", "origin", REPO], check=True)
        subprocess.run(["git", "-C", str(src), "fetch", "-q", "--depth", "1", "origin", COMMIT], check=True)
    subprocess.run(["git", "-C", str(src), "-c", "advice.detachedHead=false", "checkout", "-q", COMMIT], check=True)
    return src


def _answer(raw: str) -> str | None:
    a = (raw or "").strip().strip(").").strip()
    if not a:
        return None
    a = a[0]
    if a in LATIN:
        return LATIN[a]
    if a in ARABIC:
        return "أ" if a == "ا" else a
    return None


def _options(question: str) -> dict[str, str]:
    opts = {}
    for line in question.splitlines():
        m = OPTION_LINE.match(line)
        if m:
            k = _answer(m.group(1))
            if k:
                opts[k] = m.group(2)
    return opts


def build(src: Path) -> tuple[list[dict], Counter]:
    cases, seen, drops = [], set(), Counter()
    for f in sorted(src.glob("*/*_questions.csv")):
        unit = f.parent.name
        qtype = f.name.replace(f"{unit}_", "").replace("_questions.csv", "")
        with f.open(encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.DictReader(fh))
        qcol = next(c for c in rows[0] if c.endswith("_question"))
        for i, r in enumerate(rows):
            q = (r.get(qcol) or "").strip()
            ans = _answer(r.get("correct_answer", ""))
            opts = _options(q)
            if not q or not ans:
                drops["empty question/answer"] += 1
                continue
            if ans not in opts:
                drops["answer not among options"] += 1
                continue
            key = normalize(q)
            if key in seen:
                drops["duplicate"] += 1
                continue
            seen.add(key)
            region = " ".join((r.get("Dialect type") or "").split()) or "Unknown"
            cases.append({
                "id": f"ABS-{UNIT_CODE.get(unit, 'X')}-{QTYPE_CODE.get(qtype, 'OTH')}-{i:05d}",
                "severity": "low",
                "variant": "saudi",
                "title": f"{unit} · {qtype.replace('_', ' ')} · {region}",
                # match the instruction to how this question labels its options
                "prompt": q + (INSTRUCTION_LATIN if re.search(r"^\s*[A-D]\s*[)\-.:]", q, re.M) else INSTRUCTION_AR),
                "check": {"choice": {"answer": ans, "options": opts}, "no_leak": False},
                "meta": {"unit": unit, "qtype": qtype, "region": region, "term": (r.get("Term") or "").strip()},
            })
    return cases, drops


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", type=Path, help="use an existing local copy instead of fetching")
    a = ap.parse_args()
    src = a.src or fetch(SRC)
    cases, drops = build(src)
    doc = {
        "axis": "dialect_knowledge",
        "suite": "absher",
        "source": "absher",
        "license": "No licence declared upstream — fetched at run time, not redistributed.",
        "citation": "Al-Monef, Alhuzali, Alturayeif, Alasmari. From words to proverbs: Evaluating LLMs' linguistic and cultural competence in Saudi dialects with Absher. Alexandria Engineering Journal, 2026. doi:10.1016/j.aej.2025.12.066",
        "applies_to": ["llm"],
        "description": f"Absher @ {COMMIT[:7]}: Saudi dialect words/phrases/proverbs, 6 question types, 5 regions + general.",
        "cases": cases,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, ensure_ascii=False) + "\n", encoding="utf-8")
    sys.stdout.reconfigure(errors="replace")
    print(f"absher: {len(cases)} cases → {OUT.relative_to(ROOT)}  (dropped: {dict(drops)})")
    print("  by region:", dict(Counter(c['meta']['region'] for c in cases).most_common()))
    print("  by type:  ", dict(Counter(c['meta']['qtype'] for c in cases).most_common()))


if __name__ == "__main__":
    main()
