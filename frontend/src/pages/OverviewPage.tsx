import React, { useMemo } from 'react';
import type { WorkflowOutput } from '../types/workflow';
import { WorkflowAdapter } from '../adapters/WorkflowAdapter';

export const OverviewPage: React.FC<{ data: WorkflowOutput, onNavigateCase: (id: string) => void }> = ({ data, onNavigateCase }) => {
  const summary = WorkflowAdapter.getSummary(data);
  const demoCases = WorkflowAdapter.getDemoCases(data);
  const allCases = WorkflowAdapter.getCases(data);

  // Find a case where AI was overridden by policy for the highlight story
  const overrideCase = useMemo(() => {
    return allCases.find(c => 
      c.reconciliation.route === 'AI_INVESTIGATOR' && 
      c.investigation?.recommended_action !== c.policy.authorized_action
    );
  }, [allCases]);

  const renderDist = (label: string, count: number, total: number) => {
    const pct = total > 0 ? (count / total) * 100 : 0;
    return (
      <div className="dist-row" key={label}>
        <div className="dist-label">{label.replace(/_/g, ' ')}</div>
        <div className="dist-bar-bg">
          <div className="dist-bar-fill" style={{ width: `${pct}%` }}></div>
        </div>
        <div className="dist-value">
          {count} <span style={{ color: 'var(--text-muted)' }}>({pct.toFixed(0)}%)</span>
        </div>
      </div>
    );
  };

  const getPolicyBadge = (decision: string) => {
    if (decision === 'ALLOW') return 'badge-success';
    if (decision === 'ESCALATE' || decision === 'DENY') return 'badge-error';
    return 'badge-warning';
  };

  return (
    <div className="dashboard-container">
      
      {/* 1. HERO PIPELINE */}
      <section className="pipeline-story-hero">
        <div className="pipeline-node">
          <div className="pipeline-box">
            <div className="pipeline-box-title">Total Cases</div>
            <div className="pipeline-box-value">{summary.total_cases.toLocaleString()}</div>
          </div>
          <div className="pipeline-connector" style={{ transform: 'rotate(90deg)', margin: '20px 0', width: '2px', height: '40px' }}></div>
          
          <div style={{ display: 'flex', gap: '32px', width: '100%', justifyContent: 'center' }}>
            <div className="pipeline-box" style={{ flex: 1, borderColor: 'var(--status-info)' }}>
              <div className="pipeline-box-title" style={{ color: 'var(--status-info)' }}>Deterministic Engine</div>
              <div className="pipeline-box-value">{summary.deterministic_cases.toLocaleString()}</div>
              <div style={{ fontSize: '0.65rem', color: 'var(--text-secondary)', marginTop: '4px' }}>
                {((summary.deterministic_cases / summary.total_cases) * 100).toFixed(1)}% AUTO-RESOLVED
              </div>
            </div>
            <div className="pipeline-box" style={{ flex: 1, borderColor: 'var(--status-warning)' }}>
              <div className="pipeline-box-title" style={{ color: 'var(--status-warning)' }}>AI Investigator</div>
              <div className="pipeline-box-value">{summary.ai_cases.toLocaleString()}</div>
              <div style={{ fontSize: '0.65rem', color: 'var(--text-secondary)', marginTop: '4px' }}>
                {((summary.ai_cases / summary.total_cases) * 100).toFixed(1)}% EXCEPTIONS
              </div>
            </div>
          </div>

          <div className="pipeline-connector" style={{ transform: 'rotate(90deg)', margin: '20px 0', width: '2px', height: '40px' }}></div>
          <div className="pipeline-box" style={{ width: '100%', borderColor: 'var(--accent-brand)', backgroundColor: 'var(--accent-brand-subtle)' }}>
            <div className="pipeline-box-title" style={{ color: 'var(--accent-brand)' }}>Policy Engine</div>
            <div className="pipeline-box-value" style={{ fontSize: '1rem' }}>AUTHORITATIVE BOUNDARY</div>
          </div>

          <div className="pipeline-connector" style={{ transform: 'rotate(90deg)', margin: '20px 0', width: '2px', height: '40px' }}></div>
          <div className="pipeline-box" style={{ width: '100%' }}>
            <div className="pipeline-box-title">Simulated Action</div>
            <div className="pipeline-box-value" style={{ fontSize: '1rem', color: 'var(--text-secondary)' }}>NO MONEY MOVEMENT</div>
          </div>

          <div className="pipeline-connector" style={{ transform: 'rotate(90deg)', margin: '20px 0', width: '2px', height: '40px' }}></div>
          <div className="pipeline-box" style={{ width: '100%' }}>
            <div className="pipeline-box-title">Audit Trail</div>
            <div className="pipeline-box-value" style={{ fontSize: '1rem', color: 'var(--text-secondary)' }}>IMMUTABLE RECORD</div>
          </div>
        </div>
      </section>

      {/* 2. KPI GRID */}
      <section className="kpi-grid">
        <div className="surface-card kpi-card">
          <div className="kpi-title">Total Processed</div>
          <div className="kpi-value">{summary.total_cases.toLocaleString()}</div>
          <div className="kpi-supporting">Dataset: {data.run_metadata.split.toUpperCase()}</div>
        </div>
        <div className="surface-card kpi-card">
          <div className="kpi-title">Straight Through</div>
          <div className="kpi-value">{summary.deterministic_cases.toLocaleString()}</div>
          <div className="kpi-supporting">{((summary.deterministic_cases / summary.total_cases) * 100).toFixed(1)}% Deterministic</div>
        </div>
        <div className="surface-card kpi-card">
          <div className="kpi-title">AI Investigations</div>
          <div className="kpi-value">{summary.ai_cases.toLocaleString()}</div>
          <div className="kpi-supporting">{((summary.ai_cases / summary.total_cases) * 100).toFixed(1)}% Ambiguous</div>
        </div>
        <div className="surface-card kpi-card">
          <div className="kpi-title">Human Escalations</div>
          <div className="kpi-value" style={{ color: 'var(--status-error)' }}>{summary.policy.ESCALATE.toLocaleString()}</div>
          <div className="kpi-supporting">Requires manual review</div>
        </div>
      </section>

      {/* 3. HIGHLIGHT STORY (AI OVERRIDE) */}
      {overrideCase && (
        <section className="override-box" onClick={() => onNavigateCase(overrideCase.operational_reference_id)} style={{ cursor: 'pointer', transition: 'transform 0.2s' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
            <div>
              <h3 className="section-title" style={{ margin: 0, color: 'var(--status-error)' }}>SAFETY OVERRIDE DEMONSTRATION</h3>
              <div className="mono-text" style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginTop: '4px' }}>{overrideCase.operational_reference_id}</div>
            </div>
            <span className="badge badge-error">CLICK TO VIEW</span>
          </div>
          
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '16px', textAlign: 'center' }}>
            <div style={{ flex: 1, backgroundColor: 'rgba(0,0,0,0.3)', padding: '16px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)' }}>
              <div className="meta-label">AI Recommended</div>
              <div style={{ fontWeight: 600, marginTop: '8px', fontSize: '1.1rem', color: 'var(--text-primary)' }}>{overrideCase.investigation?.recommended_action}</div>
            </div>
            <div style={{ color: 'var(--status-error)' }}>
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m9 18 6-6-6-6"/></svg>
            </div>
            <div style={{ flex: 1.5, backgroundColor: 'var(--status-error-bg)', padding: '16px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--status-error)' }}>
              <div className="meta-label" style={{ color: 'var(--status-error)' }}>Policy Engine Detected</div>
              <div style={{ fontWeight: 700, marginTop: '8px', color: 'var(--status-error)', fontSize: '1.1rem' }}>{overrideCase.policy.decision}</div>
              <div style={{ fontSize: '0.7rem', color: 'var(--status-error)', marginTop: '4px' }}>{overrideCase.investigation?.subtype || overrideCase.reconciliation.detected_issue}</div>
            </div>
            <div style={{ color: 'var(--status-error)' }}>
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m9 18 6-6-6-6"/></svg>
            </div>
            <div style={{ flex: 1, backgroundColor: 'rgba(0,0,0,0.3)', padding: '16px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)' }}>
              <div className="meta-label">Final Action</div>
              <div style={{ fontWeight: 600, marginTop: '8px', fontSize: '1.1rem', color: 'var(--text-primary)' }}>{overrideCase.policy.authorized_action}</div>
            </div>
          </div>
        </section>
      )}

      {/* 4. METRICS PANELS */}
      <div className="panel-grid">
        <section className="surface-card">
          <h3 className="section-title">Reconciliation Classifications</h3>
          <div style={{ marginTop: '16px' }}>
            {Object.entries(summary.reconciliation_counts).map(([key, count]) => 
              renderDist(key, count, summary.total_cases)
            )}
          </div>
        </section>

        <section className="surface-card">
          <h3 className="section-title">Policy Authorizations</h3>
          <div style={{ marginTop: '16px' }}>
            {renderDist('ALLOW', summary.policy.ALLOW, summary.total_cases)}
            {renderDist('MONITOR', summary.policy.MONITOR, summary.total_cases)}
            {renderDist('ESCALATE', summary.policy.ESCALATE, summary.total_cases)}
            {renderDist('DENY', summary.policy.DENY, summary.total_cases)}
          </div>
        </section>
      </div>

      {/* 5. DEMO STORY CASES */}
      {demoCases.length > 0 && (
        <section>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
            <div>
              <h3 className="section-title" style={{ margin: 0 }}>8 Decision Paths</h3>
              <p style={{ color: 'var(--text-secondary)', fontSize: '0.8rem', marginTop: '4px' }}>
                Representative operational cases highlighting exact decision flows.
              </p>
            </div>
            <span className="badge badge-brand">DEMO CASES</span>
          </div>
          
          <div className="demo-grid">
            {demoCases.map((c) => (
              <div 
                key={c.operational_reference_id} 
                className="demo-card"
                onClick={() => onNavigateCase(c.operational_reference_id)}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '16px' }}>
                  <div className="mono-text" style={{ fontWeight: 600 }}>{c.operational_reference_id}</div>
                  <span className={`badge ${c.reconciliation.route === 'AI_INVESTIGATOR' ? 'badge-warning' : 'badge-info'}`}>
                    {c.reconciliation.route === 'AI_INVESTIGATOR' ? 'AI' : 'DET'}
                  </span>
                </div>
                <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '24px', flex: 1 }}>
                  {c.investigation?.subtype || c.reconciliation.detected_issue}
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', borderTop: '1px solid var(--border-subtle)', paddingTop: '16px' }}>
                  <div>
                    <div className="meta-label">Final Action</div>
                    <div className="mono-text" style={{ fontWeight: 600, marginTop: '4px', color: 'var(--text-primary)' }}>{c.policy.authorized_action}</div>
                  </div>
                  <div>
                    <span className={`badge ${getPolicyBadge(c.policy.decision)}`}>
                      {c.policy.decision}
                    </span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

    </div>
  );
};
