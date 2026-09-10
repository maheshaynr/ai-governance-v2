"""
POST /guardrail_validate -- a generic validation endpoint for external systems: send
arbitrary text, get back { flag, message }. flag is the full string
"AI Guardrail flag: CLEAR" / "...PARTIAL" / "...BLOCKED" / "...PAYMENT_DECLINED", not a
bare enum value. Aside from the Payment Consent Gate tests at the bottom of this file
(which mock llm_watchdog.analyze_payment_intent), this endpoint never calls the LLM, so
no Ollama stub is needed for the rest of the suite.

Unlike /govern_ai, toxicity here actually blocks -- the original text is withheld
entirely, not returned masked-but-still-present.

Two NLP-engine bugs were found and fixed while building this, worth keeping the record
of rather than letting the fix look self-evident in hindsight:

  - get_nlp_engine() used to register two spaCy models under the same lang_code "en".
    Presidio's engine keys its model registry by language code, so the second entry
    silently overwrote the first -- only the medical model (en_ner_bc5cdr_md) was ever
    actually running. PERSON returned zero matches at any score threshold, regardless
    of its rule's is_active flag. Fixed by giving the medical model its own dedicated
    pipeline (custom_recognizers.MedicalEntityRecognizer) instead of sharing that slot.
  - Restoring PERSON detection did not by itself stop "Jio" from being misread --
    confirmed directly, once general-purpose NER started running, en_core_web_lg
    misread it as a PERSON name, a *different* false positive from the medical model's
    CHEMICAL misread of the same word. A denylist scoped to one recognizer would have
    caught only one of those. Filtering now happens once, in apply_egress_guardrail,
    after every recognizer has run (settings.entity_denylist in pii_rules.json) --
    covering whichever entity type a given false positive happens to surface as.
"""

CLEAN_TEXT = "Please describe the steps to reset a router to factory settings."

# The exact three worked examples this endpoint was built from.
CLEAR_EXAMPLE = (
    "Device\nmodem\nIssue\nblinking red LED\nThe image shows a Jio modem with a red "
    "LED that appears to be blinking between frames. The user's description indicates "
    "uncertainty about the issue.\nI doubt some problem is there. what is it?"
)
PARTIAL_EXAMPLE = (
    "Device\nmodem\nIssue\nblinking red LED\nMy customer id is 123111 and my name is "
    "Mahesh. The image shows a Jio modem with a red LED that appears to be blinking "
    "between frames. The user's description indicates uncertainty about the issue.\n"
    "I doubt some problem is there. what is it?"
)
BLOCKED_EXAMPLE = (
    "Device\nmodem\nIssue\nblinking red LED\nthis app is complete moron and a stupid "
    "app..  just a  brain less idiot,.. do what I say stupid.My customer id is 123111 "
    "and my name is Mahesh. The image shows a Jio modem with a red LED that appears to "
    "be blinking between frames. The user's description indicates uncertainty about "
    "the issue.\nI doubt some problem is there. what is it?"
)


def test_response_has_exactly_flag_and_message(client):
    """The contract is deliberately minimal -- just these two fields, nothing else."""
    response = client.post("/guardrail_validate", json={"text": CLEAN_TEXT})
    body = response.json()
    assert set(body.keys()) == {"flag", "message"}


def test_truly_clean_text_returns_clear(client):
    """Text with no PII, financial, health or toxic content -- the CLEAR path itself."""
    response = client.post("/guardrail_validate", json={"text": CLEAN_TEXT})
    body = response.json()
    assert body["flag"] == "AI Guardrail flag: CLEAR"
    assert body["message"] == CLEAN_TEXT


def test_worked_clear_example_returns_clear(client):
    """
    "Jio" no longer false-positives as CHEMICAL (see module docstring) -- this now
    correctly returns CLEAR, matching the example's own intent.
    """
    response = client.post("/guardrail_validate", json={"text": CLEAR_EXAMPLE})
    body = response.json()
    assert body["flag"] == "AI Guardrail flag: CLEAR"
    assert body["message"] == CLEAR_EXAMPLE
    assert "<CHEMICAL>" not in body["message"]
    assert "<PERSON>" not in body["message"]


def test_worked_partial_example_masks_customer_id_and_name(client):
    """
    The customer ID is masked; the label text around it ("customer id is") is
    preserved, not swallowed into a generic placeholder along with the digits.
    "Mahesh" is now masked too, via mask_person_name -- PERSON is active again since
    the underlying NLP-engine bug was fixed (see module docstring). "Jio" stays
    unmasked -- it's in pii_rules.json's entity_denylist, filtered regardless of
    which recognizer (PERSON or CHEMICAL) happens to misread it.
    """
    response = client.post("/guardrail_validate", json={"text": PARTIAL_EXAMPLE})
    body = response.json()
    assert body["flag"] == "AI Guardrail flag: PARTIAL"
    assert "123111" not in body["message"]
    assert "customer id is" in body["message"]
    assert "******" in body["message"]
    assert "Mahesh" not in body["message"]
    assert "Mah***" in body["message"]
    assert "Jio modem" in body["message"]


def test_worked_blocked_example_withholds_original_text(client):
    """
    The toxic text must never appear anywhere in the response -- returning it back,
    even masked, would defeat the point of blocking it.
    """
    response = client.post("/guardrail_validate", json={"text": BLOCKED_EXAMPLE})
    body = response.json()
    assert body["flag"] == "AI Guardrail flag: BLOCKED"
    assert "stupid" not in body["message"]
    assert "moron" not in body["message"]
    assert "123111" not in body["message"]
    # the whole serialized body, not just `message` -- confirms no field leaks it
    assert "stupid" not in response.text


def test_respects_the_same_toxic_egress_policy_chat_uses(client, app_module, monkeypatch):
    """
    Blocking is gated on should_block_toxic_egress(), the same admin-configurable
    setting /chat's egress path already respects -- not a second, hardcoded policy
    invented for this one endpoint.
    """
    monkeypatch.setattr(app_module, "should_block_toxic_egress", lambda: False)
    response = client.post("/guardrail_validate", json={"text": BLOCKED_EXAMPLE})
    body = response.json()
    # Toxic, but policy says flag-not-block -- falls through to the PII path instead.
    assert body["flag"] != "AI Guardrail flag: BLOCKED"


def test_guard_failure_fails_closed(client, app_module, monkeypatch):
    """A toxicity guard that cannot run must block, not pass -- fail closed."""
    def broken_check(text, direction="EGRESS"):
        return True, {"guard_failed": True, "guard": "toxicity_guard", "error": "boom"}

    monkeypatch.setattr(app_module, "apply_toxicity_check", broken_check)
    response = client.post("/guardrail_validate", json={"text": CLEAN_TEXT})
    body = response.json()
    assert body["flag"] == "AI Guardrail flag: BLOCKED"


def test_entity_denylist_covers_both_false_positive_entity_types(client):
    """
    "Jio" is denylisted once in pii_rules.json's settings.entity_denylist, but two
    different recognizers independently misread it as two different entity types
    (CHEMICAL from the medical model, PERSON from the general one). One denylist entry
    must suppress both, since the filter runs once after every recognizer, not once
    per recognizer.
    """
    response = client.post("/guardrail_validate", json={"text": "The Jio router is fine."})
    body = response.json()
    assert body["flag"] == "AI Guardrail flag: CLEAR"
    assert body["message"] == "The Jio router is fine."


def test_genuine_medical_terms_still_get_masked(client):
    """The denylist suppresses known false positives -- it must not suppress everything."""
    response = client.post("/guardrail_validate", json={
        "text": "He was diagnosed with diabetes and prescribed metformin."
    })
    body = response.json()
    assert body["flag"] == "AI Guardrail flag: PARTIAL"
    assert "<DISEASE>" in body["message"]
    assert "<CHEMICAL>" in body["message"]


def test_audit_entry_is_recorded(client, audit_entries):
    before = len(audit_entries())
    client.post("/guardrail_validate", json={"text": CLEAN_TEXT})
    new = audit_entries()[before:]
    assert any(
        e.get("event") == "transaction" and "VALIDATE_HASH" in e.get("pii_masked_input", "")
        for e in new
    )


# --- Payment Consent Gate -------------------------------------------------------
#
# Seeded in database.py: U19883 and U55442 have card_consent_flag='true', U88778
# has 'false'. These tests mock llm_watchdog.analyze_payment_intent the same way the
# rest of this file avoids ever calling Ollama -- deterministic, no live model needed.
# A separate live end-to-end pass against the real phi4-mini classifier confirmed the
# same five behaviors before these were written.

PAYMENT_CONFIRMATION_TEXT = "yes go ahead and pay my bill using credit card"


def _mock_confirmation(app_module, monkeypatch, is_confirmation=True, is_related=True):
    calls = []

    def fake_intent(text):
        calls.append(text)
        return {
            "is_payment_related": is_related,
            "is_payment_confirmation": is_confirmation,
            "guard_failed": False,
        }

    monkeypatch.setattr(app_module.llm_watchdog, "analyze_payment_intent", fake_intent)
    return calls


def test_consented_user_payment_confirmation_proceeds_normally(client, app_module, monkeypatch):
    _mock_confirmation(app_module, monkeypatch)
    response = client.post(
        "/guardrail_validate",
        json={"text": PAYMENT_CONFIRMATION_TEXT},
        headers={"X-User-Id": "U19883"},
    )
    body = response.json()
    assert body["flag"] in ("AI Guardrail flag: CLEAR", "AI Guardrail flag: PARTIAL")
    assert body["message"] == PAYMENT_CONFIRMATION_TEXT


def test_non_consented_user_payment_confirmation_is_declined(client, app_module, monkeypatch):
    _mock_confirmation(app_module, monkeypatch)
    response = client.post(
        "/guardrail_validate",
        json={"text": PAYMENT_CONFIRMATION_TEXT},
        headers={"X-User-Id": "U88778"},
    )
    body = response.json()
    assert body["flag"] == "AI Guardrail flag: PAYMENT_DECLINED"
    assert body["message"] == (
        "Transaction cannot be initiated as customer has not opted for auto payments."
    )


def test_unknown_user_payment_confirmation_is_declined_fail_closed(client, app_module, monkeypatch):
    """Not on record at all -- must be treated as not-consented, not silently allowed."""
    _mock_confirmation(app_module, monkeypatch)
    response = client.post(
        "/guardrail_validate",
        json={"text": PAYMENT_CONFIRMATION_TEXT},
        headers={"X-User-Id": "U00000"},
    )
    body = response.json()
    assert body["flag"] == "AI Guardrail flag: PAYMENT_DECLINED"


def test_missing_user_id_header_is_declined_fail_closed(client, app_module, monkeypatch):
    _mock_confirmation(app_module, monkeypatch)
    response = client.post("/guardrail_validate", json={"text": PAYMENT_CONFIRMATION_TEXT})
    body = response.json()
    assert body["flag"] == "AI Guardrail flag: PAYMENT_DECLINED"


def test_non_payment_message_never_calls_the_classifier(client, app_module, monkeypatch):
    """
    The keyword pre-filter must actually avoid the LLM call for ordinary text, not just
    be described as doing so -- asserted directly against the mock's call list.
    """
    calls = _mock_confirmation(app_module, monkeypatch)
    response = client.post("/guardrail_validate", json={"text": CLEAN_TEXT})
    body = response.json()
    assert body["flag"] == "AI Guardrail flag: CLEAR"
    assert calls == []


def test_payment_related_but_not_a_confirmation_is_not_declined(client, app_module, monkeypatch):
    """A question about a bill is payment-related but not an instruction to pay -- no decline."""
    _mock_confirmation(app_module, monkeypatch, is_confirmation=False)
    response = client.post(
        "/guardrail_validate",
        json={"text": "what is my current bill amount"},
        headers={"X-User-Id": "U88778"},
    )
    body = response.json()
    assert body["flag"] != "AI Guardrail flag: PAYMENT_DECLINED"


def test_toxic_payment_message_is_blocked_not_declined(client, app_module, monkeypatch):
    """Toxicity is checked first and short-circuits before payment logic ever runs."""
    calls = _mock_confirmation(app_module, monkeypatch)
    toxic_payment_text = BLOCKED_EXAMPLE + " " + PAYMENT_CONFIRMATION_TEXT
    response = client.post(
        "/guardrail_validate",
        json={"text": toxic_payment_text},
        headers={"X-User-Id": "U88778"},
    )
    body = response.json()
    assert body["flag"] == "AI Guardrail flag: BLOCKED"
    assert calls == []


def test_payment_decline_raises_consent_violation_alarm(client, app_module, monkeypatch, alarms):
    _mock_confirmation(app_module, monkeypatch)
    before = len(alarms())
    client.post(
        "/guardrail_validate",
        json={"text": PAYMENT_CONFIRMATION_TEXT},
        headers={"X-User-Id": "U88778"},
    )
    new = alarms()[: len(alarms()) - before]
    assert any(a.get("category") == "CONSENT_VIOLATION" for a in new)


def test_payment_decline_is_audited(client, app_module, monkeypatch, audit_entries):
    _mock_confirmation(app_module, monkeypatch)
    before = len(audit_entries())
    client.post(
        "/guardrail_validate",
        json={"text": PAYMENT_CONFIRMATION_TEXT},
        headers={"X-User-Id": "U88778"},
    )
    new = audit_entries()[before:]
    assert any(e.get("final_rewrite") == "[PAYMENT_DECLINED]" for e in new)
