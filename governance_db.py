"""
Agent Governance Layer storage -- agent registry, activity log, and agent-scoped compliance
events. See Implementation_Plan/Agent_Governance_Layer_Design.md for the full rationale.

Deliberately a separate SQLite file (governance.db) from cohort.db: this is a distinct bounded
concern from customer/consent data, the same way the DPDP Engine keeps its own dpdp.db separate
from anything Guardrail-specific. Plain sqlite3, no ORM, matching consent.py/database.py's idiom.
"""

import sqlite3
from datetime import datetime, timezone

DB_FILE = "governance.db"


def _connect():
    return sqlite3.connect(DB_FILE)


def _now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def init_db():
    conn = _connect()
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS agents (
            agent_id TEXT PRIMARY KEY,
            agent_name TEXT,
            agent_secret_hash TEXT,
            business_unit TEXT,
            owner_name TEXT,
            location_of_deployment TEXT,
            in_house_or_external TEXT,
            identity_assignment_timestamp TEXT,
            status TEXT
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT,
            agent_id TEXT,
            invoking_user_id TEXT,
            action TEXT,
            outcome TEXT,
            latency_ms INTEGER,
            correlation_id TEXT
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS governance_events (
            event_id TEXT PRIMARY KEY,
            event_type TEXT,
            severity TEXT,
            agent_id TEXT,
            reason_code TEXT,
            correlation_id TEXT,
            occurred_at TEXT
        )
    ''')

    conn.commit()
    conn.close()


def create_agent(agent_id, agent_name, agent_secret_hash, business_unit, owner_name,
                  location_of_deployment, in_house_or_external):
    conn = _connect()
    cursor = conn.cursor()
    timestamp = _now()
    cursor.execute(
        'INSERT INTO agents (agent_id, agent_name, agent_secret_hash, business_unit, owner_name, '
        'location_of_deployment, in_house_or_external, identity_assignment_timestamp, status) '
        'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
        (agent_id, agent_name, agent_secret_hash, business_unit, owner_name,
         location_of_deployment, in_house_or_external, timestamp, "active"),
    )
    conn.commit()
    conn.close()
    return timestamp


def get_agent(agent_id):
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        'SELECT agent_id, agent_name, agent_secret_hash, business_unit, owner_name, '
        'location_of_deployment, in_house_or_external, identity_assignment_timestamp, status '
        'FROM agents WHERE agent_id = ?',
        (agent_id,),
    )
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    return {
        "agent_id": row[0],
        "agent_name": row[1],
        "agent_secret_hash": row[2],
        "business_unit": row[3],
        "owner_name": row[4],
        "location_of_deployment": row[5],
        "in_house_or_external": row[6],
        "identity_assignment_timestamp": row[7],
        "status": row[8],
    }


def revoke_agent(agent_id) -> bool:
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute('UPDATE agents SET status = ? WHERE agent_id = ?', ("revoked", agent_id))
    updated = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return updated


def list_agents():
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        'SELECT agent_id, agent_name, business_unit, owner_name, location_of_deployment, '
        'in_house_or_external, identity_assignment_timestamp, status '
        'FROM agents ORDER BY identity_assignment_timestamp DESC'
    )
    rows = cursor.fetchall()
    conn.close()
    return [
        {
            "agent_id": r[0], "agent_name": r[1], "business_unit": r[2], "owner_name": r[3],
            "location_of_deployment": r[4], "in_house_or_external": r[5],
            "identity_assignment_timestamp": r[6], "status": r[7],
        }
        for r in rows
    ]


def log_activity(agent_id, invoking_user_id, action, outcome, latency_ms=None, correlation_id=None):
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO activity_log (ts, agent_id, invoking_user_id, action, outcome, latency_ms, correlation_id) '
        'VALUES (?, ?, ?, ?, ?, ?, ?)',
        (_now(), agent_id, invoking_user_id, action, outcome, latency_ms, correlation_id),
    )
    conn.commit()
    conn.close()


def list_activity(limit=100):
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        'SELECT id, ts, agent_id, invoking_user_id, action, outcome, latency_ms, correlation_id '
        'FROM activity_log ORDER BY id DESC LIMIT ?',
        (limit,),
    )
    rows = cursor.fetchall()
    conn.close()
    return [
        {
            "id": r[0], "ts": r[1], "agent_id": r[2], "invoking_user_id": r[3],
            "action": r[4], "outcome": r[5], "latency_ms": r[6], "correlation_id": r[7],
        }
        for r in rows
    ]


def log_governance_event(event_id, event_type, severity, agent_id, reason_code, correlation_id):
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO governance_events (event_id, event_type, severity, agent_id, reason_code, correlation_id, occurred_at) '
        'VALUES (?, ?, ?, ?, ?, ?, ?)',
        (event_id, event_type, severity, agent_id, reason_code, correlation_id, _now()),
    )
    conn.commit()
    conn.close()


def list_governance_events(limit=100):
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        'SELECT event_id, event_type, severity, agent_id, reason_code, correlation_id, occurred_at '
        'FROM governance_events ORDER BY occurred_at DESC LIMIT ?',
        (limit,),
    )
    rows = cursor.fetchall()
    conn.close()
    return [
        {
            "event_id": r[0], "event_type": r[1], "severity": r[2], "agent_id": r[3],
            "reason_code": r[4], "correlation_id": r[5], "occurred_at": r[6],
        }
        for r in rows
    ]


def get_stats():
    """Pure read-side aggregation over the three tables above -- no running counters maintained,
    same approach as the DPDP Engine's own get_stats()."""
    conn = _connect()
    cursor = conn.cursor()

    cursor.execute('SELECT outcome, COUNT(*) FROM activity_log GROUP BY outcome')
    calls_by_outcome = {row[0]: row[1] for row in cursor.fetchall()}

    cursor.execute(
        'SELECT agent_id, COUNT(*) FROM activity_log GROUP BY agent_id ORDER BY COUNT(*) DESC LIMIT 10'
    )
    calls_by_agent = {row[0]: row[1] for row in cursor.fetchall()}

    cursor.execute('SELECT severity, COUNT(*) FROM governance_events GROUP BY severity')
    events_by_severity = {row[0]: row[1] for row in cursor.fetchall()}

    cursor.execute('SELECT COUNT(DISTINCT agent_id) FROM agents')
    distinct_agents = cursor.fetchone()[0]

    cursor.execute('SELECT COUNT(DISTINCT invoking_user_id) FROM activity_log')
    distinct_users = cursor.fetchone()[0]

    conn.close()
    return {
        "calls_by_outcome": calls_by_outcome,
        "calls_by_agent": calls_by_agent,
        "events_by_severity": events_by_severity,
        "distinct_agents": distinct_agents,
        "distinct_invoking_users": distinct_users,
    }
