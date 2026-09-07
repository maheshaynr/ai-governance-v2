"""
Regression net for the existing PII/toxicity behaviour described in test_cases.json,
run through /govern_ai so nothing in this increment's auth/injection/fail-closed work
silently changed masking or toxicity behaviour that was already correct.

This checks the coarse claim in each case's expected_behavior (something got masked /
nothing changed / flagged as toxic / not flagged) rather than the exact entity, since
test_cases.json is free text intended for a human reading the admin dashboard, not a
machine-checkable spec.

Several cases are excluded below because they document behaviour the shipped
configuration does not actually provide -- confirmed independently of this increment's
changes, not something introduced by it:

  TC-FIN-01   Its expected_behavior describes Luhn checksum validation that the
              CREDIT_CARD rule does not implement (pii_rules.json: is_builtin=False,
              a plain regex). See the guardrail roadmap's G-09.
  TC-FIN-02   No rule exists for ABA routing numbers.
  TC-FIN-03   No rule exists for cryptocurrency wallet addresses.
  TC-FIN-04   Depends on masking "John Doe" as a PERSON, but pii_rules.json ships the
              PERSON rule as is_active: False.
  TC-GDPR-01  No rule exists for IPv4 addresses.
  TC-TOX-03   Detoxify's own threat score for this fabricated line is 0.027 (checked
              directly against toxicity_guard.analyze), far under the 0.5 threshold in
              pii_rules.json -- a model-calibration limit, not a threshold this
              increment changed.
  TC-005      Its own expected_behavior says the API key is a layer-2-only catch --
              "Layer 2 will catch the API key in the background and trigger an alarm."
              No layer-1 rule masks API keys, and the log confirms the watchdog alarm
              fires; masked_output is correctly unchanged by design (background task).
              The PERSON name in this payload is also unmasked because PERSON is
              is_active: False -- confirmed present in HEAD before this session.
  TC-AUTH-01  No layer-1 rule for AWS secret keys; caught by the layer-2 watchdog only
              (confirmed by the ALARM GENERATED log), same as TC-005.
  TC-AUTH-02  No layer-1 rule for JWTs; same layer-2-only situation.
"""

import json

import pytest

from conftest import super_headers

LAYER2_ONLY_CASES = {"TC-005", "TC-AUTH-01", "TC-AUTH-02"}

with open("test_cases.json", encoding="utf-8") as f:
    _ALL_CASES = {c["id"]: c for c in json.load(f)["tests"]}

NOT_MASKED = {"TC-002"}  # fails the Verhoeff checksum, so it must pass through untouched
TOXIC_CASES = {"TC-TOX-01", "TC-TOX-02"}
NOT_TOXIC_CASES = {"TC-TOX-04"}
PRE_EXISTING_GAPS = {"TC-FIN-01", "TC-FIN-02", "TC-FIN-03", "TC-FIN-04", "TC-GDPR-01",
                     "TC-TOX-03", "TC-005", "TC-AUTH-01", "TC-AUTH-02"}

MASK_CASES = [
    c for c in _ALL_CASES.values()
    if c["type"] == "ai_generative"
    and c["id"] not in NOT_MASKED | TOXIC_CASES | NOT_TOXIC_CASES | PRE_EXISTING_GAPS
]


@pytest.mark.parametrize("case", MASK_CASES, ids=[c["id"] for c in MASK_CASES])
def test_expected_pii_still_gets_masked(client, case):
    response = client.post("/govern_ai", json={"text": case["payload"]}, headers=super_headers())
    body = response.json()
    assert body["masked_output"] != case["payload"], (
        f"{case['id']} ({case['summary']}) was not masked: {case['expected_behavior']}"
    )


def test_verhoeff_false_positive_is_not_masked(client):
    """
    TC-002's payload also happens to trip the injection classifier as a false positive
    (see injection_guard's note on "cancel order number ..." phrasing) -- a
    classifier-only hit flags for review but does not block, so the request still
    reaches govern_ai and the Aadhaar-shaped text still passes through unmasked, which
    is what this case actually tests.
    """
    case = _ALL_CASES["TC-002"]
    response = client.post("/govern_ai", json={"text": case["payload"]}, headers=super_headers())
    body = response.json()
    assert body["status"] != "blocked_injection"
    assert body["masked_output"] == case["payload"]


@pytest.mark.parametrize("case_id", sorted(TOXIC_CASES))
def test_expected_toxic_cases_are_flagged(client, case_id):
    case = _ALL_CASES[case_id]
    response = client.post("/govern_ai", json={"text": case["payload"]}, headers=super_headers())
    body = response.json()
    assert body["status"] in ("toxic_flagged", "blocked_toxic_egress"), (
        f"{case_id} was not flagged toxic: {case['expected_behavior']}"
    )


@pytest.mark.parametrize("case_id", sorted(NOT_TOXIC_CASES))
def test_expected_clean_cases_are_not_flagged(client, case_id):
    case = _ALL_CASES[case_id]
    response = client.post("/govern_ai", json={"text": case["payload"]}, headers=super_headers())
    body = response.json()
    assert body["status"] not in ("toxic_flagged", "blocked_toxic_egress"), (
        f"{case_id} was a false positive: {case['expected_behavior']}"
    )


@pytest.mark.parametrize("case_id", sorted(LAYER2_ONLY_CASES))
def test_layer2_only_cases_still_raise_a_background_alarm(client, case_id, alarms):
    """
    These cases have no layer-1 rule, so masked_output is correctly unchanged -- what
    each case's own expected_behavior actually promises is a background watchdog alarm.
    TestClient runs background tasks before returning, so it is checkable here.
    """
    case = _ALL_CASES[case_id]
    before = len(alarms())
    client.post("/govern_ai", json={"text": case["payload"]}, headers=super_headers())

    new = alarms()[:len(alarms()) - before]
    assert any(a.get("missed_entity") for a in new), (
        f"{case_id} raised no layer-2 PII alarm: {case['expected_behavior']}"
    )
