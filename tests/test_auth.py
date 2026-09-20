"""
G-03: every endpoint requires a caller, and configuration changes require super_admin.

Before this, /toggle_toxicity, /add_rule and /delete_rule were open to anyone who could
reach the API -- so the guardrails could be switched off and the alarm recording it
deleted. RBAC was later removed entirely (by explicit request) and has since been
restored -- this file is the restored band-matrix, extended to cover everything added
to api.py while auth was off (the DPDP consent ledger, the Agent Governance Layer).
"""

import pytest

from conftest import SUPER_KEY, caller_headers, pii_admin_headers, super_headers

# (method, path, json body) for each band.
SUPER_ADMIN_ONLY = [
    ("post", "/toggle_watchdog", {"enable_llm_watchdog": True}),
    ("post", "/toggle_toxicity", {"enable_toxicity_guard": True}),
    ("post", "/toggle_category", {"category": "PII", "enabled": True}),
    ("post", "/update_toxicity_settings", {"thresholds": {}, "enable_toxicity_guard": True}),
    ("post", "/add_rule", {"name": "T", "entity": "T_ENTITY", "regex": "x", "score": 0.5}),
    ("post", "/update_rule", {"original_name": "T", "name": "T", "entity": "T_ENTITY",
                              "regex": "x", "score": 0.5}),
    ("post", "/delete_rule", {"name": "T"}),
    ("post", "/add_subscriber", {"user_name": "u", "role": "r", "alert_type": "ALL"}),
    ("post", "/update_subscriber", {"original_user_name": "u", "user_name": "u",
                                    "role": "r", "alert_type": "ALL"}),
    ("post", "/delete_subscriber", {"user_name": "u"}),
]

# Either admin role may use these -- views, plus record-level triage/admin actions (like
# dismissing one alarm or withdrawing one consent) that are not guardrail-config changes.
ADMIN_ROLES_SURFACE = [
    ("get", "/rules", None),
    ("get", "/alarms", None),
    ("get", "/analytics", None),
    ("get", "/toxicity_settings", None),
    ("get", "/subscribers", None),
    ("get", "/test_cases", None),
    ("post", "/delete_alarm", {"alarm_id": "no-such-alarm"}),
    ("get", "/consents", None),
    ("post", "/withdraw_consent", {"customer_id": "999", "data_category": "CREDIT_CARD",
                                   "purpose": "BILLING_SUPPORT"}),
    ("get", "/v1/agent/agents", None),
    ("post", "/v1/agent/agents/nonexistent-agent-id/revoke", {}),
    ("get", "/v1/agent/activity", None),
    ("get", "/v1/agent/events", None),
    ("get", "/v1/agent/stats", None),
]

# /get_benchmarks is latency numbers only (no PII, no configuration) and is exposed on
# the Chat Bot tab for any caller, not just admins -- it belongs with the caller band.
CALLER_READABLE = [
    ("get", "/get_benchmarks", None),
]

# Deliberately excluded from human RBAC entirely -- external-system-facing, see auth.py.
NEVER_REQUIRES_API_KEY = [
    ("post", "/guardrail_validate", {"text": "hello"}),
    ("post", "/v1/agent/register", {"agent_name": "test-open-check"}),
]


def _call(client, method, path, body, headers):
    if method == "get":
        return client.get(path, headers=headers)
    return client.post(path, json=body or {}, headers=headers)


@pytest.mark.parametrize("method,path,body", SUPER_ADMIN_ONLY + ADMIN_ROLES_SURFACE)
def test_requires_a_key(client, method, path, body):
    """No key at all is a 401, on every guarded endpoint."""
    response = _call(client, method, path, body, headers=None)
    assert response.status_code == 401, f"{path} answered {response.status_code} unauthenticated"


@pytest.mark.parametrize("method,path,body", SUPER_ADMIN_ONLY + ADMIN_ROLES_SURFACE)
def test_rejects_unknown_key(client, method, path, body):
    response = _call(client, method, path, body, headers={"X-API-Key": "not-a-real-key"})
    assert response.status_code == 401


@pytest.mark.parametrize("method,path,body", SUPER_ADMIN_ONLY)
def test_config_changes_need_super_admin(client, method, path, body):
    """
    A PII admin can read governance data but must not be able to change the guard
    configuration. The UI already drew this distinction; now the server enforces it.
    """
    response = _call(client, method, path, body, headers=pii_admin_headers())
    assert response.status_code == 403, f"{path} let admin_pii through"


@pytest.mark.parametrize("method,path,body", SUPER_ADMIN_ONLY + ADMIN_ROLES_SURFACE)
def test_callers_cannot_reach_admin_surface(client, method, path, body):
    response = _call(client, method, path, body, headers=caller_headers())
    assert response.status_code == 403, f"{path} let a plain caller through"


@pytest.mark.parametrize("method,path,body", ADMIN_ROLES_SURFACE)
def test_admins_can_use_the_admin_surface(client, method, path, body):
    for headers in (super_headers(), pii_admin_headers()):
        response = _call(client, method, path, body, headers=headers)
        assert response.status_code == 200, f"{path} refused an admin: {response.text}"


@pytest.mark.parametrize("method,path,body", CALLER_READABLE)
def test_callers_can_read_non_sensitive_endpoints(client, method, path, body):
    for headers in (super_headers(), pii_admin_headers(), caller_headers()):
        response = _call(client, method, path, body, headers=headers)
        assert response.status_code == 200, f"{path} refused {headers}: {response.text}"


@pytest.mark.parametrize("method,path,body", NEVER_REQUIRES_API_KEY)
def test_external_facing_endpoints_never_require_an_api_key(client, method, path, body):
    """
    /guardrail_validate and /v1/agent/register are for external systems (e.g. VOXA) that
    have no internal admin key -- confirmed explicitly here rather than left implicit.
    """
    response = _call(client, method, path, body, headers=None)
    assert response.status_code not in (401, 403), f"{path} started requiring human RBAC"


def test_system_status_is_open(client):
    """Health checks must work without a key, and must not leak configuration."""
    response = client.get("/system_status")
    assert response.status_code == 200

    body = response.json()
    assert "guards" in body and "status" in body

    serialized = response.text.lower()
    assert SUPER_KEY.lower() not in serialized
    assert "regex" not in serialized


def test_whoami_reports_the_server_side_role(client):
    for headers, expected_role, expected_admin in [
        (super_headers(), "super_admin", True),
        (pii_admin_headers(), "admin_pii", True),
        (caller_headers(), "caller", False),
    ]:
        body = client.get("/whoami", headers=headers).json()
        assert body["role"] == expected_role
        assert body["is_admin"] is expected_admin


def test_config_change_is_audited(client, audit_entries, app_module):
    """A guard being switched off must leave a record of who did it."""
    before_count = len(audit_entries())

    response = client.post("/toggle_watchdog", json={"enable_llm_watchdog": False},
                           headers=super_headers())
    assert response.status_code == 200

    new = audit_entries()[before_count:]
    changes = [e for e in new if e.get("event") == app_module.AuditLogger.EVENT_CONFIG_CHANGE]
    assert changes, "toggling a guard wrote no config_change audit entry"

    entry = changes[-1]
    assert entry["actor"] == "test_super"
    assert entry["actor_role"] == "super_admin"
    assert entry["action"] == "toggle_watchdog"
    assert entry["after"] is False

    # put it back
    client.post("/toggle_watchdog", json={"enable_llm_watchdog": True}, headers=super_headers())


def test_config_changes_are_not_counted_as_traffic(client, app_module):
    """
    Audit entries share one file, so analytics must count transactions only. Otherwise
    every administrative click inflates the request figures.
    """
    before = client.get("/analytics", headers=super_headers()).json()["metrics"]["total_requests"]

    for enabled in (False, True):
        client.post("/toggle_watchdog", json={"enable_llm_watchdog": enabled},
                    headers=super_headers())

    after = client.get("/analytics", headers=super_headers()).json()["metrics"]["total_requests"]
    assert after == before
