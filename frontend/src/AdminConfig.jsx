import { useState, useEffect } from 'react';
import { fetchRules, addRule, updateRule } from './api';

export default function AdminConfig() {
  const [loggedIn, setLoggedIn] = useState(false);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [loginError, setLoginError] = useState('');

  const [rules, setRules] = useState([]);
  const [editingRule, setEditingRule] = useState(null);
  
  const [formData, setFormData] = useState({ name: '', entity: '', regex: '', score: 0.85 });
  const [formMessage, setFormMessage] = useState(null);

  useEffect(() => {
    if (loggedIn) {
      loadRules();
    }
  }, [loggedIn]);

  const loadRules = async () => {
    try {
      const data = await fetchRules();
      if (data.rules) setRules(data.rules);
    } catch (e) {
      console.error("Failed to load rules", e);
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
    setFormData({ name: rule.name, entity: rule.entity, regex: rule.regex, score: rule.score });
    setFormMessage(null);
  };

  const handleCancelEdit = () => {
    setEditingRule(null);
    setFormData({ name: '', entity: '', regex: '', score: 0.85 });
    setFormMessage(null);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!formData.name || !formData.entity || !formData.regex) {
      setFormMessage({ type: 'error', text: 'All fields are required.' });
      return;
    }

    try {
      if (editingRule) {
        const payload = { ...formData, original_name: editingRule.name };
        const res = await updateRule(payload);
        if (res.status === 'success') {
          setFormMessage({ type: 'success', text: 'Rule updated and hot-reloaded!' });
          setEditingRule(null);
          setFormData({ name: '', entity: '', regex: '', score: 0.85 });
        } else {
          setFormMessage({ type: 'error', text: res.message });
        }
      } else {
        const res = await addRule(formData);
        if (res.status === 'success') {
          setFormMessage({ type: 'success', text: 'Rule added and hot-reloaded!' });
          setFormData({ name: '', entity: '', regex: '', score: 0.85 });
        } else {
          setFormMessage({ type: 'error', text: res.message });
        }
      }
      loadRules(); // Refresh list
    } catch (e) {
      setFormMessage({ type: 'error', text: 'Failed to connect to backend.' });
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
        <h2>⚙️ Rule Configuration Portal</h2>
        <button className="secondary" onClick={() => setLoggedIn(false)}>Logout</button>
      </div>

      <div className="admin-layout">
        <div className="rules-list">
          <h3>Existing Rules</h3>
          {rules.map((r, idx) => (
            <div className="rule-card" key={idx}>
              <h4>#{idx + 1}: {r.name}</h4>
              <div className="rule-meta">Entity: {r.entity}</div>
              <div className="rule-meta">Score: {r.score}</div>
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

              <div className="form-group">
                <label>Regex Pattern</label>
                <input type="text" value={formData.regex} onChange={e => setFormData({...formData, regex: e.target.value})} />
                <small className="help-text">The mathematical regular expression that matches the sensitive data. Make sure to use word boundaries (\b).</small>
              </div>

              <div className="form-group">
                <label>Confidence Score: {formData.score}</label>
                <input type="range" min="0" max="1" step="0.05" value={formData.score} onChange={e => setFormData({...formData, score: parseFloat(e.target.value)})} />
                <small className="help-text">How confident the AI should be when making this match. A lower score (0.4) might catch more data but cause false positives.</small>
              </div>

              <div style={{display: 'flex', gap: '1rem'}}>
                <button type="submit" className="primary">{editingRule ? 'Update Rule' : 'Add New Rule'}</button>
                {editingRule && (
                  <button type="button" className="secondary" onClick={handleCancelEdit}>Cancel</button>
                )}
              </div>
              
              {formMessage && (
                <div className={`alert-${formMessage.type}`}>{formMessage.text}</div>
              )}
            </form>
          </div>
        </div>
      </div>
    </div>
  );
}
