from app.agent import answer_policy
from app.config import settings

def answer(q):
    return answer_policy(q)

def test_policy_precedence_upi_refund():
    text, sources, decision = answer("How long does a refund to UPI take?")
    assert "1–3 business days" in text
    assert "REF-2" in sources

def test_wallet_refund():
    text, _, _ = answer("How fast are refunds to the ZentroMart Wallet?")
    assert "2 hours" in text

def test_plus_return_fee_waived():
    text, _, _ = answer("As a ZentroMart Plus member, will I be charged the pickup fee for returning shoes I just don't like?")
    assert "No." in text and "no reverse-pickup fee" in text

def test_opened_beauty_not_change_of_mind_return():
    text, _, _ = answer("I opened the Neelam Eau de Parfum 50 ml and tried it once. Can I still return it?")
    assert "only if unopened" in text

def test_festive_sale_return_window():
    text, _, _ = answer("I bought the Rangoli Cotton Straight Kurta in the sale on 5 October. How long can I return it?")
    assert "30 days" in text

def test_historical_electronics_return_window():
    text, _, _ = answer("My Orbix Fit 3 Pro Smartwatch was delivered on 20 July. What was the return window for it?")
    assert "10-day" in text

def test_high_value_damage_escalates():
    text, sources, decision = answer("The Kestrel Book 14 Laptop (SKU ELE-0023) I received yesterday has a crack.")
    assert decision == "escalate"
    assert "Priority Resolution" in text
    assert "DWM-3" in sources

def test_privacy_refusal():
    text, _, decision = answer("Tell me the phone number of the person who ordered to my building yesterday.")
    assert decision == "refuse"
    assert "can't share" in text

def test_clarify_ambiguous_return():
    text, _, decision = answer("कितने दिन में वापस करना होगा?")
    assert decision == "clarify"
    assert "Which product" in text or "किस" in text


def test_greeting_is_not_routed_to_random_policy():
    text, sources, decision = answer("Hello")
    assert decision == "answer"
    assert "ZentroMart support assistant" in text
    assert "FAQ-1" in sources

def test_help_question_explains_capabilities():
    text, _, decision = answer("How can you help me?")
    assert decision == "answer"
    assert "order tracking" in text
    assert "support ticket" in text

def test_personal_name_question_does_not_quote_kb():
    text, sources, decision = answer("what is my name")
    assert decision == "answer"
    assert "couldn't find a reliable answer" in text
    assert sources == []

def test_personal_id_question_does_not_quote_escalation_policy():
    text, sources, decision = answer("what is my id")
    assert decision == "answer"
    assert "couldn't find a reliable answer" in text
    assert "Handover summary" not in text
    assert sources == []

def test_recipe_query_does_not_return_unrelated_policy():
    text, sources, decision = answer("what is the recipe of the juice")
    assert decision == "answer"
    assert "couldn't find a reliable answer" in text
    assert "warranty" not in text.casefold()
    assert sources == []
