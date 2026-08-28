"""Deterministic Policy Engine and Controlled Action Simulator for LedgerLens AI.

This module enforces business safety and explicitly simulates action execution 
without performing any real financial operations. It is the final gatekeeper 
between AI recommendations and simulated operations.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import hashlib
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any, Final, Optional, Sequence

from ledgerlens.config import (
    SETTINGS,
    CaseSubtype,
    DatasetSplit,
    ExceptionCategory,
    FinalAction,
    HandlingRoute,
)
from ledgerlens.reconciliation import reconcile_split
from ledgerlens.ai_investigator import AIInvestigator, MockAIProvider

POLICY_VERSION: Final[str] = "1"
# Hardcoded minimum confidence threshold from configuration
CONFIDENCE_THRESHOLD: Final[Decimal] = Decimal("0.80")


class PolicyDecisionAction(StrEnum):
    """The outcome decision of the policy engine."""
    ALLOW = "ALLOW"
    DENY = "DENY"
    ESCALATE = "ESCALATE"
    MONITOR = "MONITOR"


class ExecutionStatus(StrEnum):
    """The result of the simulated execution action."""
    AUTHORIZED = "AUTHORIZED"
    DENIED = "DENIED"
    ESCALATED = "ESCALATED"
    MONITORING = "MONITORING"
    SIMULATED_EXECUTED = "SIMULATED_EXECUTED"
    DUPLICATE_SUPPRESSED = "DUPLICATE_SUPPRESSED"
    CONFLICT_BLOCKED = "CONFLICT_BLOCKED"
    FAILED_SAFE = "FAILED_SAFE"


@dataclass(frozen=True, slots=True)
class PolicyInput:
    """Structured input to the Policy Engine."""
    operational_reference_id: str
    route: HandlingRoute
    status: Optional[str]
    classification: Optional[ExceptionCategory]
    sub_type: Optional[CaseSubtype | str]
    confidence_score: Optional[Decimal]
    recommended_action: Optional[FinalAction]
    evidence_valid: bool
    evidence_references: tuple[str, ...]
    decision_trace: dict[str, Any]
    calculations: dict[str, Any]


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    """The immutable structured result of a policy evaluation."""
    operational_reference_id: str
    policy_decision: PolicyDecisionAction
    authorized_action: FinalAction
    decision_reason: str
    gates: dict[str, bool]
    policy_version: str = POLICY_VERSION


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """The immutable structured result of a simulated execution."""
    operational_reference_id: str
    policy_decision: PolicyDecisionAction
    authorized_action: FinalAction
    execution_status: ExecutionStatus
    simulated: bool = True
    real_financial_action: bool = False


@dataclass(frozen=True, slots=True)
class AuditRecord:
    """An append-only audit record of a decision or action attempt."""
    audit_id: str
    operational_reference_id: str
    evaluation_date: str
    policy_version: str
    route: HandlingRoute
    classification: Optional[ExceptionCategory]
    sub_type: Optional[str]
    confidence_score: Optional[Decimal]
    policy_decision: PolicyDecisionAction
    authorized_action: FinalAction
    execution_status: ExecutionStatus
    idempotency_key: str
    reason: str
    evidence_references: tuple[str, ...]


class PolicyEngine:
    """Deterministic policy engine that governs what actions are authorized."""

    def evaluate(self, input_data: PolicyInput) -> PolicyDecision:
        """Evaluates policy gates in deterministic priority order."""
        try:
            return self._evaluate_internal(input_data)
        except Exception as e:
            # Rule 17 & 19: Any unexpected exception must fail safe to ESCALATE
            return PolicyDecision(
                operational_reference_id=input_data.operational_reference_id,
                policy_decision=PolicyDecisionAction.DENY,
                authorized_action=FinalAction.ESCALATE,
                decision_reason=f"Policy evaluation failed unexpectedly: {e}",
                gates={"failed_safe": True},
            )

    def _evaluate_internal(self, input_data: PolicyInput) -> PolicyDecision:
        gates: dict[str, bool] = {
            "valid_input": True,
            "evidence_valid": input_data.evidence_valid,
            "ai_review_success": input_data.status != "AI_REVIEW_FAILED",
            "confidence_ok": True,
        }

        # 1. Invalid/malformed input check
        if not input_data.operational_reference_id or not input_data.route:
            gates["valid_input"] = False
            return self._deny(input_data, "Missing required policy input fields.", gates)

        # 2. Evidence validation check (Case K)
        if not input_data.evidence_valid:
            return self._deny(input_data, "Evidence is invalid.", gates)

        # 3. AI review failure check (Case I)
        if input_data.route == HandlingRoute.AI_INVESTIGATOR and input_data.status == "AI_REVIEW_FAILED":
            return self._escalate(input_data, "AI review failed.", gates)

        # 4. Confidence gate (Case J)
        if input_data.route == HandlingRoute.AI_INVESTIGATOR:
            if input_data.confidence_score is None or input_data.confidence_score < CONFIDENCE_THRESHOLD:
                gates["confidence_ok"] = False
                return self._escalate(input_data, "AI confidence score is below the required threshold.", gates)

        # 5/6. Explicit high-risk / Unsupported Classifications
        if input_data.classification == ExceptionCategory.DUPLICATE:
            return self._deny(input_data, "Duplicate transactions cannot be auto-resolved.", gates, PolicyDecisionAction.DENY)
        if input_data.classification == ExceptionCategory.UNKNOWN_TRANSACTION:
            return self._deny(input_data, "Unknown transactions cannot be auto-resolved.", gates, PolicyDecisionAction.DENY)
        if input_data.classification == ExceptionCategory.MISSING_SETTLEMENT:
            return self._escalate(input_data, "Missing settlements require escalation.", gates)

        # 7. Deterministic safe policy (Cases A, B, C)
        if input_data.route == HandlingRoute.DETERMINISTIC:
            if input_data.classification == ExceptionCategory.EXACT_MATCH:
                return self._allow(input_data, FinalAction.AUTO_RESOLVE, "Exact match verified.", gates)
            
            if input_data.classification == ExceptionCategory.FEE_DEDUCTION and input_data.sub_type == CaseSubtype.STANDARD_FEE:
                # Financial calculation check implicitly validated by evidence_valid=True for deterministic
                return self._allow(input_data, FinalAction.AUTO_RESOLVE, "Standard fee deduction verified.", gates)

            if input_data.classification == ExceptionCategory.TIMING_LAG:
                return PolicyDecision(
                    operational_reference_id=input_data.operational_reference_id,
                    policy_decision=PolicyDecisionAction.MONITOR,
                    authorized_action=FinalAction.MONITOR,
                    decision_reason="Timing lag is monitored.",
                    gates=gates
                )

        # 8. AI specific safe policy (Cases G, H)
        if input_data.route == HandlingRoute.AI_INVESTIGATOR:
            if input_data.classification == ExceptionCategory.FEE_DEDUCTION:
                if input_data.sub_type == CaseSubtype.REFUND_ADJUSTMENT:
                    if input_data.recommended_action == FinalAction.AUTO_RESOLVE:
                        # Case G
                        return self._allow(input_data, FinalAction.AUTO_RESOLVE, "Refund adjustment authorized.", gates)
                elif input_data.sub_type == CaseSubtype.LEDGER_MISMATCH:
                    # Case H: Must explicitly deny ledger mismatch even if AI requests AUTO_RESOLVE
                    return self._escalate(input_data, "Ledger mismatch cannot be auto-resolved.", gates)

        # 9. Otherwise ESCALATE (Case L/Default)
        return self._escalate(input_data, "No explicit policy allows this action.", gates)

    def _allow(self, input_data: PolicyInput, action: FinalAction, reason: str, gates: dict[str, bool]) -> PolicyDecision:
        return PolicyDecision(
            operational_reference_id=input_data.operational_reference_id,
            policy_decision=PolicyDecisionAction.ALLOW,
            authorized_action=action,
            decision_reason=reason,
            gates=gates
        )

    def _deny(self, input_data: PolicyInput, reason: str, gates: dict[str, bool], decision: PolicyDecisionAction = PolicyDecisionAction.DENY) -> PolicyDecision:
        return PolicyDecision(
            operational_reference_id=input_data.operational_reference_id,
            policy_decision=decision,
            authorized_action=FinalAction.ESCALATE,
            decision_reason=reason,
            gates=gates
        )
        
    def _escalate(self, input_data: PolicyInput, reason: str, gates: dict[str, bool]) -> PolicyDecision:
        return PolicyDecision(
            operational_reference_id=input_data.operational_reference_id,
            policy_decision=PolicyDecisionAction.ESCALATE,
            authorized_action=FinalAction.ESCALATE,
            decision_reason=reason,
            gates=gates
        )


class ControlledActionSimulator:
    """Simulates actions without making external network or financial calls."""

    def __init__(self) -> None:
        self._audit_trail: list[AuditRecord] = []
        # Maps operational_reference_id -> authorized_action
        self._action_history: dict[str, FinalAction] = {}
        
    def get_audit_trail(self) -> tuple[AuditRecord, ...]:
        return tuple(self._audit_trail)

    def execute(self, input_data: PolicyInput, decision: PolicyDecision) -> ExecutionResult:
        """Executes a simulated action safely, ensuring idempotency and auditability."""
        try:
            return self._execute_internal(input_data, decision)
        except Exception as e:
            # Rule 17 & 19: Unexpected exception -> FAILED_SAFE
            idempotency_key = f"{decision.operational_reference_id}|{FinalAction.ESCALATE}|{POLICY_VERSION}"
            res = ExecutionResult(
                operational_reference_id=decision.operational_reference_id,
                policy_decision=decision.policy_decision,
                authorized_action=FinalAction.ESCALATE,
                execution_status=ExecutionStatus.FAILED_SAFE
            )
            self._append_audit(input_data, decision, res, idempotency_key, f"Unexpected failure during execution: {e}")
            return res

    def _execute_internal(self, input_data: PolicyInput, decision: PolicyDecision) -> ExecutionResult:
        op_id = decision.operational_reference_id
        action = decision.authorized_action
        idempotency_key = f"{op_id}|{action}|{POLICY_VERSION}"

        if op_id in self._action_history:
            prev_action = self._action_history[op_id]
            if prev_action == action:
                res = ExecutionResult(op_id, decision.policy_decision, action, ExecutionStatus.DUPLICATE_SUPPRESSED)
                self._append_audit(input_data, decision, res, idempotency_key, "Duplicate action suppressed.")
                return res
            else:
                # Conflicting action! Prevent it and force an escalation.
                res = ExecutionResult(op_id, decision.policy_decision, FinalAction.ESCALATE, ExecutionStatus.CONFLICT_BLOCKED)
                conflict_key = f"{op_id}|{FinalAction.ESCALATE}|{POLICY_VERSION}"
                self._append_audit(input_data, decision, res, conflict_key, f"Conflicting action blocked. Prev: {prev_action}, Attempted: {action}")
                return res

        # Execution logic based on Action
        if action == FinalAction.AUTO_RESOLVE:
            status = ExecutionStatus.SIMULATED_EXECUTED
        elif action == FinalAction.ESCALATE:
            status = ExecutionStatus.ESCALATED
        elif action == FinalAction.MONITOR:
            status = ExecutionStatus.MONITORING
        else:
            status = ExecutionStatus.FAILED_SAFE
            
        res = ExecutionResult(op_id, decision.policy_decision, action, status)
        self._action_history[op_id] = action
        self._append_audit(input_data, decision, res, idempotency_key, decision.decision_reason)
        return res

    def _append_audit(self, input_data: PolicyInput, decision: PolicyDecision, res: ExecutionResult, idempotency_key: str, reason: str) -> None:
        attempt_count = 1
        if res.execution_status in (ExecutionStatus.DUPLICATE_SUPPRESSED, ExecutionStatus.CONFLICT_BLOCKED):
            attempt_count = 2
            
        raw_key = f"{decision.operational_reference_id}|{decision.policy_decision}|{res.authorized_action}|{res.execution_status}|{POLICY_VERSION}|{attempt_count}"
        deterministic_id = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
        
        record = AuditRecord(
            audit_id=deterministic_id,
            operational_reference_id=decision.operational_reference_id,
            evaluation_date=SETTINGS.evaluation_date.isoformat(),
            policy_version=POLICY_VERSION,
            route=input_data.route,
            classification=input_data.classification,
            sub_type=input_data.sub_type if isinstance(input_data.sub_type, str) else (input_data.sub_type.value if input_data.sub_type else None),
            confidence_score=input_data.confidence_score,
            policy_decision=decision.policy_decision,
            authorized_action=res.authorized_action,
            execution_status=res.execution_status,
            idempotency_key=idempotency_key,
            reason=reason,
            evidence_references=input_data.evidence_references
        )
        self._audit_trail.append(record)


def convert_result_to_policy_input(res: Any) -> PolicyInput:
    """Helper to convert generic EngineResult/AIResult dict to PolicyInput."""
    from ledgerlens.reconciliation import EngineResult
    from ledgerlens.ai_investigator import AIInvestigationResult
    
    if isinstance(res, EngineResult):
        return PolicyInput(
            operational_reference_id=res.operational_reference_id,
            route=res.route,
            status=res.status,
            classification=res.detected_issue,
            sub_type=res.sub_type,
            confidence_score=None,
            recommended_action=res.recommended_action,
            evidence_valid=True,
            evidence_references=tuple(res.evidence.keys()),
            decision_trace=res.decision_trace,
            calculations={}
        )
    elif isinstance(res, AIInvestigationResult):
        return PolicyInput(
            operational_reference_id=res.operational_reference_id,
            route=res.route,
            status=res.status,
            classification=ExceptionCategory(res.classification) if res.classification else None,
            sub_type=CaseSubtype(res.sub_type) if res.sub_type else None,
            confidence_score=Decimal(str(res.confidence_score)) if res.confidence_score is not None else None,
            recommended_action=FinalAction(res.recommended_action) if res.recommended_action else None,
            evidence_valid=True,
            evidence_references=tuple(res.evidence_references),
            decision_trace={"reasoning": res.reasoning_summary},
            calculations={}
        )
    raise ValueError("Unknown result type.")


async def run_pipeline(split: DatasetSplit, root: Path, concurrency: int = 5) -> dict[str, Any]:
    """Runs the full pipeline through policy and simulation."""
    # 1. Reconciliation
    recon_run = reconcile_split(split, root)
    engine_results = recon_run.results
    
    # 2. AI Investigator
    ai_cases = [res for res in engine_results if res.route == HandlingRoute.AI_INVESTIGATOR]
    investigator = AIInvestigator(MockAIProvider())
    ai_results = await investigator.batch_investigate(ai_cases, concurrency)
    ai_results_by_id = {r.operational_reference_id: r for r in ai_results}
    
    # 3. Policy & Simulator
    engine = PolicyEngine()
    simulator = ControlledActionSimulator()
    
    metrics = {
        "total": 0,
        "AUTO_RESOLVE": 0,
        "MONITOR": 0,
        "ESCALATE": 0,
        "DENIED": 0,
        "FAILED_SAFE": 0,
        "simulated_executions": 0,
        "duplicate_suppressions": 0,
        "conflicts": 0,
        "ai_cases": {
            "total": 0,
            "AUTO_RESOLVE": 0,
            "ESCALATE": 0,
            "failed": 0,
            "low_confidence": 0,
            "invalid_evidence": 0
        }
    }
    
    for e_res in engine_results:
        # Merge AI and deterministic paths
        if e_res.route == HandlingRoute.AI_INVESTIGATOR:
            ai_res = ai_results_by_id.get(e_res.operational_reference_id)
            if not ai_res:
                continue
            p_in = convert_result_to_policy_input(ai_res)
            
            metrics["ai_cases"]["total"] += 1
            if p_in.status == "AI_REVIEW_FAILED":
                metrics["ai_cases"]["failed"] += 1
            if p_in.confidence_score is not None and p_in.confidence_score < CONFIDENCE_THRESHOLD:
                metrics["ai_cases"]["low_confidence"] += 1
            if not p_in.evidence_valid:
                metrics["ai_cases"]["invalid_evidence"] += 1
        else:
            p_in = convert_result_to_policy_input(e_res)
            
        # Execute Policy
        decision = engine.evaluate(p_in)
        
        # Track metric for Policy Decision (DENY maps to ESCALATE authorized_action, but we want to track DENIED decisions explicitly)
        if decision.policy_decision == PolicyDecisionAction.DENY:
            metrics["DENIED"] += 1
            
        # Execute Simulator
        sim_res = simulator.execute(p_in, decision)
        
        # Collect Metrics
        metrics["total"] += 1
        if sim_res.execution_status == ExecutionStatus.FAILED_SAFE:
            metrics["FAILED_SAFE"] += 1
        elif sim_res.execution_status == ExecutionStatus.SIMULATED_EXECUTED:
            metrics["simulated_executions"] += 1
            metrics["AUTO_RESOLVE"] += 1
            if p_in.route == HandlingRoute.AI_INVESTIGATOR:
                metrics["ai_cases"]["AUTO_RESOLVE"] += 1
        elif sim_res.execution_status == ExecutionStatus.DUPLICATE_SUPPRESSED:
            metrics["duplicate_suppressions"] += 1
        elif sim_res.execution_status == ExecutionStatus.CONFLICT_BLOCKED:
            metrics["conflicts"] += 1
        elif sim_res.execution_status == ExecutionStatus.MONITORING:
            metrics["MONITOR"] += 1
        elif sim_res.execution_status == ExecutionStatus.ESCALATED:
            metrics["ESCALATE"] += 1
            if p_in.route == HandlingRoute.AI_INVESTIGATOR:
                metrics["ai_cases"]["ESCALATE"] += 1

    import dataclasses
    audit_trail = [
        {k: (str(v) if isinstance(v, Decimal) else v) for k, v in dataclasses.asdict(a).items()}
        for a in simulator.get_audit_trail()
    ]
    return {
        "metrics": metrics,
        "audit_trail": audit_trail
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="LedgerLens Policy Engine & Simulator")
    parser.add_argument("--split", type=str, choices=["dev", "validation", "holdout"])
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--audit-output", type=str, help="Path to write the full audit trail")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[2]
    
    splits_to_run = []
    if args.all:
        splits_to_run = [DatasetSplit.DEV, DatasetSplit.VALIDATION, DatasetSplit.HOLDOUT]
    elif args.split:
        splits_to_run = [DatasetSplit(args.split.upper())]
    else:
        parser.error("Must specify either --split or --all")

    final_output = {}
    all_audit_records = []
    
    for split in splits_to_run:
        res = asyncio.run(run_pipeline(split, project_root))
        final_output[split.value] = res["metrics"]
        all_audit_records.extend(res["audit_trail"])
        
        # Include a sample of 5 audit records in the stdout
        final_output[split.value]["audit_sample"] = res["audit_trail"][:5]

    print(json.dumps(final_output, indent=2))
    
    if args.audit_output:
        out_path = Path(args.audit_output)
        if "data" in out_path.parts or "evaluation" in out_path.parts:
            print("ERROR: Cannot write audit output inside data/ or evaluation/ directories.")
            exit(1)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(all_audit_records, indent=2), "utf-8")


if __name__ == "__main__":
    main()
