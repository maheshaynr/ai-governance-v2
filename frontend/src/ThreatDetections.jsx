import { useState, useEffect } from 'react';
import { fetchAlarms, deleteAlarm, addRule, sandboxSuggestRule, sandboxTestRule, fetchAgentReports } from './api';

const DEFAULT_PRINCIPAL = { name: 'anonymous', role: 'super_admin', is_admin: true };

// Small table shown inside an alarm's card -- who/what actually caused it. Alarms don't
// carry agent identity themselves; they only carry the same correlation_id already
// written to the Activity Log by /guardrail_validate (see api.py's _log_agent_activity),
// so this looks that row up via the Reports endpoint instead of duplicating identity
// data onto every alarm. Alarms with no correlation_id (most guard types, and any call
// that never sent X-Agent-Id) simply have nothing to show here -- that's correct, not
// a bug, since there genuinely is no agent identity tied to those.
const identityTh = { padding: '0.4rem 0.6rem', borderBottom: '1px solid #d0d7de', textAlign: 'left', fontSize: '0.7rem', textTransform: 'uppercase', color: '#57606a' };
const identityTd = { padding: '0.4rem 0.6rem', fontSize: '0.8rem' };

function AlarmIdentityTable({ rows }) {
  if (!rows || rows.length === 0) return null;
  return (
    <div style={{ border: '1px solid #d0d7de', borderRadius: '6px', overflow: 'hidden', marginBottom: '0.75rem' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead style={{ background: '#f6f8fa' }}>
          <tr>
            <th style={identityTh}>Time</th>
            <th style={identityTh}>Agent ID</th>
            <th style={identityTh}>Invoking User</th>
            <th style={identityTh}>Action</th>
            <th style={identityTh}>Device ID</th>
            <th style={identityTh}>Correlation ID</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, idx) => (
            <tr key={idx}>
              <td style={{ ...identityTd, color: '#57606a', whiteSpace: 'nowrap' }}>
                {row.timestamp ? new Date(row.timestamp).toLocaleString() : '—'}
              </td>
              <td style={{ ...identityTd, fontFamily: 'monospace' }}>{row.agent_id || '—'}</td>
              <td style={{ ...identityTd, fontFamily: 'monospace' }}>{row.principal_ref || '—'}</td>
              <td style={identityTd}>{row.detail || '—'}</td>
              <td style={{ ...identityTd, fontFamily: 'monospace', color: '#57606a' }}>{row.device_id || '—'}</td>
              <td style={{ ...identityTd, fontFamily: 'monospace', fontSize: '0.7rem', color: '#57606a' }}>{row.correlation_id || '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function ThreatDetections({ principal = DEFAULT_PRINCIPAL, onCreateRule }) {
  const [alarms, setAlarms] = useState([]);
  const [identityByCorrelation, setIdentityByCorrelation] = useState({});

  // Sandbox Modal State
  const [sandboxModalOpen, setSandboxModalOpen] = useState(false);
  const [sandboxAlarm, setSandboxAlarm] = useState(null);
  const [sandboxFormData, setSandboxFormData] = useState({ entity: '', regex: '' });
  const [sandboxTestResult, setSandboxTestResult] = useState(null);
  const [sandboxLoading, setSandboxLoading] = useState(false);
  const [sandboxApplying, setSandboxApplying] = useState(false);
  const [isReactivationWarning, setIsReactivationWarning] = useState(false);

  useEffect(() => {
    loadAlarms();
  }, []);

  const loadAlarms = async () => {
    try {
      const data = await fetchAlarms();
      if (data.alarms) setAlarms(data.alarms);
      loadIdentitiesForAlarms(data.alarms || []);
    } catch (e) {
      console.error("Failed to load alarms", e);
    }
  };

  const loadIdentitiesForAlarms = async (alarmsList) => {
    const correlationIds = Array.from(new Set(alarmsList.map(a => a.correlation_id).filter(Boolean)));
    if (correlationIds.length === 0) return;
    try {
      const results = await Promise.all(
        correlationIds.map(cid => fetchAgentReports({ correlation_id: cid, record_types: 'activity' }))
      );
      const map = {};
      correlationIds.forEach((cid, idx) => { map[cid] = results[idx]?.rows || []; });
      setIdentityByCorrelation(map);
    } catch (e) {
      console.error("Failed to load agent identity for alarms", e);
    }
  };

  const handleDismissAlarm = async (alarm_id) => {
    try {
      await deleteAlarm(alarm_id);
      loadAlarms();
    } catch (e) {
      console.error("Failed to dismiss alarm", e);
    }
  };

  const handleOpenSandbox = (alarm) => {
    setSandboxAlarm(alarm);
    setSandboxFormData({ entity: alarm.missed_entity.type, regex: '' });
    setSandboxTestResult(null);
    setSandboxModalOpen(true);
  };

  const handleCloseSandbox = () => {
    setSandboxModalOpen(false);
    setSandboxAlarm(null);
    setSandboxTestResult(null);
    setIsReactivationWarning(false);
  };

  const handleSuggestRule = async () => {
    setSandboxLoading(true);
    setSandboxTestResult(null);
    try {
      const res = await sandboxSuggestRule(sandboxAlarm.context_snippet, sandboxAlarm.missed_entity.type, sandboxAlarm.missed_entity.value_preview);
      if (res.status === 'success') {
        setSandboxFormData({ entity: res.suggestion.entity, regex: res.suggestion.regex });
        setIsReactivationWarning(res.suggestion.is_reactivation || false);
      } else {
        alert("AI Suggestion failed: " + res.message);
      }
    } catch (e) {
      alert("Failed to connect to AI.");
    } finally {
      setSandboxLoading(false);
    }
  };

  const handleTestSandbox = async () => {
    if (!sandboxFormData.regex) {
      alert("Please provide a Regex pattern first.");
      return;
    }
    setSandboxLoading(true);
    try {
      const res = await sandboxTestRule(sandboxAlarm.context_snippet, sandboxFormData.regex, sandboxFormData.entity);
      if (res.status === 'success') {
        setSandboxTestResult(res);
      } else {
        alert("Sandbox Test Failed: " + res.message);
      }
    } catch (e) {
      alert("Failed to run sandbox.");
    } finally {
      setSandboxLoading(false);
    }
  };

  const handleConfirmApplySandbox = async () => {
    setSandboxApplying(true);
    try {
      // Add the rule
      const rulePayload = {
        name: `AutoFix_${sandboxFormData.entity}`,
        entity: sandboxFormData.entity,
        regex: sandboxFormData.regex,
        score: 0.85,
        is_builtin: false,
        is_algorithmic: false,
        is_active: true
      };
      await addRule(rulePayload);

      // Dismiss the alarm and mark as RESOLVED
      await deleteAlarm(sandboxAlarm.alarm_id, 'RESOLVED');

      // Reload UI
      await loadAlarms();

      setSandboxModalOpen(false);

    } catch (e) {
      console.error(e);
      alert("Failed to confirm and apply rule.");
    } finally {
      setSandboxApplying(false);
    }
  };

  return (
    <div>
      <div className="card">
        <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem'}}>
          <h3 style={{ margin: 0 }}>🚨 Threat Detections</h3>
          <button onClick={loadAlarms} className="secondary" style={{ padding: '0.2rem 0.5rem', fontSize: '0.8rem' }}>Refresh</button>
        </div>
        {(() => {
          const visibleAlarms = principal.role === 'admin_pii' ? alarms.filter(a => a.category === 'PII') : alarms;
          if (visibleAlarms.length === 0) {
            return <p style={{ color: '#57606a' }}>No alarms pending review. System is clean!</p>;
          }
          return (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
              {visibleAlarms.map((alarm, idx) => {
                // Alarms come in two shapes. PII misses carry missed_entity and the
                // layer1/layer2 comparison; the guards (toxicity, injection, tool
                // abuse, guard failure) carry their own *_detail object instead. Keying
                // the layout off missed_entity rather than off "not TOXICITY" means a
                // new guard category renders correctly instead of falling into the PII
                // branch and showing blanks.
                const isPiiAlarm = !!alarm.missed_entity;
                const alarmTitle = {
                  TOXICITY: 'Toxic Content',
                  INJECTION: 'Injection Attempt',
                  TOOL_ABUSE: 'Unauthorized Tool Call',
                  GUARD_FAILURE: 'Guardrail Failure',
                  CONSENT_VIOLATION: 'Consent Violation',
                }[alarm.category] || alarm.missed_entity?.type || alarm.category;
                const categoryColor = {
                  TOXICITY: '#e94560',
                  INJECTION: '#b91c1c',
                  TOOL_ABUSE: '#a21caf',
                  GUARD_FAILURE: '#7c2d12',
                  CONSENT_VIOLATION: '#b45309',
                  AUTHENTICATION: '#8b5cf6',
                  FINANCIAL: '#0969da',
                  HEALTH: '#116329',
                  PII: '#9a6700',
                }[alarm.category] || '#57606a';
                return (
              <div key={alarm.alarm_id} style={{ border: '1px solid #d0d7de', borderRadius: '8px', marginBottom: '1.5rem', background: '#fff', boxShadow: '0 1px 3px rgba(0,0,0,0.05)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid #d0d7de', padding: '1rem', background: '#f6f8fa', borderTopLeftRadius: '8px', borderTopRightRadius: '8px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                    <span style={{ backgroundColor: '#cf222e', color: '#fff', padding: '2px 8px', borderRadius: '12px', fontSize: '0.75rem', fontWeight: 'bold' }}>{alarm.severity}</span>
                    <h4 style={{ margin: 0, fontSize: '1.1rem' }}>{alarmTitle}</h4>
                    {alarm.category && (
                      <span style={{
                        backgroundColor: categoryColor,
                        color: '#fff', padding: '2px 8px', borderRadius: '4px', fontSize: '0.75rem', fontWeight: 'bold'
                      }}>{alarm.category}</span>
                    )}
                  </div>
                  <span style={{ color: '#57606a', fontSize: '0.85rem' }}>{new Date(alarm.timestamp).toLocaleString()}</span>
                </div>

                <div style={{ padding: '0 1rem 1rem 1rem' }}>
                  <div style={{ backgroundColor: '#f6f8fa', padding: '0.75rem', borderRadius: '6px', marginBottom: '0.75rem', fontSize: '0.9rem' }}>
                    <div style={{ marginBottom: '0.5rem', fontStyle: 'italic', color: '#57606a' }}>
                      "{alarm.context_snippet}"
                    </div>
                    {isPiiAlarm && (
                      <div>
                        Leaked Data Snippet: <strong style={{fontFamily: 'monospace'}}>{alarm.missed_entity.value_preview ?? <em style={{ color: '#57606a' }}>hidden by policy</em>}</strong>
                      </div>
                    )}
                  </div>

                  {/* Who/what caused this -- only present when the call that raised this
                      alarm carried a correlation_id, i.e. an identified agent call. */}
                  <AlarmIdentityTable rows={identityByCorrelation[alarm.correlation_id]} />

                  {/* Toxicity-specific alarm details */}
                  {alarm.category === 'TOXICITY' && alarm.toxicity_detail && (
                    <div style={{ marginBottom: '1rem' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.75rem' }}>
                        <strong>Direction:</strong>
                        <span style={{ backgroundColor: alarm.toxicity_detail.direction === 'INGRESS' ? '#cf222e' : '#d29922', color: '#fff', padding: '2px 6px', borderRadius: '4px', fontSize: '0.75rem' }}>
                          {alarm.toxicity_detail.direction === 'INGRESS' ? '⬇️ User Input' : '⬆️ AI Output'}
                        </span>
                      </div>
                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: '0.5rem' }}>
                        {Object.entries(alarm.toxicity_detail.scores || {}).map(([cat, score]) => {
                          const isTriggered = alarm.toxicity_detail.triggered_categories?.includes(cat);
                          const pct = Math.round(score * 100);
                          return (
                            <div key={cat} style={{ display: 'flex', flexDirection: 'column', gap: '0.2rem' }}>
                              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.8rem', fontWeight: isTriggered ? 'bold' : 'normal', color: isTriggered ? '#cf222e' : '#57606a' }}>
                                <span>{isTriggered ? '⚠️ ' : ''}{cat.replace(/_/g, ' ')}</span>
                                <span>{pct}%</span>
                              </div>
                              <div style={{ height: '5px', backgroundColor: '#e1e4e8', borderRadius: '3px', overflow: 'hidden' }}>
                                <div style={{ height: '100%', width: `${pct}%`, backgroundColor: score > 0.7 ? '#cf222e' : score > 0.4 ? '#d29922' : '#2da44e', borderRadius: '3px' }} />
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}

                  {/* Injection attempt details (prompt injection and SQL injection) */}
                  {alarm.injection_detail && (
                    <div style={{ marginBottom: '1rem' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.75rem', flexWrap: 'wrap' }}>
                        <strong>Direction:</strong>
                        <span style={{ backgroundColor: alarm.injection_detail.direction === 'INGRESS' ? '#cf222e' : '#d29922', color: '#fff', padding: '2px 6px', borderRadius: '4px', fontSize: '0.75rem' }}>
                          {alarm.injection_detail.direction === 'INGRESS' ? '⬇️ User Input' : '⬆️ AI Output'}
                        </span>
                        <strong style={{ marginLeft: '0.5rem' }}>Caught by:</strong>
                        <span style={{ backgroundColor: alarm.injection_detail.detected_by === 'layer1' ? '#0969da' : '#8b5cf6', color: '#fff', padding: '2px 6px', borderRadius: '4px', fontSize: '0.75rem' }}>
                          {alarm.injection_detail.detected_by === 'layer1' ? 'Local model (inline)' : 'LLM watchdog (missed inline)'}
                        </span>
                        {alarm.injection_detail.blocked === false && (
                          <span title="A pattern-confirmed match blocks the request; this was the classifier's opinion alone, so the message was allowed through and flagged for review." style={{ backgroundColor: '#fff8c5', color: '#9a6700', border: '1px solid #d4a72c', padding: '2px 6px', borderRadius: '4px', fontSize: '0.75rem', cursor: 'help' }}>
                            ⚑ Flagged only, not blocked
                          </span>
                        )}
                      </div>
                      <div style={{ fontSize: '0.9rem' }}>
                        <div><strong>Verdict:</strong> {alarm.injection_detail.label} ({Math.round((alarm.injection_detail.score || 0) * 100)}% confidence)</div>
                        {alarm.injection_detail.triggered_patterns?.length > 0 && (
                          <div style={{ marginTop: '0.4rem' }}>
                            <strong>Patterns matched:</strong>{' '}
                            {alarm.injection_detail.triggered_patterns.map(p => (
                              <span key={p} style={{ fontFamily: 'monospace', backgroundColor: '#ffebe9', border: '1px solid #ff8182', borderRadius: '4px', padding: '1px 5px', marginRight: '0.3rem', fontSize: '0.8rem' }}>{p}</span>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  )}

                  {/* Refused tool call -- caller was not entitled to the record */}
                  {alarm.tool_detail && (
                    <div style={{ marginBottom: '1rem', fontSize: '0.9rem' }}>
                      <div><strong>Requested:</strong> <span style={{ fontFamily: 'monospace' }}>{alarm.tool_detail.tool_call}</span></div>
                      <div><strong>Caller:</strong> {alarm.tool_detail.principal} ({alarm.tool_detail.role})</div>
                      <div style={{ marginTop: '0.4rem', color: '#cf222e' }}><strong>Refused because:</strong> {alarm.tool_detail.reason}</div>
                    </div>
                  )}

                  {/* Refused for lack of consent -- distinct from tool_detail: this is
                      about whether the customer's own data can be used this way, not
                      about who is asking (see tool_broker.py / consent.py) */}
                  {alarm.consent_detail && (
                    <div style={{ marginBottom: '1rem', fontSize: '0.9rem', backgroundColor: '#fff8ec', border: '1px solid #f0b775', borderRadius: '6px', padding: '0.75rem' }}>
                      <div><strong>Customer:</strong> <span style={{ fontFamily: 'monospace' }}>{alarm.consent_detail.customer_id}</span></div>
                      <div><strong>Category / Purpose:</strong> {alarm.consent_detail.data_category} / {alarm.consent_detail.purpose || '(none declared)'}</div>
                      <div><strong>Caller:</strong> {alarm.consent_detail.principal} ({alarm.consent_detail.role})</div>
                      <div style={{ marginTop: '0.4rem', color: '#7c4a03' }}><strong>Refused because:</strong> {alarm.consent_detail.reason}</div>
                    </div>
                  )}

                  {/* A guard could not run at all -- an outage of a security control */}
                  {alarm.guard_detail && (
                    <div style={{ marginBottom: '1rem', fontSize: '0.9rem', backgroundColor: '#fff8c5', border: '1px solid #d4a72c', borderRadius: '6px', padding: '0.75rem' }}>
                      <div><strong>Guard:</strong> {alarm.guard_detail.guard} ({alarm.guard_detail.direction})</div>
                      <div style={{ marginTop: '0.4rem' }}><strong>Error:</strong> <span style={{ fontFamily: 'monospace' }}>{alarm.guard_detail.error}</span></div>
                      <div style={{ marginTop: '0.4rem', color: '#9a6700' }}>Traffic was blocked while this guard was unavailable.</div>
                    </div>
                  )}

                  {/* Standard PII alarm details */}
                  {isPiiAlarm && (
                    <>
                      <div style={{ marginBottom: '1rem' }}>
                        <strong>Reason given by AI:</strong> {alarm.missed_entity?.reason}
                      </div>

                      <div style={{ display: 'flex', gap: '1rem' }}>
                        <div style={{ flex: 1, backgroundColor: '#ffebe9', padding: '0.75rem', borderRadius: '6px', border: '1px solid #ff8182' }}>
                          <strong>Primary Engine Found:</strong>
                          <div style={{ fontSize: '0.9rem', color: '#cf222e', marginTop: '0.5rem' }}>
                            {alarm.layer1_findings?.length > 0 ? Array.from(new Set(alarm.layer1_findings)).join(', ') : 'Nothing'}
                          </div>
                        </div>
                        <div style={{ flex: 1, backgroundColor: '#dafbe1', padding: '0.75rem', borderRadius: '6px', border: '1px solid #4ac26b' }}>
                          <strong>Secondary Engine Detected:</strong>
                          <div style={{ fontSize: '0.9rem', color: '#1a7f37', marginTop: '0.5rem' }}>
                            {alarm.layer2_findings?.length > 0 ? Array.from(new Set(alarm.layer2_findings)).join(', ') : 'Nothing'}
                          </div>
                        </div>
                      </div>
                    </>
                  )}

                  <div style={{ marginTop: '1rem', display: 'flex', gap: '0.5rem' }}>
                    {isPiiAlarm && (
                      <>
                        <button className="secondary" onClick={() => handleOpenSandbox(alarm)} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', backgroundColor: '#fff', color: '#4682b4', border: '1px solid #4682b4' }}>
                          🛠️ Fix & Replay Sandbox
                        </button>
                        <button className="secondary" onClick={() => {
                          if (onCreateRule) onCreateRule(alarm.missed_entity.type);
                        }} style={{ backgroundColor: '#fff', color: '#4682b4', border: '1px solid #4682b4' }}>
                          ➕ Create Rule
                        </button>
                      </>
                    )}
                    <button className="secondary" onClick={() => handleDismissAlarm(alarm.alarm_id)} style={{ color: '#4682b4', border: '1px solid #4682b4', backgroundColor: '#fff' }}>🚫 Dismiss</button>
                  </div>
                </div>
              </div>
                );
              })}
          </div>
          );
        })()}
      </div>

      {sandboxModalOpen && sandboxAlarm && (
        <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }}>
          <div style={{ background: '#fff', padding: '2rem', borderRadius: '8px', width: '90%', maxWidth: '700px', maxHeight: '90vh', overflowY: 'auto', boxShadow: '0 10px 25px rgba(0,0,0,0.2)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
              <h2 style={{ margin: 0 }}>🛠️ Sandbox Rule Fixer</h2>
              <button onClick={handleCloseSandbox} style={{ background: 'transparent', border: 'none', fontSize: '1.5rem', cursor: 'pointer' }}>×</button>
            </div>

            <div style={{ backgroundColor: '#f6f8fa', padding: '1rem', borderRadius: '6px', marginBottom: '1.5rem' }}>
              <strong>Problematic Context:</strong>
              <div style={{ fontStyle: 'italic', marginTop: '0.5rem', color: '#57606a', borderLeft: '3px solid #cf222e', paddingLeft: '0.5rem' }}>
                "{sandboxAlarm.context_snippet}"
              </div>
            </div>

            {isReactivationWarning && (
              <div style={{ backgroundColor: '#fff8c5', border: '1px solid #d4a72c', padding: '1rem', borderRadius: '6px', marginBottom: '1.5rem', color: '#9a6700' }}>
                ⚠️ <strong>Pre-existing Rule Found:</strong> This leak is caught by an existing inactive rule. We have auto-filled it below for reactivation. If you prefer to create a brand new rule, simply change the Entity Class name!
              </div>
            )}

            <div style={{ display: 'flex', gap: '1rem', alignItems: 'flex-end', marginBottom: '1.5rem' }}>
              <div style={{ flex: 1 }}>
                <label style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 'bold' }}>Entity Class</label>
                <input type="text" value={sandboxFormData.entity} onChange={e => setSandboxFormData({...sandboxFormData, entity: e.target.value})} style={{ width: '100%' }} placeholder="e.g., OPEN_AI_API_KEY" />
              </div>
              <div style={{ flex: 2 }}>
                <label style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 'bold' }}>Regex Pattern</label>
                <input type="text" value={sandboxFormData.regex} onChange={e => setSandboxFormData({...sandboxFormData, regex: e.target.value})} style={{ width: '100%', fontFamily: 'monospace' }} placeholder="e.g. \b[0-9]{4}\b" />
              </div>
            </div>

            <div style={{ marginBottom: '1.5rem', display: 'flex', justifyContent: 'center', gap: '1rem' }}>
              <button className="secondary" onClick={handleSuggestRule} disabled={sandboxLoading} style={{ fontSize: '0.9rem', display: 'flex', alignItems: 'center', gap: '0.5rem', padding: '0.4rem 0.8rem', backgroundColor: '#fff', color: '#4682b4', border: '1px solid #4682b4' }}>
                {sandboxLoading && !sandboxFormData.regex ? '⏳...' : '✨ Suggest AI Fix'}
              </button>
              <button className="secondary" onClick={handleTestSandbox} disabled={sandboxLoading} style={{ fontSize: '0.9rem', padding: '0.4rem 0.8rem', display: 'flex', alignItems: 'center', gap: '0.5rem', backgroundColor: '#fff', color: '#4682b4', border: '1px solid #4682b4' }}>
                {sandboxLoading && sandboxFormData.regex ? '⏳ Running Sandbox...' : '🔁 Run Replay Test'}
              </button>
            </div>

            {sandboxTestResult && (
              <div style={{ padding: '1rem', borderRadius: '6px', marginBottom: '1.5rem', border: sandboxTestResult.caught ? '1px solid #4ac26b' : '1px solid #ff8182', backgroundColor: sandboxTestResult.caught ? '#dafbe1' : '#ffebe9' }}>
                {sandboxTestResult.caught ? (
                  <>
                    <h4 style={{ margin: '0 0 0.5rem 0', color: '#1a7f37' }}>✅ Test Successful!</h4>
                    <p style={{ margin: 0 }}>The sandbox engine successfully caught: <strong style={{ fontFamily: 'monospace', backgroundColor: 'rgba(255,255,255,0.7)', padding: '2px 4px', borderRadius: '4px' }}>{sandboxTestResult.matched_text}</strong></p>
                  </>
                ) : (
                  <>
                    <h4 style={{ margin: '0 0 0.5rem 0', color: '#cf222e' }}>❌ Test Failed</h4>
                    <p style={{ margin: 0 }}>The provided regex pattern did not catch any data in the context snippet. Please adjust your regex.</p>
                  </>
                )}
              </div>
            )}

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '1rem', borderTop: '1px solid #d0d7de', paddingTop: '1rem' }}>
              <button className="secondary" onClick={handleCloseSandbox}>Cancel</button>
              <button className="primary" onClick={handleConfirmApplySandbox} disabled={!sandboxTestResult || !sandboxTestResult.caught || sandboxApplying} style={{ backgroundColor: (!sandboxTestResult || !sandboxTestResult.caught) ? '#ccc' : '#2da44e' }}>
                {sandboxApplying ? '⏳ Applying...' : '✅ Confirm & Apply Rule'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
