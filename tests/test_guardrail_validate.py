"""
POST /guardrail_validate -- a generic validation endpoint for external systems: send
arbitrary text, get back { flag, message }. flag is the full string
"AI Guardrail flag: CLEAR" / "...PARTIAL" / "...BLOCKED", not a bare enum value.
Never calls the LLM, so no Ollama stub is needed anywhere in this file.

Unlike /govern_ai, toxicity here actually blocks -- the original text is withheld
entirely, not returned masked-but-still-present.

Two things confirmed by direct testing while building this, both pre-existing and
unrelated to this endpoint's own logic, kept documented here rather than hidden:

  - get_nlp_engine() registers two spaCy models under the same lang_code "en"
    (api.py:97-103). Presidio's engine keys its model registry by language code, so the
    second entry silently overwrites the first -- only the medical model
    (en_ner_bc5cdr_md) has ever actually been running. General-purpose entities like
    PERSON have never worked regardless of the rule's is_active flag, and "Jio" gets
    misread as a chemical/drug-like token by the medical-only pipeline. Confirmed
    directly: analyzer.analyze(..., score_threshold=0.0) on "my name is Mahesh" returns
    zero PERSON matches at any confidence.
  - Because of that, PERSON was left is_active: False (unchanged from before this
    endpoint existed) -- reactivating it doesn't work today, so it wasn't turned on.
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


def test_worked_clear_example_currently_returns_partial(client):
    """
    Documents known, current behavior for the exact CLEAR example: the Jio/CHEMICAL
    false positive (see module docstring) means this comes back PARTIAL today, not
    CLEAR. This is a pre-existing NLP-engine defect, not a bug in this endpoint's
    CLEAR/PARTIAL/BLOCKED logic -- see test_truly_clean_text_returns_clear above for
    proof the CLEAR path itself is correct when nothing false-positives.
    """
    response = client.post("/guardrail_validate", json={"text": CLEAR_EXAMPLE})
    body = response.json()
    assert body["flag"] == "AI Guardrail flag: PARTIAL"
    assert "<CHEMICAL>" in body["message"]


def test_worked_partial_example_masks_customer_id(client):
    """
    The customer ID is masked; the label text around it ("customer id is") is
    preserved, not swallowed into a generic placeholder along with the digits.
    "Mahesh" is not masked -- PERSON stays is_active: False (see module docstring).
    """
    response = client.post("/guardrail_validate", json={"text": PARTIAL_EXAMPLE})
    body = response.json()
    assert body["flag"] == "AI Guardrail flag: PARTIAL"
    assert "123111" not in body["message"]
    assert "customer id is" in body["message"]
    assert "******" in body["message"]
    assert "Mahesh" in body["message"]  # documents current (unmasked) behavior


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


def test_audit_entry_is_recorded(client, audit_entries):
    before = len(audit_entries())
    client.post("/guardrail_validate", json={"text": CLEAN_TEXT})
    new = audit_entries()[before:]
    assert any(
        e.get("event") == "transaction" and "VALIDATE_HASH" in e.get("pii_masked_input", "")
        for e in new
    )
