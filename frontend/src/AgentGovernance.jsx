import { useState, useEffect } from 'react';
import { fetchAgents, revokeAgent, fetchAgentActivity, fetchGovernanceEvents, fetchGovernanceStats, fetchAgentEntitlements, fetchAgentIncidents } from './api';

// Matches AdminConfig.jsx's own fallback -- App.jsx always passes a real principal once
// RBAC is in effect, but this keeps the component safe to render standalone (e.g. tests).
const DEFAULT_PRINCIPAL = { name: 'anonymous', role: 'super_admin', is_admin: true };

const iamTh = { padding: '0.75rem', borderBottom: '1px solid #d0d7de', textAlign: 'left' };
const iamTd = { padding: '0.75rem' };

// Deliberately a modal, not a tab alongside Registered Agents/Activity Log/etc. -- those are
// all genuinely Guardrail-owned data; this represents a real external IAM system's data that
// we have no choice but to mock. Presenting it as a peer tab would misleadingly imply it's
// "ours" the same way the rest of this page is.
const EntitlementsModal = ({ entitlements, onRefresh, onClose }) => (
  <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: 'rgba(0,0,0,0.5)', display: 'flex', justifyContent: 'center', alignItems: 'center', zIndex: 1000 }}>
    <div className="card" style={{ width: '80%', maxWidth: '900px', height: '80vh', display: 'flex', flexDirection: 'column' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid #d0d7de', padding: '1rem' }}>
        <h3 style={{ margin: 0 }}>🔌 Entitlements (Mocked IAM)</h3>
        <div style={{ display: 'flex', gap: '0.5rem', flexShrink: 0 }}>
          <button onClick={onRefresh} className="secondary" style={{ padding: '0.2rem 0.5rem', fontSize: '0.8rem' }}>Refresh</button>
          <button onClick={onClose} className="secondary" style={{ padding: '0.5rem 1rem' }}>Close</button>
        </div>
      </div>
      <div style={{ flex: 1, overflow: 'auto', padding: '1rem' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.9rem' }}>
          <thead style={{ background: '#f6f8fa' }}>
            <tr>
              <th style={iamTh}>Principal</th>
              <th style={iamTh}>Agent ID</th>
              <th style={iamTh}>Device ID</th>
              <th style={iamTh}>Allowed App</th>
              <th style={iamTh}>Granted</th>
            </tr>
          </thead>
          <tbody>
            {entitlements.length === 0 ? (
              <tr><td colSpan="5" style={{ padding: '2rem', textAlign: 'center', color: '#57606a' }}>No entitlements granted yet.</td></tr>
            ) : entitlements.map((row, idx) => (
              <tr key={idx} style={{ borderBottom: '1px solid #d0d7de' }}>
                <td style={{ ...iamTd, fontFamily: 'monospace', fontSize: '0.75rem' }}>{row.principal_ref}</td>
                <td style={{ ...iamTd, fontFamily: 'monospace', fontSize: '0.75rem' }}>{row.agent_id}</td>
                <td style={{ ...iamTd, fontFamily: 'monospace', fontSize: '0.75rem', color: '#57606a' }}>{row.device_id || '— (any device)'}</td>
                <td style={{ ...iamTd, fontWeight: '500' }}>{row.allowed_app}</td>
                <td style={{ ...iamTd, fontSize: '0.8rem', color: '#57606a', whiteSpace: 'nowrap' }}>
                  {row.granted_at ? new Date(row.granted_at).toLocaleString() : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  </div>
);

// Agent Governance Layer -- a separate page from Admin Configuration on purpose: this governs
// which external agents (e.g. VOXA) may call this Guardrail at all, and what they did, which is
// a different concern from the content-policy tuning AdminConfig.jsx covers. See
// Implementation_Plan/Agent_Governance_Layer_Design.md for the full design.
export default function AgentGovernance({ principal = DEFAULT_PRINCIPAL }) {
  const [activeTab, setActiveTab] = useState('agents'); // 'agents', 'activity', 'events', 'incidents', 'stats'

  const [agents, setAgents] = useState([]);
  const [entitlements, setEntitlements] = useState([]);
  const [activity, setActivity] = useState([]);
  const [events, setEvents] = useState([]);
  const [incidents, setIncidents] = useState([]);
  const [stats, setStats] = useState(null);
  const [revokingAgentId, setRevokingAgentId] = useState(null);
  const [showEntitlements, setShowEntitlements] = useState(false);

  useEffect(() => {
    loadAgents();
    loadActivity();
    loadEvents();
    loadIncidents();
    loadStats();
  }, [activeTab]);

  const loadAgents = async () => {
    try {
      const data = await fetchAgents();
      if (data.agents) setAgents(data.agents);
    } catch (e) {
      console.error('Failed to load agents', e);
    }
  };

  const loadEntitlements = async () => {
    try {
      const data = await fetchAgentEntitlements();
      if (data.entitlements) setEntitlements(data.entitlements);
    } catch (e) {
      console.error('Failed to load entitlements', e);
    }
  };

  const loadIncidents = async () => {
    try {
      const data = await fetchAgentIncidents();
      if (data.incidents) setIncidents(data.incidents);
    } catch (e) {
      console.error('Failed to load incidents', e);
    }
  };

  const loadActivity = async () => {
    try {
      const data = await fetchAgentActivity();
      if (data.activity) setActivity(data.activity);
    } catch (e) {
      console.error('Failed to load activity log', e);
    }
  };

  const loadEvents = async () => {
    try {
      const data = await fetchGovernanceEvents();
      if (data.events) setEvents(data.events);
    } catch (e) {
      console.error('Failed to load governance events', e);
    }
  };

  const loadStats = async () => {
    try {
      const data = await fetchGovernanceStats();
      setStats(data);
    } catch (e) {
      console.error('Failed to load stats', e);
    }
  };

  const handleRevoke = async (agentId) => {
    setRevokingAgentId(agentId);
    try {
      await revokeAgent(agentId);
      await loadAgents();
    } catch (e) {
      console.error('Failed to revoke agent', e);
    } finally {
      setRevokingAgentId(null);
    }
  };

  const th = { padding: '0.75rem', borderBottom: '1px solid #d0d7de' };
  const td = { padding: '0.75rem' };
  const cardHeader = (title, onRefresh) => (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
      <h3 style={{ margin: 0 }}>{title}</h3>
      <button onClick={onRefresh} className="secondary" style={{ padding: '0.2rem 0.5rem', fontSize: '0.8rem', whiteSpace: 'nowrap' }}>Refresh</button>
    </div>
  );
  const statusPill = (text, good) => (
    <span style={{
      backgroundColor: good ? '#dafbe1' : '#ffebe9',
      color: good ? '#1a7f37' : '#cf222e',
      padding: '2px 8px', borderRadius: '12px', fontSize: '0.75rem', fontWeight: '600',
    }}>
      {text}
    </span>
  );

  return (
    <div>
      {showEntitlements && (
        <EntitlementsModal
          entitlements={entitlements}
          onRefresh={loadEntitlements}
          onClose={() => setShowEntitlements(false)}
        />
      )}

      <div style={{ marginBottom: '1rem', display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end' }}>
        <div>
          <h2 style={{ margin: 0 }}>🧭 Agent Governance</h2>
          <div className="nav-tabs">
            <button className={activeTab === 'agents' ? 'active' : ''} onClick={() => setActiveTab('agents')}>Registered Agents</button>
            <button className={activeTab === 'activity' ? 'active' : ''} onClick={() => setActiveTab('activity')}>Activity Log</button>
            <button className={activeTab === 'events' ? 'active' : ''} onClick={() => setActiveTab('events')}>Compliance Events</button>
            <button className={activeTab === 'incidents' ? 'active' : ''} onClick={() => setActiveTab('incidents')}>Incidents</button>
            <button className={activeTab === 'stats' ? 'active' : ''} onClick={() => setActiveTab('stats')}>Stats</button>
          </div>
        </div>
        <button
          className="secondary"
          onClick={() => { loadEntitlements(); setShowEntitlements(true); }}
          style={{ padding: '0.4rem 0.8rem', fontSize: '0.85rem', whiteSpace: 'nowrap' }}
          title="A mocked external IAM system -- not Guardrail's own data, shown separately on purpose."
        >
          🔌 Entitlements (Mocked IAM)
        </button>
      </div>

      <div>
        {activeTab === 'agents' && (
          <div className="admin-layout">
            <div className="rules-list">
              {cardHeader('Registered Agents', loadAgents)}
              <div style={{ border: '1px solid #d0d7de', borderRadius: '6px', background: '#fff', overflow: 'hidden' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.9rem' }}>
                  <thead style={{ background: '#f6f8fa' }}>
                    <tr>
                      <th style={th}>Agent Name</th>
                      <th style={th}>Agent ID</th>
                      <th style={th}>Business Unit</th>
                      <th style={th}>Owner</th>
                      <th style={th}>Location</th>
                      <th style={th}>Device</th>
                      <th style={th}>Type</th>
                      <th style={th}>Status</th>
                      <th style={th}>Registered</th>
                      <th style={{ ...th, textAlign: 'right' }}>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {agents.length === 0 ? (
                      <tr><td colSpan="10" style={{ padding: '2rem', textAlign: 'center', color: '#57606a' }}>No agents registered yet.</td></tr>
                    ) : agents.map((a) => (
                      <tr key={a.agent_id} style={{ borderBottom: '1px solid #d0d7de' }}>
                        <td style={{ ...td, fontWeight: '500' }}>{a.agent_name}</td>
                        <td style={{ ...td, fontFamily: 'monospace', fontSize: '0.8rem' }} title={a.agent_id}>{a.agent_id ? `${a.agent_id.slice(0, 8)}…` : '—'}</td>
                        <td style={td}>{a.business_unit || '—'}</td>
                        <td style={td}>{a.owner_name || '—'}</td>
                        <td style={{ ...td, fontFamily: 'monospace', fontSize: '0.8rem' }}>{a.location_of_deployment || '—'}</td>
                        <td style={{ ...td, fontFamily: 'monospace', fontSize: '0.8rem' }} title={a.device_id || ''}>{a.device_id || '—'}</td>
                        <td style={td}>{a.in_house_or_external || '—'}</td>
                        <td style={td}>{statusPill(a.status, a.status === 'active')}</td>
                        <td style={{ ...td, fontSize: '0.8rem', color: '#57606a', whiteSpace: 'nowrap' }}>
                          {a.identity_assignment_timestamp ? new Date(a.identity_assignment_timestamp).toLocaleString() : '—'}
                        </td>
                        <td style={{ ...td, textAlign: 'right', whiteSpace: 'nowrap' }}>
                          {a.status === 'active' && principal.is_admin && (
                            <button
                              className="secondary"
                              onClick={() => handleRevoke(a.agent_id)}
                              disabled={revokingAgentId === a.agent_id}
                              style={{ padding: '0.2rem 0.6rem', fontSize: '0.8rem', color: '#cf222e' }}
                            >
                              {revokingAgentId === a.agent_id ? '⏳ Revoking...' : 'Revoke'}
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}

        {activeTab === 'activity' && (
          <div className="admin-layout">
            <div className="rules-list">
              {cardHeader('Activity Log', loadActivity)}
              <div style={{ border: '1px solid #d0d7de', borderRadius: '6px', background: '#fff', overflow: 'hidden' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.9rem' }}>
                  <thead style={{ background: '#f6f8fa' }}>
                    <tr>
                      <th style={th}>Time</th>
                      <th style={th}>Agent ID</th>
                      <th style={th}>Invoking User</th>
                      <th style={th}>Action</th>
                      <th style={th}>Outcome</th>
                      <th style={th}>Reason</th>
                      <th style={th}>Device ID</th>
                      <th style={th}>Correlation ID</th>
                    </tr>
                  </thead>
                  <tbody>
                    {activity.length === 0 ? (
                      <tr><td colSpan="8" style={{ padding: '2rem', textAlign: 'center', color: '#57606a' }}>No activity logged yet.</td></tr>
                    ) : activity.map((row) => (
                      <tr key={row.id} style={{ borderBottom: '1px solid #d0d7de' }}>
                        <td style={{ ...td, fontSize: '0.8rem', color: '#57606a', whiteSpace: 'nowrap' }}>
                          {row.ts ? new Date(row.ts).toLocaleString() : '—'}
                        </td>
                        <td style={{ ...td, fontFamily: 'monospace', fontSize: '0.75rem' }}>{row.agent_id}</td>
                        <td style={{ ...td, fontFamily: 'monospace', fontSize: '0.75rem' }}>{row.invoking_user_id || '—'}</td>
                        <td style={td}>{row.action}</td>
                        <td style={td}>{statusPill(row.outcome, row.outcome === 'SERVED')}</td>
                        <td style={{ ...td, fontFamily: 'monospace', fontSize: '0.75rem', color: '#57606a' }}>{row.reason_code || '—'}</td>
                        <td style={{ ...td, fontFamily: 'monospace', fontSize: '0.75rem', color: '#57606a' }}>{row.device_id || '—'}</td>
                        <td style={{ ...td, fontFamily: 'monospace', fontSize: '0.75rem', color: '#57606a' }}>{row.correlation_id || '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}

        {activeTab === 'events' && (
          <div className="admin-layout">
            <div className="rules-list">
              {cardHeader('Compliance Events', loadEvents)}
              <div style={{ border: '1px solid #d0d7de', borderRadius: '6px', background: '#fff', overflow: 'hidden' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.9rem' }}>
                  <thead style={{ background: '#f6f8fa' }}>
                    <tr>
                      <th style={th}>Time</th>
                      <th style={th}>Event Type</th>
                      <th style={th}>Severity</th>
                      <th style={th}>Agent ID</th>
                      <th style={th}>Reason</th>
                    </tr>
                  </thead>
                  <tbody>
                    {events.length === 0 ? (
                      <tr><td colSpan="5" style={{ padding: '2rem', textAlign: 'center', color: '#57606a' }}>No compliance events yet.</td></tr>
                    ) : events.map((row) => (
                      <tr key={row.event_id} style={{ borderBottom: '1px solid #d0d7de' }}>
                        <td style={{ ...td, fontSize: '0.8rem', color: '#57606a', whiteSpace: 'nowrap' }}>
                          {row.occurred_at ? new Date(row.occurred_at).toLocaleString() : '—'}
                        </td>
                        <td style={{ ...td, fontFamily: 'monospace', fontSize: '0.8rem' }}>{row.event_type}</td>
                        <td style={td}>{statusPill(row.severity, false)}</td>
                        <td style={{ ...td, fontFamily: 'monospace', fontSize: '0.75rem' }}>{row.agent_id}</td>
                        <td style={td}>{row.reason_code || '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}

        {activeTab === 'incidents' && (
          <div className="admin-layout">
            <div className="rules-list">
              {cardHeader('Incidents', loadIncidents)}
              <div style={{ border: '1px solid #d0d7de', borderRadius: '6px', background: '#fff', overflow: 'hidden' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.9rem' }}>
                  <thead style={{ background: '#f6f8fa' }}>
                    <tr>
                      <th style={th}>Time</th>
                      <th style={th}>Incident ID</th>
                      <th style={th}>Type</th>
                      <th style={th}>Severity</th>
                      <th style={th}>Agent ID</th>
                      <th style={th}>Principal</th>
                      <th style={th}>Reason</th>
                      <th style={th}>Correlation ID</th>
                    </tr>
                  </thead>
                  <tbody>
                    {incidents.length === 0 ? (
                      <tr><td colSpan="8" style={{ padding: '2rem', textAlign: 'center', color: '#57606a' }}>No incidents raised yet.</td></tr>
                    ) : incidents.map((row) => (
                      <tr key={row.incident_id} style={{ borderBottom: '1px solid #d0d7de' }}>
                        <td style={{ ...td, fontSize: '0.8rem', color: '#57606a', whiteSpace: 'nowrap' }}>
                          {row.created_at ? new Date(row.created_at).toLocaleString() : '—'}
                        </td>
                        <td style={{ ...td, fontFamily: 'monospace', fontWeight: '600' }}>{row.incident_id}</td>
                        <td style={td}>{row.event_type}</td>
                        <td style={td}>{statusPill(row.severity, false)}</td>
                        <td style={{ ...td, fontFamily: 'monospace', fontSize: '0.75rem' }}>{row.agent_id}</td>
                        <td style={{ ...td, fontFamily: 'monospace', fontSize: '0.75rem' }}>{row.principal_ref}</td>
                        <td style={td}>{row.reason_code}</td>
                        <td style={{ ...td, fontFamily: 'monospace', fontSize: '0.75rem', color: '#57606a' }}>{row.correlation_id || '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}

        {activeTab === 'stats' && (
          <div className="admin-layout">
            <div className="rules-list">
              {cardHeader('Stats', loadStats)}
              {!stats ? (
                <p style={{ color: '#57606a' }}>Loading...</p>
              ) : (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '1rem' }}>
                  <StatCard title="Calls by outcome" data={stats.calls_by_outcome} />
                  <StatCard title="Calls by agent" data={stats.calls_by_agent} />
                  <StatCard title="Events by severity" data={stats.events_by_severity} />
                  <div style={{ border: '1px solid #d0d7de', borderRadius: '6px', background: '#fff', padding: '1rem' }}>
                    <h4 style={{ margin: '0 0 0.5rem 0', fontSize: '0.9rem' }}>Distinct counts</h4>
                    <div style={{ fontSize: '0.85rem', color: '#57606a' }}>Agents seen: <strong>{stats.distinct_agents}</strong></div>
                    <div style={{ fontSize: '0.85rem', color: '#57606a' }}>Invoking users seen: <strong>{stats.distinct_invoking_users}</strong></div>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function StatCard({ title, data }) {
  const entries = Object.entries(data || {});
  return (
    <div style={{ border: '1px solid #d0d7de', borderRadius: '6px', background: '#fff', padding: '1rem' }}>
      <h4 style={{ margin: '0 0 0.5rem 0', fontSize: '0.9rem' }}>{title}</h4>
      {entries.length === 0 ? (
        <div style={{ fontSize: '0.85rem', color: '#57606a' }}>No data yet.</div>
      ) : entries.map(([key, value]) => (
        <div key={key} style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem', color: '#57606a' }}>
          <span style={{ fontFamily: 'monospace' }}>{key}</span>
          <strong>{value}</strong>
        </div>
      ))}
    </div>
  );
}
