import React, { useState, useMemo } from 'react';
import type { WorkflowOutput } from '../types/workflow';
import { WorkflowAdapter } from '../adapters/WorkflowAdapter';

interface PolicySafetyPageProps {
  data: WorkflowOutput;
  onNavigateCase: (id: string) => void;
}

export const PolicySafetyPage: React.FC<PolicySafetyPageProps> = ({ data, onNavigateCase }) => {
  const allCases = WorkflowAdapter.getCases(data);
  const summary = WorkflowAdapter.getSummary(data);

  const [search, setSearch] = useState('');
  const [routeFilter, setRouteFilter] = useState('ALL');
  const [policyFilter, setPolicyFilter] = useState('ALL');
  const [actionFilter, setActionFilter] = useState('ALL');
  
  const [page, setPage] = useState(1);
  const pageSize = 25;

  const overrideCases = useMemo(() => {
    return allCases.filter(c => 
      c.reconciliation.route === 'AI_INVESTIGATOR' && 
      c.investigation?.recommended_action !== c.policy.authorized_action
    );
  }, [allCases]);

  const overrideCase = overrideCases.length > 0 ? overrideCases[0] : null;

  const filteredCases = useMemo(() => {
    return allCases.filter(c => {
      if (search && !c.operational_reference_id.toLowerCase().includes(search.toLowerCase().trim())) {
        return false;
      }
      if (routeFilter !== 'ALL' && c.reconciliation.route !== routeFilter) return false;
      if (policyFilter !== 'ALL' && c.policy.decision !== policyFilter) return false;
      if (actionFilter !== 'ALL' && c.policy.authorized_action !== actionFilter) return false;
      return true;
    });
  }, [allCases, search, routeFilter, policyFilter, actionFilter]);

  const availableActions = useMemo(() => {
    const set = new Set<string>();
    allCases.forEach(c => set.add(c.policy.authorized_action));
    return Array.from(set).sort();
  }, [allCases]);

  const totalPages = Math.ceil(filteredCases.length / pageSize) || 1;
  const currentPage = Math.min(page, totalPages);
  
  const paginatedCases = useMemo(() => {
    const start = (currentPage - 1) * pageSize;
    return filteredCases.slice(start, start + pageSize);
  }, [filteredCases, currentPage, pageSize]);

  const getPolicyBadge = (decision: string) => {
    if (decision === 'ALLOW') return 'badge-success';
    if (decision === 'ESCALATE' || decision === 'DENY') return 'badge-error';
    return 'badge-warning';
  };

  return (
    <div className="dashboard-container">
      <header style={{ marginBottom: '24px' }}>
        <h2 style={{ fontSize: '1.5rem', margin: '0 0 4px 0', fontWeight: 600 }}>Policy & Safety</h2>
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', margin: 0 }}>
          The Policy Engine is the authoritative safety boundary. AI recommendations cannot bypass it.
        </p>
      </header>

      <section className="surface-card" style={{ marginBottom: '32px', backgroundColor: 'var(--bg-app)', borderLeft: '4px solid var(--accent-brand)' }}>
        <h3 className="section-title" style={{ color: 'var(--accent-brand)', marginBottom: '8px' }}>Safety Principles</h3>
        <p style={{ fontSize: '0.95rem', fontWeight: 600, color: 'var(--text-primary)', margin: '0 0 4px 0' }}>
          AI recommendations are advisory. The Policy Engine is authoritative.
        </p>
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', margin: 0 }}>
          An AI recommendation can never bypass deterministic policy controls.
        </p>
      </section>

      <section className="kpi-grid" style={{ marginBottom: '32px' }}>
        <div className="surface-card kpi-card">
          <div className="kpi-title">ALLOW</div>
          <div className="kpi-value" style={{ color: 'var(--status-success)' }}>{summary.policy.ALLOW}</div>
          <div className="kpi-supporting">Execution permitted</div>
        </div>
        <div className="surface-card kpi-card">
          <div className="kpi-title">MONITOR</div>
          <div className="kpi-value" style={{ color: 'var(--status-warning)' }}>{summary.policy.MONITOR}</div>
          <div className="kpi-supporting">Execution permitted with log</div>
        </div>
        <div className="surface-card kpi-card">
          <div className="kpi-title">ESCALATE</div>
          <div className="kpi-value" style={{ color: 'var(--status-error)' }}>{summary.policy.ESCALATE}</div>
          <div className="kpi-supporting">Requires human attention</div>
        </div>
        <div className="surface-card kpi-card">
          <div className="kpi-title">DENY</div>
          <div className="kpi-value" style={{ color: 'var(--status-error)' }}>{summary.policy.DENY}</div>
          <div className="kpi-supporting">Execution blocked</div>
        </div>
      </section>

      <section className="surface-card" style={{ marginBottom: '32px' }}>
        <h3 className="section-title">AI Safety Override</h3>
        
        {overrideCase ? (
          <div>
            <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '16px' }}>
              The following case demonstrates the deterministic safety boundary overriding an AI recommendation.
            </p>
            <div 
              className="override-box hover-card"
              style={{ cursor: 'pointer', transition: 'all 0.2s', padding: '24px' }}
              onClick={() => onNavigateCase(overrideCase.operational_reference_id)}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
                <div className="mono-text" style={{ fontSize: '1.25rem', fontWeight: 700, color: 'var(--text-primary)' }}>{overrideCase.operational_reference_id}</div>
                <div className="badge badge-error">OVERRIDE DEMONSTRATION</div>
              </div>
              
              <div className="override-flow">
                <div style={{ flex: 1, backgroundColor: 'rgba(0,0,0,0.3)', padding: '16px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)' }}>
                  <div className="meta-label">AI Recommendation</div>
                  <div className="mono-text" style={{ fontWeight: 600, marginTop: '8px', fontSize: '1.125rem' }}>{overrideCase.investigation?.recommended_action}</div>
                </div>
                <div style={{ color: 'var(--status-error)', fontSize: '1.5rem', fontWeight: 'bold' }}>&rarr;</div>
                <div style={{ flex: 1.5, backgroundColor: 'var(--bg-app)', padding: '16px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--status-error)' }}>
                  <div className="meta-label" style={{ color: 'var(--status-error)' }}>Deterministic Policy Engine</div>
                  <div className="mono-text" style={{ fontWeight: 700, marginTop: '8px', color: 'var(--status-error)', fontSize: '1.25rem' }}>{overrideCase.policy.decision}</div>
                  <div style={{ fontSize: '0.75rem', color: 'var(--status-error)', marginTop: '8px' }}>{overrideCase.policy.reason}</div>
                </div>
                <div style={{ color: 'var(--status-error)', fontSize: '1.5rem', fontWeight: 'bold' }}>&rarr;</div>
                <div style={{ flex: 1, backgroundColor: 'rgba(0,0,0,0.3)', padding: '16px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)' }}>
                  <div className="meta-label">Final Authorized Action</div>
                  <div className="mono-text" style={{ fontWeight: 600, marginTop: '8px', fontSize: '1.125rem' }}>{overrideCase.policy.authorized_action}</div>
                </div>
              </div>
              <div style={{ marginTop: '24px', backgroundColor: 'var(--bg-app)', padding: '16px', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
                <h4 style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', margin: '0 0 12px 0', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Failing Policy Gates</h4>
                <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                  {Object.entries(overrideCase.policy.gates)
                    .filter(([_, passed]) => !passed)
                    .map(([gate]) => (
                      <span key={gate} className="badge badge-error" style={{ fontFamily: 'var(--font-mono)', letterSpacing: 0, textTransform: 'none' }}>{gate}</span>
                  ))}
                </div>
              </div>
            </div>
          </div>
        ) : (
          <div className="state-container" style={{ padding: '32px', border: '1px dashed var(--border-strong)', borderRadius: 'var(--radius-lg)' }}>
            <h4 style={{ color: 'var(--text-primary)', marginBottom: '8px', fontSize: '1.1rem' }}>No AI policy overrides in this dataset.</h4>
            <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
              All AI recommendations matched the deterministic policy boundaries.
            </p>
          </div>
        )}
      </section>

      <section className="surface-card">
        <h3 className="section-title">Policy Explorer</h3>
        
        <div className="filter-bar" style={{ marginBottom: '24px' }}>
          <div className="filter-group" style={{ flex: 1.5 }}>
            <label className="meta-label">Search Reference</label>
            <input 
              type="text" 
              className="search-input" 
              placeholder="e.g. RZP_HOLDOUT_000048"
              value={search}
              onChange={e => { setSearch(e.target.value); setPage(1); }}
            />
          </div>
          <div className="filter-group">
            <label className="meta-label">Route</label>
            <select className="search-input" value={routeFilter} onChange={e => { setRouteFilter(e.target.value); setPage(1); }}>
              <option value="ALL">All Routes</option>
              <option value="DETERMINISTIC">Deterministic</option>
              <option value="AI_INVESTIGATOR">AI Investigator</option>
            </select>
          </div>
          <div className="filter-group">
            <label className="meta-label">Decision</label>
            <select className="search-input" value={policyFilter} onChange={e => { setPolicyFilter(e.target.value); setPage(1); }}>
              <option value="ALL">All Decisions</option>
              <option value="ALLOW">ALLOW</option>
              <option value="DENY">DENY</option>
              <option value="MONITOR">MONITOR</option>
              <option value="ESCALATE">ESCALATE</option>
            </select>
          </div>
          <div className="filter-group">
            <label className="meta-label">Authorized Action</label>
            <select className="search-input" value={actionFilter} onChange={e => { setActionFilter(e.target.value); setPage(1); }}>
              <option value="ALL">All Actions</option>
              {availableActions.map(a => <option key={a} value={a}>{a}</option>)}
            </select>
          </div>
        </div>

        {filteredCases.length === 0 ? (
          <div className="state-container" style={{ padding: '48px 0', border: '1px dashed var(--border-strong)', borderRadius: 'var(--radius-lg)' }}>
            <div style={{ fontSize: '2rem', marginBottom: '16px', opacity: 0.5 }}>🔍</div>
            <h4 style={{ marginBottom: '8px', color: 'var(--text-primary)' }}>No matching cases</h4>
          </div>
        ) : (
          <>
            <div className="meta-label" style={{ marginBottom: '12px' }}>
              Showing {((currentPage - 1) * pageSize) + 1}–{Math.min(currentPage * pageSize, filteredCases.length)} of {filteredCases.length} policy decisions
            </div>
            
            <div className="data-table-container">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Reference</th>
                    <th>Route</th>
                    <th>Policy Decision</th>
                    <th>Authorized Action</th>
                    <th>Policy Gates Passed</th>
                  </tr>
                </thead>
                <tbody>
                  {paginatedCases.map((c) => {
                    const totalGates = Object.keys(c.policy.gates).length;
                    const passedGates = Object.values(c.policy.gates).filter(Boolean).length;
                    
                    return (
                      <tr 
                        key={c.operational_reference_id}
                        style={{ cursor: 'pointer' }}
                        onClick={() => onNavigateCase(c.operational_reference_id)}
                      >
                        <td className="mono-text" style={{ fontWeight: 600 }}>{c.operational_reference_id}</td>
                        <td>
                          <span className={`badge ${c.reconciliation.route === 'AI_INVESTIGATOR' ? 'badge-warning' : 'badge-info'}`}>
                            {c.reconciliation.route === 'AI_INVESTIGATOR' ? 'AI' : 'DET'}
                          </span>
                        </td>
                        <td>
                          <span className={`badge ${getPolicyBadge(c.policy.decision)}`}>
                            {c.policy.decision}
                          </span>
                        </td>
                        <td className="mono-text" style={{ fontWeight: 600 }}>{c.policy.authorized_action}</td>
                        <td className="mono-text" style={{ color: passedGates === totalGates ? 'var(--status-success)' : 'var(--status-error)' }}>
                          {passedGates} / {totalGates}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            <div className="pagination-controls">
              <button 
                className="pagination-btn" 
                disabled={currentPage === 1}
                onClick={() => setPage(p => Math.max(1, p - 1))}
              >
                &larr; Previous
              </button>
              <div className="meta-label" style={{ color: 'var(--text-secondary)' }}>
                Page {currentPage} of {totalPages}
              </div>
              <button 
                className="pagination-btn" 
                disabled={currentPage === totalPages}
                onClick={() => setPage(p => Math.min(totalPages, p + 1))}
              >
                Next &rarr;
              </button>
            </div>
          </>
        )}
      </section>
    </div>
  );
};
;
