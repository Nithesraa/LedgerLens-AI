import React from 'react';
import type { SplitType } from '../hooks/useWorkflowData';
import type { ViewState } from '../App';

interface AppShellProps {
  children: React.ReactNode;
  split: SplitType;
  onSplitChange: (split: SplitType) => void;
  metadata?: { evaluation_date: string };
  currentView: ViewState;
  onNavigate: (view: ViewState, caseId?: string) => void;
}

export const AppShell: React.FC<AppShellProps> = ({ 
  children, split, onSplitChange, metadata, currentView, onNavigate 
}) => {
  const getPageTitle = () => {
    switch (currentView) {
      case 'overview': return 'Overview';
      case 'explorer': return 'Case Explorer';
      case 'detail': return 'Case Detail';
      case 'ai': return 'AI Investigations';
      case 'policy': return 'Policy & Safety';
      case 'audit': return 'Audit Trail';
      default: return '';
    }
  };

  return (
    <div className="app-layout">
      
      <aside className="app-sidebar">
        <div className="sidebar-brand">
          <h1>LedgerLens</h1>
          <p>AI Controller</p>
        </div>
        
        <nav className="sidebar-nav">
          <div 
            className={`nav-item ${currentView === 'overview' ? 'active' : ''}`}
            onClick={() => onNavigate('overview')}
          >
            Overview
          </div>
          <div 
            className={`nav-item ${currentView === 'explorer' || currentView === 'detail' ? 'active' : ''}`}
            onClick={() => onNavigate('explorer')}
          >
            Cases
          </div>
          <div 
            className={`nav-item ${currentView === 'ai' ? 'active' : ''}`}
            onClick={() => onNavigate('ai')}
          >
            AI Investigations
          </div>
          <div 
            className={`nav-item ${currentView === 'policy' ? 'active' : ''}`}
            onClick={() => onNavigate('policy')}
          >
            Policy & Safety
          </div>
          <div 
            className={`nav-item ${currentView === 'audit' ? 'active' : ''}`}
            onClick={() => onNavigate('audit')}
          >
            Audit Trail
          </div>
        </nav>

        <div className="sidebar-footer">
          <div className="dataset-selector">
            <div className="meta-label">DATASET</div>
            <select 
              className="split-selector"
              value={split} 
              onChange={(e) => onSplitChange(e.target.value as SplitType)}
            >
              <option value="dev">DEV</option>
              <option value="validation">VALIDATION</option>
              <option value="holdout">HOLDOUT</option>
            </select>
          </div>
          {metadata && (
            <div>
              <div className="meta-label">EVALUATION DATE</div>
              <div className="mono-text" style={{ color: 'var(--text-secondary)', marginTop: '4px' }}>
                {metadata.evaluation_date}
              </div>
            </div>
          )}
        </div>
      </aside>
      
      <div className="app-content">
        <header className="app-topbar">
          <div className="topbar-title">
            <h2>{getPageTitle()}</h2>
          </div>
          <div className="topbar-controls">
            <div className="simulation-indicator" title="No real financial actions are executed. All actions shown are simulated.">
              SIMULATION MODE
            </div>
          </div>
        </header>
        
        <main className="main-scroll">
          {children}
        </main>
      </div>
      
    </div>
  );
};
