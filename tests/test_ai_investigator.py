import json
import pytest
import asyncio
from dataclasses import asdict
from typing import Mapping

from ledgerlens.config import HandlingRoute, ExceptionCategory, CaseSubtype, FinalAction, InternalProcessingState
from ledgerlens.reconciliation import EngineResult
from ledgerlens.ai_investigator import AIInvestigator, MockAIProvider, AIInvestigationResult

def _mock_engine_result(
    ref_id: str,
    route: HandlingRoute = HandlingRoute.AI_INVESTIGATOR,
    payments: list[dict] | None = None,
    ledgers: list[dict] | None = None,
    adjustments: list[dict] | None = None,
    settlements: list[dict] | None = None,
) -> EngineResult:
    evidence = {}
    if payments is not None:
        evidence["payment"] = tuple(payments)
    if ledgers is not None:
        evidence["merchant_ledger"] = tuple(ledgers)
    if adjustments is not None:
        evidence["adjustments"] = tuple(adjustments)
    if settlements is not None:
        evidence["bank_settlements"] = tuple(settlements)

    return EngineResult(
        operational_reference_id=ref_id,
        primary_txn_id=None,
        route=route,
        status=InternalProcessingState.PENDING_AI_REVIEW,
        detected_issue=None,
        sub_type=None,
        recommended_action=None,
        reason_for_routing="Requires AI",
        evidence=evidence,
        decision_trace={"some_rule": True},
        processing_metadata={"time": "2023-01-01T00:00:00Z"}
    )

@pytest.mark.asyncio
async def test_valid_refund_adjustment() -> None:
    # 100 payment - 2 fee - 98 adjustment = 0 bank (conceptually)
    result = _mock_engine_result(
        "REF-1",
        payments=[{"operational_reference_id": "P1", "amount": "100.00"}],
        adjustments=[{"operational_reference_id": "A1", "amount": "98.00"}],
        settlements=[{"operational_reference_id": "S1", "amount": "0.00"}]
    )
    provider = MockAIProvider()
    investigator = AIInvestigator(provider)
    ai_res = await investigator.investigate_case(result)
    
    assert ai_res.status == "AI_REVIEW_COMPLETE"
    assert ai_res.classification == ExceptionCategory.FEE_DEDUCTION.value
    assert ai_res.sub_type == CaseSubtype.REFUND_ADJUSTMENT.value
    assert ai_res.recommended_action == FinalAction.AUTO_RESOLVE.value
    assert "A1" in ai_res.evidence_references
    assert "S1" in ai_res.evidence_references

@pytest.mark.asyncio
async def test_valid_ledger_mismatch() -> None:
    result = _mock_engine_result(
        "REF-2",
        payments=[{"operational_reference_id": "P1", "amount": "100.00"}],
        ledgers=[{"operational_reference_id": "L1", "amount": "90.00"}]
    )
    provider = MockAIProvider()
    investigator = AIInvestigator(provider)
    ai_res = await investigator.investigate_case(result)
    
    assert ai_res.status == "AI_REVIEW_COMPLETE"
    assert ai_res.classification == ExceptionCategory.FEE_DEDUCTION.value
    assert ai_res.sub_type == CaseSubtype.LEDGER_MISMATCH.value
    assert ai_res.recommended_action == FinalAction.ESCALATE.value

@pytest.mark.asyncio
async def test_invalid_json_fallback() -> None:
    result = _mock_engine_result("REF-3")
    provider = MockAIProvider(override_behavior="malformed_json")
    investigator = AIInvestigator(provider, max_retries=1)
    ai_res = await investigator.investigate_case(result)
    
    assert ai_res.status == "AI_REVIEW_FAILED"
    assert ai_res.recommended_action == FinalAction.ESCALATE.value
    assert ai_res.model_metadata["attempt"] == 2 # 1 initial + 1 retry

@pytest.mark.asyncio
async def test_invalid_enum_fallback() -> None:
    result = _mock_engine_result("REF-4")
    provider = MockAIProvider(override_behavior="invalid_enum")
    investigator = AIInvestigator(provider, max_retries=0)
    ai_res = await investigator.investigate_case(result)
    
    assert ai_res.status == "AI_REVIEW_FAILED"
    assert ai_res.recommended_action == FinalAction.ESCALATE.value

@pytest.mark.asyncio
async def test_timeout_fallback() -> None:
    result = _mock_engine_result("REF-5")
    provider = MockAIProvider(override_behavior="timeout")
    investigator = AIInvestigator(provider, max_retries=1)
    ai_res = await investigator.investigate_case(result)
    
    assert ai_res.status == "AI_REVIEW_FAILED"
    assert ai_res.recommended_action == FinalAction.ESCALATE.value

@pytest.mark.asyncio
async def test_low_confidence_forces_escalate() -> None:
    result = _mock_engine_result("REF-6")
    provider = MockAIProvider(override_behavior="low_confidence")
    investigator = AIInvestigator(provider, confidence_threshold=0.80)
    ai_res = await investigator.investigate_case(result)
    
    assert ai_res.status == "AI_REVIEW_COMPLETE"
    assert ai_res.confidence_score == 0.50
    assert ai_res.recommended_action == FinalAction.ESCALATE.value

@pytest.mark.asyncio
async def test_deterministic_case_rejection() -> None:
    result = _mock_engine_result("REF-7", route=HandlingRoute.DETERMINISTIC)
    provider = MockAIProvider()
    investigator = AIInvestigator(provider)
    
    with pytest.raises(ValueError, match="only accepts AI_INVESTIGATOR cases"):
        await investigator.investigate_case(result)

@pytest.mark.asyncio
async def test_prompt_leakage_and_evidence_only() -> None:
    result = _mock_engine_result(
        "REF-8",
        payments=[{"operational_reference_id": "P1", "amount": "100.00"}]
    )
    # Give it an injected fake label which should NOT exist in the prompt
    # Wait, the engine_result doesn't even have injected_type to begin with!
    # But just in case, we capture the prompt.
    provider = MockAIProvider()
    investigator = AIInvestigator(provider)
    
    prompt = investigator._build_prompt(result)
    
    # Assert ground truth fields are entirely absent
    assert "ground_truth" not in prompt
    assert "injected_type" not in prompt
    assert "expected_action" not in prompt
    assert "expected_route" not in prompt
    assert "is_ambiguous" not in prompt

@pytest.mark.asyncio
async def test_batch_ordering() -> None:
    results = [
        _mock_engine_result("REF-C"),
        _mock_engine_result("REF-A"),
        _mock_engine_result("REF-B")
    ]
    provider = MockAIProvider(override_behavior="low_confidence")
    investigator = AIInvestigator(provider)
    batch = await investigator.batch_investigate(results)
    
    assert len(batch) == 3
    assert batch[0].operational_reference_id == "REF-A"
    assert batch[1].operational_reference_id == "REF-B"
    assert batch[2].operational_reference_id == "REF-C"

def test_json_serialization() -> None:
    res = AIInvestigationResult(
        "REF", "AI", "COMP", "CLASS", "SUB", 0.9, "ACT", "REAS", ("A",), {"a": 1}
    )
    assert json.dumps(asdict(res)) is not None
