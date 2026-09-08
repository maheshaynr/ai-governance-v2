"""
Authentication is disabled, by explicit request.

auth.py's require_role() dependency used to gate every endpoint in three bands
(super_admin / either admin role / any authenticated caller), and this file tested that
matrix. It was removed from api.py's endpoints -- every request now runs as
auth.ANONYMOUS_PRINCIPAL, an unrestricted super_admin-equivalent, and no header is
checked. What's left here documents and guards that current state:

  - no endpoint ever returns 401/403, with or without a header
  - /whoami no longer exists (it existed only to serve the frontend login gate, also
    removed)
  - /system_status reports plainly that authentication is off, so this isn't silently
    forgotten
  - configuration changes are still audited, now under the "anonymous" actor name

require_role() and the key-lookup machinery are still in auth.py, unused, so
re-enabling this is a matter of wiring Depends(require_role(...)) back onto the
endpoints -- see that module's docstring.
"""

import pytest

# A representative sample of what used to be gated -- endpoints spanning every former
# band (config mutation, governance-data reads, and traffic), so one test sweeps the
# whole surface without re-deriving the full endpoint list from api.py.
FORMERLY_GATED = [
    ("post", "/toggle_watchdog", {"enable_llm_watchdog": True}),
    ("post", "/toggle_toxicity", {"enable_toxicity_guard": True}),
    ("post", "/add_rule", {"name": "T", "entity": "T_ENTITY", "regex": "x", "score": 0.5}),
    ("post", "/delete_rule", {"name": "T"}),
    ("get", "/rules", None),
    ("get", "/alarms", None),
    ("get", "/analytics", None),
    ("get", "/subscribers", None),
    ("get", "/test_cases", None),
]


def _call(client, method, path, body, headers=None):
    if method == "get":
        return client.get(path, headers=headers)
    return client.post(path, json=body or {}, headers=headers)


@pytest.mark.parametrize("method,path,body", FORMERLY_GATED)
def test_no_key_required(client, method, path, body):
    """Every request succeeds with no X-API-Key header at all."""
    response = _call(client, method, path, body)
    assert response.status_code == 200, f"{path} answered {response.status_code} unauthenticated"


@pytest.mark.parametrize("method,path,body", FORMERLY_GATED)
def test_unknown_key_is_accepted_too(client, method, path, body):
    """
    A header that would have been an unknown key is simply ignored now -- nothing reads
    X-API-Key any more, so this is indistinguishable from sending no header.
    """
    response = _call(client, method, path, body, headers={"X-API-Key": "not-a-real-key"})
    assert response.status_code == 200


def test_whoami_no_longer_exists(client):
    """Removed along with the frontend login gate that was its only caller."""
    response = client.get("/whoami")
    assert response.status_code == 404


def test_system_status_reports_auth_is_disabled(client):
    response = client.get("/system_status")
    assert response.status_code == 200

    body = response.json()
    assert body["status"] == "ready"  # disabled auth is a notice, not a guard failure
    assert any("authentication is disabled" in p.lower() for p in body["problems"])


def test_config_change_is_still_audited(client, audit_entries, app_module):
    """A guard being switched off still leaves a record, now under the anonymous actor."""
    before_count = len(audit_entries())

    response = client.post("/toggle_watchdog", json={"enable_llm_watchdog": False})
    assert response.status_code == 200

    new = audit_entries()[before_count:]
    changes = [e for e in new if e.get("event") == app_module.AuditLogger.EVENT_CONFIG_CHANGE]
    assert changes, "toggling a guard wrote no config_change audit entry"

    entry = changes[-1]
    assert entry["actor"] == "anonymous"
    assert entry["actor_role"] == "super_admin"
    assert entry["action"] == "toggle_watchdog"
    assert entry["after"] is False

    # put it back
    client.post("/toggle_watchdog", json={"enable_llm_watchdog": True})


def test_config_changes_are_not_counted_as_traffic(client, app_module):
    """
    Audit entries share one file, so analytics must count transactions only. Otherwise
    every administrative click inflates the request figures.
    """
    before = client.get("/analytics").json()["metrics"]["total_requests"]

    for enabled in (False, True):
        client.post("/toggle_watchdog", json={"enable_llm_watchdog": enabled})

    after = client.get("/analytics").json()["metrics"]["total_requests"]
    assert after == before
