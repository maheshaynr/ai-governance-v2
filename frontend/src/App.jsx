import { useState, useEffect } from 'react';
import Dashboard from './Dashboard';
import AdminConfig from './AdminConfig';
import AnalyticsDashboard from './AnalyticsDashboard';
import ChatBot from './ChatBot';
import AgentGovernance from './AgentGovernance';
import { fetchAlarms, fetchSystemStatus, fetchWhoAmI, getApiKey, setApiKey, clearApiKey, AuthError } from './api';

// Every endpoint but /system_status (and the deliberately-open external-facing ones,
// see auth.py) now requires an X-API-Key header again, so the whole app sits behind one
// login gate here rather than each tab handling it -- the Chat Bot, Testing Dashboard
// and Analytics tabs have no login UI of their own.
function LoginGate({ onAuthenticated, error }) {
  const [key, setKey] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [localError, setLocalError] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!key.trim()) return;
    setSubmitting(true);
    setLocalError('');
    try {
      setApiKey(key.trim());
      const principal = await fetchWhoAmI();
      onAuthenticated(principal);
    } catch (err) {
      clearApiKey();
      setLocalError(err instanceof AuthError ? err.message : 'Could not reach the backend.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="login-box">
      <h2>🛡️ Enterprise AI Governance</h2>
      <p style={{ color: '#57606a', marginBottom: '1.5rem' }}>
        Enter your API key to continue. Every action in this app is tied to the role your
        key carries.
      </p>
      <form onSubmit={handleSubmit}>
        <div className="form-group">
          <label>API Key</label>
          <input
            type="password"
            value={key}
            onChange={(e) => setKey(e.target.value)}
            placeholder="X-API-Key"
            autoFocus
          />
        </div>
        {(localError || error) && (
          <div style={{ color: 'red', marginBottom: '1rem' }}>{localError || error}</div>
        )}
        <button type="submit" className="primary" style={{ width: '100%' }} disabled={submitting}>
          {submitting ? 'Checking...' : 'Continue'}
        </button>
      </form>
    </div>
  );
}

function App() {
  const [activeTab, setActiveTab] = useState('chatbot');
  const [alarms, setAlarms] = useState([]);
  const [sysStatus, setSysStatus] = useState('loading');

  // null = not checked yet, false = needs login, an object = authenticated principal
  const [principal, setPrincipal] = useState(null);
  const [authError, setAuthError] = useState('');

  // On first mount, a key may already be sitting in localStorage from a previous
  // session -- validate it against /whoami rather than trusting it blindly, since it
  // could have been revoked since.
  useEffect(() => {
    const existingKey = getApiKey();
    if (!existingKey) {
      setPrincipal(false);
      return;
    }
    fetchWhoAmI()
      .then(setPrincipal)
      .catch(() => {
        clearApiKey();
        setPrincipal(false);
      });
  }, []);

  const handleLogout = () => {
    clearApiKey();
    setPrincipal(false);
    setAlarms([]);
  };

  useEffect(() => {
    if (!principal) return; // Nothing to poll until a valid key is in place.

    fetchSystemStatus().then(data => setSysStatus(data.status));

    const interval = setInterval(() => {
      fetchAlarms().then(data => {
        if (data.alarms) setAlarms(data.alarms);
      }).catch(e => {
        // The key that was valid a moment ago may have just been revoked elsewhere --
        // send the user back to the login gate rather than polling a 401 forever.
        if (e instanceof AuthError) handleLogout();
        else console.error(e);
      });

      fetchSystemStatus().then(data => setSysStatus(data.status));
    }, 5000);

    return () => clearInterval(interval);
  }, [principal]);

  if (principal === null) {
    return <div className="app-container"><p style={{ padding: '2rem' }}>Loading...</p></div>;
  }

  if (!principal) {
    return (
      <div className="app-container" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '100vh' }}>
        <LoginGate onAuthenticated={setPrincipal} error={authError} />
      </div>
    );
  }

  return (
    <div className="app-container">
      <div className="header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <h1>🛡️ Enterprise AI Governance v1.1</h1>
          <div className="nav-tabs">
            <button
              className={activeTab === 'chatbot' ? 'active' : ''}
              onClick={() => setActiveTab('chatbot')}
            >
              Chat Bot
            </button>
            <button
              className={activeTab === 'admin' ? 'active' : ''}
              onClick={() => setActiveTab('admin')}
            >
              Admin Configuration
            </button>
            <button
              className={activeTab === 'analytics' ? 'active' : ''}
              onClick={() => setActiveTab('analytics')}
            >
              Analytics & Metrics
            </button>
            <button
              className={activeTab === 'dashboard' ? 'active' : ''}
              onClick={() => setActiveTab('dashboard')}
            >
              Testing Dashboard
            </button>
            <button
              className={activeTab === 'governance' ? 'active' : ''}
              onClick={() => setActiveTab('governance')}
            >
              Agent Governance
            </button>
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem', alignItems: 'flex-end' }}>
          <div style={{ visibility: alarms.length > 0 ? 'visible' : 'hidden', backgroundColor: '#cf222e', color: 'white', padding: '0.4rem 0.8rem', borderRadius: '6px', display: 'flex', alignItems: 'center', gap: '0.5rem', boxShadow: '0 2px 4px rgba(0,0,0,0.1)', fontSize: '0.85rem' }}>
            <span style={{ fontSize: '1rem' }}>🚨</span>
            <div>
              <strong>Alert:</strong> {alarms.length} pending Threat Detection{alarms.length > 1 ? 's' : ''}.
            </div>
          </div>

          <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
            <div style={{ backgroundColor: sysStatus === 'ready' ? '#dafbe1' : '#fff8c5', color: sysStatus === 'ready' ? '#1a7f37' : '#9a6700', padding: '0.4rem 0.8rem', borderRadius: '6px', display: 'flex', alignItems: 'center', gap: '0.5rem', boxShadow: '0 1px 3px rgba(0,0,0,0.1)', fontSize: '0.85rem', border: `1px solid ${sysStatus === 'ready' ? '#4ac26b' : '#d4a72c'}` }}>
              <span style={{ fontSize: '1rem' }}>{sysStatus === 'ready' ? '🟢' : '🟠'}</span>
              <div>
                <strong>System Status:</strong> {sysStatus === 'ready' ? 'Live' : 'Offline, try after sometime'}
              </div>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', background: '#f6f8fa', padding: '0.4rem 0.8rem', borderRadius: '6px', border: '1px solid #d0d7de', fontSize: '0.85rem' }}>
              <span>👤 {principal.name} ({principal.role})</span>
              <button className="secondary" onClick={handleLogout} style={{ padding: '0.15rem 0.5rem', fontSize: '0.8rem' }}>Logout</button>
            </div>
          </div>
        </div>
      </div>

      <main>
        {activeTab === 'dashboard' && <Dashboard />}
        {activeTab === 'chatbot' && <ChatBot />}
        {activeTab === 'analytics' && <AnalyticsDashboard />}
        {activeTab === 'admin' && <AdminConfig principal={principal} />}
        {activeTab === 'governance' && <AgentGovernance principal={principal} />}
      </main>
    </div>
  );
}

export default App;
