"""
Agent Governance Layer -- agent registry, identity verification, activity log, and
agent-scoped compliance events. See Implementation_Plan/Agent_Governance_Layer_Design.md.

/v1/agent/decisions/check is a thin, identity-verified wrapper around dpdp_client.check_decision
-- these tests mock that function the same way test_consent_gate.py/test_guardrail_validate.py
already do, since the DPDP Engine itself isn't under test here.
"""

import pytest

from conftest import caller_headers, super_headers


def _register(client, agent_name="Test Agent"):
    response = client.post("/v1/agent/register", json={
        "agent_name": agent_name,
        "business_unit": "Test BU",
        "owner_name": "Test Owner",
        "location_of_deployment": "on-device:test",
        "in_house_or_external": "in_house",
    })
    body = response.json()
    return body["agent_id"], body["agent_secret"]


def _auth_headers(agent_id, secret):
    return {"X-Agent-Id": agent_id, "Authorization": f"Bearer {secret}"}


@pytest.fixture
def fake_dpdp_decision(app_module, monkeypatch):
    """Stubs dpdp_client.check_decision with a fixed, caller-controlled response and records
    every call made to it, so tests can assert both the outcome and whether it was even called."""
    calls = []
    state = {"response": {"decision": "ALLOW", "guard_failed": False, "error": None,
                           "decision_id": "dec_test", "notice_version": None, "reason_code": None}}

    def fake_check_decision(principal_ref, data_categories, purpose, operation,
                             recipient_ref=None, policy_context=None, correlation_id=None):
        calls.append({"principal_ref": principal_ref, "purpose": purpose, "operation": operation})
        return state["response"]

    monkeypatch.setattr(app_module.dpdp_client, "check_decision", fake_check_decision)

    def _set_response(response):
        state["response"] = response

    return calls, _set_response


# --- Registration ---

def test_registration_returns_distinct_ids(client):
    agent_id_1, secret_1 = _register(client, "Agent One")
    agent_id_2, secret_2 = _register(client, "Agent Two")
    assert agent_id_1 != agent_id_2
    assert secret_1 != secret_2


def test_registered_agent_appears_in_admin_list(client):
    agent_id, _ = _register(client, "Listed Agent")
    response = client.get("/v1/agent/agents", headers=super_headers())
    agents = response.json()["agents"]
    assert any(a["agent_id"] == agent_id and a["agent_name"] == "Listed Agent" for a in agents)
    # The secret hash must never be exposed through the admin listing.
    assert all("agent_secret_hash" not in a for a in agents)


def test_admin_surface_refuses_a_plain_caller(client):
    """
    The agent-admin routes (list/revoke/activity/events/stats) require an admin role --
    a plain caller key must be refused, same band as the Consents ledger and Alarms tab.
    """
    agent_id, _ = _register(client, "Caller-Refused Agent")
    assert client.get("/v1/agent/agents", headers=caller_headers()).status_code == 403
    assert client.get("/v1/agent/activity", headers=caller_headers()).status_code == 403
    assert client.get("/v1/agent/events", headers=caller_headers()).status_code == 403
    assert client.get("/v1/agent/stats", headers=caller_headers()).status_code == 403
    assert client.post(f"/v1/agent/agents/{agent_id}/revoke",
                       headers=caller_headers()).status_code == 403


# --- Identity verification ---

def test_decision_check_with_valid_identity_and_dpdp_allow(client, fake_dpdp_decision):
    calls, set_response = fake_dpdp_decision
    set_response({"decision": "ALLOW", "guard_failed": False, "error": None,
                  "decision_id": "dec_1", "notice_version": "v1", "reason_code": None})
    agent_id, secret = _register(client)

    response = client.post(
        "/v1/agent/decisions/check",
        json={"principal_ref": "U19883", "purpose": "BILLING_SUPPORT", "operation": "READ",
              "data_categories": ["PAYMENT_TOKEN"]},
        headers=_auth_headers(agent_id, secret),
    )
    assert response.status_code == 200
    assert response.json()["decision"] == "ALLOW"
    assert len(calls) == 1

    activity = client.get("/v1/agent/activity", headers=super_headers()).json()["activity"]
    assert any(a["agent_id"] == agent_id and a["outcome"] == "SERVED" for a in activity)

    events = client.get("/v1/agent/events", headers=super_headers()).json()["events"]
    assert not any(e["agent_id"] == agent_id for e in events)


def test_decision_check_with_dpdp_deny_logs_activity_and_event(client, fake_dpdp_decision):
    calls, set_response = fake_dpdp_decision
    set_response({"decision": "DENY", "guard_failed": False, "error": None,
                  "decision_id": "dec_2", "notice_version": None, "reason_code": "CONSENT_NOT_GRANTED"})
    agent_id, secret = _register(client)

    response = client.post(
        "/v1/agent/decisions/check",
        json={"principal_ref": "U88778", "purpose": "BILLING_SUPPORT", "operation": "READ",
              "data_categories": ["PAYMENT_TOKEN"]},
        headers=_auth_headers(agent_id, secret),
    )
    assert response.json()["decision"] == "DENY"
    assert len(calls) == 1

    activity = client.get("/v1/agent/activity", headers=super_headers()).json()["activity"]
    assert any(a["agent_id"] == agent_id and a["outcome"] == "BLOCKED" for a in activity)

    events = client.get("/v1/agent/events", headers=super_headers()).json()["events"]
    matching = [e for e in events if e["agent_id"] == agent_id]
    assert matching and matching[0]["event_type"] == "AGENT_UNAUTHORIZED_ACTION"
    assert matching[0]["reason_code"] == "CONSENT_NOT_GRANTED"


def test_decision_check_with_wrong_secret_never_calls_dpdp(client, fake_dpdp_decision):
    """The core 'verify before processing' guarantee -- an unverified caller must never reach
    the decision logic at all, not just get a denied-looking response."""
    calls, _ = fake_dpdp_decision
    agent_id, _real_secret = _register(client)

    response = client.post(
        "/v1/agent/decisions/check",
        json={"principal_ref": "U19883", "purpose": "BILLING_SUPPORT", "operation": "READ",
              "data_categories": ["PAYMENT_TOKEN"]},
        headers=_auth_headers(agent_id, "totally-wrong-secret"),
    )
    assert response.status_code == 401
    assert calls == []

    events = client.get("/v1/agent/events", headers=super_headers()).json()["events"]
    matching = [e for e in events if e["agent_id"] == agent_id]
    assert matching and matching[0]["event_type"] == "AGENT_IDENTITY_UNVERIFIED"


def test_decision_check_with_unknown_agent_id_is_rejected(client, fake_dpdp_decision):
    calls, _ = fake_dpdp_decision
    response = client.post(
        "/v1/agent/decisions/check",
        json={"principal_ref": "U19883", "purpose": "BILLING_SUPPORT", "operation": "READ",
              "data_categories": ["PAYMENT_TOKEN"]},
        headers=_auth_headers("no-such-agent", "whatever"),
    )
    assert response.status_code == 401
    assert calls == []


def test_decision_check_with_missing_headers_is_rejected(client, fake_dpdp_decision):
    calls, _ = fake_dpdp_decision
    response = client.post(
        "/v1/agent/decisions/check",
        json={"principal_ref": "U19883", "purpose": "BILLING_SUPPORT", "operation": "READ",
              "data_categories": ["PAYMENT_TOKEN"]},
    )
    assert response.status_code == 401
    assert calls == []


# --- Non-gating activity logging ---

def test_activity_endpoint_logs_without_calling_dpdp(client, fake_dpdp_decision):
    calls, _ = fake_dpdp_decision
    agent_id, secret = _register(client)

    response = client.post(
        "/v1/agent/activity",
        json={"invoking_user_id": "device-1", "action": "stock_price_lookup", "outcome": "SERVED"},
        headers=_auth_headers(agent_id, secret),
    )
    assert response.json()["status"] == "logged"
    assert calls == []

    activity = client.get("/v1/agent/activity", headers=super_headers()).json()["activity"]
    assert any(a["agent_id"] == agent_id and a["action"] == "stock_price_lookup" for a in activity)


# --- Revocation ---

def test_revoked_agent_fails_verification(client, fake_dpdp_decision):
    agent_id, secret = _register(client)

    revoke_response = client.post(f"/v1/agent/agents/{agent_id}/revoke", headers=super_headers())
    assert revoke_response.json()["status"] == "success"

    response = client.post(
        "/v1/agent/decisions/check",
        json={"principal_ref": "U19883", "purpose": "BILLING_SUPPORT", "operation": "READ",
              "data_categories": ["PAYMENT_TOKEN"]},
        headers=_auth_headers(agent_id, secret),
    )
    assert response.status_code == 401


def test_revoking_a_nonexistent_agent_reports_an_error(client):
    response = client.post("/v1/agent/agents/no-such-agent/revoke", headers=super_headers())
    assert response.json()["status"] == "error"


# --- Stats ---

def test_stats_reflects_recorded_activity(client, fake_dpdp_decision):
    _calls, set_response = fake_dpdp_decision
    set_response({"decision": "ALLOW", "guard_failed": False, "error": None,
                  "decision_id": "dec_stats", "notice_version": None, "reason_code": None})
    agent_id, secret = _register(client, "Stats Agent")

    client.post(
        "/v1/agent/decisions/check",
        json={"principal_ref": "U19883", "purpose": "BILLING_SUPPORT", "operation": "READ",
              "data_categories": ["PAYMENT_TOKEN"]},
        headers=_auth_headers(agent_id, secret),
    )

    stats = client.get("/v1/agent/stats", headers=super_headers()).json()
    assert stats["calls_by_outcome"].get("SERVED", 0) >= 1
    assert stats["distinct_agents"] >= 1
