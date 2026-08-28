export type HandlingRoute = 'DETERMINISTIC' | 'AI_INVESTIGATOR';

export type Classification =
  | 'EXACT_MATCH'
  | 'FEE_DEDUCTION'
  | 'TIMING_LAG'
  | 'DUPLICATE'
  | 'MISSING_SETTLEMENT'
  | 'UNKNOWN_TRANSACTION';

export type AISubtype = 'REFUND_ADJUSTMENT' | 'LEDGER_MISMATCH';

export type PolicyDecision = 'ALLOW' | 'DENY' | 'MONITOR' | 'ESCALATE';

export type ExecutionStatus =
  | 'SIMULATED_EXECUTED'
  | 'ESCALATED'
  | 'MONITORING'
  | 'DUPLICATE_SUPPRESSED'
  | 'CONFLICT_BLOCKED'
  | 'FAILED_SAFE';

export type AIReviewStatus = 'AI_REVIEW_COMPLETE' | 'AI_REVIEW_FAILED' | 'PENDING_AI_REVIEW';

export interface RunMetadata {
  workflow_version: string;
  split: string;
  evaluation_date: string;
}

export interface ReconciliationCounts {
  EXACT_MATCH: number;
  FEE_DEDUCTION: number;
  TIMING_LAG: number;
  DUPLICATE: number;
  MISSING_SETTLEMENT: number;
  UNKNOWN_TRANSACTION: number;
}

export interface AIMetrics {
  ai_success: number;
  ai_failed: number;
  ai_low_confidence: number;
}

export interface PolicyMetrics {
  ALLOW: number;
  DENY: number;
  MONITOR: number;
  ESCALATE: number;
}

export interface ExecutionMetrics {
  SIMULATED_EXECUTED: number;
  ESCALATED: number;
  MONITORING: number;
  DUPLICATE_SUPPRESSED: number;
  CONFLICT_BLOCKED: number;
  FAILED_SAFE: number;
}

export interface WorkflowSummary {
  total_cases: number;
  deterministic_cases: number;
  ai_cases: number;
  reconciliation_counts: ReconciliationCounts;
  ai: AIMetrics;
  policy: PolicyMetrics;
  execution: ExecutionMetrics;
}

export interface EvidenceSummary {
  payment_amount: number;
  ledger_amount: number;
}

export interface DecisionTrace {
  payment_exists: boolean;
  merchant_ledger_exists: boolean;
  settlement_exists: boolean;
  settlement_count: number;
  duplicate_detected: boolean;
  payment_age_days: number | null;
  settlement_within_window: boolean | null;
  ledger_matches_payment: boolean | null;
  adjustment_count: number;
}

export interface Reconciliation {
  route: HandlingRoute;
  detected_issue: Classification | null;
  subtype: AISubtype | null;
  decision_trace: DecisionTrace;
}

export interface Investigation {
  status: AIReviewStatus;
  subtype: AISubtype;
  confidence_score: number | null;
  recommended_action: string;
  reasoning: string;
  evidence_references: string[];
}

export interface PolicyGates {
  valid_input: boolean;
  evidence_valid: boolean;
  ai_review_success: boolean;
  confidence_ok: boolean;
}

export interface Policy {
  decision: PolicyDecision;
  authorized_action: string;
  reason: string;
  gates: PolicyGates;
  policy_version: string;
}

export interface Execution {
  status: ExecutionStatus;
  simulated: boolean;
  real_financial_action: boolean;
}

export interface Audit {
  audit_reference: string;
}

export interface WorkflowCase {
  operational_reference_id: string;
  evidence_summary: EvidenceSummary;
  reconciliation: Reconciliation;
  investigation: Investigation | null;
  policy: Policy;
  execution: Execution;
  audit: Audit;
}

export type DemoStoryCase = WorkflowCase;

export interface AuditSummary {
  total_events: number;
}

export interface WorkflowOutput {
  run_metadata: RunMetadata;
  summary: WorkflowSummary;
  demo_story_cases: DemoStoryCase[];
  cases: WorkflowCase[];
  audit_summary: AuditSummary;
}
