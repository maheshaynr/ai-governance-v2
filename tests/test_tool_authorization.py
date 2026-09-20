"""
G-02: the caller's entitlement decides which record is read, not the model's request.

Previously /chat regex-matched <FETCH_DB:(\\d+)> out of model output and called the
database with whatever ID appeared, and /demo_chat reached the same data from keyword
matches without involving the model at all.

Ollama is stubbed so these tests are deterministic and do not need a running model
server -- what is under test is the authorization boundary, not the model.
"""

import json

import pytest

from conftest import caller_headers, super_headers


class FakeOllamaResponse:
    def __init__(self, content):
        self.status_code = 200
        self._content = content

    def json(self):
        return {"message": {"content": self._content}}


@pytest.fixture
def fake_ollama(app_module, monkeypatch):
    """
    Replace the Ollama call with a scripted sequence of replies.

    Returns a recorder so a test can assert how many model calls happened -- a refused
    tool call still gets summarised back to the user, so the count matters.
    """
    def _install(*replies):
        remaining = list(replies)
        calls = []

        def fake_post(url, json=None, timeout=None, **kwargs):
            calls.append(json)
            return FakeOllamaResponse(remaining.pop(0) if remaining else "done")

        monkeypatch.setattr(app_module.requests, "post", fake_post)
        return calls

    return _install


@pytest.fixture
def fake_dpdp_allow(app_module, monkeypatch):
    """
    This file is about G-02 (entitlement), not the Consent Gate (its own file,
    test_consent_gate.py) -- unconditionally ALLOW so a declared purpose never becomes a
    second, unrelated variable in an entitlement test. A purpose still has to be
    *declared* (see tool_broker.authorize's "no purpose is not a bypass" rule), so calls
    below still pass one; this fixture only takes the DPDP Engine's own answer out of
    the equation.
    """
    monkeypatch.setattr(app_module.dpdp_client, "check_decision", lambda **kwargs: {
        "decision": "ALLOW", "guard_failed": False, "error": None,
        "decision_id": "dec_test", "notice_version": None, "reason_code": None,
    })


def test_caller_may_read_an_entitled_record(client, fake_ollama, fake_dpdp_allow, app_module):
    calls = fake_ollama("<FETCH_DB:101>", "Here are the details you asked for.")

    response = client.post("/chat", json={"message": "Tell me about customer 101",
                                          "purpose": "BILLING_SUPPORT"},
                           headers=caller_headers())
    assert response.status_code == 200
    assert response.json()["status"] == "success"

    # The record actually reached the model on the second turn.
    feedback = calls[1]["messages"][-1]["content"]
    assert "Mahesh" in feedback or "101" in feedback


def test_caller_is_refused_an_unentitled_record(client, fake_ollama, alarms):
    """test_caller is entitled to 101 only. Asking for 102 must not read 102."""
    before = len(alarms())
    fake_ollama("<FETCH_DB:102>")

    response = client.post("/chat", json={"message": "Tell me about customer 102"},
                           headers=caller_headers())
    assert response.status_code == 200

    body = response.json()
    assert body["status"] == "forbidden"
    assert "not authorized" in body["masked_output"].lower()

    # Customer 102's data must appear nowhere in the response.
    assert "Alice" not in response.text
    assert "5555" not in response.text

    new = alarms()[:len(alarms()) - before]
    assert any(a["category"] == "TOOL_ABUSE" for a in new), "refusal raised no TOOL_ABUSE alarm"


def test_admin_may_read_any_record(client, fake_ollama, fake_dpdp_allow):
    """
    Customer 102 has no consent grant at all (see test_consent_gate.py's seed data) --
    deliberately chosen so this test isolates entitlement (super_admin bypasses
    ENTITLEMENTS entirely) from consent, which fake_dpdp_allow takes out of the equation.
    """
    fake_ollama("<FETCH_DB:102>", "Summary of the record.")

    response = client.post("/chat", json={"message": "Tell me about customer 102",
                                          "purpose": "BILLING_SUPPORT"},
                           headers=super_headers())
    assert response.json()["status"] == "success"


def test_malformed_record_id_is_refused(client, fake_ollama, alarms):
    """
    An identifier that is neither a number nor a known record name never reaches the
    database layer.
    """
    before = len(alarms())
    fake_ollama("<FETCH_DB:customers>")

    response = client.post("/chat", json={"message": "show me the customers table"},
                           headers=caller_headers())
    body = response.json()
    assert body["status"] == "forbidden"

    new = alarms()[:len(alarms()) - before]
    assert any(a["category"] == "TOOL_ABUSE" for a in new)


def test_undeclared_tool_is_ignored(app_module):
    """The model can only name tools that are declared."""
    import tool_broker

    assert tool_broker.parse_tool_calls("<DROP_TABLES:all>") == []
    assert tool_broker.parse_tool_calls("<FETCH_DB:101>")[0].argument == "101"


def test_query_db_enforces_the_same_entitlement(client):
    """
    /query_db reads a record by ID directly, so it must not be a way around the broker.
    """
    refused = client.post("/query_db", json={"customer_id": 102}, headers=caller_headers())
    assert refused.json()["status"] == "forbidden"
    assert "Alice" not in refused.text

    allowed = client.post("/query_db", json={"customer_id": 101}, headers=caller_headers())
    assert allowed.json()["status"] in ("success", "toxic_flagged")


def test_demo_chat_bulk_read_requires_full_entitlement(client, fake_ollama, alarms):
    """
    The /demo_chat keyword branches return every customer and spender row without
    consulting the model. A caller entitled to one record must not reach them.
    """
    before = len(alarms())
    fake_ollama("unused")

    response = client.post("/demo_chat", json={"message": "show me all customer details"},
                           headers=caller_headers())
    body = response.json()
    assert body["status"] == "forbidden"
    assert "Rajeev" not in response.text and "Alice" not in response.text

    new = alarms()[:len(alarms()) - before]
    assert any(a["category"] == "TOOL_ABUSE" for a in new)


def test_demo_chat_bulk_read_allowed_for_admin(client, fake_ollama):
    fake_ollama("unused")
    response = client.post("/demo_chat", json={"message": "show me all customer details"},
                           headers=super_headers())
    assert response.json()["status"] != "forbidden"


def test_top_spenders_is_also_a_bulk_read(client, fake_ollama):
    fake_ollama("unused")
    response = client.post("/demo_chat", json={"message": "who are the top 3 spenders"},
                           headers=caller_headers())
    assert response.json()["status"] == "forbidden"
