"""
Shared test fixtures.

The application reads its config and writes its alarms, audit log and monitor logs using
relative paths, so the whole suite runs in a temporary working directory seeded with
copies of the real config. Without this, running the tests would rewrite the project's
own pii_rules.json, alarms.json and governance_audit.json.
"""

import json
import os
import shutil
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Roles are self-declared (X-Role header, see auth.py) -- there's no key to set up, just
# an entitlements map. Set before `api` is imported, because config.py reads the
# environment once at import time. caller may read record 101 only, so the refusal path
# is exercised by asking for 102.
TEST_ENTITLEMENTS = {
    "super_admin": ["*"],
    "admin_pii": ["*"],
    "caller": ["101"],
}

SEEDED_FILES = ["pii_rules.json", "test_cases.json"]


@pytest.fixture(scope="session")
def workdir(tmp_path_factory):
    """A temp directory seeded with the project's config, made the process CWD."""
    work = tmp_path_factory.mktemp("governance")

    for name in SEEDED_FILES:
        source = PROJECT_ROOT / name
        if source.exists():
            shutil.copy(source, work / name)

    # The RAG engine globs this directory; an empty one keeps it quiet.
    (work / "governance_policies").mkdir(exist_ok=True)

    os.chdir(work)
    return work


@pytest.fixture(scope="session")
def app_module(workdir):
    """
    Import the API once for the whole session -- it loads three models, so importing per
    test would make the suite unusably slow.
    """
    os.environ["ENTITLEMENTS"] = json.dumps(TEST_ENTITLEMENTS)
    os.environ["EXPOSE_RAW_OUTPUT"] = "false"

    import api
    return api


@pytest.fixture(scope="session")
def client(app_module):
    from fastapi.testclient import TestClient

    with TestClient(app_module.app) as test_client:
        yield test_client


@pytest.fixture
def rules_path(workdir):
    return workdir / "pii_rules.json"


@pytest.fixture
def read_rules(rules_path):
    def _read():
        return json.loads(rules_path.read_text(encoding="utf-8"))
    return _read


@pytest.fixture
def alarms(workdir):
    """Alarms raised so far, newest first (diff_engine prepends)."""
    def _read():
        path = workdir / "alarms.json"
        if not path.exists():
            return []
        return json.loads(path.read_text(encoding="utf-8"))
    return _read


@pytest.fixture
def audit_entries(workdir):
    """Every JSON Lines audit record written so far."""
    def _read():
        path = workdir / "governance_audit.json"
        if not path.exists():
            return []
        entries = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                entries.append(json.loads(line))
        return entries
    return _read


def super_headers():
    return {"X-Role": "super_admin"}


def pii_admin_headers():
    return {"X-Role": "admin_pii"}


def caller_headers():
    return {"X-Role": "caller"}
