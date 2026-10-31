from __future__ import annotations

import csv
import logging
import re
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

from app.config import settings
from app.session_store import SessionStore
import app.main as main


def norm(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").casefold()).strip()


def fact_ok(answer: str, required: str) -> bool:
    if not required:
        return True

    for fact in (x.strip() for x in required.split(" ; ") if x.strip()):
        options = [x.strip() for x in fact.split(" / ") if x.strip()]

        matched = any(norm(option) in norm(answer) for option in options)

        if not matched:
            answer_digits = re.sub(r"\D", "", answer)
            matched = any(
                (lambda digits: len(digits) >= 6 and digits in answer_digits)(
                    re.sub(r"\D", "", option)
                )
                for option in options
            )

        if not matched:
            return False

    return True


def forbidden(answer: str, values: str) -> bool:
    return any(
        norm(item) in norm(answer)
        for item in (
            x.strip()
            for x in (values or "").split(" ; ")
        )
        if item
    )


def main_run() -> int:
    path = settings.dataset_dir / "practice" / "conversations.csv"

    if not path.is_file():
        print(f"Missing conversation practice file: {path}")
        return 2

    with path.open(encoding="utf-8-sig", newline="") as csv_file:
        rows = list(csv.DictReader(csv_file))

    logging.getLogger("zentromart.api").setLevel(logging.CRITICAL)

    passed = 0
    misses = []

    original_store = main.store

    try:
        # Use an isolated temporary database for evaluation.
        with tempfile.TemporaryDirectory(prefix="zentro-eval-") as tmp:
            main.store = SessionStore(Path(tmp) / "sessions.sqlite3")

            # TestClient's context manager runs application shutdown
            # handlers and closes the client when evaluation finishes.
            with TestClient(main.app) as client:
                # Prevent evaluation tickets from being written to
                # the supplied dataset.
                with patch(
                    "app.main._ticket",
                    return_value={
                        "created": True,
                        "ticket_id": "EVAL-TICKET",
                    },
                ):
                    groups: dict[str, list[dict[str, str]]] = {}

                    for row in rows:
                        groups.setdefault(
                            row["conversation_id"], []
                        ).append(row)

                    for index, (cid, turns) in enumerate(groups.items()):
                        sid = f"abcdef12-1234-1234-1234-{index:012d}"

                        for row in sorted(
                            turns,
                            key=lambda item: int(item["turn"]),
                        ):
                            response = client.post(
                                "/chat",
                                json={
                                    "session_id": sid,
                                    "message": row["customer_message"],
                                },
                            )

                            if response.status_code != 200:
                                misses.append(
                                    (
                                        cid,
                                        row["turn"],
                                        f"HTTP {response.status_code}",
                                        row["expected_decision"],
                                        "",
                                    )
                                )
                                continue

                            body = response.json()
                            reply = body.get("reply", "")

                            decision_ok = (
                                body.get("decision")
                                == row["expected_decision"]
                            )

                            facts_ok = fact_ok(
                                reply,
                                row.get("must_include", ""),
                            )

                            has_forbidden = forbidden(
                                reply,
                                row.get("must_not_include", ""),
                            )

                            if (
                                decision_ok
                                and facts_ok
                                and not has_forbidden
                            ):
                                passed += 1
                            else:
                                misses.append(
                                    (
                                        cid,
                                        row["turn"],
                                        body.get("decision"),
                                        row["expected_decision"],
                                        (
                                            f"facts_ok={facts_ok}; "
                                            f"forbidden={has_forbidden}; "
                                            f"reply={reply[:180]!r}"
                                        ),
                                    )
                                )
    finally:
        # Restore the application's original session store even
        # if evaluation raises an exception.
        main.store = original_store

    print(
        f"Conversation checks: {passed}/{len(rows)} pass "
        "on decision and exact/alternative fact checks."
    )

    if misses:
        print("Rows needing review:")

        for item in misses:
            print(
                f"- {item[0]} turn={item[1]} "
                f"actual={item[2]} expected={item[3]} {item[4]}"
            )

    print(
        "Note: automated phrase matching is diagnostic; "
        "review semantic equivalence and Hindi/Hinglish phrasing manually."
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main_run())
