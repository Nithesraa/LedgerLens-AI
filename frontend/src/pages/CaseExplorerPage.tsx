import React, { useState, useMemo } from 'react';
import type { WorkflowOutput } from '../types/workflow';
import { WorkflowAdapter } from '../adapters/WorkflowAdapter';

interface CaseExplorerPageProps {
  data: WorkflowOutput;
  onNavigateCase: (id: string) => void;
}

export const CaseExplorerPage: React.FC<CaseExplorerPageProps> = ({ data, onNavigateCase }) => {
  const allCases = WorkflowAdapter.getCases(data);
  const totalCases = allCases.length;

  const [search, setSearch] = useState('');
  const [routeFilter, setRouteFilter] = useState('ALL');
  const [classFilter, setClassFilter] = useState('ALL');
  const [policyFilter, setPolicyFilter] = useState('ALL');
  const [executionFilter, setExecutionFilter] = useState('ALL');
  
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);

  const filteredCases = useMemo(() => {
    return allCases.filter(c => {
      if (search && !c.operational_reference_id.toLowerCase().includes(search.toLowerCase().trim())) {
        return false;
      }
      if (routeFilter !== 'ALL' && c.reconciliation.route !== routeFilter) {
        return false;
      }
      if (classFilter !== 'ALL') {
        const cClass = c.investigation?.subtype || c.reconciliation.detected_issue;
        if (cClass !== classFilter) return false;
      }
      if (policyFilter !== 'ALL' && c.policy.decision !== policyFilter) {
        return false;
      }
      if (executionFilter !== 'ALL' && c.execution.status !== executionFilter) {
        return false;
      }
      return true;
    });
  }, [allCases, search, routeFilter, classFilter, policyFilter, executionFilter]);

  const totalPages = Math.ceil(filteredCases.length / pageSize) || 1;
  const currentPage = Math.min(page, totalPages);
  
  const paginatedCases = useMemo(() => {
    const start = (currentPage - 1) * pageSize;
    return filteredCases.slice(start, start + pageSize);
  }, [filteredCases, currentPage, pageSize]);

  // Derive available filter options from the current dataset dynamically
  const availableClassifications = useMemo(() => {
    const set = new Set<string>();
    allCases.forEach(c => {
      const cls = c.investigation?.subtype || c.reconciliation.detected_issue;
      if (cls) set.add(cls);
    });
    return Array.from(set).sort();
  }, [allCases]);

  const clearFilters = () => {
    setSearch('');
    setRouteFilter('ALL');
    setClassFilter('ALL');
    setPolicyFilter('ALL');
    setExecutionFilter('ALL');
    setPage(1);
  };

  const getPolicyBadge = (decision: string) => {
    if (decision === 'ALLOW') return 'badge-success';
    if (decision === 'ESCALATE' || decision === 'DENY') return 'badge-error';
    return 'badge-warning';
  };

  return (
    <div className="dashboard-container" style={{ maxWidth: '100%' }}>
      <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', marginBottom: '16px' }}>
        <div>
          <h2 style={{ fontSize: '1.5rem', margin: '0 0 4px 0', fontWeight: 600 }}>Case Explorer</h2>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', margin: 0 }}>
            Filter and inspect reconciliation cases across the decision pipeline.
          </p>
        </div>
        <div style={{ textAlign: 'right' }}>
          <div className="meta-label">Total Cases</div>
          <div className="mono-text" style={{ fontSize: '1.25rem', fontWeight: 700, color: 'var(--text-primary)' }}>
            {totalCases.toLocaleString()}
          </div>
        </div>
      </header>

      <div className="filter-bar">
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

        <div className="filter-group" style={{ flex: 1.5 }}>
          <label className="meta-label">Classification</label>
          <select className="search-input" value={classFilter} onChange={e => { setClassFilter(e.target.value); setPage(1); }}>
            <option value="ALL">All Classifications</option>
            {availableClassifications.map(c => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>

        <div className="filter-group">
          <label className="meta-label">Policy Decision</label>
          <select className="search-input" value={policyFilter} onChange={e => { setPolicyFilter(e.target.value); setPage(1); }}>
            <option value="ALL">All Decisions</option>
            <option value="ALLOW">ALLOW</option>
            <option value="DENY">DENY</option>
            <option value="MONITOR">MONITOR</option>
            <option value="ESCALATE">ESCALATE</option>
          </select>
        </div>

        <div className="filter-group">
          <label className="meta-label">Execution Status</label>
          <select className="search-input" value={executionFilter} onChange={e => { setExecutionFilter(e.target.value); setPage(1); }}>
            <option value="ALL">All Statuses</option>
            <option value="SIMULATED_EXECUTED">SIMULATED_EXECUTED</option>
            <option value="ESCALATED">ESCALATED</option>
            <option value="MONITORING">MONITORING</option>
            <option value="DUPLICATE_SUPPRESSED">DUPLICATE_SUPPRESSED</option>
            <option value="FAILED_SAFE">FAILED_SAFE</option>
          </select>
        </div>
      </div>

      {filteredCases.length === 0 ? (
        <div className="state-container" style={{ padding: '64px 0', border: '1px dashed var(--border-strong)', borderRadius: 'var(--radius-lg)' }}>
          <div style={{ fontSize: '2rem', marginBottom: '16px', opacity: 0.5 }}>🔍</div>
          <h3 style={{ marginBottom: '8px', color: 'var(--text-primary)' }}>No matching cases</h3>
          <p style={{ marginBottom: '24px', fontSize: '0.85rem' }}>Try adjusting your filters to find what you're looking for.</p>
          <button 
            className="pagination-btn" 
            style={{ backgroundColor: 'var(--bg-hover)', color: 'var(--text-primary)' }}
            onClick={clearFilters}
          >
            Clear All Filters
          </button>
        </div>
      ) : (
        <>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
            <div className="meta-label">
              Showing {((currentPage - 1) * pageSize) + 1}–{Math.min(currentPage * pageSize, filteredCases.length)} of {filteredCases.length} cases
            </div>
            <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
              <span className="meta-label">Per page:</span>
              <select className="search-input" style={{ padding: '4px 8px', width: 'auto' }} value={pageSize} onChange={e => { setPageSize(Number(e.target.value)); setPage(1); }}>
                <option value={25}>25</option>
                <option value={50}>50</option>
                <option value={100}>100</option>
              </select>
            </div>
          </div>

          <div className="data-table-container">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Reference</th>
                  <th>Route</th>
                  <th>Classification</th>
                  <th>Confidence</th>
                  <th>Decision</th>
                  <th>Execution Status</th>
                </tr>
              </thead>
              <tbody>
                {paginatedCases.map((c) => (
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
                    <td>{c.investigation?.subtype || c.reconciliation.detected_issue || '—'}</td>
                    <td className="mono-text">
                      {c.investigation?.confidence_score !== undefined && c.investigation?.confidence_score !== null 
                        ? `${(c.investigation.confidence_score * 100).toFixed(1)}%` 
                        : '—'
                      }
                    </td>
                    <td>
                      <span className={`badge ${getPolicyBadge(c.policy.decision)}`}>
                        {c.policy.decision}
                      </span>
                    </td>
                    <td className="mono-text">{c.execution.status}</td>
                  </tr>
                ))}
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
    </div>
  );
};
