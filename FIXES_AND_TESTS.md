# ZentroMart Support Agent — correction notes

## Changes in this revision

- Added explicit greeting handling so short greetings do not retrieve arbitrary KB sections.
- Added a clear capability response for “How can you help me?”
- Added safe handling for questions about the user's own name or ID; the assistant does not infer identity from policy documents.
- Tightened the generic KB fallback: it now requires a meaningful overlap and minimum score before quoting a KB section; otherwise it returns the safe unknown response.
- Added a verified-order delay path: if the record says delivered while the customer reports a delay, the assistant explains the mismatch and asks for confirmation instead of repeating the order total/status as if that resolved the issue.
- Corrected whitespace and digit-normalization regexes in the conversation evaluation script.
- Added regression tests for greeting, help, personal identity, and unrelated recipe queries.
- Preserved verification gates and the existing ticket creation confirmation behavior.

## Validation run

Commands run from the project root:

```powershell
pytest -q
python scripts/evaluate_practice.py
python scripts/evaluate_conversations.py
python Capstone_Project_Dataset_FTTT_2026/validate_dataset.py
python -m compileall -q app frontend scripts tests
```

Results on the supplied dataset:

- Pytest: 27 passed
- Practice evaluation: 52/52 passed
- Conversation evaluation: 96/96 passed
- Dataset validation: passed (9 CSVs, 21 KB documents, 1,000 orders, 1,783 order items, 244 support logs, 52 practice questions, 23 conversations)

The conversation evaluator checks decisions and exact/alternative required phrases. It is a useful regression check, not a guarantee of correctness for every possible customer message.
