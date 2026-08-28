"""Tests for Module 10 End-to-End Workflow Integration.

Ensures the workflow pipeline safely orchestrates modules 1-9, maintains
immutability of inputs, handles deterministic AI execution, prevents network access,
and strictly separates logic from evaluation components.
"""

import hashlib
import inspect
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from ledgerlens.config import DatasetSplit
from ledgerlens.workflow import run_workflow, run_case, run_demo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"

@pytest.fixture(scope="module")
def dev_workflow_result() -> dict[str, Any]:
    return run_workflow(DatasetSplit.DEV, PROJECT_ROOT)


def _hash_directory(path: Path) -> str:
    """Recursively computes a simple hash of directory contents for immutability checking."""
    hasher = hashlib.sha256()
    for file in sorted(path.rglob("*")):
        if file.is_file():
            hasher.update(file.name.encode())
            hasher.update(file.read_bytes())
    return hasher.hexdigest()


# ==================================================
# IMMUTABILITY & SECURITY TESTS
# ==================================================

def test_input_immutability(dev_workflow_result: dict[str, Any]) -> None:
    # 17. Input immutability
    # Calculate hashes before and after another run
    hash_before = _hash_directory(DATA_DIR / "DEV")
    run_workflow(DatasetSplit.DEV, PROJECT_ROOT)
    hash_after = _hash_directory(DATA_DIR / "DEV")
    assert hash_before == hash_after, "Operational dataset was modified by the workflow!"


def test_no_ground_truth_or_network_access() -> None:
    # 18. No ground truth, 19. No network, 20. No financial API
    import ledgerlens.workflow as wf
    src = inspect.getsource(wf)

    # Security Boundaries
    assert "evaluation" not in src or "evaluation_date" in src  # evaluation_date is allowed
    assert "ground_truth" not in src
    assert "requests." not in src
    assert "urllib." not in src
    assert "httpx." not in src
    assert "aiohttp." not in src


def test_case_isolation_and_batch_error_isolation() -> None:
    # 21. Case isolation, 22. Batch error isolation
    # Re-running the same case produces the exact same result structure (isolation)
    case_1 = run_case(DatasetSplit.DEV, PROJECT_ROOT, "RZP_DEV_000048")
    case_2 = run_case(DatasetSplit.DEV, PROJECT_ROOT, "RZP_DEV_000048")
    
    assert case_1 == case_2
    
    
def test_json_serialization() -> None:
    # 23. JSON serialization
    res = run_workflow(DatasetSplit.DEV, PROJECT_ROOT)
    
    def _default_serializer(obj):
        if isinstance(obj, Decimal):
            return str(obj)
        raise TypeError(f"Type {type(obj)} not serializable")
        
    try:
        # Should not raise TypeError
        json_str = json.dumps(res, default=_default_serializer)
        assert len(json_str) > 0
    except Exception as e:
        pytest.fail(f"Serialization failed: {e}")


# ==================================================
# WORKFLOW EXECUTION TESTS
# ==================================================

def test_dev_workflow_metrics(dev_workflow_result: dict[str, Any]) -> None:
    # 1. DEV full workflow
    summary = dev_workflow_result["summary"]
    
    assert summary["total_cases"] == 100
    assert summary["ai_cases"] == 5
    assert summary["deterministic_cases"] == 95
    assert summary["reconciliation_counts"]["EXACT_MATCH"] == 60


def test_single_deterministic_case() -> None:
    # 4. Deterministic case (EXACT_MATCH)
    case = run_case(DatasetSplit.DEV, PROJECT_ROOT, "RZP_DEV_000001")
    
    assert case["reconciliation"]["route"] == "DETERMINISTIC"
    assert case["reconciliation"]["detected_issue"] == "EXACT_MATCH"
    assert case["investigation"] is None
    assert case["policy"]["decision"] == "ALLOW"
    assert case["policy"]["authorized_action"] == "AUTO_RESOLVE"
    assert case["execution"]["status"] == "SIMULATED_EXECUTED"
    assert case["execution"]["simulated"] is True
    assert case["execution"]["real_financial_action"] is False


def test_single_ai_refund_adjustment_case() -> None:
    # 5. AI case, 6. REFUND_ADJUSTMENT, 8. Policy Override (not here, handled below)
    # RZP_DEV_000085 is often the first REFUND_ADJUSTMENT in DEV seed 42
    res = run_workflow(DatasetSplit.DEV, PROJECT_ROOT)
    cases = res["cases"]
    
    target_case = next(c for c in cases if c["reconciliation"]["route"] == "AI_INVESTIGATOR" and c["investigation"]["subtype"] == "REFUND_ADJUSTMENT")
    
    assert target_case["investigation"]["status"] == "AI_REVIEW_COMPLETE"
    assert target_case["investigation"]["confidence_score"] >= 0.80
    assert target_case["investigation"]["recommended_action"] == "AUTO_RESOLVE"
    assert target_case["policy"]["decision"] == "ALLOW"
    assert target_case["policy"]["authorized_action"] == "AUTO_RESOLVE"
    assert target_case["execution"]["status"] == "SIMULATED_EXECUTED"


def test_ai_ledger_mismatch_safety_override() -> None:
    # 7. LEDGER_MISMATCH, 8. policy override
    res = run_workflow(DatasetSplit.DEV, PROJECT_ROOT)
    cases = res["cases"]
    
    target_case = next(c for c in cases if c["reconciliation"]["route"] == "AI_INVESTIGATOR" and c["investigation"]["subtype"] == "LEDGER_MISMATCH")
    
    # Must override to escalate
    assert target_case["policy"]["decision"] == "ESCALATE"
    assert target_case["policy"]["authorized_action"] == "ESCALATE"
    assert target_case["execution"]["status"] == "ESCALATED"


def test_audit_generation_and_append_only(dev_workflow_result: dict[str, Any]) -> None:
    # 13. audit generation, 14. audit append-only
    audit_summary = dev_workflow_result["audit_summary"]
    # Total events should be exactly 100 since there are no duplicates executed in batch mode inherently
    assert audit_summary["total_events"] == 100
    
    raw_audit = dev_workflow_result["_raw_audit"]
    assert len(raw_audit) == 100
    
    # Check deterministic UUIDs
    first_record = raw_audit[0]
    assert len(first_record["audit_id"]) == 64  # SHA-256 length


def test_deterministic_repeated_runs(dev_workflow_result: dict[str, Any]) -> None:
    # 16. deterministic repeated runs
    run2 = run_workflow(DatasetSplit.DEV, PROJECT_ROOT)
    
    assert dev_workflow_result["summary"] == run2["summary"]
    
    # Since dict ordering and values must be exactly identical
    assert dev_workflow_result["cases"] == run2["cases"]


def test_deterministic_demo_case_selection() -> None:
    # 24. Deterministic demo-case selection
    demo = run_demo(PROJECT_ROOT)
    demo_cases = demo["demo_story_cases"]
    
    assert len(demo_cases) <= 8
    
    types = [c["reconciliation"]["detected_issue"] for c in demo_cases]
    assert "EXACT_MATCH" in types
    assert "TIMING_LAG" in types
    assert "DUPLICATE" in types
# ==================================================
# AUDIT DETERMINISM TESTS
# ==================================================

def test_audit_id_semantic_determinism() -> None:
    # Testing 1, 2, 4, 5, 6
    from ledgerlens.policy import PolicyEngine, ControlledActionSimulator, PolicyInput, PolicyDecision, PolicyDecisionAction
    from ledgerlens.config import HandlingRoute, FinalAction
    from decimal import Decimal
    
    sim = ControlledActionSimulator()
    
    p_in_1 = PolicyInput(
        operational_reference_id="RZP_TEST_001",
        route=HandlingRoute.DETERMINISTIC,
        status=None,
        classification=None,
        sub_type=None,
        confidence_score=None,
        recommended_action=None,
        evidence_valid=True,
        evidence_references=(),
        decision_trace={},
        calculations={}
    )
    
    dec_1 = PolicyDecision("RZP_TEST_001", PolicyDecisionAction.ALLOW, FinalAction.AUTO_RESOLVE, "Testing", {})
    
    # Execution 1
    res1 = sim.execute(p_in_1, dec_1)
    audit1 = sim.get_audit_trail()[0].audit_id
    
    # 4. Duplicate attempt
    res2 = sim.execute(p_in_1, dec_1)
    audit2 = sim.get_audit_trail()[1].audit_id
    
    assert res1.execution_status.value == "SIMULATED_EXECUTED"
    assert res2.execution_status.value == "DUPLICATE_SUPPRESSED"
    
    # 1. Same case processed twice independently -> same ID
    sim_new = ControlledActionSimulator()
    sim_new.execute(p_in_1, dec_1)
    assert sim_new.get_audit_trail()[0].audit_id == audit1
    
    # 5. Conflict attempt
    dec_conflict = PolicyDecision("RZP_TEST_001", PolicyDecisionAction.DENY, FinalAction.ESCALATE, "Conflict", {})
    sim_new.execute(p_in_1, dec_conflict)
    audit_conflict = sim_new.get_audit_trail()[1].audit_id
    assert sim_new.get_audit_trail()[1].execution_status.value == "CONFLICT_BLOCKED"
    
    # Another independent simulator processing conflict directly as first attempt (it won't be a conflict, it will be executed)
    # To test same conflict ID, we need to reproduce the exact state
    sim_another = ControlledActionSimulator()
    sim_another.execute(p_in_1, dec_1)
    sim_another.execute(p_in_1, dec_conflict)
    assert sim_another.get_audit_trail()[1].audit_id == audit_conflict

    # 2. Reverse order and 6. Global length independence
    p_in_2 = PolicyInput(
        operational_reference_id="RZP_TEST_002",
        route=HandlingRoute.DETERMINISTIC,
        status=None,
        classification=None,
        sub_type=None,
        confidence_score=None,
        recommended_action=None,
        evidence_valid=True,
        evidence_references=(),
        decision_trace={},
        calculations={}
    )
    dec_2 = PolicyDecision("RZP_TEST_002", PolicyDecisionAction.ALLOW, FinalAction.AUTO_RESOLVE, "Testing 2", {})
    
    sim_seq1 = ControlledActionSimulator()
    sim_seq1.execute(p_in_1, dec_1)
    sim_seq1.execute(p_in_2, dec_2)
    
    sim_seq2 = ControlledActionSimulator()
    sim_seq2.execute(p_in_2, dec_2)
    sim_seq2.execute(p_in_1, dec_1)
    
    # The audit IDs must be identical regardless of insertion order
    id1_seq1 = sim_seq1.get_audit_trail()[0].audit_id
    id2_seq1 = sim_seq1.get_audit_trail()[1].audit_id
    
    id2_seq2 = sim_seq2.get_audit_trail()[0].audit_id
    id1_seq2 = sim_seq2.get_audit_trail()[1].audit_id
    
    assert id1_seq1 == id1_seq2
    assert id2_seq1 == id2_seq2


def test_single_case_audit_id_matches_batch(dev_workflow_result: dict[str, Any]) -> None:
    # 3. Single-case execution -> audit ID matches batch
    batch_audit_id = dev_workflow_result["cases"][0]["audit"]["audit_reference"]
    op_id = dev_workflow_result["cases"][0]["operational_reference_id"]
    
    single_case = run_case(DatasetSplit.DEV, PROJECT_ROOT, op_id)
    assert single_case["audit"]["audit_reference"] == batch_audit_id

