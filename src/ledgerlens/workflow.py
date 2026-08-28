"""Module 10: End-to-End Workflow Integration / Demo Pipeline.

This module orchestrates the complete LedgerLens pipeline from validation
to action simulation, strictly enforcing safety boundaries and generating
a unified JSON payload for the demo.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import logging
from decimal import Decimal
from pathlib import Path
from typing import Any, Sequence

from ledgerlens.config import (
    SETTINGS,
    DatasetSplit,
    ExceptionCategory,
    FinalAction,
    HandlingRoute,
)
from ledgerlens.validator import validate_split
from ledgerlens.reconciliation import reconcile_split, EngineResult
from ledgerlens.ai_investigator import AIInvestigator, MockAIProvider, AIInvestigationResult
from ledgerlens.policy import (
    PolicyEngine,
    ControlledActionSimulator,
    convert_result_to_policy_input,
    PolicyInput,
    PolicyDecision,
    ExecutionResult,
)


def _build_unified_case(
    engine_res: EngineResult,
    ai_res: AIInvestigationResult | None,
    p_in: PolicyInput,
    decision: PolicyDecision,
    sim_res: ExecutionResult,
    audit_id: str,
) -> dict[str, Any]:
    """Constructs the unified JSON output for a single processed case."""
    
    # Calculate simple evidence summary deterministically
    payment_amount = 0.0
    if engine_res.evidence.get("payment"):
        payments = engine_res.evidence["payment"]
        if not isinstance(payments, (list, tuple)):
            payments = [payments]
        payment_amount = sum(float(p.get("amount", 0.0)) for p in payments if isinstance(p, dict) and "amount" in p)
        
    ledger_amount = 0.0
    if engine_res.evidence.get("merchant_ledger"):
        ledgers = engine_res.evidence["merchant_ledger"]
        if not isinstance(ledgers, (list, tuple)):
            ledgers = [ledgers]
        for l in ledgers:
            if isinstance(l, dict):
                if "recorded_amount" in l:
                    ledger_amount += float(l["recorded_amount"])
                elif "amount" in l:
                    ledger_amount += float(l["amount"])

    unified = {
        "operational_reference_id": engine_res.operational_reference_id,
        "evidence_summary": {
            "payment_amount": payment_amount,
            "ledger_amount": ledger_amount
        },
        "reconciliation": {
            "route": engine_res.route.value,
            "detected_issue": engine_res.detected_issue.value if engine_res.detected_issue else None,
            "subtype": engine_res.sub_type.value if engine_res.sub_type else None,
            "decision_trace": engine_res.decision_trace
        },
        "investigation": None,
        "policy": {
            "decision": decision.policy_decision.value,
            "authorized_action": decision.authorized_action.value,
            "reason": decision.decision_reason,
            "gates": decision.gates,
            "policy_version": decision.policy_version
        },
        "execution": {
            "status": sim_res.execution_status.value,
            "simulated": sim_res.simulated,
            "real_financial_action": sim_res.real_financial_action,
        },
        "audit": {
            "audit_reference": audit_id
        }
    }

    if ai_res:
        unified["investigation"] = {
            "status": ai_res.status,
            "subtype": ai_res.sub_type,
            "confidence_score": ai_res.confidence_score,
            "recommended_action": ai_res.recommended_action,
            "reasoning": ai_res.reasoning_summary,
            "evidence_references": ai_res.evidence_references
        }
    return unified


async def _run_workflow_internal(split: DatasetSplit, root: Path, concurrency: int = 5) -> dict[str, Any]:
    """Core workflow logic separating validation, reconciliation, AI, and Policy."""
    # 1. Validation (fails fast if corrupt)
    validate_split(split, root)

    # 2. Reconciliation Engine
    recon_run = reconcile_split(split, root)
    engine_results = recon_run.results

    # 3. AI Investigator (only for routed cases)
    ai_cases = [res for res in engine_results if res.route == HandlingRoute.AI_INVESTIGATOR]
    investigator = AIInvestigator(MockAIProvider())
    ai_results = await investigator.batch_investigate(ai_cases, concurrency)
    ai_results_by_id = {r.operational_reference_id: r for r in ai_results}

    # 4. Policy Engine and Simulator
    policy_engine = PolicyEngine()
    simulator = ControlledActionSimulator()

    metrics = {
        "total_cases": 0,
        "deterministic_cases": 0,
        "ai_cases": 0,
        "reconciliation_counts": {c.value: 0 for c in ExceptionCategory},
        "ai": {
            "ai_success": 0,
            "ai_failed": 0,
            "ai_low_confidence": 0
        },
        "policy": {
            "ALLOW": 0,
            "DENY": 0,
            "MONITOR": 0,
            "ESCALATE": 0
        },
        "execution": {
            "SIMULATED_EXECUTED": 0,
            "DUPLICATE_SUPPRESSED": 0,
            "CONFLICT_BLOCKED": 0,
            "FAILED_SAFE": 0,
            "ESCALATED": 0,
            "MONITORING": 0,
            "AUTHORIZED": 0,
            "DENIED": 0
        }
    }

    unified_cases = []

    # Process all cases in deterministic order based on reference ID
    sorted_engine_results = sorted(engine_results, key=lambda x: x.operational_reference_id)
    
    for e_res in sorted_engine_results:
        metrics["total_cases"] += 1
        if e_res.detected_issue:
            metrics["reconciliation_counts"][e_res.detected_issue.value] += 1

        ai_res = None
        if e_res.route == HandlingRoute.AI_INVESTIGATOR:
            metrics["ai_cases"] += 1
            ai_res = ai_results_by_id.get(e_res.operational_reference_id)
            if not ai_res:
                continue
            
            p_in = convert_result_to_policy_input(ai_res)
            if p_in.status == "AI_REVIEW_COMPLETE" and p_in.confidence_score is not None and p_in.confidence_score >= Decimal("0.80"):
                metrics["ai"]["ai_success"] += 1
            elif p_in.status == "AI_REVIEW_FAILED":
                metrics["ai"]["ai_failed"] += 1
            else:
                metrics["ai"]["ai_low_confidence"] += 1
        else:
            metrics["deterministic_cases"] += 1
            p_in = convert_result_to_policy_input(e_res)
        
        # Policy Evaluation
        decision = policy_engine.evaluate(p_in)
        metrics["policy"][decision.policy_decision.value] += 1

        # Execution Simulation
        # Track initial audit size to find the exact audit_id generated
        initial_audit_count = len(simulator.get_audit_trail())
        sim_res = simulator.execute(p_in, decision)
        
        metrics["execution"][sim_res.execution_status.value] += 1

        # Fetch Audit ID generated by simulator
        audit_trail = simulator.get_audit_trail()
        audit_id = audit_trail[-1].audit_id if len(audit_trail) > initial_audit_count else "unknown"

        unified_cases.append(_build_unified_case(e_res, ai_res, p_in, decision, sim_res, audit_id))

    raw_audit = [dataclasses.asdict(a) for a in simulator.get_audit_trail()]
    
    return {
        "run_metadata": {
            "workflow_version": "1",
            "split": split.value,
            "evaluation_date": SETTINGS.evaluation_date.isoformat()
        },
        "summary": metrics,
        "cases": unified_cases,
        "audit_summary": {
            "total_events": len(raw_audit)
        },
        "_raw_audit": raw_audit
    }


def run_workflow(split: DatasetSplit, root: Path) -> dict[str, Any]:
    """Synchronous wrapper for the full workflow pipeline."""
    return asyncio.run(_run_workflow_internal(split, root))


def run_case(split: DatasetSplit, root: Path, reference: str) -> dict[str, Any]:
    """Runs the workflow but filters output exclusively for a single reference ID."""
    result = run_workflow(split, root)
    target_case = next((c for c in result["cases"] if c["operational_reference_id"] == reference), None)
    
    if not target_case:
        raise ValueError(f"Case {reference} not found in split {split.value}")
        
    return target_case


def run_demo(root: Path) -> dict[str, Any]:
    """Runs the DEV workflow and selects 8 representative cases for a demo story."""
    result = run_workflow(DatasetSplit.DEV, root)
    cases = result["cases"]
    
    demo_cases = []
    
    def _find_first(condition) -> dict[str, Any] | None:
        return next((c for c in cases if condition(c)), None)
        
    # 1. EXACT_MATCH
    c1 = _find_first(lambda c: c["reconciliation"]["detected_issue"] == "EXACT_MATCH")
    if c1: demo_cases.append(c1)
    
    # 2. STANDARD_FEE
    c2 = _find_first(lambda c: c["reconciliation"]["detected_issue"] == "FEE_DEDUCTION" and c["reconciliation"]["route"] == "DETERMINISTIC")
    if c2: demo_cases.append(c2)
    
    # 3. TIMING_LAG
    c3 = _find_first(lambda c: c["reconciliation"]["detected_issue"] == "TIMING_LAG")
    if c3: demo_cases.append(c3)
    
    # 4. MISSING_SETTLEMENT
    c4 = _find_first(lambda c: c["reconciliation"]["detected_issue"] == "MISSING_SETTLEMENT")
    if c4: demo_cases.append(c4)
    
    # 5. DUPLICATE
    c5 = _find_first(lambda c: c["reconciliation"]["detected_issue"] == "DUPLICATE")
    if c5: demo_cases.append(c5)
    
    # 6. UNKNOWN_TRANSACTION
    c6 = _find_first(lambda c: c["reconciliation"]["detected_issue"] == "UNKNOWN_TRANSACTION")
    if c6: demo_cases.append(c6)
    
    # 7. REFUND_ADJUSTMENT (AI case)
    c7 = _find_first(lambda c: c["reconciliation"]["route"] == "AI_INVESTIGATOR" and c["investigation"] and c["investigation"]["subtype"] == "REFUND_ADJUSTMENT" and c["policy"]["decision"] == "ALLOW")
    if c7: demo_cases.append(c7)
    
    # 8. LEDGER_MISMATCH (AI safety override)
    c8 = _find_first(lambda c: c["reconciliation"]["route"] == "AI_INVESTIGATOR" and c["investigation"] and c["investigation"]["subtype"] == "LEDGER_MISMATCH" and c["policy"]["decision"] == "ESCALATE")
    if c8: demo_cases.append(c8)
    
    return {
        "run_metadata": result["run_metadata"],
        "summary": result["summary"],
        "demo_story_cases": demo_cases
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="LedgerLens End-to-End Workflow")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--split", type=str, choices=["dev", "validation", "holdout"], help="Run full batch workflow for a split")
    group.add_argument("--case", type=str, help="Run single case. Format: RZP_DEV_XXXXX")
    group.add_argument("--demo", action="store_true", help="Run the DEV split and display exactly 8 representative cases")
    
    parser.add_argument("--audit-output", type=str, help="Save complete audit trail to file (only works with --split)")
    
    args = parser.parse_args()
    project_root = Path(__file__).resolve().parents[2]
    
    def _default_serializer(obj):
        from decimal import Decimal
        if isinstance(obj, Decimal):
            return str(obj)
        raise TypeError(f"Type {type(obj)} not serializable")
    
    try:
        if args.demo:
            out = run_demo(project_root)
            print(json.dumps(out, indent=2, default=_default_serializer))
        elif args.case:
            # Infer split from case ID (e.g. RZP_DEV_000048 -> dev)
            parts = args.case.split("_")
            if len(parts) != 3 or parts[1] not in ["DEV", "VALIDATION", "HOLDOUT"]:
                print("ERROR: --case argument must be formatted like RZP_DEV_XXXXX")
                return 1
            split = DatasetSplit(parts[1])
            out = run_case(split, project_root, args.case)
            print(json.dumps(out, indent=2, default=_default_serializer))
        elif args.split:
            split = DatasetSplit(args.split.upper())
            out = run_workflow(split, project_root)
            
            raw_audit = out.pop("_raw_audit")
            
            # Print without full audit trail
            print(json.dumps(out, indent=2, default=_default_serializer))
            
            if args.audit_output:
                out_path = Path(args.audit_output)
                if "data" in out_path.parts or "evaluation" in out_path.parts:
                    print("ERROR: Cannot write audit output inside data/ or evaluation/ directories.")
                    return 1
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(json.dumps(raw_audit, indent=2, default=_default_serializer), "utf-8")
                
        return 0
    except Exception as e:
        print(f"Workflow execution failed: {e}")
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
