import { useState, useEffect } from 'react';
import Dashboard from './Dashboard';
import AdminConfig from './AdminConfig';
import AnalyticsDashboard from './AnalyticsDashboard';
import ChatBot from './ChatBot';
import { fetchAlarms, fetchSystemStatus } from './api';

function App() {
  const [activeTab, setActiveTab] = useState('chatbot');
  const [alarms, setAlarms] = useState([]);
  const [sysStatus, setSysStatus] = useState('loading');

  useEffect(() => {
    // Initial fetch for system status
    fetchSystemStatus().then(data => setSysStatus(data.status));

    // Poll for background alarms every 5 seconds
    const interval = setInterval(() => {
      fetchAlarms().then(data => {
        if (data.alarms) {
          setAlarms(data.alarms);
        }
      }).catch(e => console.error(e));

      // Poll system status
      fetchSystemStatus().then(data => setSysStatus(data.status));
    }, 5000);

    return () => clearInterval(interval);
  }, []);

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
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem', alignItems: 'flex-end' }}>
          <div style={{ visibility: alarms.length > 0 ? 'visible' : 'hidden', backgroundColor: '#cf222e', color: 'white', padding: '0.4rem 0.8rem', borderRadius: '6px', display: 'flex', alignItems: 'center', gap: '0.5rem', boxShadow: '0 2px 4px rgba(0,0,0,0.1)', fontSize: '0.85rem' }}>
            <span style={{ fontSize: '1rem' }}>🚨</span>
            <div>
              <strong>Alert:</strong> {alarms.length} pending Threat Detection{alarms.length > 1 ? 's' : ''}.
            </div>
          </div>

          <div style={{ backgroundColor: sysStatus === 'ready' ? '#dafbe1' : '#fff8c5', color: sysStatus === 'ready' ? '#1a7f37' : '#9a6700', padding: '0.4rem 0.8rem', borderRadius: '6px', display: 'flex', alignItems: 'center', gap: '0.5rem', boxShadow: '0 1px 3px rgba(0,0,0,0.1)', fontSize: '0.85rem', border: `1px solid ${sysStatus === 'ready' ? '#4ac26b' : '#d4a72c'}` }}>
            <span style={{ fontSize: '1rem' }}>{sysStatus === 'ready' ? '🟢' : '🟠'}</span>
            <div>
              <strong>System Status:</strong> {sysStatus === 'ready' ? 'Live' : 'Offline, try after sometime'}
            </div>
          </div>
        </div>
      </div>

      <main>
        {activeTab === 'dashboard' && <Dashboard />}
        {activeTab === 'chatbot' && <ChatBot />}
        {activeTab === 'analytics' && <AnalyticsDashboard />}
        {activeTab === 'admin' && <AdminConfig />}
      </main>
    </div>
  );
}

export default App;
