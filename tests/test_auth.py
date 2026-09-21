"""
Role-based behavior for the admin/config surface -- self-declared via X-Role (see
auth.py), not authenticated. There's no login, no key, and no 401 case any more: a
missing or unrecognized role simply defaults to the least-privileged role (caller), and
require_role() enforces what that role may do from there. What's still real and worth
testing: admin_pii can view governance data but not change guardrail config, only
super_admin can, and a caller can't reach either.
"""

import pytest

from conftest import caller_headers, pii_admin_headers, super_headers

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

# Never gated by require_role() at all -- external-system-facing (VOXA etc.), see
# auth.py. Unaffected by X-Role entirely, not just defaulted to caller.
NOT_ROLE_GATED = [
    ("post", "/guardrail_validate", {"text": "hello"}),
    ("post", "/v1/agent/register", {"agent_name": "test-open-check"}),
]


def _call(client, method, path, body, headers):
    if method == "get":
        return client.get(path, headers=headers)
    return client.post(path, json=body or {}, headers=headers)


@pytest.mark.parametrize("method,path,body", SUPER_ADMIN_ONLY + ADMIN_ROLES_SURFACE)
def test_no_role_declared_defaults_to_caller(client, method, path, body):
    """No X-Role header at all defaults to caller, which can't reach any admin surface."""
    response = _call(client, method, path, body, headers=None)
    assert response.status_code == 403, f"{path} answered {response.status_code} with no role declared"


@pytest.mark.parametrize("method,path,body", SUPER_ADMIN_ONLY + ADMIN_ROLES_SURFACE)
def test_unrecognized_role_defaults_to_caller(client, method, path, body):
    response = _call(client, method, path, body, headers={"X-Role": "not-a-real-role"})
    assert response.status_code == 403


@pytest.mark.parametrize("method,path,body", SUPER_ADMIN_ONLY)
def test_config_changes_need_super_admin(client, method, path, body):
    """
    A PII admin can read governance data but must not be able to change the guard
    configuration. The UI already drew this distinction; the server still enforces it,
    based on whichever role was declared.
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


@pytest.mark.parametrize("method,path,body", NOT_ROLE_GATED)
def test_external_facing_endpoints_are_never_role_gated(client, method, path, body):
    """
    /guardrail_validate and /v1/agent/register are for external systems (e.g. VOXA) that
    never send X-Role at all -- confirmed explicitly here rather than left implicit.
    """
    response = _call(client, method, path, body, headers=None)
    assert response.status_code != 403, f"{path} started requiring a declared role"


def test_system_status_is_open(client):
    """Health checks must work with no role declared, and must not leak configuration."""
    response = client.get("/system_status")
    assert response.status_code == 200

    body = response.json()
    assert "guards" in body and "status" in body
    assert "regex" not in response.text.lower()


def test_whoami_reports_the_declared_role(client):
    for headers, expected_role, expected_admin in [
        (super_headers(), "super_admin", True),
        (pii_admin_headers(), "admin_pii", True),
        (caller_headers(), "caller", False),
    ]:
        body = client.get("/whoami", headers=headers).json()
        assert body["role"] == expected_role
        assert body["is_admin"] is expected_admin


def test_config_change_is_audited(client, audit_entries, app_module):
    """A guard being switched off must leave a record of who (which declared role) did it."""
    before_count = len(audit_entries())

    response = client.post("/toggle_watchdog", json={"enable_llm_watchdog": False},
                           headers=super_headers())
    assert response.status_code == 200

    new = audit_entries()[before_count:]
    changes = [e for e in new if e.get("event") == app_module.AuditLogger.EVENT_CONFIG_CHANGE]
    assert changes, "toggling a guard wrote no config_change audit entry"

    entry = changes[-1]
    assert entry["actor"] == "super_admin"
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
