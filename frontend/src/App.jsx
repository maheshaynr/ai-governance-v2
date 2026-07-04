import { useState } from 'react';
import Dashboard from './Dashboard';
import AdminConfig from './AdminConfig';

function App() {
  const [activeTab, setActiveTab] = useState('dashboard');

  return (
    <div className="app-container">
      <div className="header">
        <h1>🛡️ Enterprise AI Governance v1.0</h1>
        <div className="nav-tabs">
          <button 
            className={activeTab === 'dashboard' ? 'active' : ''} 
            onClick={() => setActiveTab('dashboard')}
          >
            Testing Dashboard
          </button>
          <button 
            className={activeTab === 'admin' ? 'active' : ''} 
            onClick={() => setActiveTab('admin')}
          >
            Admin Configuration
          </button>
        </div>
      </div>

      <main>
        {activeTab === 'dashboard' ? <Dashboard /> : <AdminConfig />}
      </main>
    </div>
  );
}

export default App;
