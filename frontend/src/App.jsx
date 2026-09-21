import { useState, useEffect } from 'react';
import Dashboard from './Dashboard';
import AdminConfig from './AdminConfig';
import AnalyticsDashboard from './AnalyticsDashboard';
import ChatBot from './ChatBot';
import AgentGovernance from './AgentGovernance';
import { fetchAlarms, fetchSystemStatus, getRole, setRole as persistRole } from './api';

const ROLES = ['super_admin', 'admin_pii', 'caller'];
const ADMIN_ROLES = ['super_admin', 'admin_pii'];

function principalFor(role) {
  return { name: role, role, is_admin: ADMIN_ROLES.includes(role) };
}

function App() {
  const [activeTab, setActiveTab] = useState('chatbot');
  const [alarms, setAlarms] = useState([]);
  const [sysStatus, setSysStatus] = useState('loading');

  // No login -- a role is just declared (see auth.py), defaulting to full access so
  // there's no friction opening the app. Switch roles from the picker below to see
  // what a more restricted role can and can't do.
  const [role, setRoleState] = useState(() => {
    const initialRole = getRole() || 'super_admin';
    persistRole(initialRole); // otherwise api.js's currentRole stays unset until the
    // picker is touched, so every request up to that point silently sends no X-Role
    // header at all and gets treated as the lowest-privileged role.
    return initialRole;
  });
  const principal = principalFor(role);

  const handleRoleChange = (newRole) => {
    persistRole(newRole);
    setRoleState(newRole);
  };

  useEffect(() => {
    fetchSystemStatus().then(data => setSysStatus(data.status));

    const interval = setInterval(() => {
      fetchAlarms().then(data => {
        if (data.alarms) setAlarms(data.alarms);
      }).catch(e => console.error(e));

      fetchSystemStatus().then(data => setSysStatus(data.status));
    }, 5000);

    return () => clearInterval(interval);
  }, []);

  return (
    <div className="app-container">
      <div className="header">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h1 style={{ margin: 0 }}>🛡️ Enterprise AI Governance v1.1</h1>
          <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
            <div style={{ backgroundColor: sysStatus === 'ready' ? '#dafbe1' : '#fff8c5', color: sysStatus === 'ready' ? '#1a7f37' : '#9a6700', padding: '0.4rem 0.8rem', borderRadius: '6px', display: 'flex', alignItems: 'center', gap: '0.5rem', boxShadow: '0 1px 3px rgba(0,0,0,0.1)', fontSize: '0.85rem', border: `1px solid ${sysStatus === 'ready' ? '#4ac26b' : '#d4a72c'}`, whiteSpace: 'nowrap' }}>
              <span style={{ fontSize: '1rem' }}>{sysStatus === 'ready' ? '🟢' : '🟠'}</span>
              <div style={{ whiteSpace: 'nowrap' }}>
                <strong>System Status:</strong> {sysStatus === 'ready' ? 'Live' : 'Offline, try after sometime'}
              </div>
            </div>
            <div style={{ visibility: alarms.length > 0 ? 'visible' : 'hidden', backgroundColor: '#cf222e', color: 'white', padding: '0.4rem 0.8rem', borderRadius: '6px', display: 'flex', alignItems: 'center', gap: '0.5rem', boxShadow: '0 2px 4px rgba(0,0,0,0.1)', fontSize: '0.85rem', whiteSpace: 'nowrap' }}>
              <span style={{ fontSize: '1rem' }}>🚨</span>
              <div>
                <strong>Alert:</strong> {alarms.length} pending Threat Detection{alarms.length > 1 ? 's' : ''}.
              </div>
            </div>
          </div>
        </div>

        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '1rem' }}>
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

          <div
            style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', background: '#f6f8fa', padding: '0.4rem 0.8rem', borderRadius: '6px', border: '1px solid #d0d7de', fontSize: '0.85rem', whiteSpace: 'nowrap' }}
            title="Self-declared -- no login, just a workflow role. See auth.py."
          >
            <span>👤 Acting as:</span>
            <select
              value={role}
              onChange={(e) => handleRoleChange(e.target.value)}
              style={{ fontSize: '0.85rem', padding: '0.15rem 0.3rem' }}
            >
              {ROLES.map((r) => (
                <option key={r} value={r}>{r}</option>
              ))}
            </select>
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
