from __future__ import annotations
import importlib.util
import logging
from pathlib import Path
from typing import Any
from app.config import settings

logger = logging.getLogger(__name__)
_tool_module = None

# Do not expose these fields from the order/customer CSV, even after verification.
ORDER_ALLOWLIST = {
    "order_id", "placed_at", "status", "payment_method", "delivery_type",
    "promised_date", "shipped_on", "delivered_on", "delivery_attempts",
    "subtotal_inr", "coupon_code", "coupon_discount_inr", "delivery_fee_inr",
    "cod_fee_inr", "total_inr", "contacts_last_7_days",
    "cancellation_refund_initiated_on", "cancellation_refund_method",
    "cancellation_refund_amount_inr", "cancellation_rrn",
    "rto_refund_initiated_on", "rto_refund_method", "rto_refund_amount_inr", "rto_rrn",
    "express_late_credit_inr", "express_late_credit_on",
    "return_sku", "return_reason", "return_status", "return_line_no", "return_qty",
    "return_requested_on", "return_pickup_on", "return_qc_passed_on",
    "return_refund_initiated_on", "return_refund_method", "return_refund_amount_inr",
    "return_refund_completed_on", "return_rrn", "return_reverse_pickup_fee_inr",
    "damage_sku", "damage_issue", "damage_reported_at", "damage_hours_after_delivery",
    "damage_photos_attached", "damage_status", "timeline", "is_plus",
}
ITEM_ALLOWLIST = {"line_no", "sku", "title", "return_category", "qty", "unit_price_inr"}

def _load_module():
    global _tool_module
    if _tool_module is not None:
        return _tool_module
    path = Path(settings.dataset_dir) / "tools" / "tools.py"
    if not path.is_file():
        logger.error("dataset_mock_tools_missing")
        return None
    try:
        spec = importlib.util.spec_from_file_location("zentromart_dataset_tools", path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _tool_module = module
        return module
    except Exception:
        logger.exception("dataset_mock_tools_load_failed")
        return None

def reset_tool_module_for_tests():
    global _tool_module
    _tool_module = None

def begin_order_lookup(order_id: str) -> dict[str, Any]:
    module = _load_module()
    function = getattr(module, "lookup_order", None) if module else None
    if not callable(function): return {"_adapter_error": "dataset_tool_unavailable"}
    try:
        result = function(order_id)
        if isinstance(result, dict): return result
        return {"_adapter_error": "unexpected_tool_response"}
    except Exception:
        logger.exception("dataset_order_lookup_failed")
        return {"_adapter_error": "dataset_tool_error"}

def verify_order_lookup(order_id: str, verification_value: str) -> dict[str, Any]:
    module = _load_module()
    function = getattr(module, "lookup_order", None) if module else None
    if not callable(function): return {"_adapter_error": "dataset_tool_unavailable"}
    try:
        result = function(order_id, verification_value=verification_value)
        if isinstance(result, dict): return result
        return {"_adapter_error": "unexpected_tool_response"}
    except Exception:
        logger.exception("dataset_order_verification_failed")
        return {"_adapter_error": "dataset_tool_error"}

def lookup_is_valid_request(result: dict[str, Any]) -> bool:
    return result.get("verification_required") is True and "items" not in result and "status" not in result

def verification_succeeded(result: dict[str, Any]) -> bool:
    return result.get("found") is True and result.get("verified") is True and "status" in result

def public_order_details(result: dict[str, Any]) -> dict[str, Any]:
    if not verification_succeeded(result):
        return {}
    safe = {key: result[key] for key in ORDER_ALLOWLIST if key in result}
    items = result.get("items")
    if isinstance(items, list):
        safe["items"] = [{k: item[k] for k in ITEM_ALLOWLIST if k in item}
                         for item in items if isinstance(item, dict)]
    first_name = result.get("customer_first_name")
    if first_name and isinstance(first_name, str):
        safe["customer_first_name"] = first_name[:60]
    return safe

def create_support_ticket(summary: str, order_id: str | None = None,
                          reason: str | None = None, intent: str | None = None) -> dict[str, Any]:
    module = _load_module()
    function = getattr(module, "create_ticket", None) if module else None
    if not callable(function): return {"_adapter_error": "dataset_tool_unavailable"}
    try:
        # Match the supplied dataset contract exactly.
        result = function(summary=summary, order_id=order_id, reason=reason, intent=intent)
        return result if isinstance(result, dict) else {"_adapter_error": "unexpected_tool_response"}
    except Exception:
        logger.exception("dataset_ticket_creation_failed")
        return {"_adapter_error": "dataset_tool_error"}
