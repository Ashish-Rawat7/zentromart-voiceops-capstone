from app.retrieval import retrieve_kb
from app.tools_adapter import lookup_is_valid_request, verification_succeeded, public_order_details

def test_retrieval_current_policy_sections():
    from app.config import settings
    docs = retrieve_kb("UPI refund business days", settings.dataset_dir)
    assert docs
    assert any(d.get("section_id") == "REF-2" for d in docs)

def test_superseded_policy_not_default_retrieval():
    from app.config import settings
    docs = retrieve_kb("electronics return window", settings.dataset_dir, top_k=10)
    assert not any(d.get("status") == "superseded" for d in docs)

def test_tool_contract_and_order_allowlist():
    assert lookup_is_valid_request({"verification_required": True})
    assert not lookup_is_valid_request({"found": True})
    raw = {"found": True, "verified": True, "status": "Shipped", "order_id": "12345678",
           "phone": "5555551234", "email": "secret@example.com", "delivery_pincode": "123456",
           "items": [{"sku": "ELE-0001", "title": "Laptop", "qty": 1, "phone": "no"}]}
    assert verification_succeeded(raw)
    safe = public_order_details(raw)
    assert "phone" not in safe and "email" not in safe and "delivery_pincode" not in safe
    assert "phone" not in safe["items"][0]


def test_verification_proofs_are_redacted_before_handover():
    from app.security import redact_secrets
    text = "Customer said last four digits are 4533 and pincode 110001."
    redacted = redact_secrets(text)
    assert "4533" not in redacted
    assert "110001" not in redacted
    assert "[REDACTED]" in redacted or "[REDACTED_NUMBER]" in redacted
