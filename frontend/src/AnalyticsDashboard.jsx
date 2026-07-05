import { useState, useEffect } from 'react';
import { fetchAnalytics } from './api';
import { 
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip, Legend, 
  LineChart, Line, ResponsiveContainer, PieChart, Pie, Cell 
} from 'recharts';

export default function AnalyticsDashboard() {
  const [timeframe, setTimeframe] = useState('24h');
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState({
    metrics: { total_requests: 0, total_alarms: 0, resolved: 0, dismissed: 0, pending: 0 },
    category_data: [],
    trend_data: []
  });

  const loadData = async () => {
    setLoading(true);
    try {
      const res = await fetchAnalytics(timeframe);
      if (res.status === 'success') {
        setData({
          metrics: res.metrics,
          category_data: res.category_data,
          trend_data: res.trend_data
        });
      } else {
        alert("Failed to load analytics: " + res.message);
      }
    } catch (e) {
      console.error(e);
      alert("Failed to connect to backend for analytics.");
    } finally {
      setLoading(false);
    }
  };

  // Load initial data
  useEffect(() => {
    loadData();
  }, [timeframe]);

  const COLORS = ['#8b5cf6', '#0969da', '#1a7f37', '#9a6700', '#cf222e'];
  
  const statusData = [
    { name: 'Pending', value: data.metrics.pending },
    { name: 'Resolved', value: data.metrics.resolved },
    { name: 'Dismissed', value: data.metrics.dismissed }
  ];
  const STATUS_COLORS = ['#cf222e', '#1a7f37', '#57606a'];
  
  const healthScore = data.metrics.total_requests > 0 
    ? Math.max(0, 100 - (data.metrics.total_alarms / data.metrics.total_requests * 100)).toFixed(2)
    : 100.00;

  return (
    <div className="admin-layout" style={{ marginTop: '1rem', flexDirection: 'column' }}>
      
      {/* Top Header & Controls */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '2rem' }}>
        <h2>📈 Security Analytics & Metrics</h2>
        
        <div style={{ display: 'flex', gap: '1rem', alignItems: 'center' }}>
          <select 
            value={timeframe} 
            onChange={(e) => setTimeframe(e.target.value)}
            style={{ padding: '0.5rem', borderRadius: '6px', border: '1px solid #d0d7de', fontSize: '1rem' }}
          >
            <option value="24h">Last 24 Hours</option>
            <option value="7d">Last 7 Days</option>
            <option value="30d">Last 30 Days</option>
            <option value="90d">Last 3 Months</option>
            <option value="all">All Time</option>
          </select>
          <button 
            className="primary" 
            onClick={loadData} 
            disabled={loading}
            style={{ padding: '0.5rem 1.5rem', fontSize: '1rem' }}
          >
            {loading ? '⏳ Loading...' : '🔄 Run Query / Refresh'}
          </button>
        </div>
      </div>

      {/* KPI Cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '1.5rem', marginBottom: '2rem' }}>
        <div className="card" style={{ textAlign: 'center' }}>
          <div style={{ fontSize: '2.5rem', fontWeight: 'bold', color: '#0969da' }}>{data.metrics.total_requests}</div>
          <div style={{ color: '#57606a', fontWeight: '600' }}>Total Processed</div>
        </div>
        <div className="card" style={{ textAlign: 'center' }}>
          <div style={{ fontSize: '2.5rem', fontWeight: 'bold', color: '#cf222e' }}>{data.metrics.total_alarms}</div>
          <div style={{ color: '#57606a', fontWeight: '600' }}>Alarms Triggered</div>
        </div>
        <div className="card" style={{ textAlign: 'center' }}>
          <div style={{ fontSize: '2.5rem', fontWeight: 'bold', color: '#1a7f37' }}>{data.metrics.resolved}</div>
          <div style={{ color: '#57606a', fontWeight: '600' }}>Alarms Resolved</div>
        </div>
        <div className="card" style={{ textAlign: 'center' }}>
          <div style={{ fontSize: '2.5rem', fontWeight: 'bold', color: healthScore < 95 ? '#cf222e' : '#1a7f37' }}>
            {healthScore}%
          </div>
          <div style={{ color: '#57606a', fontWeight: '600' }}>System Health Score</div>
        </div>
      </div>

      {/* Charts Grid */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.5rem' }}>
        
        {/* Category Breakdown */}
        <div className="card">
          <h3>Alarm Categories</h3>
          <div style={{ height: '300px' }}>
            {data.category_data.length === 0 ? (
              <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#57606a' }}>No alarms in this timeframe.</div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={data.category_data} layout="vertical" margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis type="number" />
                  <YAxis dataKey="name" type="category" width={120} />
                  <RechartsTooltip />
                  <Bar dataKey="value" fill="#8b5cf6" radius={[0, 4, 4, 0]}>
                    {data.category_data.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>

        {/* Status Breakdown */}
        <div className="card">
          <h3>Alarm Resolution Status</h3>
          <div style={{ height: '300px' }}>
             {data.metrics.total_alarms === 0 ? (
              <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#57606a' }}>No alarms in this timeframe.</div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={statusData}
                    cx="50%"
                    cy="50%"
                    innerRadius={60}
                    outerRadius={100}
                    paddingAngle={5}
                    dataKey="value"
                    label={({name, percent}) => `${name} ${(percent * 100).toFixed(0)}%`}
                  >
                    {statusData.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={STATUS_COLORS[index % STATUS_COLORS.length]} />
                    ))}
                  </Pie>
                  <RechartsTooltip />
                </PieChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>
        
        {/* Trend Analysis - Full Width */}
        <div className="card" style={{ gridColumn: '1 / -1' }}>
          <h3>Traffic & Alarm Trends</h3>
          <div style={{ height: '350px' }}>
            {data.trend_data.length === 0 ? (
              <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#57606a' }}>No traffic in this timeframe.</div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={data.trend_data} margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="date" />
                  <YAxis />
                  <RechartsTooltip />
                  <Legend />
                  <Line type="monotone" dataKey="requests" stroke="#0969da" strokeWidth={3} name="Total Requests" activeDot={{ r: 8 }} />
                  <Line type="monotone" dataKey="alarms" stroke="#cf222e" strokeWidth={3} name="Alarms Triggered" />
                </LineChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>

      </div>
    </div>
  );
}
