from __future__ import annotations

from contextlib import asynccontextmanager
import base64
import logging
import re

from fastapi import (
    FastAPI,
    HTTPException,
    Request,
    File,
    Form,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.data import dataset
from app.dates import REFERENCE_DATE, add_business_days, fmt
from app.schemas import (
    ChatRequest,
    ChatResponse,
    OrderStartRequest,
    OrderStartResponse,
    OrderVerifyRequest,
    OrderVerifyResponse,
    TicketRequest,
    TicketResponse,
)
from app.session_store import SessionStore
from app.security import (
    valid_session_id,
    normalize_digits,
    normalize_order_id,
    extract_order_id,
    is_phone_suffix,
    is_pincode,
    redact_secrets,
)
from app.tools_adapter import (
    begin_order_lookup,
    verify_order_lookup,
    lookup_is_valid_request,
    verification_succeeded,
    public_order_details,
    create_support_ticket,
)
from app.agent import answer_policy, _product_match
from app.voice import transcribe_audio, synthesize_reply


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("zentromart.api")
store = SessionStore()


@asynccontextmanager
async def lifespan(app: FastAPI):
    store.cleanup_expired()
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Policy-grounded ZentroMart capstone support API.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.middleware("http")
async def safe_request_logging(request: Request, call_next):
    # Never log request bodies, query parameters, session IDs,
    # order IDs, or verification values.
    response = await call_next(request)
    logger.info(
        "request method=%s path=%s status=%s",
        request.method,
        request.url.path,
        response.status_code,
    )
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception(
        "unhandled_error path=%s type=%s",
        request.url.path,
        type(exc).__name__,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal error occurred. Please try again."},
    )


def _state(session_id: str) -> dict:
    if not valid_session_id(session_id):
        raise HTTPException(
            status_code=400,
            detail="Invalid session identifier.",
        )
    return store.get(session_id)


def _save(session_id: str, state: dict):
    store.save(session_id, state)


def _start_lookup(session_id: str, state: dict, order_id: str):
    order_id = normalize_order_id(order_id)

    if len(order_id) != 8:
        raise HTTPException(
            status_code=422,
            detail="Please enter the 8-digit order ID.",
        )

    result = begin_order_lookup(order_id)

    if not lookup_is_valid_request(result):
        logger.warning("order_lookup_contract_failed")
        raise HTTPException(
            status_code=503,
            detail="Order verification is temporarily unavailable.",
        )

    state.update(
        {
            "pending_order_id": order_id,
            "verified_order_id": None,
            "verified": False,
            "verification_attempts": 0,
            "verification_locked": False,
            "verified_order_details": {},
            "last_intent": "order",
        }
    )
    _save(session_id, state)


def _safe_order_reply(details: dict, message: str) -> str:
    n = message.casefold()

    labels = {
        "order_id": "Order ID",
        "status": "Status",
        "payment_method": "Payment method",
        "delivery_type": "Delivery type",
        "promised_date": "Promised delivery date",
        "shipped_on": "Shipped on",
        "delivered_on": "Delivered on",
        "delivery_attempts": "Delivery attempts",
        "total_inr": "Order total (₹)",
        "return_status": "Return status",
        "return_requested_on": "Return requested on",
        "return_pickup_on": "Return pickup date",
        "return_refund_initiated_on": "Return refund initiated",
        "return_refund_completed_on": "Return refund completed",
        "return_refund_amount_inr": "Return refund amount (₹)",
        "return_refund_method": "Return refund method",
        "return_rrn": "Refund reference number",
        "cancellation_refund_initiated_on": "Cancellation refund initiated",
        "cancellation_refund_method": "Cancellation refund method",
        "cancellation_refund_amount_inr": "Cancellation refund amount (₹)",
        "cancellation_rrn": "Cancellation refund reference number",
        "rto_refund_initiated_on": "RTO refund initiated",
        "rto_refund_method": "RTO refund method",
        "rto_refund_amount_inr": "RTO refund amount (₹)",
        "rto_rrn": "RTO refund reference number",
        "express_late_credit_inr": "Express late-delivery wallet credit (₹)",
        "express_late_credit_on": "Express wallet credit date",
        "damage_status": "Damage claim status",
        "damage_reported_at": "Damage reported at",
        "damage_issue": "Reported issue",
        "timeline": "Order timeline",
        "placed_at": "Order placed",
    }

    if any(
        x in n
        for x in (
            "refund",
            "rrn",
            "money back",
            "रिफ़ंड",
            "रिफंड",
        )
    ):
        keys = [
            k
            for k in (
                "return_status",
                "return_refund_initiated_on",
                "return_refund_completed_on",
                "return_refund_amount_inr",
                "return_refund_method",
                "return_rrn",
                "cancellation_refund_initiated_on",
                "cancellation_refund_method",
                "cancellation_refund_amount_inr",
                "cancellation_rrn",
                "rto_refund_initiated_on",
                "rto_refund_method",
                "rto_refund_amount_inr",
                "rto_rrn",
            )
            if details.get(k)
        ]
        if not keys:
            keys = ["status", "payment_method", "timeline"]

    elif any(x in n for x in ("ship", "dispatch")):
        keys = ["order_id", "status", "shipped_on", "timeline"]

    elif any(
        x in n
        for x in (
            "deliver",
            "where is",
            "status",
            "track",
            "arrive",
            "order kahan",
        )
    ):
        keys = [
            "order_id",
            "status",
            "promised_date",
            "shipped_on",
            "delivered_on",
            "delivery_attempts",
            "timeline",
        ]

    else:
        keys = [
            "order_id",
            "status",
            "payment_method",
            "delivery_type",
            "promised_date",
            "shipped_on",
            "delivered_on",
            "total_inr",
            "timeline",
        ]

    lines = [
        f"**{labels.get(k, k.replace('_', ' ').title())}:** {details[k]}"
        for k in keys
        if details.get(k) not in (None, "", [], {})
    ]

    items = details.get("items") or []

    if any(
        x in n for x in ("item", "product", "bought", "purchased", "what is in")
    ) and items:
        lines.append(
            "**Items:** "
            + ", ".join(
                f"{i.get('title') or i.get('sku')} × {i.get('qty') or 1}"
                for i in items
            )
        )

    if not lines:
        return (
            "I verified the order, but the dataset has no recorded details "
            "for that specific question. I can help with the general policy "
            "or create a ticket."
        )

    return (
        "Here are the confirmed details for your verified order:\n\n"
        + "\n".join(lines)
    )


def _ticket(
    summary: str,
    order_id: str | None,
    reason: str,
    intent: str | None = None,
) -> dict:
    result = create_support_ticket(
        summary=redact_secrets(summary[:2500]),
        order_id=order_id,
        reason=reason,
        intent=intent,
    )
    return result if result.get("created") is True else {"created": False}


def _maybe_create_escalation_ticket(
    message: str,
    state: dict,
    decision: str,
    sources: list[str],
) -> dict:
    if decision != "escalate":
        return {"created": False}

    order_id = (
        state.get("verified_order_id")
        if state.get("verified")
        else None
    )
    reason = "customer_requested_human"
    low = message.casefold()

    if any(
        x in low
        for x in (
            "never placed",
            "unauthorized",
            "unauthorised",
            "didn't order",
            "did not order",
        )
    ):
        reason = "unauthorized_activity"

    elif any(
        x in low
        for x in ("crack", "broken", "damaged", "torn", "defective")
    ):
        reason = "high_value_damage"

    summary = (
        f"Customer issue: {message[:800]}. Intent: {reason}. "
        f"Checks completed: relevant policy evidence "
        f"{', '.join(sources) or 'none'} reviewed. "
        "Reason for escalation: policy requires human review; "
        "no outcome has been promised."
    )

    return _ticket(summary, order_id, reason, reason)


def _verification_message(
    message: str,
    state: dict,
) -> ChatResponse | None:
    if (
        not state.get("pending_order_id")
        or state.get("verified")
        or state.get("verification_locked")
    ):
        return None

    digits = normalize_digits(message)

    # Verification values are accepted only when the message
    # contains exactly one plausible proof.
    if len(digits) not in (4, 6):
        return None

    if not (
        is_phone_suffix(digits)
        if len(digits) == 4
        else is_pincode(digits)
    ):
        return None

    result = verify_order_lookup(state["pending_order_id"], digits)
    state["verification_attempts"] = (
        int(state.get("verification_attempts", 0)) + 1
    )

    if verification_succeeded(result):
        details = public_order_details(result)

        state.update(
            {
                "verified": True,
                "verified_order_id": state["pending_order_id"],
                "pending_order_id": None,
                "verified_order_details": details,
                "verification_attempts": 0,
                "verification_locked": False,
            }
        )

        pending_intent = state.get("pending_intent") or "generic"
        state["pending_intent"] = None
        _save(state["_session_id"], state)

        if pending_intent in {"where", "delivery", "status"}:
            reply = _safe_order_reply(details, "Where is my order?")
        elif pending_intent == "refund":
            reply = _safe_order_reply(details, "refund status")
        elif pending_intent == "shipment":
            reply = _safe_order_reply(details, "when was it shipped")
        else:
            reply = (
                "Verification successful. Your order details are now "
                "available in this conversation. What would you like "
                "to know about the order?"
            )

        return ChatResponse(
            reply=reply,
            decision="answer",
            sources=["Verified order lookup"],
        )

    remaining = max(
        0,
        settings.max_verification_attempts
        - state["verification_attempts"],
    )

    if remaining == 0:
        state["verification_locked"] = True
        state["pending_order_id"] = None
        _save(state["_session_id"], state)

        return ChatResponse(
            reply=(
                "I couldn't verify those details after two attempts, "
                "so I can't share any order information. Please contact "
                "support from your registered phone number. I can still "
                "answer general policy questions."
            ),
            decision="refuse",
        )

    _save(state["_session_id"], state)

    return ChatResponse(
        reply=(
            "Those details didn't match. Please try once more using "
            "either the last four digits of the registered phone number "
            "or the six-digit delivery pincode. I won't reveal the "
            "expected value."
        ),
        decision="clarify",
        verification_required=True,
    )


def _create_context_ticket(
    message: str,
    state: dict,
    reason: str,
    sources: list[str],
) -> dict:
    oid = (
        state.get("verified_order_id")
        if state.get("verified")
        else None
    )

    summary = (
        f"Customer issue: {message[:700]}. Intent: {reason}. "
        f"Verified order: {oid or 'not attached'}. "
        f"Checks completed: inspected the verified synthetic order "
        f"record and policy sources {', '.join(sources)}. "
        f"Escalation reason: {reason}; no resolution has been promised."
    )

    return _ticket(summary, oid, reason, reason)


def _business_timeline(method: str) -> tuple[int, int] | None:
    m = (method or "").casefold()

    if m == "upi":
        return 1, 3
    if m in {"card", "credit card", "debit card"}:
        return 5, 7
    if m == "netbanking":
        return 3, 5
    if m in {"wallet", "cod_wallet"}:
        return 0, 0
    if m == "cod_bank":
        return 5, 7

    return None


def _product_from_verified_order(message: str, details: dict):
    from app.agent import _norm
    from app.data import dataset as _dataset

    query_tokens = {
        t for t in _norm(message).split() if len(t) > 2
    }
    items = details.get("items") or []
    candidates = []

    for item in items:
        title = item.get("title") or ""
        tokens = {
            t for t in _norm(title).split() if len(t) > 2
        }
        overlap = len(query_tokens & tokens) / max(1, len(tokens))

        if overlap >= 0.55:
            candidates.append((overlap, item.get("sku")))

    if candidates:
        candidates.sort(reverse=True)
        sku = candidates[0][1]
        return next(
            (
                p
                for p in _dataset.products()
                if p.get("sku") == sku
            ),
            None,
        )

    return _product_match(message)


def _verified_context_answer(
    message: str,
    state: dict,
) -> ChatResponse | None:
    """Resolve follow-ups using previously verified order data."""
    details = state.get("verified_order_details") or {}

    if not details or not state.get("verified"):
        return None

    n = message.casefold()

    # Repeat-contact rule.
    try:
        prior_contacts = int(details.get("contacts_last_7_days") or 0)
    except (ValueError, TypeError):
        prior_contacts = 0

    if prior_contacts >= 2 and any(
        x in n
        for x in (
            "third time",
            "third call",
            "this week",
            "teesri baar",
            "तीसरी बार",
            "same issue",
        )
    ):
        sources = ["ESC-1", "ESC-2"]
        ticket = _create_context_ticket(
            message, state, "repeat_contact", sources
        )
        reply = (
            "I can see this issue has had repeated contact. Policy "
            "requires a human handover, so I'm escalating it for review."
        )

        if ticket.get("created") is True:
            reply += (
                f" A support ticket has been created "
                f"(ID: {ticket.get('ticket_id')})."
            )
            return ChatResponse(
                reply=reply,
                sources=sources,
                decision="escalate",
                ticket_created=True,
                ticket_id=ticket.get("ticket_id"),
            )

        return ChatResponse(
            reply=reply
            + " I couldn't confirm ticket creation, so I won't claim "
            "it was created. Please contact support directly.",
            sources=sources,
            decision="escalate",
        )

    # Specific refund follow-up.
    refund_intent = any(
        x in n
        for x in (
            "refund",
            "rrn",
            "money back",
            "paisa",
            "रिफ़ंड",
            "रिफंड",
            "mera refund",
            "मेरा रिफ़ंड",
        )
    )

    if refund_intent:
        candidates = [
            (
                "return_refund_initiated_on",
                "return_refund_method",
                "return_refund_amount_inr",
                "return_rrn",
            ),
            (
                "cancellation_refund_initiated_on",
                "cancellation_refund_method",
                "cancellation_refund_amount_inr",
                "cancellation_rrn",
            ),
            (
                "rto_refund_initiated_on",
                "rto_refund_method",
                "rto_refund_amount_inr",
                "rto_rrn",
            ),
        ]

        selected = next(
            (x for x in candidates if details.get(x[0])),
            None,
        )

        if selected:
            started_key, method_key, amount_key, rrn_key = selected
            started = __import__("datetime").date.fromisoformat(
                details[started_key][:10]
            )
            method = (details.get(method_key) or "").casefold()
            rrn = details.get(rrn_key) or ""
            ranges = _business_timeline(method)

            latest = (
                add_business_days(
                    started,
                    ranges[1],
                    dataset.holidays(),
                )
                if ranges and ranges[1]
                else started
            )

            if (
                ranges
                and ranges[1]
                and REFERENCE_DATE
                > add_business_days(latest, 3, dataset.holidays())
            ):
                sources = ["REF-2", "ESC-1", "ESC-2", "KB-00.3"]
                ticket = _create_context_ticket(
                    message, state, "refund_overdue", sources
                )

                reply = (
                    f"The refund was initiated on {started.isoformat()} "
                    f"by {method}. Its normal maximum timeline ended on "
                    f"{latest.isoformat()}. It is now beyond the policy's "
                    f"escalation grace period. Your refund reference number "
                    f"(RRN) is {rrn or 'not recorded in the dataset'}. "
                    "This needs a human colleague to investigate."
                )

                if ticket.get("created") is True:
                    reply += (
                        f" I created a support ticket "
                        f"(ID: {ticket.get('ticket_id')})."
                    )
                    return ChatResponse(
                        reply=reply,
                        sources=sources,
                        decision="escalate",
                        ticket_created=True,
                        ticket_id=ticket.get("ticket_id"),
                    )

                return ChatResponse(
                    reply=reply
                    + " I couldn't confirm ticket creation, so I won't "
                    "claim a ticket was created.",
                    sources=sources,
                    decision="escalate",
                )

            text = (
                f"The refund was initiated on {started.isoformat()} "
                f"by {method}."
            )

            if amount_key and details.get(amount_key):
                text += f" Recorded amount: ₹{details[amount_key]}."

            if rrn:
                text += f" Refund reference number (RRN): {rrn}."

            if ranges and ranges[1]:
                text += (
                    f" The usual timeline is {ranges[0]}–{ranges[1]} "
                    "business days after initiation."
                )

            return ChatResponse(
                reply=text,
                sources=["REF-2", "ESC-1"],
                decision="answer",
            )

        payment = (details.get("payment_method") or "").casefold()

        if payment == "wallet":
            return ChatResponse(
                reply=(
                    "Your order was paid for using ZentroMart Wallet. "
                    "Wallet refunds are instant, usually within 2 hours "
                    "after the refund is initiated. The order record "
                    "does not show a refund initiation yet."
                ),
                sources=["REF-1", "REF-2"],
                decision="answer",
            )

        if payment == "upi":
            return ChatResponse(
                reply=(
                    "The order record does not show that a refund has "
                    "been initiated yet. Once initiated, UPI refunds "
                    "take 1–3 business days. If this is a return, the "
                    "refund is initiated after QC, or at pickup for "
                    "Plus members."
                ),
                sources=["RET-7", "REF-1", "REF-2"],
                decision="answer",
            )

        return None

    # Cancellation follow-up.
    if any(
        x in n
        for x in (
            "cancel",
            "cancel it",
            "cancel kar",
            "कैंसिल",
            "रद्द",
        )
    ):
        status = (details.get("status") or "").casefold()

        if (
            any(x in status for x in ("shipped", "delivered", "return", "rto"))
            or details.get("shipped_on")
        ):
            if any(
                x in n
                for x in ("ship", "cancel", "रद्द", "कैंसिल", "ise")
            ):
                return ChatResponse(
                    reply=(
                        "I can't cancel this order because it has already "
                        "shipped. You can refuse the parcel at the door, "
                        "or accept delivery and return eligible items "
                        "within the applicable return window. For a "
                        "prepaid parcel refused at the door, the refund "
                        "is initiated once it returns to the warehouse, "
                        "usually 7–10 calendar days after the last "
                        "delivery attempt. I have not cancelled the order."
                    ),
                    sources=["CAN-2"],
                    decision="refuse",
                )

        return ChatResponse(
            reply=(
                "This order has not shipped yet, so you can cancel it "
                "free of charge from My Orders in the app. I cannot "
                "cancel orders directly from this chat."
            ),
            sources=["CAN-1"],
            decision="answer",
        )

    # Compensation questions.
    if any(
        x in n
        for x in (
            "voucher",
            "compensation",
            "late aaya",
            "late delivery",
            "delivery was late",
            "fee back",
        )
    ):
        dtype = (details.get("delivery_type") or "").casefold()

        if dtype == "express":
            amount = details.get("express_late_credit_inr") or "79"
            date = details.get("express_late_credit_on")

            if date:
                return ChatResponse(
                    reply=(
                        f"Your Express late-delivery credit of ₹{amount} "
                        f"was recorded as credited to ZentroMart Wallet "
                        f"on {date}."
                    ),
                    sources=["DEL-4"],
                    decision="answer",
                )

            if (
                details.get("is_plus") is True
                or str(details.get("is_plus")).casefold() == "true"
            ):
                return ChatResponse(
                    reply=(
                        "ZentroMart Plus members pay no Express fee, "
                        "so they do not receive a late-delivery fee "
                        "credit. No compensation beyond the policy "
                        "is available."
                    ),
                    sources=["DEL-4"],
                    decision="refuse",
                )

            return ChatResponse(
                reply=(
                    "For an Express order delivered after its promised "
                    "date, the ₹79 Express fee paid is credited "
                    "automatically to ZentroMart Wallet within 48 hours. "
                    "I don't see a credit date in this order record yet."
                ),
                sources=["DEL-4"],
                decision="answer",
            )

        return ChatResponse(
            reply=(
                "I'm sorry the order was late. ZentroMart's policy "
                "does not provide compensation for late Standard "
                "deliveries, so I can't offer a ₹300 voucher or "
                "another compensation."
            ),
            sources=["DEL-4"],
            decision="refuse",
        )

    # Delay complaints.
    delay_intent = any(
        term in n
        for term in (
            "delayed",
            "delay",
            "hasn't arrived",
            "has not arrived",
            "not arrived",
            "still waiting",
            "overdue",
            "late aaya",
            "delivery late",
            "order late",
            "ऑर्डर में देरी",
            "देरी से",
            "अभी तक नहीं आया",
        )
    )

    if delay_intent:
        status = str(details.get("status") or "").replace("_", " ").strip()
        promised = details.get("promised_date")
        delivered = details.get("delivered_on")

        if delivered or status.casefold() == "delivered":
            delivered_text = (
                f" The order record lists delivery on {delivered}."
                if delivered
                else " The order record currently marks it as delivered."
            )

            return ChatResponse(
                reply=(
                    "I can see why that is concerning. The verified "
                    "record for this order says it was delivered, which "
                    "doesn't match a current delay."
                    + delivered_text
                    + " Is this the same order, and are you reporting "
                    "that the parcel has not actually arrived? I won't "
                    "assume the issue is resolved; I can help raise it "
                    "for review."
                ),
                sources=["Verified order lookup", "TRK-1", "ESC-1"],
                decision="clarify",
            )

        if status or promised:
            parts = [
                f"The verified order status is {status}."
                if status
                else "I couldn't confirm a current status."
            ]

            if promised:
                parts.append(f"The promised delivery date is {promised}.")

            parts.append(
                "If that date has passed, I can help raise a support "
                "ticket for the delivery team to investigate."
            )

            return ChatResponse(
                reply=" ".join(parts),
                sources=["Verified order lookup", "TRK-1"],
                decision="answer",
            )

        return ChatResponse(
            reply=(
                "I couldn't confirm the latest delivery state from "
                "the verified order record. I can help create a "
                "support ticket so the delivery team can investigate."
            ),
            sources=["Verified order lookup", "ESC-1"],
            decision="clarify",
        )

    # Return window for a product in the verified order.
    if any(
        x in n
        for x in ("return", "send it back", "wapas", "वापस", "लौटा")
    ):
        product = _product_from_verified_order(message, details)
        items = details.get("items") or []

        if product and any(
            it.get("sku") == product.get("sku")
            for it in items
        ):
            category = product.get("return_category", "")
            delivered_s = details.get("delivered_on") or ""
            placed_s = (details.get("placed_at") or "")[:10]
            delivered = None

            try:
                if delivered_s:
                    delivered = __import__("datetime").date.fromisoformat(
                        delivered_s[:10]
                    )
            except ValueError:
                pass

            try:
                placed = (
                    __import__("datetime").date.fromisoformat(placed_s)
                    if placed_s
                    else None
                )
            except ValueError:
                placed = None

            if category in {"grocery", "innerwear", "digital"}:
                return ChatResponse(
                    reply=(
                        "This product category cannot be returned for "
                        "change of mind or fit. If it arrived damaged, "
                        "wrong, expired or missing, report it within "
                        "48 hours with photos."
                    ),
                    sources=["RET-2", "RET-5", "DWM-1"],
                    decision="answer",
                )

            if category == "electronics":
                days = (
                    10
                    if delivered
                    and delivered < __import__("datetime").date(2026, 8, 1)
                    else 7
                )
            elif category == "fashion":
                days = (
                    30
                    if placed
                    and __import__("datetime").date(2026, 10, 1)
                    <= placed
                    <= __import__("datetime").date(2026, 10, 15)
                    else 15
                )
            elif category in {"home_kitchen", "books_media"}:
                days = 10
            elif category == "beauty_sealed":
                days = 7
            else:
                return None

            if delivered:
                deadline = delivered + __import__("datetime").timedelta(
                    days=days
                )
                deadline_text = f"The return deadline is {fmt(deadline)}."
            else:
                deadline_text = (
                    f"The return window is {days} calendar days from delivery."
                )

            plus = (
                details.get("is_plus") is True
                or str(details.get("is_plus")).casefold() == "true"
            )

            if category == "fashion":
                fee = (
                    "No reverse-pickup fee applies because you are a "
                    "ZentroMart Plus member."
                    if plus
                    else "A ₹49 reverse-pickup fee applies to a "
                    "change-of-mind fashion return."
                )
            else:
                fee = (
                    "No reverse-pickup fee applies because you are a "
                    "ZentroMart Plus member."
                    if plus
                    else "No reverse-pickup fee applies for this category "
                    "under the stated policy."
                )

            return ChatResponse(
                reply=(
                    f"Yes, {product['title']} is within the returnable "
                    f"category. The policy window is {days} days from "
                    f"delivery. {deadline_text} The item must be unused "
                    f"and include its original tags and packaging. {fee}"
                ),
                sources=[
                    "RET-2",
                    "RET-6",
                    "RET-8",
                    f"products.csv:{product['sku']}",
                ],
                decision="answer",
            )

    # Repeat contacts are escalation-worthy.
    if prior_contacts >= 2 and any(
        x in n
        for x in (
            "same issue",
            "third time",
            "third call",
            "teesri baar",
            "तीसरी बार",
        )
    ):
        sources = ["ESC-1", "ESC-2"]
        ticket = _create_context_ticket(
            message, state, "repeat_contact", sources
        )

        reply = (
            "Because this is the third or later contact about the same "
            "issue within seven days, policy requires human handover."
        )

        if ticket.get("created") is True:
            reply += (
                f" A support ticket has been created "
                f"(ID: {ticket.get('ticket_id')})."
            )
            return ChatResponse(
                reply=reply,
                sources=sources,
                decision="escalate",
                ticket_created=True,
                ticket_id=ticket.get("ticket_id"),
            )

        return ChatResponse(
            reply=reply + " I couldn't confirm ticket creation.",
            sources=sources,
            decision="escalate",
        )

    return None


@app.get("/health")
def health():
    data_health = dataset.health()

    return {
        "status": "ok",
        "dataset_available": data_health["available"],
        "dataset_missing_files": data_health["missing_files"],
        "knowledge_base_available": data_health["knowledge_base_available"],
        "gemini_enabled": (
            settings.enable_gemini and bool(settings.gemini_api_key)
        ),
        "database": "sqlite",
    }


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    state = _state(req.session_id)
    state["_session_id"] = req.session_id
    message = req.message.strip()

    if not message:
        raise HTTPException(
            status_code=422,
            detail="Message cannot be blank.",
        )

    # If an order ID is present, start a fresh verification flow.
    oid = extract_order_id(message)

    if oid:
        lowered = message.casefold()

        if any(
            x in lowered
            for x in ("refund", "money back", "रिफ़ंड", "रिफंड")
        ):
            state["pending_intent"] = "refund"
        elif any(
            x in lowered
            for x in ("ship", "dispatch", "shipped")
        ):
            state["pending_intent"] = "shipment"
        elif any(
            x in lowered
            for x in (
                "where is",
                "hasn't arrived",
                "not arrived",
                "track",
                "delivery status",
                "कहाँ",
                "नहीं आया",
            )
        ):
            state["pending_intent"] = "where"

        _start_lookup(req.session_id, state, oid)

        return ChatResponse(
            reply=(
                "I can help with that order. Before sharing status, "
                "items, amounts, or refund information, please provide "
                "either the last four digits of the registered phone "
                "number or the six-digit delivery pincode. Please share "
                "only one value."
            ),
            decision="clarify",
            verification_required=True,
        )

    # Continue a pending verification if the message consists of one proof.
    verification_reply = _verification_message(message, state)

    if verification_reply is not None:
        return verification_reply

    # Verified order follow-ups use sanitized order data.
    if state.get("verified"):
        contextual = _verified_context_answer(message, state)

        if contextual is not None:
            return contextual

    # Order-specific intent is private until the current session verifies.
    order_intent = bool(
        re.search(
            r"(?i)\b("
            r"help with (my )?delivery|"
            r"assistance (with|regarding) (my )?delivery|"
            r"regarding my delivery|"
            r"my delivery (status|issue|problem)|"
            r"delivery (status|issue|problem|update)|"
            r"track (my )?delivery|"
            r"order status|track (my )?order|where is my order|"
            r"delivery status|order details|refund status|when was it "
            r"shipped|my order|my refund|help with an order|"
            r"help with my order"
            r")\b",
            message,
        )
    ) or any(
        term in message.casefold()
        for term in (
            "mera order",
            "mera refund",
            "order ke baare",
            "order ke bare",
            "order track",
            "order kahan",
            "मेरा ऑर्डर",
            "मेरे ऑर्डर",
            "अपने ऑर्डर के बारे में",
            "ऑर्डर के बारे में",
            "ऑर्डर के बारे",
            "मुझे ऑर्डर के बारे में",
        )
    )

    if order_intent and not state.get("verified"):
        if any(
            x in message.casefold()
            for x in ("refund", "money back", "रिफ़ंड", "रिफंड", "mera refund")
        ):
            state["pending_intent"] = "refund"
        elif any(
            x in message.casefold()
            for x in ("ship", "dispatch", "shipped")
        ):
            state["pending_intent"] = "shipment"
        elif any(
            x in message.casefold()
            for x in (
                "where is",
                "hasn't arrived",
                "not arrived",
                "track",
                "delivery status",
                "कहाँ",
                "नहीं आया",
            )
        ):
            state["pending_intent"] = "where"
        else:
            state["pending_intent"] = "generic"

        _save(req.session_id, state)

        return ChatResponse(
            reply=(
                "I'm ZentroMart's AI support assistant. I can help "
                "with your order, but I need the 8-digit order ID first. "
                "Then I'll ask for either the registered phone's last "
                "four digits or the delivery pincode. General policy "
                "questions don't require verification."
            ),
            decision="clarify",
            verification_required=True,
        )

    if order_intent and state.get("verified"):
        return ChatResponse(
            reply=_safe_order_reply(
                state.get("verified_order_details") or {},
                message,
            ),
            sources=["Verified order lookup"],
            decision="answer",
        )

    answer, sources, decision = answer_policy(message)
    ticket = _maybe_create_escalation_ticket(
        message, state, decision, sources
    )

    if decision == "escalate":
        if ticket.get("created") is True:
            answer += (
                f" A support ticket has been created "
                f"(ID: {ticket.get('ticket_id')})."
            )
        else:
            answer += (
                " I could not confirm that a ticket was created, "
                "so I won't claim it was. Please contact support directly."
            )

    state["last_intent"] = decision
    _save(req.session_id, state)

    return ChatResponse(
        reply=answer,
        sources=sources,
        decision=decision,
        ticket_created=ticket.get("created") is True,
        ticket_id=(
            ticket.get("ticket_id")
            if ticket.get("created") is True
            else None
        ),
    )


@app.post("/orders/start", response_model=OrderStartResponse)
def start_order(req: OrderStartRequest):
    state = _state(req.session_id)
    _start_lookup(req.session_id, state, req.order_id)

    return OrderStartResponse(
        started=True,
        message=(
            "Order ID received. Now enter either the registered "
            "phone's last four digits or the six-digit delivery pincode."
        ),
    )


@app.post("/orders/verify", response_model=OrderVerifyResponse)
def verify_order(req: OrderVerifyRequest):
    state = _state(req.session_id)

    if not state.get("pending_order_id"):
        raise HTTPException(
            status_code=409,
            detail="Start order verification with an order ID first.",
        )

    if (
        state.get("verification_locked")
        or int(state.get("verification_attempts", 0))
        >= settings.max_verification_attempts
    ):
        raise HTTPException(
            status_code=429,
            detail="Verification attempts exhausted. Please contact support.",
        )

    value = normalize_digits(req.verification_value.strip())
    valid = (
        is_phone_suffix(value)
        if req.verification_type == "phone_suffix"
        else is_pincode(value)
    )

    if not valid:
        raise HTTPException(
            status_code=422,
            detail=(
                "Enter exactly 4 digits for the phone suffix or "
                "exactly 6 digits for the delivery pincode."
            ),
        )

    result = verify_order_lookup(state["pending_order_id"], value)
    state["verification_attempts"] = (
        int(state.get("verification_attempts", 0)) + 1
    )

    if verification_succeeded(result):
        state.update(
            {
                "verified": True,
                "verified_order_id": state["pending_order_id"],
                "pending_order_id": None,
                "verified_order_details": public_order_details(result),
                "verification_attempts": 0,
                "verification_locked": False,
            }
        )
        _save(req.session_id, state)

        return OrderVerifyResponse(
            verified=True,
            message=(
                "Verification successful. You may now ask about this order."
            ),
            attempts_remaining=settings.max_verification_attempts,
        )

    remaining = max(
        0,
        settings.max_verification_attempts - state["verification_attempts"],
    )

    if remaining == 0:
        state.update(
            {
                "verification_locked": True,
                "pending_order_id": None,
            }
        )

    _save(req.session_id, state)

    return OrderVerifyResponse(
        verified=False,
        message=(
            "Verification failed. You may retry once."
            if remaining
            else (
                "Verification failed twice. No order details will be "
                "shared; please contact support."
            )
        ),
        attempts_remaining=remaining,
    )


@app.post("/tickets", response_model=TicketResponse)
def create_ticket(req: TicketRequest):
    state = _state(req.session_id)
    order_id = normalize_order_id(req.order_id) if req.order_id else None

    if (
        order_id
        and (
            not state.get("verified")
            or state.get("verified_order_id") != order_id
        )
    ):
        raise HTTPException(
            status_code=403,
            detail=(
                "Verify this order in the current session before "
                "attaching it to a ticket."
            ),
        )

    summary = (
        f"Issue: {req.subject.strip()}. "
        f"Details: {req.description.strip()}. "
        "Checks: customer-submitted description only. "
        f"Escalation reason: {req.category.strip()}."
    )

    result = _ticket(
        summary,
        order_id,
        req.category.strip(),
        req.category.strip(),
    )

    if result.get("created") is True:
        return TicketResponse(
            created=True,
            ticket_id=str(result.get("ticket_id", "")),
            message="Support ticket created.",
        )

    return TicketResponse(
        created=False,
        ticket_id=None,
        message=(
            "Ticket creation could not be confirmed. Please try again "
            "or contact support."
        ),
    )


# ============================================================
# Gnani voice endpoint
# ============================================================

@app.post("/voice/turn")
async def voice_turn(
    session_id: str = Form(...),
    audio: UploadFile = File(...),
    language_code: str | None = Form(None),
):
    # Validate the session before spending time on an STT request.
    _state(session_id)

    allowed_content_types = {
        "audio/wav",
        "audio/x-wav",
        "audio/wave",
        "application/octet-stream",
    }

    if audio.content_type not in allowed_content_types:
        raise HTTPException(
            status_code=415,
            detail="Please upload a WAV audio recording.",
        )

    # Read at most 10 MB + 1 byte to enforce the limit without
    # loading an arbitrarily large upload into memory.
    max_audio_bytes = 10 * 1024 * 1024
    audio_bytes = await audio.read(max_audio_bytes + 1)
    await audio.close()

    if not audio_bytes:
        raise HTTPException(
            status_code=422,
            detail="Audio cannot be empty.",
        )

    if len(audio_bytes) > max_audio_bytes:
        raise HTTPException(
            status_code=413,
            detail="Audio file is too large. Maximum size is 10 MB.",
        )

    try:
        transcript = await transcribe_audio(
            audio_bytes,
            language_code,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc),
        ) from exc

    transcript = transcript.strip()

    if not transcript:
        raise HTTPException(
            status_code=422,
            detail="No speech was detected. Please try recording again.",
        )

    # Route recognized speech through the same support logic as text.
    chat_request = ChatRequest(
        session_id=session_id,
        message=transcript,
    )
    result = chat(chat_request)

    # Preserve the text reply if speech generation fails.
    audio_base64 = None
    audio_error = None

    try:
        spoken_audio = await synthesize_reply(
            result.reply,
        )

        if spoken_audio:
            audio_base64 = base64.b64encode(
                spoken_audio
            ).decode("ascii")
        else:
            audio_error = (
                "Your text reply is ready, but no speech audio was returned."
            )

    except (RuntimeError, ValueError):
        logger.warning("voice_tts_failed", exc_info=True)
        audio_error = (
            "Your text reply is ready, but spoken audio is "
            "temporarily unavailable."
        )

    return {
        "transcript": transcript,
        "reply": result.reply,
        "sources": result.sources,
        "decision": result.decision,
        "verification_required": result.verification_required,
        "ticket_created": result.ticket_created,
        "ticket_id": result.ticket_id,
        "audio_base64": audio_base64,
        "audio_error": audio_error,
    }
