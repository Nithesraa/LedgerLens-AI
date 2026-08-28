import { useState } from 'react';
import { useWorkflowData } from './hooks/useWorkflowData';
import { AppShell } from './components/AppShell';
import { OverviewPage } from './pages/OverviewPage';
import { CaseExplorerPage } from './pages/CaseExplorerPage';
import { CaseDetailPage } from './pages/CaseDetailPage';
import { AIInvestigationsPage } from './pages/AIInvestigationsPage';
import { PolicySafetyPage } from './pages/PolicySafetyPage';
import { AuditTrailPage } from './pages/AuditTrailPage';
import './App.css';

export type ViewState = 'overview' | 'explorer' | 'detail' | 'ai' | 'policy' | 'audit';

function App() {
  const { data, split, setSplit, loading, error } = useWorkflowData('dev');
  
  const [currentView, setCurrentView] = useState<ViewState>('overview');
  const [selectedCaseId, setSelectedCaseId] = useState<string | null>(null);

  const navigateTo = (view: ViewState, caseId?: string) => {
    setCurrentView(view);
    if (caseId !== undefined) {
      setSelectedCaseId(caseId);
    }
  };

  return (
    <AppShell 
      split={split} 
      onSplitChange={setSplit} 
      metadata={data?.run_metadata}
      currentView={currentView}
      onNavigate={navigateTo}
    >
      {loading && (
        <div className="state-container" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', gap: '16px' }}>
          <div className="loader"></div>
          <div style={{ color: 'var(--text-secondary)', fontSize: '1.125rem' }}>Loading workflow artifact for {split.toUpperCase()} dataset...</div>
        </div>
      )}

      {error && (
        <div className="state-container" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', gap: '16px' }}>
          <div style={{ fontSize: '3rem' }}>⚠️</div>
          <h2 style={{ color: 'var(--status-error)', margin: 0 }}>Unable to load workflow artifact</h2>
          <div style={{ color: 'var(--text-secondary)', maxWidth: '600px', textAlign: 'center' }}>
            Verify that the local static data artifact <code>{split}.json</code> exists in the <code>public/data/</code> directory and is valid JSON.
          </div>
        </div>
      )}

      {error && !loading && (
        <div className="state-container">
          <div style={{ color: 'var(--status-error)', marginBottom: '16px' }}>
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="10"></circle>
              <line x1="12" y1="8" x2="12" y2="12"></line>
              <line x1="12" y1="16" x2="12.01" y2="16"></line>
            </svg>
          </div>
          <h3>Failed to load data</h3>
          <p style={{ color: 'var(--text-secondary)', maxWidth: '400px', marginTop: '8px' }}>{error}</p>
        </div>
      )}

      {!loading && !error && data && currentView === 'overview' && (
        <OverviewPage data={data} onNavigateCase={(id) => navigateTo('detail', id)} />
      )}
      
      {!loading && !error && data && currentView === 'explorer' && (
        <CaseExplorerPage data={data} onNavigateCase={(id) => navigateTo('detail', id)} />
      )}
      
      {!loading && !error && data && currentView === 'detail' && selectedCaseId && (
        <CaseDetailPage 
          data={data} 
          caseId={selectedCaseId} 
          onBack={() => navigateTo('explorer')} 
        />
      )}
      
      {!loading && !error && data && currentView === 'ai' && (
        <AIInvestigationsPage data={data} onNavigateCase={(id) => navigateTo('detail', id)} />
      )}
      
      {!loading && !error && data && currentView === 'policy' && (
        <PolicySafetyPage data={data} onNavigateCase={(id) => navigateTo('detail', id)} />
      )}
      
      {!loading && !error && data && currentView === 'audit' && (
        <AuditTrailPage data={data} onNavigateCase={(id) => navigateTo('detail', id)} />
      )}
    </AppShell>
  );
}

export default App;
