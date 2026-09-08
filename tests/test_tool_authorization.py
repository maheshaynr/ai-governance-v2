"""
Tool call parsing and shape validation (G-02's structural half).

Authentication was removed from the backend by explicit request -- every endpoint now
runs as auth.ANONYMOUS_PRINCIPAL, an unrestricted super_admin-equivalent, and no header
is checked at all. That means the per-caller entitlement refusal this file used to test
no longer exists: any record is readable by anyone (or no one, since no key is required).

What still holds, because it is identity-independent: the broker only dispatches tools it
declares (parse_tool_calls ignores anything else), and a malformed record identifier --
neither a number nor a known name -- never reaches the database layer regardless of who
is asking.

Ollama is stubbed so these tests are deterministic and do not need a running model
server -- what is under test is the tool-call boundary, not the model.
"""

import pytest


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

    Returns a recorder so a test can assert how many model calls happened.
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


def test_any_record_is_readable_with_no_key_at_all(client, fake_ollama):
    """
    No X-API-Key header is sent here at all. Before auth was removed, this record was
    reachable only by an entitled or admin key; now every request is unrestricted.

    Uses a named misc_data record (swiggy), not a customer ID -- customer records are
    also subject to the Consent Gate (see test_consent_gate.py), which is an
    independent, later-added axis this test predates and isn't exercising here. Named
    records carry no card data and are unaffected by that gate.
    """
    fake_ollama("<FETCH_DB:swiggy>", "Here is your delivery status.")

    response = client.post("/chat", json={"message": "wheres my swiggy order"})
    assert response.status_code == 200
    assert response.json()["status"] == "success"


def test_malformed_record_id_is_refused(client, fake_ollama, alarms):
    """
    An identifier that is neither a number nor a known record name never reaches the
    database layer -- this is shape validation, independent of who is asking, so it holds
    with authentication removed just as it did before.
    """
    before = len(alarms())
    fake_ollama("<FETCH_DB:customers>")

    response = client.post("/chat", json={"message": "show me the customers table"})
    body = response.json()
    assert body["status"] == "forbidden"

    new = alarms()[:len(alarms()) - before]
    assert any(a["category"] == "TOOL_ABUSE" for a in new)


def test_undeclared_tool_is_ignored(app_module):
    """The model can only name tools that are declared."""
    import tool_broker

    assert tool_broker.parse_tool_calls("<DROP_TABLES:all>") == []
    assert tool_broker.parse_tool_calls("<FETCH_DB:101>")[0].argument == "101"


def test_query_db_allows_any_record_with_no_key(client):
    """
    /query_db reads a record by ID directly. Previously a caller key was restricted to
    101; now no key is required and 102 is readable too.
    """
    response = client.post("/query_db", json={"customer_id": 102})
    assert response.json()["status"] in ("success", "toxic_flagged")
    assert "Alice" in response.text  # customer 102's data is actually present


def test_demo_chat_bulk_read_no_longer_needs_entitlement(client, fake_ollama):
    """
    The /demo_chat keyword branches return every customer and spender row without
    consulting the model. This used to require unrestricted entitlement; now it requires
    nothing at all.
    """
    fake_ollama("unused")
    response = client.post("/demo_chat", json={"message": "show me all customer details"})
    assert response.json()["status"] != "forbidden"


def test_top_spenders_bulk_read_no_longer_needs_entitlement(client, fake_ollama):
    fake_ollama("unused")
    response = client.post("/demo_chat", json={"message": "who are the top 3 spenders"})
    assert response.json()["status"] != "forbidden"
