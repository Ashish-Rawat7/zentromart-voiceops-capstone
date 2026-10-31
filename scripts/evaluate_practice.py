from __future__ import annotations
import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.agent import answer_policy
from app.config import settings

def normalize(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").casefold()).strip()

def fact_present(answer: str, fact: str) -> bool:
    # Dataset alternatives use slash separators. Date spellings are also compared by digits.
    answer_n = normalize(answer)
    options = [x.strip() for x in fact.split(" / ") if x.strip()]
    for option in options:
        option_n = normalize(option)
        if option_n and option_n in answer_n:
            return True
        digits = re.sub(r"\D", "", option)
        answer_digits = re.sub(r"\D", "", answer_n)
        if len(digits) >= 6 and digits in answer_digits:
            return True
    return False

def main() -> int:
    path = settings.dataset_dir / "practice" / "questions.csv"
    if not path.is_file():
        print(f"Missing practice file: {path}")
        return 2
    rows = list(csv.DictReader(path.open(encoding="utf-8-sig", newline="")))
    passed = 0
    misses = []
    for row in rows:
        answer, sources, decision = answer_policy(row["question"])
        expected_decisions = [x.strip() for x in (row.get("acceptable_decisions") or row["expected_decision"]).split(" ; ") if x.strip()]
        if row["expected_decision"] not in ("", None) and not expected_decisions:
            expected_decisions = [row["expected_decision"]]
        decision_ok = decision in expected_decisions or decision == row["expected_decision"]
        include_facts = [x.strip() for x in row.get("must_include", "").split(" ; ") if x.strip()]
        missing = [fact for fact in include_facts if not fact_present(answer, fact)]
        forbidden = [x.strip() for x in row.get("must_not_include", "").split(" ; ") if x.strip()]
        forbidden_found = [fact for fact in forbidden if normalize(fact) and normalize(fact) in normalize(answer)]
        # Evaluation score is diagnostic; native-language semantic equivalence needs review.
        ok = decision_ok and not missing and not forbidden_found
        if ok: passed += 1
        else:
            misses.append((row["id"], row["intent"], decision, row["expected_decision"], missing, forbidden_found, answer[:180]))
    print(f"Practice question checks: {passed}/{len(rows)} pass on exact/alternative fact checks.")
    if misses:
        print("\nNeeds review (some language paraphrases can be false negatives):")
        for row in misses:
            print(f"- {row[0]} intent={row[1]} decision={row[2]} expected={row[3]} missing={row[4]} forbidden={row[5]} answer={row[6]!r}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
