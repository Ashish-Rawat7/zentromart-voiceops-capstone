# ZentroMart Support Agent — Capstone v3

This project is built against the supplied `Capstone_Project_Dataset_FTTT_2026` folder. It uses **FastAPI + Streamlit + SQLite + CSV/Markdown**. PostgreSQL is not required.

> **Honest scope:** This is an evaluation-oriented capstone implementation with explicit policy rules, guarded mock-tool access, tests, and an offline practice-question evaluator. It is not certified for real customer production use. The dataset's mock verification is educational, and production deployment would require real authentication, access controls, observability, rate limiting, deployment hardening, and privacy review.

## Included dataset

The supplied dataset is bundled at `./Capstone_Project_Dataset_FTTT_2026/`, so the default `.env` path works when run from this project root. The project reads CSV data as strings to preserve IDs, SKUs, and pincodes. The dataset's fixed reference date is **20 October 2026**.

## Setup (Windows / VS Code)

1. Extract the ZIP.
2. Open the extracted `zentromart_support_agent_capstone_v3` folder in VS Code.
3. Create a virtual environment:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

4. Install dependencies:

   ```powershell
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   ```

5. Create your local `.env` from `.env.example`:

   ```powershell
   Copy-Item .env.example .env
   ```

6. Leave `ENABLE_GEMINI=false` for deterministic offline behavior. To enable Gemini, set `ENABLE_GEMINI=true`, add your own `GEMINI_API_KEY`, and keep `.env` out of Git.

## Run the dataset validator and tests

```powershell
python Capstone_Project_Dataset_FTTT_2026/validate_dataset.py
pytest
python scripts/evaluate_practice.py
python scripts/evaluate_conversations.py
```

The evaluation scripts print single-question and multi-turn conversation failures. It uses exact/alternative phrase checks as a diagnostic; it is not a replacement for semantic and native-language human review. The official practice data includes Hindi and Hinglish, so review the output instead of assuming a perfect score.

## Start the application

Open **two VS Code terminals** in the project root.

Terminal 1 — API:

```powershell
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Terminal 2 — Streamlit:

```powershell
streamlit run frontend/streamlit_app.py
```

Open the local Streamlit URL shown in the terminal (normally `http://localhost:8501`). API docs are at `http://127.0.0.1:8000/docs`; health is at `http://127.0.0.1:8000/health`.

## Implemented behavior

- CSV tables are read-only and loaded with all fields preserved as text.
- Section-aware Markdown retrieval parses metadata, section IDs, status, and effective dates; current policy documents rank above agent guides/help/FAQs/marketing.
- Deterministic policy rules cover the retained practice set's common intents: returns, festive sale exceptions, historical electronics windows, pickup fees, refund timelines and business-day calculations, cancellation, delivery attempts, warranty, damage claims, product safety, coupons, unsupported questions, and privacy refusal.
- Order lookup uses the dataset's exact `lookup_order(order_id, verification_value=...)` contract.
- Order details are only disclosed when both `found=True` and `verified=True`.
- Verification allows at most two attempts. Proof values are not stored in the SQLite session table or logged by the API.
- Only allowlisted order fields and item fields are persisted; registered phone, email, address, and delivery pincode are not exposed in the API response.
- Ticket creation uses `create_ticket(summary=..., order_id=..., reason=..., intent=...)` and success is claimed only when the tool returns `created=True`.
- SQLite stores session state. It is appropriate for this local single-instance capstone; use a database migration before multi-instance deployment.
- Gemini is optional and is only used for unresolved questions when enabled and configured. Core benchmark rules work without it.

## Main API routes

- `GET /health`
- `POST /chat` — `{"session_id":"<opaque-id>","message":"..."}`
- `POST /orders/start` — start order verification
- `POST /orders/verify` — verify with phone suffix or delivery pincode
- `POST /tickets` — create a support ticket; an attached order must be verified in the current session

## Example request

```json
{
  "session_id": "12345678-1234-1234-1234-123456789abc",
  "message": "How long does a refund to UPI take?"
}
```

## Important boundaries

- The dataset's tool verification is not real authentication and the app is intended for synthetic capstone data only.
- Never ask for OTPs, passwords, UPI PINs, full card details, or another customer's personal data.
- No cancellation tool exists: the assistant guides the customer to My Orders and never claims to cancel an order.
- The support-log CSV is historical data, not an authoritative policy source.
- Gnani STT/TTS voice integration is not implemented in this version because API credentials and service configuration are not included in the dataset ZIP.
- Do not expose the service publicly as-is. Before real deployment, add authenticated accounts, server-side session authorization, CSRF considerations for browser auth, request rate limits, monitoring, secrets management, migrations/backups, and a privacy/security review.
