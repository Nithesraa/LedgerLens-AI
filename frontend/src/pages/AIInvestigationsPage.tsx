import React, { useMemo } from 'react';
import type { WorkflowOutput } from '../types/workflow';
import { WorkflowAdapter } from '../adapters/WorkflowAdapter';

interface AIInvestigationsPageProps {
  data: WorkflowOutput;
  onNavigateCase: (id: string) => void;
}

export const AIInvestigationsPage: React.FC<AIInvestigationsPageProps> = ({ data, onNavigateCase }) => {
  const allCases = WorkflowAdapter.getCases(data);
  const summary = WorkflowAdapter.getSummary(data);
  
  // Filter only AI cases
  const aiCases = useMemo(() => {
    return allCases.filter(c => c.reconciliation.route === 'AI_INVESTIGATOR');
  }, [allCases]);

  const getPolicyBadge = (decision: string) => {
    if (decision === 'ALLOW') return 'badge-success';
    if (decision === 'ESCALATE' || decision === 'DENY') return 'badge-error';
    return 'badge-warning';
  };

  return (
    <div className="dashboard-container">
      <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', marginBottom: '24px' }}>
        <div>
          <h2 style={{ fontSize: '1.5rem', margin: '0 0 4px 0', fontWeight: 600 }}>AI Investigations</h2>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', margin: 0 }}>
            AI is invoked only for cases the deterministic engine cannot safely resolve. Review these cases prior to deterministic policy enforcement.
          </p>
        </div>
        <div style={{ textAlign: 'right' }}>
          <div className="meta-label">Total AI Cases</div>
          <div className="mono-text" style={{ fontSize: '1.25rem', fontWeight: 700, color: 'var(--status-warning)' }}>
            {summary.ai_cases.toLocaleString()}
          </div>
        </div>
      </header>

      <section className="kpi-grid" style={{ marginBottom: '32px' }}>
        <div className="surface-card kpi-card">
          <div className="kpi-title">Total AI Cases</div>
          <div className="kpi-value" style={{ color: 'var(--status-warning)' }}>{summary.ai_cases}</div>
          <div className="kpi-supporting">Routed to AI</div>
        </div>
        <div className="surface-card kpi-card">
          <div className="kpi-title">Successful</div>
          <div className="kpi-value" style={{ color: 'var(--status-success)' }}>{summary.ai.ai_success}</div>
          <div className="kpi-supporting">Review completed</div>
        </div>
        <div className="surface-card kpi-card">
          <div className="kpi-title">Failed</div>
          <div className="kpi-value" style={{ color: 'var(--status-error)' }}>{summary.ai.ai_failed}</div>
          <div className="kpi-supporting">Execution failed</div>
        </div>
        <div className="surface-card kpi-card">
          <div className="kpi-title">Low Confidence</div>
          <div className="kpi-value">{summary.ai.ai_low_confidence}</div>
          <div className="kpi-supporting">Below threshold</div>
        </div>
      </section>

      {aiCases.length === 0 ? (
        <div className="state-container" style={{ padding: '64px', border: '1px dashed var(--border-strong)', borderRadius: 'var(--radius-lg)' }}>
          <div style={{ fontSize: '2rem', marginBottom: '16px', opacity: 0.5 }}>🤖</div>
          <h3 style={{ color: 'var(--text-primary)', marginBottom: '8px' }}>No AI investigations found</h3>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>All cases in this dataset were resolved deterministically.</p>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
          {aiCases.map((c) => {
            const hasOverride = c.investigation?.recommended_action !== c.policy.authorized_action;
            
            return (
              <div 
                key={c.operational_reference_id} 
                className="surface-card hover-card"
                style={{ cursor: 'pointer', transition: 'all 0.2s', borderColor: hasOverride ? 'rgba(245, 158, 11, 0.5)' : 'var(--border-subtle)' }}
                onClick={() => onNavigateCase(c.operational_reference_id)}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '16px', borderBottom: '1px solid var(--border-subtle)', paddingBottom: '16px' }}>
                  <div>
                    <div className="mono-text" style={{ fontSize: '1.25rem', fontWeight: 700, marginBottom: '6px', color: 'var(--text-primary)' }}>
                      {c.operational_reference_id}
                    </div>
                    <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                      <span className="badge badge-warning" style={{ fontSize: '0.7rem' }}>AI INVESTIGATION</span>
                      <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                        {c.investigation?.subtype || c.reconciliation.detected_issue}
                      </span>
                    </div>
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <div className="meta-label">Status</div>
                    <div className="mono-text" style={{ fontWeight: 600, marginTop: '4px', fontSize: '0.875rem', color: 'var(--text-primary)' }}>{c.investigation?.status || '—'}</div>
                  </div>
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '24px', marginBottom: '24px' }}>
                  <div>
                    <div className="meta-label">Confidence Score</div>
                    <div className="mono-text" style={{ fontSize: '1.25rem', fontWeight: 700, marginTop: '4px', color: 'var(--text-primary)' }}>
                      {c.investigation?.confidence_score !== null && c.investigation?.confidence_score !== undefined
                        ? `${(c.investigation.confidence_score * 100).toFixed(1)}%` 
                        : '—'}
                    </div>
                  </div>
                  
                  <div style={{ gridColumn: 'span 2' }}>
                    {hasOverride ? (
                      <div className="override-box" style={{ padding: '16px' }}>
                        <div className="meta-label" style={{ color: 'var(--status-error)', marginBottom: '12px' }}>⚠️ Policy Override Activated</div>
                        <div className="override-flow" style={{ fontSize: '0.875rem' }}>
                          <div style={{ flex: 1, backgroundColor: 'rgba(0,0,0,0.3)', padding: '12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)' }}>
                            <div style={{ color: 'var(--text-secondary)', fontSize: '0.7rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>AI Recommendation</div>
                            <div className="mono-text" style={{ fontWeight: 600, marginTop: '4px' }}>{c.investigation?.recommended_action || '—'}</div>
                          </div>
                          <div style={{ color: 'var(--status-error)', fontSize: '1.2rem' }}>&rarr;</div>
                          <div style={{ flex: 1, backgroundColor: 'var(--bg-app)', padding: '12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--status-error)' }}>
                            <div style={{ color: 'var(--status-error)', fontSize: '0.7rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Policy Decision</div>
                            <div className="mono-text" style={{ fontWeight: 700, color: 'var(--status-error)', marginTop: '4px' }}>{c.policy.decision}</div>
                          </div>
                          <div style={{ color: 'var(--status-error)', fontSize: '1.2rem' }}>&rarr;</div>
                          <div style={{ flex: 1, backgroundColor: 'rgba(0,0,0,0.3)', padding: '12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)' }}>
                            <div style={{ color: 'var(--text-secondary)', fontSize: '0.7rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Authorized Action</div>
                            <div className="mono-text" style={{ fontWeight: 600, marginTop: '4px' }}>{c.policy.authorized_action}</div>
                          </div>
                        </div>
                      </div>
                    ) : (
                      <div style={{ padding: '16px', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-md)', backgroundColor: 'var(--bg-app)' }}>
                        <div className="meta-label" style={{ marginBottom: '12px' }}>Aligned Decision</div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '16px', fontSize: '0.875rem' }}>
                          <div style={{ flex: 1 }}>
                            <div style={{ color: 'var(--text-secondary)', fontSize: '0.7rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>AI Recommendation</div>
                            <div className="mono-text" style={{ fontWeight: 600, marginTop: '4px', color: 'var(--text-primary)' }}>{c.investigation?.recommended_action || '—'}</div>
                          </div>
                          <div style={{ color: 'var(--text-secondary)' }}>&rarr;</div>
                          <div style={{ flex: 1 }}>
                            <div style={{ color: 'var(--text-secondary)', fontSize: '0.7rem', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '4px' }}>Policy Decision</div>
                            <div><span className={`badge ${getPolicyBadge(c.policy.decision)}`}>{c.policy.decision}</span></div>
                          </div>
                          <div style={{ color: 'var(--text-secondary)' }}>&rarr;</div>
                          <div style={{ flex: 1 }}>
                            <div style={{ color: 'var(--text-secondary)', fontSize: '0.7rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Authorized Action</div>
                            <div className="mono-text" style={{ fontWeight: 600, marginTop: '4px', color: 'var(--text-primary)' }}>{c.policy.authorized_action}</div>
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                </div>

                <div style={{ marginBottom: '16px' }}>
                  <div className="meta-label">AI Reasoning</div>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginBottom: '8px' }}>AI-generated operational explanation</div>
                  <div style={{ padding: '16px', backgroundColor: 'var(--bg-app)', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)', fontSize: '0.85rem', lineHeight: 1.6, color: 'var(--text-primary)' }}>
                    {c.investigation?.reasoning || '—'}
                  </div>
                </div>

                {c.investigation?.evidence_references && c.investigation.evidence_references.length > 0 && (
                  <div>
                    <div className="meta-label" style={{ marginBottom: '8px' }}>Evidence References</div>
                    <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                      {c.investigation.evidence_references.map(ref => (
                        <span key={ref} className="badge badge-info" style={{ fontFamily: 'var(--font-mono)', letterSpacing: 0, textTransform: 'none', backgroundColor: 'var(--bg-app)', border: '1px solid var(--border-strong)' }}>
                          {ref}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};
