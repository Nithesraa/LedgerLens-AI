import inspect
import json
import shutil
import hashlib
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
import asyncio

from ledgerlens.config import DatasetSplit, ExceptionCategory, HandlingRoute, FinalAction
from ledgerlens.evaluator import evaluate_split, EvaluationError, _safe_div, main
from ledgerlens import reconciliation
from ledgerlens.reconciliation import EngineResult
from ledgerlens.ai_investigator import AIInvestigationResult, AIInvestigator, MockAIProvider

PROJECT_ROOT = Path(__file__).resolve().parents[1]

import stat
import os

@pytest.fixture
def isolated_op_fixture(tmp_path: Path) -> Path:
    # Instead of copying thousands of files, we just use the real ROOT for deterministic data,
    # but for tests that need isolated ground truth, we can mock `open` where appropriate.
    # Actually, for test_valid_evaluations_run, using PROJECT_ROOT directly is safe.
    return PROJECT_ROOT

# 1-3. Valid evaluations
@pytest.mark.asyncio
async def test_valid_evaluations_run() -> None:
    res = await evaluate_split(DatasetSplit.DEV, concurrency=1, root=PROJECT_ROOT)
    assert res["split"] == "dev"
    assert res["join_integrity"]["matched"] == 100

def test_missing_engine_result_fails() -> None:
    def mock_reconcile(*args, **kwargs):
        run = reconciliation.reconcile_split(DatasetSplit.DEV, PROJECT_ROOT)
        return reconciliation.ReconciliationRun(split="dev", results=run.results[:-1])
    
    with patch("ledgerlens.evaluator.reconcile_split", mock_reconcile):
        with pytest.raises(EvaluationError, match="Unmatched GT: 1"):
            asyncio.run(evaluate_split(DatasetSplit.DEV, root=PROJECT_ROOT))

def test_extra_engine_result_fails() -> None:
    def mock_reconcile(*args, **kwargs):
        run = reconciliation.reconcile_split(DatasetSplit.DEV, PROJECT_ROOT)
        extra = EngineResult(
            operational_reference_id="RZP_EXTRA", primary_txn_id=None, route=HandlingRoute.DETERMINISTIC,
            status=None, detected_issue=ExceptionCategory.EXACT_MATCH, sub_type=None,
            recommended_action=FinalAction.AUTO_RESOLVE, reason_for_routing=None, evidence={}, decision_trace={}, processing_metadata={}
        )
        return reconciliation.ReconciliationRun(split="dev", results=run.results + (extra,))
    
    with patch("ledgerlens.evaluator.reconcile_split", mock_reconcile):
        with pytest.raises(EvaluationError, match="Unmatched engine: 1"):
            asyncio.run(evaluate_split(DatasetSplit.DEV, root=PROJECT_ROOT))

def test_duplicate_ground_truth_fails(tmp_path: Path) -> None:
    gt_file = tmp_path / "ground_truth.json"
    gt = json.loads((PROJECT_ROOT / "evaluation" / "dev" / "ground_truth.json").read_text("utf-8"))
    gt.append(gt[0])
    gt_file.write_text(json.dumps(gt), "utf-8")
    
    original_open = Path.open
    def mock_is_file(*args, **kwargs): return True
    def mock_open(self, *args, **kwargs):
        if self.name == "ground_truth.json":
            return original_open(gt_file, *args, **kwargs)
        return original_open(self, *args, **kwargs)
    
    with patch("pathlib.Path.is_file", side_effect=mock_is_file):
        with patch("pathlib.Path.open", side_effect=mock_open, autospec=True):
            with pytest.raises(EvaluationError, match="Duplicate operational_reference_id"):
                asyncio.run(evaluate_split(DatasetSplit.DEV, root=PROJECT_ROOT))

@pytest.mark.asyncio
async def test_correct_metric_calculations(tmp_path: Path) -> None:
    gt_data = []
    engine_data = []
    
    # Det Correct EXACT_MATCH
    gt_data.append({"operational_reference_id": "R1", "expected_route": "DETERMINISTIC", "injected_type": "EXACT_MATCH", "expected_action": "AUTO_RESOLVE"})
    engine_data.append(EngineResult("R1", None, HandlingRoute.DETERMINISTIC, None, ExceptionCategory.EXACT_MATCH, None, FinalAction.AUTO_RESOLVE, None, {}, {}, {}))
    
    # Det FP (Det predicted FEE_DEDUCTION but was EXACT_MATCH) -> causes False Escalation + Exact Match FP
    gt_data.append({"operational_reference_id": "R2", "expected_route": "DETERMINISTIC", "injected_type": "EXACT_MATCH", "expected_action": "AUTO_RESOLVE"})
    engine_data.append(EngineResult("R2", None, HandlingRoute.DETERMINISTIC, None, ExceptionCategory.FEE_DEDUCTION, None, FinalAction.ESCALATE, None, {}, {}, {}))
    
    # AI case: Correct Refund Adjustment (FEE_DEDUCTION / REFUND_ADJUSTMENT -> AUTO_RESOLVE)
    gt_data.append({"operational_reference_id": "R3", "expected_route": "AI_INVESTIGATOR", "sub_type": "REFUND_ADJUSTMENT", "injected_type": "FEE_DEDUCTION", "expected_action": "AUTO_RESOLVE"})
    engine_data.append(EngineResult("R3", None, HandlingRoute.AI_INVESTIGATOR, None, None, None, None, None, {}, {}, {}))
    
    # AI case: Incorrect Subtype (Predicted Mismatch, GT was Refund) -> causes AI auto-resolve err or false escalation
    gt_data.append({"operational_reference_id": "R4", "expected_route": "AI_INVESTIGATOR", "sub_type": "REFUND_ADJUSTMENT", "injected_type": "FEE_DEDUCTION", "expected_action": "AUTO_RESOLVE"})
    engine_data.append(EngineResult("R4", None, HandlingRoute.AI_INVESTIGATOR, None, None, None, None, None, {}, {}, {}))
    
    # AI case: AI failed
    gt_data.append({"operational_reference_id": "R5", "expected_route": "AI_INVESTIGATOR", "sub_type": "LEDGER_MISMATCH", "injected_type": "FEE_DEDUCTION", "expected_action": "ESCALATE"})
    engine_data.append(EngineResult("R5", None, HandlingRoute.AI_INVESTIGATOR, None, None, None, None, None, {}, {}, {}))
    
    gt_file = tmp_path / "ground_truth.json"
    gt_file.write_text(json.dumps(gt_data), "utf-8")
    
    def mock_reconcile(*args, **kwargs):
        return reconciliation.ReconciliationRun(split="dev", results=tuple(engine_data))
        
    async def mock_batch_investigate(self, cases, concurrency):
        res = []
        for c in cases:
            if c.operational_reference_id == "R3":
                res.append(AIInvestigationResult("R3", "AI_INVESTIGATOR", "AI_REVIEW_COMPLETE", "FEE_DEDUCTION", "REFUND_ADJUSTMENT", 0.99, "AUTO_RESOLVE", "...", (), {}))
            elif c.operational_reference_id == "R4":
                # Falsely escalates due to mismatch
                res.append(AIInvestigationResult("R4", "AI_INVESTIGATOR", "AI_REVIEW_COMPLETE", "FEE_DEDUCTION", "LEDGER_MISMATCH", 0.99, "ESCALATE", "...", (), {}))
            elif c.operational_reference_id == "R5":
                res.append(AIInvestigationResult("R5", "AI_INVESTIGATOR", "AI_REVIEW_FAILED", None, None, None, "ESCALATE", "...", (), {}))
        return res
        
    original_open = Path.open
    def mock_is_file(*args, **kwargs): return True
    def mock_open(self, *args, **kwargs): 
        if self.name == "ground_truth.json":
            return original_open(gt_file, *args, **kwargs)
        return original_open(self, *args, **kwargs)
        
    with patch("pathlib.Path.is_file", side_effect=mock_is_file):
        with patch("pathlib.Path.open", side_effect=mock_open, autospec=True):
            with patch("ledgerlens.evaluator.reconcile_split", mock_reconcile):
                with patch.object(AIInvestigator, "batch_investigate", mock_batch_investigate):
                    res = await evaluate_split(DatasetSplit.DEV, root=PROJECT_ROOT)
                    
                    # AI cases = 3. Successful = 2, Failed = 1
                    ai = res["ai"]
                    assert ai["cases"] == 3
                    assert ai["successful"] == 2
                    assert ai["failed"] == 1
                    
                    # Subtype accuracy (only checks valid sub_types vs expected, ignoring failed which don't map cleanly to a predicted subtype string? wait, if it fails subtype is None, which != REFUND_ADJUSTMENT)
                    # R3 = correct subtype. R4 = incorrect subtype. R5 = failed (None). Total support = 3.
                    # R3 (REFUND support 1, correct 1), R4 (REFUND support 1, incorrect), R5 (MISMATCH support 1, incorrect).
                    assert ai["subtypes"]["REFUND_ADJUSTMENT"]["support"] == 2
                    assert ai["subtypes"]["REFUND_ADJUSTMENT"]["correct"] == 1
                    assert ai["subtypes"]["LEDGER_MISMATCH"]["support"] == 1
                    assert ai["subtypes"]["LEDGER_MISMATCH"]["correct"] == 0
                    
                    # Safety
                    saf = res["safety"]
                    assert saf["exact_match_false_positive_rate"] == 0.5  # 2 exact match total, 1 missed (R2)
                    assert saf["false_escalation_rate"] == 0.5 # 4 expected auto-resolve (R1, R2, R3, R4). R2 and R4 were escalated.
                    assert saf["ai_auto_resolve_error_rate"] == 0.0 # No AI case wrongly auto-resolved
                    
                    # Coverage
                    cov = res["coverage"]
                    assert cov["deterministic"] == 0.4  # R1, R2 out of 5 total
                    assert cov["ai"] == 0.4  # R3, R4 successful out of 5 total
                    assert cov["overall"] == 0.8 # R1, R2, R3, R4 resolved out of 5
                    
                    # End to end Action accuracy
                    # R1 (correct), R2 (wrong action), R3 (correct), R4 (wrong action), R5 (wrongly got ESCALATE? Wait, R5 GT=ESCALATE, and it fell back to ESCALATE safely! So R5 action is correct!)
                    e2e = res["end_to_end"]
                    assert e2e["action_accuracy"] == 0.6  # R1, R3, R5 correct out of 5
            
def test_zero_denominator_handling() -> None:
    assert _safe_div(0, 0) == 0.0
    assert _safe_div(1, 0) == 0.0
    assert _safe_div(1, 2) == 0.5

def test_ground_truth_isolation() -> None:
    src = inspect.getsource(reconciliation)
    assert "ground_truth" not in src
    assert '"evaluation/' not in src
    assert '"/evaluation' not in src
    
    src2 = inspect.getsource(AIInvestigator)
    assert "ground_truth" not in src2

def test_determinism_and_read_only() -> None:
    def get_hashes():
        return {p.as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() 
                for p in (PROJECT_ROOT / "data").rglob("*") if p.is_file()}
        
    h1 = get_hashes()
    res1 = asyncio.run(evaluate_split(DatasetSplit.DEV, root=PROJECT_ROOT))
    h2 = get_hashes()
    res2 = asyncio.run(evaluate_split(DatasetSplit.DEV, root=PROJECT_ROOT))
    h3 = get_hashes()
    
    assert res1 == res2
    assert h1 == h2 == h3

def test_cli_outputs_json(capsys) -> None:
    main(["--split", "dev"])
    out = capsys.readouterr().out
    data = json.loads(out)
    assert "total_cases" in data

@pytest.mark.asyncio
async def test_cross_case_evidence_protection() -> None:
    inv = AIInvestigator(MockAIProvider())
    
    resultA = EngineResult("A", None, HandlingRoute.AI_INVESTIGATOR, None, None, None, None, None, {"payment": [{"rzp_id": "P_A", "amount": "1"}]}, {}, {})
    resultB = EngineResult("B", None, HandlingRoute.AI_INVESTIGATOR, None, None, None, None, None, {"payment": [{"rzp_id": "P_B", "amount": "1"}]}, {}, {})
    
    # Validate evidence reference rejecting B's evidence when given A
    assert inv._validate_evidence_references(["P_A"], resultA) is True
    assert inv._validate_evidence_references(["P_B"], resultA) is False
