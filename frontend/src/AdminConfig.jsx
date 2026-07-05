import { useState, useEffect } from 'react';
import { fetchRules, addRule, updateRule, deleteRule, fetchAlarms, toggleWatchdog } from './api';

export default function AdminConfig() {
  const [loggedIn, setLoggedIn] = useState(false);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [loginError, setLoginError] = useState('');

  const [activeTab, setActiveTab] = useState('rules'); // 'rules' or 'alarms'

  const [rules, setRules] = useState([]);
  const [alarms, setAlarms] = useState([]);
  const [llmWatchdogEnabled, setLlmWatchdogEnabled] = useState(false);

  const [editingRule, setEditingRule] = useState(null);
  
  const [formData, setFormData] = useState({ name: '', entity: '', regex: '', score: 0.85, is_builtin: false, is_algorithmic: false });
  const [formMessage, setFormMessage] = useState(null);
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    if (loggedIn) {
      loadRules();
      if (activeTab === 'alarms') {
        loadAlarms();
      }
    }
  }, [loggedIn, activeTab]);

  const loadRules = async () => {
    try {
      const data = await fetchRules();
      if (data.rules) setRules(data.rules);
      if (data.settings && data.settings.enable_llm_watchdog !== undefined) {
        setLlmWatchdogEnabled(data.settings.enable_llm_watchdog);
      }
    } catch (e) {
      console.error("Failed to load rules", e);
    }
  };

  const loadAlarms = async () => {
    try {
      const data = await fetchAlarms();
      if (data.alarms) setAlarms(data.alarms);
    } catch (e) {
      console.error("Failed to load alarms", e);
    }
  };

  const handleToggleWatchdog = async (enabled) => {
    try {
      await toggleWatchdog(enabled);
      setLlmWatchdogEnabled(enabled);
    } catch (e) {
      console.error("Failed to toggle watchdog", e);
    }
  };

  const handleLogin = (e) => {
    e.preventDefault();
    if (username === 'admin' && password === 'admin') {
      setLoggedIn(true);
      setLoginError('');
    } else {
      setLoginError('Invalid credentials.');
    }
  };

  const handleEditClick = (rule) => {
    setEditingRule(rule);
    setFormData({ name: rule.name, entity: rule.entity, regex: rule.regex, score: rule.score, is_builtin: rule.is_builtin || false, is_algorithmic: rule.is_algorithmic || false });
    setFormMessage(null);
  };

  const handleCancelEdit = () => {
    setEditingRule(null);
    setFormData({ name: '', entity: '', regex: '', score: 0.85, is_builtin: false, is_algorithmic: false });
    setFormMessage(null);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!formData.name || !formData.entity || (!formData.is_builtin && !formData.is_algorithmic && !formData.regex)) {
      setFormMessage({ type: 'error', text: 'All fields are required.' });
      return;
    }

    setIsSaving(true);
    setFormMessage(null);

    try {
      if (editingRule) {
        const payload = { ...formData, original_name: editingRule.name };
        const res = await updateRule(payload);
        if (res.status === 'success') {
          setFormMessage({ type: 'success', text: 'Rule updated and hot-reloaded!' });
          setEditingRule(null);
          setFormData({ name: '', entity: '', regex: '', score: 0.85, is_builtin: false, is_algorithmic: false });
        } else {
          setFormMessage({ type: 'error', text: res.message });
        }
      } else {
        const res = await addRule(formData);
        if (res.status === 'success') {
          setFormMessage({ type: 'success', text: 'Rule added and hot-reloaded!' });
          setFormData({ name: '', entity: '', regex: '', score: 0.85, is_builtin: false, is_algorithmic: false });
        } else {
          setFormMessage({ type: 'error', text: res.message });
        }
      }
      loadRules();
    } catch (e) {
      setFormMessage({ type: 'error', text: 'Failed to connect to backend.' });
    } finally {
      setIsSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!editingRule) return;
    if (!window.confirm(`Are you sure you want to delete ${editingRule.name}?`)) return;

    setIsSaving(true);
    setFormMessage(null);

    try {
      const res = await deleteRule(editingRule.name);
      if (res.status === 'success') {
        setFormMessage({ type: 'success', text: 'Rule deleted!' });
        setEditingRule(null);
        setFormData({ name: '', entity: '', regex: '', score: 0.85, is_builtin: false, is_algorithmic: false });
        loadRules();
      } else {
        setFormMessage({ type: 'error', text: res.message });
      }
    } catch (e) {
      setFormMessage({ type: 'error', text: 'Failed to connect to backend.' });
    } finally {
      setIsSaving(false);
    }
  };

  if (!loggedIn) {
    return (
      <div className="login-box">
        <h2>Admin Login Required</h2>
        <form onSubmit={handleLogin}>
          <div className="form-group">
            <label>Username</label>
            <input type="text" value={username} onChange={e => setUsername(e.target.value)} />
          </div>
          <div className="form-group">
            <label>Password</label>
            <input type="password" value={password} onChange={e => setPassword(e.target.value)} />
          </div>
          {loginError && <div style={{color: 'red', marginBottom: '1rem'}}>{loginError}</div>}
          <button type="submit" className="primary" style={{width: '100%'}}>Login</button>
        </form>
      </div>
    );
  }

  return (
    <div>
      <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem'}}>
        <h2>⚙️ Enterprise Governance Command Center</h2>
        <div style={{display: 'flex', gap: '1rem', alignItems: 'center'}}>
          <div style={{display: 'flex', alignItems: 'center', gap: '0.5rem', background: '#f6f8fa', padding: '0.5rem 1rem', borderRadius: '6px', border: '1px solid #d0d7de'}}>
            <label style={{margin: 0, fontWeight: '600', fontSize: '0.9rem', color: '#24292f'}}>LLM Watchdog (Layer 2):</label>
            <label className="switch" style={{position: 'relative', display: 'inline-block', width: '40px', height: '20px'}}>
              <input type="checkbox" checked={llmWatchdogEnabled} onChange={(e) => handleToggleWatchdog(e.target.checked)} style={{opacity: 0, width: 0, height: 0}} />
              <span className="slider" style={{position: 'absolute', cursor: 'pointer', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: llmWatchdogEnabled ? '#2da44e' : '#cf222e', transition: '.4s', borderRadius: '20px'}}>
                <span style={{position: 'absolute', height: '14px', width: '14px', left: llmWatchdogEnabled ? '22px' : '3px', bottom: '3px', backgroundColor: 'white', transition: '.4s', borderRadius: '50%'}}></span>
              </span>
            </label>
          </div>
          <button className="secondary" onClick={() => setLoggedIn(false)}>Logout</button>
        </div>
      </div>

      <div style={{ display: 'flex', gap: '1rem', marginBottom: '1rem', borderBottom: '1px solid #d0d7de', paddingBottom: '0.5rem' }}>
        <button 
          onClick={() => setActiveTab('rules')}
          style={{ background: 'none', border: 'none', padding: '0.5rem 1rem', fontSize: '1rem', fontWeight: '600', color: activeTab === 'rules' ? '#0969da' : '#57606a', borderBottom: activeTab === 'rules' ? '2px solid #0969da' : '2px solid transparent', cursor: 'pointer' }}>
          Rule Configuration
        </button>
        <button 
          onClick={() => setActiveTab('alarms')}
          style={{ background: 'none', border: 'none', padding: '0.5rem 1rem', fontSize: '1rem', fontWeight: '600', color: activeTab === 'alarms' ? '#cf222e' : '#57606a', borderBottom: activeTab === 'alarms' ? '2px solid #cf222e' : '2px solid transparent', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          Alarm Queue {alarms.length > 0 && <span style={{ background: '#cf222e', color: 'white', borderRadius: '12px', padding: '2px 6px', fontSize: '0.75rem' }}>{alarms.length}</span>}
        </button>
      </div>

      {activeTab === 'rules' && (
        <div className="admin-layout">
          <div className="rules-list">
            <h3>Existing Rules (Layer 1)</h3>
            {rules.map((r, idx) => (
              <div className="rule-card" key={idx}>
                <h4>#{idx + 1}: {r.name}</h4>
                <div className="rule-meta">Entity: {r.entity}</div>
                <div className="rule-meta">Score: {r.score}</div>
                <div style={{ marginBottom: '0.5rem' }}>
                  {r.is_algorithmic ? (
                    <span style={{ backgroundColor: '#f3e8ff', color: '#7e22ce', padding: '2px 6px', borderRadius: '12px', fontSize: '0.75rem', fontWeight: '600' }}>
                      🧬 Algorithmic Rule
                    </span>
                  ) : (
                    <span style={{ backgroundColor: r.is_builtin ? '#dafbe1' : '#ddf4ff', color: r.is_builtin ? '#1a7f37' : '#0969da', padding: '2px 6px', borderRadius: '12px', fontSize: '0.75rem', fontWeight: '600' }}>
                      {r.is_builtin ? '✨ Built-In AI' : '⚙️ Custom Regex'}
                    </span>
                  )}
                </div>
                <button className="secondary" style={{padding: '0.2rem 0.5rem', fontSize: '0.8rem'}} onClick={() => handleEditClick(r)}>
                  Edit
                </button>
              </div>
            ))}
          </div>

          <div className="rule-form">
            <div className="card">
              <h3>{editingRule ? 'Edit Rule' : 'Add New Rule'}</h3>
              <form onSubmit={handleSubmit}>
                <div className="form-group">
                  <label>Rule Alias Name</label>
                  <input type="text" value={formData.name} onChange={e => setFormData({...formData, name: e.target.value})} />
                  <small className="help-text">A human-readable name for this rule (e.g., 'Corporate_Credit_Card').</small>
                </div>

                <div className="form-group">
                  <label>Entity Class</label>
                  <input type="text" value={formData.entity} onChange={e => setFormData({...formData, entity: e.target.value})} />
                  <small className="help-text">The Presidio tag used to mask the data (e.g., 'CREDIT_CARD'). The output will be replaced with &lt;ENTITY_CLASS&gt;.</small>
                </div>

                <div className="form-group" style={{ display: 'flex', alignItems: 'center', gap: '1.5rem' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <input 
                      type="checkbox" 
                      checked={formData.is_builtin} 
                      onChange={e => setFormData({...formData, is_builtin: e.target.checked, is_algorithmic: false, regex: e.target.checked ? '' : formData.regex})} 
                      style={{ width: 'auto', margin: 0 }}
                    />
                    <label style={{ margin: 0 }}>Use Built-in AI</label>
                  </div>
                  
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <input 
                      type="checkbox" 
                      checked={formData.is_algorithmic} 
                      onChange={e => setFormData({...formData, is_algorithmic: e.target.checked, is_builtin: false, regex: e.target.checked ? 'Python Code' : formData.regex})} 
                      style={{ width: 'auto', margin: 0 }}
                    />
                    <label style={{ margin: 0 }}>Algorithmic Python Rule</label>
                  </div>
                </div>

                <div className="form-group">
                  <label style={{ color: (formData.is_builtin || formData.is_algorithmic) ? '#8c959f' : 'inherit' }}>Regex Pattern</label>
                  <input 
                    type="text" 
                    value={formData.regex} 
                    onChange={e => setFormData({...formData, regex: e.target.value})} 
                    disabled={formData.is_builtin || formData.is_algorithmic}
                    style={{ backgroundColor: (formData.is_builtin || formData.is_algorithmic) ? '#f6f8fa' : '#fff' }}
                  />
                  <small className="help-text">The mathematical regular expression that matches the sensitive data. Make sure to use word boundaries (\b).</small>
                </div>

                <div className="form-group">
                  <label>Confidence Score: {formData.score}</label>
                  <input type="range" min="0" max="1" step="0.05" value={formData.score} onChange={e => setFormData({...formData, score: parseFloat(e.target.value)})} />
                  <small className="help-text">How confident the AI should be when making this match. A lower score (0.4) might catch more data but cause false positives.</small>
                </div>

                <div style={{display: 'flex', gap: '1rem', alignItems: 'center'}}>
                  <button type="submit" className="primary" disabled={isSaving}>
                    {isSaving ? 'Processing...' : (editingRule ? 'Update Rule' : 'Add New Rule')}
                  </button>
                  {editingRule && (
                    <>
                      <button type="button" className="secondary" onClick={handleCancelEdit} disabled={isSaving}>Cancel</button>
                      <button type="button" onClick={handleDelete} disabled={isSaving} style={{ backgroundColor: '#cf222e', color: 'white', border: 'none', padding: '8px 16px', borderRadius: '6px', cursor: isSaving ? 'not-allowed' : 'pointer' }}>
                        Delete
                      </button>
                    </>
                  )}
                </div>
                
                {formMessage && (
                  <div className={`alert-${formMessage.type}`}>{formMessage.text}</div>
                )}
              </form>
            </div>
          </div>
        </div>
      )}

      {activeTab === 'alarms' && (
        <div className="card">
          <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem'}}>
            <h3 style={{ margin: 0 }}>🚨 Watchdog Alarms</h3>
            <button onClick={loadAlarms} className="secondary" style={{ padding: '0.2rem 0.5rem', fontSize: '0.8rem' }}>Refresh</button>
          </div>
          {alarms.length === 0 ? (
            <p style={{ color: '#57606a' }}>No alarms pending review. System is clean!</p>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
              {alarms.map((alarm, idx) => (
                <div key={idx} style={{ border: '1px solid #d0d7de', borderRadius: '6px', padding: '1rem', backgroundColor: '#fff' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '0.5rem' }}>
                    <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                      <span style={{ backgroundColor: '#cf222e', color: 'white', padding: '2px 6px', borderRadius: '12px', fontSize: '0.75rem', fontWeight: '600' }}>{alarm.severity}</span>
                      <strong style={{ fontSize: '1.1rem' }}>{alarm.missed_entity.type}</strong>
                    </div>
                    <span style={{ color: '#57606a', fontSize: '0.85rem' }}>{new Date(alarm.timestamp).toLocaleString()}</span>
                  </div>
                  
                  <div style={{ backgroundColor: '#f6f8fa', padding: '0.75rem', borderRadius: '6px', marginBottom: '0.75rem', fontFamily: 'monospace', fontSize: '0.9rem' }}>
                    Value: <strong>{alarm.missed_entity.value_preview}</strong>
                  </div>
                  
                  <div style={{ marginBottom: '1rem' }}>
                    <strong>Reason given by LLM:</strong> {alarm.missed_entity.reason}
                  </div>
                  
                  <div style={{ display: 'flex', gap: '1rem' }}>
                    <div style={{ flex: 1, backgroundColor: '#ffebe9', padding: '0.75rem', borderRadius: '6px', border: '1px solid #ff8182' }}>
                      <strong>Layer 1 (Presidio) Found:</strong>
                      <div style={{ fontSize: '0.9rem', color: '#cf222e', marginTop: '0.5rem' }}>
                        {alarm.layer1_findings.length > 0 ? alarm.layer1_findings.join(', ') : 'Nothing'}
                      </div>
                    </div>
                    <div style={{ flex: 1, backgroundColor: '#dafbe1', padding: '0.75rem', borderRadius: '6px', border: '1px solid #4ac26b' }}>
                      <strong>Layer 2 (LLM Watchdog) Found:</strong>
                      <div style={{ fontSize: '0.9rem', color: '#1a7f37', marginTop: '0.5rem' }}>
                        {alarm.layer2_findings.length > 0 ? alarm.layer2_findings.join(', ') : 'Nothing'}
                      </div>
                    </div>
                  </div>
                  
                  <div style={{ marginTop: '1rem', display: 'flex', gap: '0.5rem' }}>
                    <button className="primary" onClick={() => {
                      setActiveTab('rules');
                      setFormData({ name: `New_${alarm.missed_entity.type}`, entity: alarm.missed_entity.type, regex: '', score: 0.85, is_builtin: false, is_algorithmic: false });
                      setFormMessage({ type: 'success', text: `Auto-filled form for ${alarm.missed_entity.type}. Please define Regex or select Built-in AI.`});
                    }}>
                      Confirm & Create Rule
                    </button>
                    <button className="secondary">Dismiss (False Positive)</button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
