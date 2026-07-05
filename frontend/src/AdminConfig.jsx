import { useState, useEffect } from 'react';
import { fetchRules, addRule, updateRule, deleteRule, fetchAlarms, toggleWatchdog, fetchSubscribers, addSubscriber, updateSubscriber, deleteSubscriber, deleteAlarm, sandboxSuggestRule, sandboxTestRule } from './api';

export default function AdminConfig() {
  const [loggedIn, setLoggedIn] = useState(false);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [loginError, setLoginError] = useState('');

  const [activeTab, setActiveTab] = useState('rules'); // 'rules', 'alarms', 'routing'

  const [rules, setRules] = useState([]);
  const [alarms, setAlarms] = useState([]);
  const [subscribers, setSubscribers] = useState([]);
  const [llmWatchdogEnabled, setLlmWatchdogEnabled] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');

  const [editingRule, setEditingRule] = useState(null);
  const [editingSubscriber, setEditingSubscriber] = useState(null);
  
  const [formData, setFormData] = useState({ name: '', entity: '', regex: '', score: 0.85, is_builtin: false, is_algorithmic: false, is_active: true });
  const [subFormData, setSubFormData] = useState({ user_name: '', role: '', alert_type: 'ALL', email: '' });
  
  const [formMessage, setFormMessage] = useState(null);
  const [subFormMessage, setSubFormMessage] = useState(null);
  const [isSaving, setIsSaving] = useState(false);

  // Sandbox Modal State
  const [sandboxModalOpen, setSandboxModalOpen] = useState(false);
  const [sandboxAlarm, setSandboxAlarm] = useState(null);
  const [sandboxFormData, setSandboxFormData] = useState({ entity: '', regex: '' });
  const [sandboxLoading, setSandboxLoading] = useState(false);
  const [sandboxTestResult, setSandboxTestResult] = useState(null);

  useEffect(() => {
    if (loggedIn) {
      loadRules();
      loadAlarms();
      loadSubscribers();
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

  const loadSubscribers = async () => {
    try {
      const data = await fetchSubscribers();
      if (data.subscribers) setSubscribers(data.subscribers);
    } catch (e) {
      console.error("Failed to load subscribers", e);
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

  const handleDismissAlarm = async (alarm_id) => {
    try {
      await deleteAlarm(alarm_id);
      loadAlarms();
    } catch (e) {
      console.error("Failed to dismiss alarm", e);
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
    setFormData({ name: rule.name, entity: rule.entity, regex: rule.regex, score: rule.score, is_builtin: rule.is_builtin || false, is_algorithmic: rule.is_algorithmic || false, is_active: rule.is_active !== false });
    setFormMessage(null);
  };

  const handleCancelEdit = () => {
    setEditingRule(null);
    setFormData({ name: '', entity: '', regex: '', score: 0.85, is_builtin: false, is_algorithmic: false, is_active: true });
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
          setFormData({ name: '', entity: '', regex: '', score: 0.85, is_builtin: false, is_algorithmic: false, is_active: true });
        } else {
          setFormMessage({ type: 'error', text: res.message });
        }
      } else {
        const res = await addRule(formData);
        if (res.status === 'success') {
          setFormMessage({ type: 'success', text: 'Rule added and hot-reloaded!' });
          setFormData({ name: '', entity: '', regex: '', score: 0.85, is_builtin: false, is_algorithmic: false, is_active: true });
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
        setFormData({ name: '', entity: '', regex: '', score: 0.85, is_builtin: false, is_algorithmic: false, is_active: true });
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

  const handleToggleRuleActive = async (rule) => {
    const payload = { ...rule, original_name: rule.name, is_active: rule.is_active === false ? true : false };
    try {
      await updateRule(payload);
      loadRules();
    } catch (e) {
      console.error("Failed to toggle rule", e);
    }
  };

  const handleEditSubscriberClick = (s) => {
    setEditingSubscriber(s);
    setSubFormData({ user_name: s.user_name, role: s.role, alert_type: s.alert_type, email: s.email || '' });
    setSubFormMessage(null);
  };

  const handleCancelEditSubscriber = () => {
    setEditingSubscriber(null);
    setSubFormData({ user_name: '', role: '', alert_type: 'ALL', email: '' });
    setSubFormMessage(null);
  };

  const handleAddSubscriber = async (e) => {
    e.preventDefault();
    if (!subFormData.user_name || !subFormData.role) {
      setSubFormMessage({ type: 'error', text: 'Name and Role are required.' });
      return;
    }
    if (!subFormData.email) {
      setSubFormMessage({ type: 'error', text: 'Email is required.' });
      return;
    }
    
    setIsSaving(true);
    try {
      if (editingSubscriber) {
        const payload = { ...subFormData, original_user_name: editingSubscriber.user_name };
        const res = await updateSubscriber(payload);
        if (res.status === 'success') {
          setSubFormMessage({ type: 'success', text: 'Subscriber updated!' });
          setEditingSubscriber(null);
          setSubFormData({ user_name: '', role: '', alert_type: 'ALL', email: '' });
          loadSubscribers();
        } else {
          setSubFormMessage({ type: 'error', text: res.message });
        }
      } else {
        const res = await addSubscriber(subFormData);
        if (res.status === 'success') {
          setSubFormMessage({ type: 'success', text: 'Subscriber added!' });
          setSubFormData({ user_name: '', role: '', alert_type: 'ALL', email: '' });
          loadSubscribers();
        } else {
          setSubFormMessage({ type: 'error', text: res.message });
        }
      }
    } catch (e) {
      setSubFormMessage({ type: 'error', text: 'Failed to connect to backend.' });
    } finally {
      setIsSaving(false);
    }
  };

  const handleDeleteSubscriber = async (user_name) => {
    if (!window.confirm(`Remove subscriber ${user_name}?`)) return;
    try {
      await deleteSubscriber(user_name);
      loadSubscribers();
    } catch (e) {
      console.error(e);
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
  };

  const handleSuggestRule = async () => {
    setSandboxLoading(true);
    setSandboxTestResult(null);
    try {
      const res = await sandboxSuggestRule(sandboxAlarm.context_snippet, sandboxAlarm.missed_entity.type, sandboxAlarm.missed_entity.value_preview);
      if (res.status === 'success') {
        setSandboxFormData({ entity: res.suggestion.entity, regex: res.suggestion.regex });
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
    setSandboxLoading(true);
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
      await loadRules();
      await loadAlarms();
      
      handleCloseSandbox();
    } catch (e) {
      alert("Failed to apply rule.");
    } finally {
      setSandboxLoading(false);
    }
  };

  const filteredRules = rules.filter(r => 
    r.name.toLowerCase().includes(searchQuery.toLowerCase()) || 
    r.entity.toLowerCase().includes(searchQuery.toLowerCase())
  );

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
            <label style={{margin: 0, fontWeight: '600', fontSize: '0.9rem', color: '#24292f'}}>Secondary Threat Engine:</label>
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
          Threat Detections {alarms.length > 0 && <span style={{ background: '#cf222e', color: 'white', borderRadius: '12px', padding: '2px 6px', fontSize: '0.75rem' }}>{alarms.length}</span>}
        </button>
        <button 
          onClick={() => setActiveTab('routing')}
          style={{ background: 'none', border: 'none', padding: '0.5rem 1rem', fontSize: '1rem', fontWeight: '600', color: activeTab === 'routing' ? '#9a6700' : '#57606a', borderBottom: activeTab === 'routing' ? '2px solid #d29922' : '2px solid transparent', cursor: 'pointer' }}>
          Alert Routing
        </button>
      </div>

      {activeTab === 'rules' && (
        <div className="admin-layout">
          <div className="rules-list">
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.8rem', marginBottom: '1rem', alignItems: 'flex-start' }}>
              <input 
                type="text" 
                placeholder="🔍 Search rules or entities..." 
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                style={{ padding: '0.4rem 0.8rem', borderRadius: '20px', border: '1px solid #d0d7de', fontSize: '0.85rem', width: '100%', maxWidth: '300px' }}
              />
              <h3 style={{ margin: 0 }}>Primary Engine Rules</h3>
            </div>
            
            <div style={{ border: '1px solid #d0d7de', borderRadius: '6px', background: '#fff' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.85rem' }}>
                <thead style={{ background: '#f6f8fa', position: 'sticky', top: 0, zIndex: 1 }}>
                  <tr>
                    <th style={{ padding: '0.75rem', borderBottom: '1px solid #d0d7de', whiteSpace: 'nowrap' }}>Rule Name</th>
                    <th style={{ padding: '0.75rem', borderBottom: '1px solid #d0d7de', whiteSpace: 'nowrap' }}>Entity Class</th>
                    <th style={{ padding: '0.75rem', borderBottom: '1px solid #d0d7de', whiteSpace: 'nowrap' }}>Type</th>
                    <th style={{ padding: '0.75rem', borderBottom: '1px solid #d0d7de', textAlign: 'center', whiteSpace: 'nowrap' }}>Status</th>
                    <th style={{ padding: '0.75rem', borderBottom: '1px solid #d0d7de', textAlign: 'right', whiteSpace: 'nowrap' }}>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredRules.length === 0 ? (
                    <tr>
                      <td colSpan="4" style={{ padding: '2rem', textAlign: 'center', color: '#57606a' }}>No rules match your search.</td>
                    </tr>
                  ) : filteredRules.map((r, idx) => (
                    <tr key={idx} style={{ borderBottom: '1px solid #d0d7de', background: editingRule?.name === r.name ? '#f0f8ff' : 'transparent' }}>
                      <td style={{ padding: '0.75rem', fontWeight: '500', maxWidth: '200px', wordWrap: 'break-word', wordBreak: 'break-word' }}>{r.name}</td>
                      <td style={{ padding: '0.75rem', fontFamily: 'monospace', color: '#cf222e', maxWidth: '180px', wordWrap: 'break-word', wordBreak: 'break-word' }}>{r.entity}</td>
                      <td style={{ padding: '0.75rem', whiteSpace: 'nowrap' }}>
                        {r.is_algorithmic ? (
                          <span style={{ backgroundColor: '#f3e8ff', color: '#7e22ce', padding: '2px 6px', borderRadius: '12px', fontSize: '0.7rem', fontWeight: '600' }}>🧬 Algorithmic</span>
                        ) : (
                          <span style={{ backgroundColor: r.is_builtin ? '#dafbe1' : '#ddf4ff', color: r.is_builtin ? '#1a7f37' : '#0969da', padding: '2px 6px', borderRadius: '12px', fontSize: '0.7rem', fontWeight: '600' }}>
                            {r.is_builtin ? '✨ Built-In AI' : '⚙️ Custom Regex'}
                          </span>
                        )}
                      </td>
                      <td style={{ padding: '0.75rem', textAlign: 'center' }}>
                        <label className="switch" style={{position: 'relative', display: 'inline-block', width: '30px', height: '16px'}}>
                          <input type="checkbox" checked={r.is_active !== false} onChange={() => handleToggleRuleActive(r)} style={{opacity: 0, width: 0, height: 0}} />
                          <span className="slider" style={{position: 'absolute', cursor: 'pointer', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: r.is_active !== false ? '#2da44e' : '#cf222e', transition: '.4s', borderRadius: '16px'}}>
                            <span style={{position: 'absolute', height: '12px', width: '12px', left: r.is_active !== false ? '16px' : '2px', bottom: '2px', backgroundColor: 'white', transition: '.4s', borderRadius: '50%'}}></span>
                          </span>
                        </label>
                      </td>
                      <td style={{ padding: '0.75rem', textAlign: 'right' }}>
                        <button className="secondary" title="Edit" style={{padding: '0.3rem 0.5rem', fontSize: '1rem', border: 'none', background: 'transparent'}} onClick={() => handleEditClick(r)}>✏️</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
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
                  <small className="help-text">The tag used to mask the data (e.g., 'CREDIT_CARD'). The output will be replaced with &lt;ENTITY_CLASS&gt;.</small>
                </div>

                <div className="form-group" style={{ display: 'flex', alignItems: 'center', gap: '1.5rem', flexWrap: 'wrap' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <input 
                      type="checkbox" 
                      checked={formData.is_active} 
                      onChange={e => setFormData({...formData, is_active: e.target.checked})} 
                      style={{ width: 'auto', margin: 0 }}
                    />
                    <label style={{ margin: 0, fontWeight: 'bold' }}>Rule Active</label>
                  </div>
                  
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
            <h3 style={{ margin: 0 }}>🚨 Threat Detections</h3>
            <button onClick={loadAlarms} className="secondary" style={{ padding: '0.2rem 0.5rem', fontSize: '0.8rem' }}>Refresh</button>
          </div>
          {alarms.length === 0 ? (
            <p style={{ color: '#57606a' }}>No alarms pending review. System is clean!</p>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
              {alarms.map((alarm, idx) => (
                <div key={alarm.alarm_id} style={{ border: '1px solid #d0d7de', borderRadius: '8px', marginBottom: '1.5rem', background: '#fff', boxShadow: '0 1px 3px rgba(0,0,0,0.05)' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid #d0d7de', padding: '1rem', background: '#f6f8fa', borderTopLeftRadius: '8px', borderTopRightRadius: '8px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                      <span style={{ backgroundColor: '#cf222e', color: '#fff', padding: '2px 8px', borderRadius: '12px', fontSize: '0.75rem', fontWeight: 'bold' }}>{alarm.severity}</span>
                      <h4 style={{ margin: 0, fontSize: '1.1rem' }}>{alarm.missed_entity.type}</h4>
                      {alarm.category && (
                        <span style={{ 
                          backgroundColor: alarm.category === 'AUTHENTICATION' ? '#8b5cf6' : 
                                           alarm.category === 'FINANCIAL' ? '#0969da' : 
                                           alarm.category === 'HIPAA' ? '#116329' : 
                                           alarm.category === 'GDPR' ? '#9a6700' : '#57606a', 
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
                      <div>
                        Leaked Data Snippet: <strong style={{fontFamily: 'monospace'}}>{alarm.missed_entity.value_preview}</strong>
                      </div>
                    </div>
                    
                    <div style={{ marginBottom: '1rem' }}>
                      <strong>Reason given by AI:</strong> {alarm.missed_entity.reason}
                    </div>
                    
                    <div style={{ display: 'flex', gap: '1rem' }}>
                      <div style={{ flex: 1, backgroundColor: '#ffebe9', padding: '0.75rem', borderRadius: '6px', border: '1px solid #ff8182' }}>
                        <strong>Primary Engine Found:</strong>
                        <div style={{ fontSize: '0.9rem', color: '#cf222e', marginTop: '0.5rem' }}>
                          {alarm.layer1_findings.length > 0 ? Array.from(new Set(alarm.layer1_findings)).join(', ') : 'Nothing'}
                        </div>
                      </div>
                      <div style={{ flex: 1, backgroundColor: '#dafbe1', padding: '0.75rem', borderRadius: '6px', border: '1px solid #4ac26b' }}>
                        <strong>Secondary Engine Detected:</strong>
                        <div style={{ fontSize: '0.9rem', color: '#1a7f37', marginTop: '0.5rem' }}>
                          {alarm.layer2_findings.length > 0 ? Array.from(new Set(alarm.layer2_findings)).join(', ') : 'Nothing'}
                        </div>
                      </div>
                    </div>
                    
                    <div style={{ marginTop: '1rem', display: 'flex', gap: '0.5rem' }}>
                      <button className="secondary" onClick={() => handleOpenSandbox(alarm)} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', backgroundColor: '#fff', color: '#4682b4', border: '1px solid #4682b4' }}>
                        🛠️ Fix & Replay Sandbox
                      </button>
                      <button className="secondary" onClick={() => {
                        setActiveTab('rules');
                        setFormData({ name: `New_${alarm.missed_entity.type}`, entity: alarm.missed_entity.type, regex: '', score: 0.85, is_builtin: false, is_algorithmic: false, is_active: true });
                        setFormMessage({ type: 'success', text: `Auto-filled form for ${alarm.missed_entity.type}. Please define Regex or select Built-in AI.`});
                      }} style={{ backgroundColor: '#fff', color: '#4682b4', border: '1px solid #4682b4' }}>
                        ➕ Create Rule
                      </button>
                      <button className="secondary" onClick={() => handleDismissAlarm(alarm.alarm_id)} style={{ color: '#4682b4', border: '1px solid #4682b4', backgroundColor: '#fff' }}>🚫 Dismiss (False Positive)</button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {activeTab === 'routing' && (
        <div className="admin-layout">
          <div className="rules-list">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
              <h3 style={{ margin: 0 }}>Active Notification Subscribers</h3>
              <button onClick={loadSubscribers} className="secondary" style={{ padding: '0.2rem 0.5rem', fontSize: '0.8rem' }}>Refresh</button>
            </div>
            
            <div style={{ border: '1px solid #d0d7de', borderRadius: '6px', background: '#fff', overflow: 'hidden' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.9rem' }}>
                <thead style={{ background: '#f6f8fa' }}>
                  <tr>
                    <th style={{ padding: '0.75rem', borderBottom: '1px solid #d0d7de' }}>Name</th>
                    <th style={{ padding: '0.75rem', borderBottom: '1px solid #d0d7de' }}>Role</th>
                    <th style={{ padding: '0.75rem', borderBottom: '1px solid #d0d7de' }}>Alert Type</th>
                    <th style={{ padding: '0.75rem', borderBottom: '1px solid #d0d7de', textAlign: 'right' }}>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {subscribers.length === 0 ? (
                    <tr>
                      <td colSpan="4" style={{ padding: '2rem', textAlign: 'center', color: '#57606a' }}>No subscribers configured.</td>
                    </tr>
                  ) : subscribers.map((s, idx) => (
                    <tr key={idx} style={{ borderBottom: '1px solid #d0d7de' }}>
                      <td style={{ padding: '0.75rem', fontWeight: '500' }}>{s.user_name}</td>
                      <td style={{ padding: '0.75rem' }}>{s.role}</td>
                      <td style={{ padding: '0.75rem' }}>
                        <span style={{ 
                          backgroundColor: s.alert_type === 'AUTHENTICATION' ? '#ede9fe' : s.alert_type === 'FINANCIAL' ? '#ddf4ff' : s.alert_type === 'HIPAA' ? '#dafbe1' : s.alert_type === 'GDPR' ? '#fff8c5' : '#f3e8ff', 
                          color: s.alert_type === 'AUTHENTICATION' ? '#8b5cf6' : s.alert_type === 'FINANCIAL' ? '#0969da' : s.alert_type === 'HIPAA' ? '#1a7f37' : s.alert_type === 'GDPR' ? '#9a6700' : '#7e22ce', 
                          padding: '2px 6px', borderRadius: '12px', fontSize: '0.75rem', fontWeight: '600' 
                        }}>
                          {s.alert_type}
                        </span>
                      </td>
                      <td style={{ padding: '0.75rem', textAlign: 'right', whiteSpace: 'nowrap' }}>
                        <button className="secondary" title="Edit" style={{padding: '0.3rem 0.5rem', fontSize: '1rem', border: 'none', background: 'transparent'}} onClick={() => handleEditSubscriberClick(s)}>✏️</button>
                        <button className="secondary" style={{padding: '0.2rem 0.5rem', fontSize: '0.8rem', color: '#cf222e'}} onClick={() => handleDeleteSubscriber(s.user_name)}>Remove</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="rule-form">
            <div className="card">
              <h3>{editingSubscriber ? 'Edit Subscriber' : 'Add Subscriber'}</h3>
              <form onSubmit={handleAddSubscriber}>
                <div className="form-group">
                  <label>Full Name</label>
                  <input type="text" value={subFormData.user_name} onChange={e => setSubFormData({...subFormData, user_name: e.target.value})} placeholder="Jane Doe" />
                </div>
                <div className="form-group">
                  <label>Role</label>
                  <input type="text" value={subFormData.role} onChange={e => setSubFormData({...subFormData, role: e.target.value})} placeholder="Compliance Officer" />
                </div>
                <div className="form-group">
                  <label>Alert Category</label>
                  <select 
                    value={subFormData.alert_type} 
                    onChange={e => setSubFormData({...subFormData, alert_type: e.target.value})}
                    style={{ width: '100%', padding: '0.5rem', borderRadius: '6px', border: '1px solid #d0d7de' }}
                  >
                    <option value="ALL">ALL (Global Admin / Uncategorized)</option>
                    <option value="FINANCIAL">FINANCIAL (PCI-DSS / Banking)</option>
                    <option value="AUTHENTICATION">AUTHENTICATION (API Keys / Credentials)</option>
                    <option value="HIPAA">HIPAA (Protected Health Info)</option>
                    <option value="GDPR">GDPR (General Privacy / EU)</option>
                  </select>
                </div>
                <div className="form-group">
                  <label>Email Address</label>
                  <input type="email" value={subFormData.email} onChange={e => setSubFormData({...subFormData, email: e.target.value})} placeholder="jane.doe@company.com" />
                </div>
                <div style={{marginTop: '1rem', display: 'flex', gap: '1rem', alignItems: 'center'}}>
                  <button type="submit" className="primary" disabled={isSaving}>
                    {isSaving ? 'Processing...' : (editingSubscriber ? 'Update Subscriber' : 'Add Subscriber')}
                  </button>
                  {editingSubscriber && (
                    <button type="button" className="secondary" onClick={handleCancelEditSubscriber} disabled={isSaving}>Cancel</button>
                  )}
                </div>
                {subFormMessage && (
                  <div className={`alert-${subFormMessage.type}`} style={{marginTop: '1rem'}}>{subFormMessage.text}</div>
                )}
              </form>
            </div>
          </div>
        </div>
      )}

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
              <button className="primary" onClick={handleConfirmApplySandbox} disabled={!sandboxTestResult || !sandboxTestResult.caught || sandboxLoading} style={{ backgroundColor: (!sandboxTestResult || !sandboxTestResult.caught) ? '#ccc' : '#2da44e' }}>
                ✅ Confirm & Apply Rule
              </button>
            </div>
          </div>
        </div>
      )}

    </div>
  );
}
