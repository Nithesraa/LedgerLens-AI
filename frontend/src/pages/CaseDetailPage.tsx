import React from 'react';
import type { WorkflowOutput } from '../types/workflow';
import { WorkflowAdapter } from '../adapters/WorkflowAdapter';

interface CaseDetailPageProps {
  data: WorkflowOutput;
  caseId: string;
  onBack: () => void;
}

export const CaseDetailPage: React.FC<CaseDetailPageProps> = ({ data, caseId, onBack }) => {
  const caseData = WorkflowAdapter.getCaseByReference(data, caseId);

  if (!caseData) {
    return (
      <div className="state-container" style={{ padding: '64px', border: '1px dashed var(--border-strong)', borderRadius: 'var(--radius-lg)' }}>
        <div style={{ fontSize: '3rem', marginBottom: '16px' }}>⚠️</div>
        <h2 style={{ margin: 0, color: 'var(--text-primary)' }}>Case Not Found</h2>
        <p style={{ color: 'var(--text-secondary)', marginTop: '8px', marginBottom: '24px' }}>
          The requested case {caseId} could not be found in the current split ({data.run_metadata.split}).
        </p>
        <button className="pagination-btn" onClick={onBack}>
          &larr; Back to Case Explorer
        </button>
      </div>
    );
  }

  const getPolicyBadge = (decision: string) => {
    if (decision === 'ALLOW') return 'badge-success';
    if (decision === 'ESCALATE' || decision === 'DENY') return 'badge-error';
    return 'badge-warning';
  };

  const isAi = caseData.reconciliation.route === 'AI_INVESTIGATOR';
  const hasAiOverride = isAi && caseData.investigation?.recommended_action !== caseData.policy.authorized_action;

  return (
    <div className="dashboard-container" style={{ maxWidth: '1000px', margin: '0 auto' }}>
      
      <header style={{ display: 'flex', gap: '16px', alignItems: 'flex-start', marginBottom: '16px' }}>
        <button 
          onClick={onBack}
          style={{ 
            background: 'none', border: 'none', color: 'var(--text-secondary)', 
            cursor: 'pointer', fontSize: '1.25rem', padding: '4px 8px',
            marginTop: '2px'
          }}
        >
          &larr;
        </button>
        <div style={{ flex: 1 }}>
          <div className="meta-label">Case Investigation</div>
          <h2 className="mono-text" style={{ fontSize: '2rem', fontWeight: 700, margin: '4px 0', color: 'var(--text-primary)', letterSpacing: '-0.03em' }}>
            {caseData.operational_reference_id}
          </h2>
        </div>
        <div style={{ textAlign: 'right' }}>
          <div className="meta-label">Route</div>
          <div style={{ marginTop: '4px' }}>
            <span className={`badge ${isAi ? 'badge-warning' : 'badge-info'}`} style={{ fontSize: '0.85rem', padding: '6px 12px' }}>
              {caseData.reconciliation.route}
            </span>
          </div>
        </div>
      </header>

      {/* Hero Decision Pipeline for this specific case */}
      <section className="surface-card" style={{ padding: '0', overflow: 'hidden', marginBottom: '32px' }}>
        <div style={{ padding: 'var(--spacing-4) var(--spacing-6)', borderBottom: '1px solid var(--border-subtle)', backgroundColor: 'var(--bg-app)' }}>
          <div className="meta-label">Case Decision Pipeline</div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', padding: '32px 24px', backgroundColor: 'var(--bg-surface-elevated)' }}>
          
          {/* Node 1 */}
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', textAlign: 'center', gap: '8px' }}>
            <div style={{ width: '48px', height: '48px', borderRadius: '50%', backgroundColor: 'var(--bg-app)', border: '2px solid var(--border-strong)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 'bold' }}>1</div>
            <div className="meta-label">Reconciliation</div>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Evaluated</div>
          </div>
          
          <div style={{ width: '40px', height: '2px', backgroundColor: 'var(--border-strong)' }}></div>
          
          {/* Node 2 */}
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', textAlign: 'center', gap: '8px', opacity: isAi ? 1 : 0.4 }}>
            <div style={{ width: '48px', height: '48px', borderRadius: '50%', backgroundColor: isAi ? 'var(--status-warning-bg)' : 'var(--bg-app)', border: `2px solid ${isAi ? 'var(--status-warning)' : 'var(--border-strong)'}`, display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 'bold', color: isAi ? 'var(--status-warning)' : 'inherit' }}>2</div>
            <div className="meta-label" style={{ color: isAi ? 'var(--status-warning)' : 'inherit' }}>AI Investigator</div>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>{isAi ? 'Invoked' : 'Bypassed'}</div>
          </div>
          
          <div style={{ width: '40px', height: '2px', backgroundColor: 'var(--border-strong)' }}></div>
          
          {/* Node 3 */}
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', textAlign: 'center', gap: '8px' }}>
            <div style={{ width: '48px', height: '48px', borderRadius: '50%', backgroundColor: 'var(--accent-brand-subtle)', border: '2px solid var(--accent-brand)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 'bold', color: 'var(--accent-brand)' }}>3</div>
            <div className="meta-label" style={{ color: 'var(--accent-brand)' }}>Policy Engine</div>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-primary)', fontWeight: 600 }}>{caseData.policy.decision}</div>
          </div>
          
          <div style={{ width: '40px', height: '2px', backgroundColor: 'var(--border-strong)' }}></div>
          
          {/* Node 4 */}
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', textAlign: 'center', gap: '8px' }}>
            <div style={{ width: '48px', height: '48px', borderRadius: '50%', backgroundColor: 'var(--bg-app)', border: '2px solid var(--border-strong)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 'bold' }}>4</div>
            <div className="meta-label">Execution</div>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Simulated</div>
          </div>
          
        </div>
      </section>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
        
        {/* RECONCILIATION & EVIDENCE */}
        <section className="surface-card">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
            <h3 className="section-title" style={{ margin: 0 }}>Reconciliation & Evidence</h3>
            <span className="badge" style={{ backgroundColor: 'var(--bg-app)', border: '1px solid var(--border-strong)' }}>DETERMINISTIC LAYER</span>
          </div>
          
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '24px' }}>
            <div>
              <div className="meta-label" style={{ marginBottom: '12px' }}>Extracted Financial Evidence</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '1px', backgroundColor: 'var(--border-subtle)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-md)', overflow: 'hidden' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', backgroundColor: 'var(--bg-app)', padding: '12px 16px' }}>
                  <span style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>Payment Amount</span>
                  <span className="mono-text" style={{ fontWeight: 600, color: 'var(--text-primary)' }}>₹{Number(caseData.evidence_summary.payment_amount).toFixed(2)}</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', backgroundColor: 'var(--bg-app)', padding: '12px 16px' }}>
                  <span style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>Ledger Amount</span>
                  <span className="mono-text" style={{ fontWeight: 600, color: 'var(--text-primary)' }}>₹{Number(caseData.evidence_summary.ledger_amount).toFixed(2)}</span>
                </div>
              </div>
            </div>
            
            <div>
              <div className="meta-label" style={{ marginBottom: '12px' }}>Deterministic Findings</div>
              <div style={{ backgroundColor: 'var(--bg-app)', padding: '16px', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)', height: '100%' }}>
                <div style={{ marginBottom: '12px' }}>
                  <span className="meta-label">Detected Issue: </span>
                  <span style={{ color: 'var(--text-primary)', fontWeight: 500, fontSize: '0.85rem' }}>{caseData.reconciliation.detected_issue || 'None'}</span>
                </div>
                <ul style={{ listStyle: 'none', padding: 0, margin: 0, fontSize: '0.8rem', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  {Object.entries(caseData.reconciliation.decision_trace).map(([key, val]) => (
                    <li key={key} style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px dashed var(--border-subtle)', paddingBottom: '4px' }}>
                      <span style={{ color: 'var(--text-muted)' }}>{key.replace(/_/g, ' ')}</span>
                      <span style={{ fontWeight: 600, color: val ? 'var(--text-primary)' : 'var(--text-secondary)' }}>
                        {val === null ? '—' : (typeof val === 'boolean' ? (val ? 'Yes' : 'No') : String(val))}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          </div>
        </section>

        {/* AI INVESTIGATION */}
        {isAi && (
          <section className="surface-card" style={{ borderColor: 'rgba(245, 158, 11, 0.3)', backgroundColor: 'var(--bg-surface)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
              <h3 className="section-title" style={{ margin: 0, color: 'var(--status-warning)' }}>AI Investigation</h3>
              <span className="badge badge-warning">AI ADVISORY</span>
            </div>
            
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(250px, 1fr))', gap: '16px', marginBottom: '16px' }}>
              <div style={{ backgroundColor: 'var(--bg-app)', padding: '16px', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
                <div className="meta-label">Recommended Action</div>
                <div className="mono-text" style={{ marginTop: '8px', fontWeight: 600, fontSize: '1.25rem', color: 'var(--text-primary)' }}>{caseData.investigation?.recommended_action}</div>
              </div>
              <div style={{ backgroundColor: 'var(--bg-app)', padding: '16px', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
                <div className="meta-label">Confidence Score</div>
                <div className="mono-text" style={{ marginTop: '8px', fontWeight: 600, fontSize: '1.25rem', color: 'var(--text-primary)' }}>
                  {caseData.investigation?.confidence_score !== null ? `${(caseData.investigation!.confidence_score! * 100).toFixed(1)}%` : '—'}
                </div>
              </div>
            </div>
            
            <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <div style={{ backgroundColor: 'var(--bg-app)', padding: '20px', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
                <div className="meta-label" style={{ marginBottom: '12px' }}>Reasoning Summary</div>
                <div style={{ fontSize: '0.9rem', lineHeight: 1.6, color: 'var(--text-primary)' }}>
                  {caseData.investigation?.reasoning || 'No reasoning provided.'}
                </div>
              </div>
              
              <div style={{ backgroundColor: 'var(--bg-app)', padding: '16px', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
                <div className="meta-label" style={{ marginBottom: '12px' }}>Evidence References</div>
                <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                  {caseData.investigation?.evidence_references?.map(ref => (
                    <span key={ref} className="badge badge-info" style={{ fontFamily: 'var(--font-mono)', letterSpacing: 0, textTransform: 'none' }}>
                      {ref}
                    </span>
                  ))}
                </div>
              </div>
            </div>
          </section>
        )}

        {/* POLICY ENGINE */}
        <section className="surface-card" style={{ borderColor: 'rgba(245, 158, 11, 0.5)', position: 'relative', overflow: 'hidden' }}>
          <div style={{ position: 'absolute', top: 0, left: 0, bottom: 0, width: '4px', backgroundColor: 'var(--accent-brand)' }}></div>
          
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
            <h3 className="section-title" style={{ margin: 0, color: 'var(--accent-brand)' }}>Policy Engine</h3>
            <span className="badge badge-brand">AUTHORITATIVE</span>
          </div>

          {hasAiOverride && (
            <div className="override-box" style={{ marginBottom: '24px' }}>
              <h4 style={{ color: 'var(--status-error)', fontSize: '0.85rem', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '12px', fontWeight: 700 }}>
                ⚠️ Policy Override Activated
              </h4>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '16px', textAlign: 'center' }}>
                <div style={{ flex: 1, backgroundColor: 'rgba(0,0,0,0.3)', padding: '16px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)' }}>
                  <div className="meta-label">AI Recommended</div>
                  <div className="mono-text" style={{ fontWeight: 600, marginTop: '8px', fontSize: '1rem', color: 'var(--text-primary)' }}>{caseData.investigation?.recommended_action}</div>
                </div>
                <div style={{ color: 'var(--status-error)', fontSize: '1.5rem' }}>&rarr;</div>
                <div style={{ flex: 1.5, backgroundColor: 'var(--bg-app)', padding: '16px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--status-error)' }}>
                  <div className="meta-label" style={{ color: 'var(--status-error)' }}>Policy Enforced</div>
                  <div className="mono-text" style={{ fontWeight: 700, marginTop: '8px', color: 'var(--status-error)', fontSize: '1.1rem' }}>{caseData.policy.decision}</div>
                </div>
                <div style={{ color: 'var(--status-error)', fontSize: '1.5rem' }}>&rarr;</div>
                <div style={{ flex: 1, backgroundColor: 'rgba(0,0,0,0.3)', padding: '16px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)' }}>
                  <div className="meta-label">Final Action</div>
                  <div className="mono-text" style={{ fontWeight: 600, marginTop: '8px', fontSize: '1rem', color: 'var(--text-primary)' }}>{caseData.policy.authorized_action}</div>
                </div>
              </div>
            </div>
          )}

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '16px', marginBottom: '16px' }}>
            <div style={{ backgroundColor: 'var(--bg-app)', padding: '16px', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
              <div className="meta-label">Policy Decision</div>
              <div style={{ marginTop: '12px' }}>
                <span className={`badge ${getPolicyBadge(caseData.policy.decision)}`}>{caseData.policy.decision}</span>
              </div>
            </div>
            <div style={{ backgroundColor: 'var(--bg-app)', padding: '16px', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
              <div className="meta-label">Authorized Action</div>
              <div className="mono-text" style={{ marginTop: '12px', fontWeight: 600, fontSize: '1rem', color: 'var(--text-primary)' }}>{caseData.policy.authorized_action}</div>
            </div>
            <div style={{ gridColumn: '1 / -1', backgroundColor: 'var(--bg-app)', padding: '16px', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
              <div className="meta-label" style={{ marginBottom: '8px' }}>Policy Reason</div>
              <div style={{ fontSize: '0.9rem', lineHeight: 1.5, color: 'var(--text-primary)' }}>{caseData.policy.reason}</div>
            </div>
          </div>

          <div style={{ backgroundColor: 'var(--bg-app)', padding: '16px', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
            <div className="meta-label" style={{ marginBottom: '12px' }}>Policy Gates Checked</div>
            <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
              {Object.entries(caseData.policy.gates).map(([gate, passed]) => (
                <div key={gate} style={{ display: 'flex', alignItems: 'center', gap: '6px', padding: '6px 10px', backgroundColor: 'var(--bg-surface)', borderRadius: 'var(--radius-sm)', border: `1px solid ${passed ? 'rgba(16, 185, 129, 0.3)' : 'rgba(239, 68, 68, 0.3)'}` }}>
                  <div style={{ color: passed ? 'var(--status-success)' : 'var(--status-error)', fontWeight: 'bold', fontSize: '0.8rem' }}>
                    {passed ? '✓' : '✗'}
                  </div>
                  <div className="mono-text" style={{ fontSize: '0.7rem' }}>{gate}</div>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* EXECUTION & AUDIT ROW */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(400px, 1fr))', gap: '24px' }}>
          
          <section className="surface-card">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
              <h3 className="section-title" style={{ margin: 0 }}>Controlled Execution</h3>
              <span className="badge badge-info">SIMULATED</span>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <div style={{ backgroundColor: 'var(--bg-app)', padding: '16px', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
                <div className="meta-label">Execution Status</div>
                <div className="mono-text" style={{ marginTop: '8px', fontWeight: 600, color: 'var(--text-primary)' }}>{caseData.execution.status}</div>
              </div>
              <div style={{ backgroundColor: 'var(--bg-app)', padding: '16px', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
                <div className="meta-label">Real Financial Action Triggered</div>
                <div className="mono-text" style={{ marginTop: '8px', color: caseData.execution.real_financial_action ? 'var(--status-error)' : 'var(--text-secondary)' }}>
                  {caseData.execution.real_financial_action ? 'YES' : 'NO'}
                </div>
              </div>
            </div>
          </section>

          <section className="surface-card" style={{ backgroundColor: '#000', borderColor: 'var(--border-strong)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
              <h3 className="section-title" style={{ margin: 0, color: '#fff' }}>Audit Record</h3>
              <span className="badge" style={{ backgroundColor: 'rgba(255,255,255,0.1)', color: '#fff', border: '1px solid rgba(255,255,255,0.2)' }}>READ ONLY</span>
            </div>
            
            <div className="mono-text" style={{ color: '#a1a1aa', fontSize: '0.8rem', display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <div style={{ display: 'flex' }}><span style={{ width: '160px', color: '#71717a' }}>Audit Ref:</span> <span style={{ color: 'var(--accent-brand)' }}>{caseData.audit.audit_reference}</span></div>
              <div style={{ display: 'flex' }}><span style={{ width: '160px', color: '#71717a' }}>Eval Date:</span> <span>{data.run_metadata.evaluation_date}</span></div>
              <div style={{ display: 'flex' }}><span style={{ width: '160px', color: '#71717a' }}>Policy Ver:</span> <span>{caseData.policy.policy_version}</span></div>
              <div style={{ display: 'flex' }}><span style={{ width: '160px', color: '#71717a' }}>Route:</span> <span style={{ color: '#fff' }}>{caseData.reconciliation.route}</span></div>
              <div style={{ display: 'flex' }}><span style={{ width: '160px', color: '#71717a' }}>Decision:</span> <span style={{ color: '#fff' }}>{caseData.policy.decision}</span></div>
              <div style={{ display: 'flex' }}><span style={{ width: '160px', color: '#71717a' }}>Action:</span> <span style={{ color: '#fff' }}>{caseData.policy.authorized_action}</span></div>
            </div>
          </section>

        </div>
      </div>
    </div>
  );
};
