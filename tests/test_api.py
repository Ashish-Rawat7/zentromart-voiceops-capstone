from fastapi.testclient import TestClient
import app.main as main
from app.session_store import SessionStore
from app.tools_adapter import reset_tool_module_for_tests
from app.config import settings

def setup_client(tmp_path, monkeypatch):
    main.store = SessionStore(tmp_path / "sessions.sqlite3")
    return TestClient(main.app)

def test_chat_requires_order_id_for_specific_order_questions(tmp_path, monkeypatch):
    client = setup_client(tmp_path, monkeypatch)
    sid = "12345678-1234-1234-1234-123456789abc"
    r = client.post("/chat", json={"session_id": sid, "message": "Where is my order?"})
    assert r.status_code == 200
    assert r.json()["decision"] == "clarify"
    assert r.json()["verification_required"] is True

def test_real_dataset_order_verification_and_redaction(tmp_path, monkeypatch):
    client = setup_client(tmp_path, monkeypatch)
    sid = "12345678-1234-1234-1234-123456789abc"
    # Find a known order/customer pair from the synthetic CSVs; use tool only to test the success path.
    from app.data import dataset
    order = dataset.table("orders")[0]
    customer = next(c for c in dataset.table("customers") if c["customer_id"] == order["customer_id"])
    r = client.post("/orders/start", json={"session_id": sid, "order_id": order["order_id"]})
    assert r.status_code == 200
    v = client.post("/orders/verify", json={"session_id": sid, "verification_type": "phone_suffix",
                                             "verification_value": customer["phone"][-4:]})
    assert v.status_code == 200 and v.json()["verified"] is True
    state = main.store.get(sid)
    assert state["verified"] is True
    assert "phone" not in state["verified_order_details"]
    assert "delivery_pincode" not in state["verified_order_details"]

def test_verification_requires_start(tmp_path, monkeypatch):
    client = setup_client(tmp_path, monkeypatch)
    sid = "12345678-1234-1234-1234-123456789abc"
    r = client.post("/orders/verify", json={"session_id": sid, "verification_type": "phone_suffix",
                                             "verification_value": "1234"})
    assert r.status_code == 409

def test_two_failed_verification_attempts_lock_flow(tmp_path, monkeypatch):
    client = setup_client(tmp_path, monkeypatch)
    sid = "12345678-1234-1234-1234-123456789abc"
    from app.data import dataset
    order = dataset.table("orders")[0]
    customer = next(c for c in dataset.table("customers") if c["customer_id"] == order["customer_id"])
    wrong = "9999" if customer["phone"][-4:] != "9999" else "8888"
    client.post("/orders/start", json={"session_id": sid, "order_id": order["order_id"]})
    for _ in range(2):
        r = client.post("/orders/verify", json={"session_id": sid, "verification_type": "phone_suffix",
                                                 "verification_value": wrong})
    assert r.status_code == 200 and r.json()["verified"] is False
    assert main.store.get(sid)["verification_locked"] is True

def test_ticket_cannot_attach_unverified_order(tmp_path, monkeypatch):
    client = setup_client(tmp_path, monkeypatch)
    sid = "12345678-1234-1234-1234-123456789abc"
    r = client.post("/tickets", json={"session_id": sid, "subject": "Order issue",
        "description": "Please help me investigate the issue.", "category": "delivery", "order_id": "12345678"})
    assert r.status_code == 403
