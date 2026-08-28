import React, { useState, useMemo } from 'react';
import type { WorkflowOutput } from '../types/workflow';
import { WorkflowAdapter } from '../adapters/WorkflowAdapter';

interface AuditTrailPageProps {
  data: WorkflowOutput;
  onNavigateCase: (id: string) => void;
}

export const AuditTrailPage: React.FC<AuditTrailPageProps> = ({ data, onNavigateCase }) => {
  const allCases = WorkflowAdapter.getCases(data);
  const totalEvents = data.audit_summary?.total_events || allCases.length;

  const [search, setSearch] = useState('');
  const [routeFilter, setRouteFilter] = useState('ALL');
  const [policyFilter, setPolicyFilter] = useState('ALL');
  const [executionFilter, setExecutionFilter] = useState('ALL');
  
  const [page, setPage] = useState(1);
  const pageSize = 25;

  const filteredCases = useMemo(() => {
    return allCases.filter(c => {
      if (search) {
        const s = search.toLowerCase().trim();
        const refMatch = c.operational_reference_id.toLowerCase().includes(s);
        const auditMatch = c.audit.audit_reference.toLowerCase().includes(s);
        if (!refMatch && !auditMatch) return false;
      }
      if (routeFilter !== 'ALL' && c.reconciliation.route !== routeFilter) return false;
      if (policyFilter !== 'ALL' && c.policy.decision !== policyFilter) return false;
      if (executionFilter !== 'ALL' && c.execution.status !== executionFilter) return false;
      return true;
    });
  }, [allCases, search, routeFilter, policyFilter, executionFilter]);

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
      <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', marginBottom: '24px' }}>
        <div>
          <h2 style={{ fontSize: '1.5rem', margin: '0 0 4px 0', fontWeight: 600 }}>Audit Trail</h2>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', margin: 0 }}>
            Audit records provide a read-only operational trace of reconciliation, policy, and simulated execution.
          </p>
        </div>
        <div style={{ textAlign: 'right' }}>
          <div className="meta-label">Total Events</div>
          <div className="mono-text" style={{ fontSize: '1.25rem', fontWeight: 700, color: 'var(--text-primary)' }}>
            {totalEvents.toLocaleString()}
          </div>
        </div>
      </header>

      <div className="safety-banner" style={{ marginBottom: '32px', backgroundColor: 'var(--bg-surface-elevated)', border: '1px solid var(--border-subtle)', borderLeft: '4px solid var(--text-secondary)' }}>
        <span className="safety-badge" style={{ backgroundColor: 'transparent', border: '1px solid var(--text-secondary)', color: 'var(--text-secondary)' }}>READ ONLY</span>
        <span className="safety-text" style={{ color: 'var(--text-primary)' }}>Audit records are informational. This UI cannot execute financial actions or alter history.</span>
      </div>

      <section className="surface-card">
        <div className="filter-bar" style={{ marginBottom: '24px' }}>
          <div className="filter-group" style={{ flex: 1.5 }}>
            <label className="meta-label">Search Audit or Operational Reference</label>
            <input 
              type="text" 
              className="search-input" 
              placeholder="e.g. AUDIT_... or RZP_..."
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
          <div className="state-container" style={{ padding: '48px 0', border: '1px dashed var(--border-strong)', borderRadius: 'var(--radius-lg)' }}>
            <div style={{ fontSize: '2rem', marginBottom: '16px', opacity: 0.5 }}>🔍</div>
            <h4 style={{ marginBottom: '8px', color: 'var(--text-primary)' }}>No matching audit records</h4>
          </div>
        ) : (
          <>
            <div className="meta-label" style={{ marginBottom: '12px' }}>
              Showing {((currentPage - 1) * pageSize) + 1}–{Math.min(currentPage * pageSize, filteredCases.length)} of {filteredCases.length} audit records
            </div>
            
            <div className="data-table-container">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Audit Reference</th>
                    <th>Operational Ref</th>
                    <th>Eval Date / Version</th>
                    <th>Route / Class</th>
                    <th>Policy / Action</th>
                    <th>Execution Status</th>
                  </tr>
                </thead>
                <tbody>
                  {paginatedCases.map((c) => (
                    <tr 
                      key={c.audit.audit_reference}
                      style={{ cursor: 'pointer' }}
                      onClick={() => onNavigateCase(c.operational_reference_id)}
                    >
                      <td className="mono-text" style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                        <div style={{ maxWidth: '150px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={c.audit.audit_reference}>
                          {c.audit.audit_reference}
                        </div>
                      </td>
                      <td className="mono-text" style={{ fontWeight: 600 }}>{c.operational_reference_id}</td>
                      <td style={{ fontSize: '0.8rem' }}>
                        <div className="mono-text">{data.run_metadata.evaluation_date}</div>
                        <div className="mono-text" style={{ color: 'var(--text-secondary)', marginTop: '2px' }}>v{c.policy.policy_version}</div>
                      </td>
                      <td style={{ fontSize: '0.8rem' }}>
                        <div style={{ fontWeight: c.reconciliation.route === 'AI_INVESTIGATOR' ? 600 : 400, color: c.reconciliation.route === 'AI_INVESTIGATOR' ? 'var(--status-warning)' : 'var(--text-primary)' }}>{c.reconciliation.route}</div>
                        <div style={{ color: 'var(--text-secondary)', marginTop: '2px' }}>
                          {c.investigation?.subtype || c.reconciliation.detected_issue || '—'}
                        </div>
                      </td>
                      <td style={{ fontSize: '0.8rem' }}>
                        <div><span className={`badge ${getPolicyBadge(c.policy.decision)}`}>{c.policy.decision}</span></div>
                        <div className="mono-text" style={{ marginTop: '4px', fontWeight: 600 }}>{c.policy.authorized_action}</div>
                      </td>
                      <td className="mono-text" style={{ fontSize: '0.8rem' }}>{c.execution.status}</td>
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
      </section>
    </div>
  );
};
