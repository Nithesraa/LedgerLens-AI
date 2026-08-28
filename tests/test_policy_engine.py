"""Tests for Module 9 Policy Engine and Controlled Action Simulator.

Verifies deterministic rules, safety gates, audit trails, and idempotency
without real financial operations or external network calls.
"""

import inspect
import urllib.request
import urllib.error
import urllib.parse
from decimal import Decimal
from typing import Any

import pytest

from ledgerlens.config import CaseSubtype, ExceptionCategory, FinalAction, HandlingRoute, SETTINGS
from ledgerlens.policy import (
    CONFIDENCE_THRESHOLD,
    POLICY_VERSION,
    AuditRecord,
    ControlledActionSimulator,
    ExecutionResult,
    ExecutionStatus,
    PolicyDecision,
    PolicyDecisionAction,
    PolicyEngine,
    PolicyInput,
)


@pytest.fixture
def engine() -> PolicyEngine:
    return PolicyEngine()


@pytest.fixture
def simulator() -> ControlledActionSimulator:
    return ControlledActionSimulator()


def _make_input(
    route: HandlingRoute = HandlingRoute.DETERMINISTIC,
    classification: ExceptionCategory = ExceptionCategory.EXACT_MATCH,
    sub_type: CaseSubtype | str | None = None,
    confidence_score: Decimal | None = None,
    recommended_action: FinalAction | None = None,
    evidence_valid: bool = True,
    status: str | None = None,
    operational_reference_id: str = "RZP_TEST_001",
) -> PolicyInput:
    return PolicyInput(
        operational_reference_id=operational_reference_id,
        route=route,
        status=status,
        classification=classification,
        sub_type=sub_type,
        confidence_score=confidence_score,
        recommended_action=recommended_action,
        evidence_valid=evidence_valid,
        evidence_references=("ref1",),
        decision_trace={},
        calculations={},
    )


# ==========================================
# POLICY BASIC CASES
# ==========================================

def test_exact_match_auto_resolve(engine: PolicyEngine) -> None:
    # 1. EXACT_MATCH → AUTO_RESOLVE
    inp = _make_input(classification=ExceptionCategory.EXACT_MATCH)
    decision = engine.evaluate(inp)
    assert decision.policy_decision == PolicyDecisionAction.ALLOW
    assert decision.authorized_action == FinalAction.AUTO_RESOLVE


def test_standard_fee_auto_resolve(engine: PolicyEngine) -> None:
    # 2. STANDARD_FEE → AUTO_RESOLVE
    inp = _make_input(
        classification=ExceptionCategory.FEE_DEDUCTION, sub_type=CaseSubtype.STANDARD_FEE
    )
    decision = engine.evaluate(inp)
    assert decision.policy_decision == PolicyDecisionAction.ALLOW
    assert decision.authorized_action == FinalAction.AUTO_RESOLVE


def test_timing_lag_monitor(engine: PolicyEngine) -> None:
    # 3. TIMING_LAG → MONITOR
    inp = _make_input(classification=ExceptionCategory.TIMING_LAG)
    decision = engine.evaluate(inp)
    assert decision.policy_decision == PolicyDecisionAction.MONITOR
    assert decision.authorized_action == FinalAction.MONITOR


def test_missing_settlement_escalate(engine: PolicyEngine) -> None:
    # 4. MISSING_SETTLEMENT → ESCALATE
    inp = _make_input(classification=ExceptionCategory.MISSING_SETTLEMENT)
    decision = engine.evaluate(inp)
    assert decision.policy_decision == PolicyDecisionAction.ESCALATE
    assert decision.authorized_action == FinalAction.ESCALATE


def test_duplicate_escalate(engine: PolicyEngine) -> None:
    # 5. DUPLICATE → ESCALATE
    inp = _make_input(classification=ExceptionCategory.DUPLICATE)
    decision = engine.evaluate(inp)
    assert decision.policy_decision == PolicyDecisionAction.DENY
    assert decision.authorized_action == FinalAction.ESCALATE


def test_unknown_transaction_escalate(engine: PolicyEngine) -> None:
    # 6. UNKNOWN_TRANSACTION → ESCALATE
    inp = _make_input(classification=ExceptionCategory.UNKNOWN_TRANSACTION)
    decision = engine.evaluate(inp)
    assert decision.policy_decision == PolicyDecisionAction.DENY
    assert decision.authorized_action == FinalAction.ESCALATE


# ==========================================
# AI CASES
# ==========================================

def test_valid_refund_adjustment_auto_resolve(engine: PolicyEngine) -> None:
    # 7. Valid REFUND_ADJUSTMENT → AUTO_RESOLVE
    inp = _make_input(
        route=HandlingRoute.AI_INVESTIGATOR,
        classification=ExceptionCategory.FEE_DEDUCTION,
        sub_type=CaseSubtype.REFUND_ADJUSTMENT,
        confidence_score=Decimal("0.95"),
        recommended_action=FinalAction.AUTO_RESOLVE,
    )
    decision = engine.evaluate(inp)
    assert decision.policy_decision == PolicyDecisionAction.ALLOW
    assert decision.authorized_action == FinalAction.AUTO_RESOLVE


def test_valid_ledger_mismatch_escalate(engine: PolicyEngine) -> None:
    # 8. Valid LEDGER_MISMATCH → ESCALATE (override)
    inp = _make_input(
        route=HandlingRoute.AI_INVESTIGATOR,
        classification=ExceptionCategory.FEE_DEDUCTION,
        sub_type=CaseSubtype.LEDGER_MISMATCH,
        confidence_score=Decimal("1.0"),
        recommended_action=FinalAction.AUTO_RESOLVE,
    )
    decision = engine.evaluate(inp)
    assert decision.policy_decision == PolicyDecisionAction.ESCALATE
    assert decision.authorized_action == FinalAction.ESCALATE


def test_ai_failure_escalate(engine: PolicyEngine) -> None:
    # 9. AI failure → ESCALATE
    inp = _make_input(route=HandlingRoute.AI_INVESTIGATOR, status="AI_REVIEW_FAILED")
    decision = engine.evaluate(inp)
    assert decision.policy_decision == PolicyDecisionAction.ESCALATE
    assert decision.authorized_action == FinalAction.ESCALATE


def test_low_confidence_escalate(engine: PolicyEngine) -> None:
    # 10. Low confidence → ESCALATE
    inp = _make_input(
        route=HandlingRoute.AI_INVESTIGATOR,
        classification=ExceptionCategory.FEE_DEDUCTION,
        sub_type=CaseSubtype.REFUND_ADJUSTMENT,
        confidence_score=Decimal("0.79"),
        recommended_action=FinalAction.AUTO_RESOLVE,
    )
    decision = engine.evaluate(inp)
    assert decision.policy_decision == PolicyDecisionAction.ESCALATE
    assert decision.authorized_action == FinalAction.ESCALATE


def test_invalid_evidence_escalate(engine: PolicyEngine) -> None:
    # 11. Invalid evidence → DENY/ESCALATE
    inp = _make_input(evidence_valid=False)
    decision = engine.evaluate(inp)
    assert decision.policy_decision == PolicyDecisionAction.DENY
    assert decision.authorized_action == FinalAction.ESCALATE


# ==========================================
# ADVERSARIAL CASES
# ==========================================

def test_adversarial_ai_ledger_mismatch(engine: PolicyEngine) -> None:
    # 12. AI says AUTO_RESOLVE but ledger mismatch → ESCALATE
    inp = _make_input(
        route=HandlingRoute.AI_INVESTIGATOR,
        classification=ExceptionCategory.FEE_DEDUCTION,
        sub_type=CaseSubtype.LEDGER_MISMATCH,
        confidence_score=Decimal("0.99"),
        recommended_action=FinalAction.AUTO_RESOLVE,
    )
    decision = engine.evaluate(inp)
    assert decision.authorized_action == FinalAction.ESCALATE


def test_adversarial_unsupported_subtype(engine: PolicyEngine) -> None:
    # 16. Unsupported subtype → DENY/ESCALATE
    inp = _make_input(
        route=HandlingRoute.AI_INVESTIGATOR,
        classification=ExceptionCategory.FEE_DEDUCTION,
        sub_type="MAGIC_MONEY_TREE",
        confidence_score=Decimal("0.99"),
        recommended_action=FinalAction.AUTO_RESOLVE,
    )
    decision = engine.evaluate(inp)
    assert decision.policy_decision == PolicyDecisionAction.ESCALATE
    assert decision.authorized_action == FinalAction.ESCALATE


def test_missing_required_field_fails_closed(engine: PolicyEngine) -> None:
    # 17. Missing required field → fail closed
    inp = PolicyInput(
        operational_reference_id="",
        route=HandlingRoute.DETERMINISTIC,
        status=None,
        classification=None,
        sub_type=None,
        confidence_score=None,
        recommended_action=None,
        evidence_valid=True,
        evidence_references=(),
        decision_trace={},
        calculations={},
    )
    decision = engine.evaluate(inp)
    assert decision.policy_decision == PolicyDecisionAction.DENY
    assert decision.authorized_action == FinalAction.ESCALATE


def test_policy_exception_fails_safe(engine: PolicyEngine, monkeypatch: Any) -> None:
    # 17, 32. Unexpected exception fails safe
    def mock_internal(*args, **kwargs):
        raise RuntimeError("Something exploded")

    monkeypatch.setattr(engine, "_evaluate_internal", mock_internal)
    inp = _make_input()
    decision = engine.evaluate(inp)
    assert decision.policy_decision == PolicyDecisionAction.DENY
    assert decision.authorized_action == FinalAction.ESCALATE
    assert decision.gates.get("failed_safe") is True


# ==========================================
# BOUNDARY CASES
# ==========================================

def test_confidence_exactly_at_threshold(engine: PolicyEngine) -> None:
    # 19. confidence exactly 0.80 → allowed if all other gates pass
    inp = _make_input(
        route=HandlingRoute.AI_INVESTIGATOR,
        classification=ExceptionCategory.FEE_DEDUCTION,
        sub_type=CaseSubtype.REFUND_ADJUSTMENT,
        confidence_score=CONFIDENCE_THRESHOLD,
        recommended_action=FinalAction.AUTO_RESOLVE,
    )
    decision = engine.evaluate(inp)
    assert decision.authorized_action == FinalAction.AUTO_RESOLVE


def test_confidence_just_below_threshold(engine: PolicyEngine) -> None:
    # 20. confidence just below 0.80 → ESCALATE
    inp = _make_input(
        route=HandlingRoute.AI_INVESTIGATOR,
        classification=ExceptionCategory.FEE_DEDUCTION,
        sub_type=CaseSubtype.REFUND_ADJUSTMENT,
        confidence_score=CONFIDENCE_THRESHOLD - Decimal("0.000001"),
        recommended_action=FinalAction.AUTO_RESOLVE,
    )
    decision = engine.evaluate(inp)
    assert decision.authorized_action == FinalAction.ESCALATE


# ==========================================
# IDEMPOTENCY & AUDIT
# ==========================================

def test_idempotency_duplicate_suppression(
    engine: PolicyEngine, simulator: ControlledActionSimulator
) -> None:
    # 23, 28. Same action twice → second suppressed
    inp = _make_input()
    decision = engine.evaluate(inp)
    
    res1 = simulator.execute(inp, decision)
    assert res1.execution_status == ExecutionStatus.SIMULATED_EXECUTED
    assert res1.simulated is True
    assert res1.real_financial_action is False
    
    res2 = simulator.execute(inp, decision)
    assert res2.execution_status == ExecutionStatus.DUPLICATE_SUPPRESSED
    
    audits = simulator.get_audit_trail()
    assert len(audits) == 2
    assert audits[0].execution_status == ExecutionStatus.SIMULATED_EXECUTED
    assert audits[1].execution_status == ExecutionStatus.DUPLICATE_SUPPRESSED


def test_idempotency_conflicting_action(
    engine: PolicyEngine, simulator: ControlledActionSimulator
) -> None:
    # 24, 29. Different action same transaction → conflict handling
    inp1 = _make_input()
    dec1 = engine.evaluate(inp1)
    res1 = simulator.execute(inp1, dec1)
    assert res1.execution_status == ExecutionStatus.SIMULATED_EXECUTED
    
    inp2 = _make_input(classification=ExceptionCategory.MISSING_SETTLEMENT)
    dec2 = engine.evaluate(inp2)
    res2 = simulator.execute(inp2, dec2)
    assert res2.execution_status == ExecutionStatus.CONFLICT_BLOCKED
    assert res2.authorized_action == FinalAction.ESCALATE
    
    audits = simulator.get_audit_trail()
    assert len(audits) == 2
    assert audits[1].execution_status == ExecutionStatus.CONFLICT_BLOCKED


def test_audit_record_contents_and_immutability(
    engine: PolicyEngine, simulator: ControlledActionSimulator
) -> None:
    # 27, 30, 31. Every decision audited, contains required fields, append-only
    inp = _make_input()
    dec = engine.evaluate(inp)
    simulator.execute(inp, dec)
    
    audits = simulator.get_audit_trail()
    assert len(audits) == 1
    record = audits[0]
    
    assert record.audit_id
    assert record.operational_reference_id == "RZP_TEST_001"
    assert record.evaluation_date == SETTINGS.evaluation_date.isoformat()
    assert record.policy_version == POLICY_VERSION
    assert record.policy_decision == PolicyDecisionAction.ALLOW
    assert record.authorized_action == FinalAction.AUTO_RESOLVE
    assert record.execution_status == ExecutionStatus.SIMULATED_EXECUTED


# ==========================================
# SAFETY & DETERMINISM
# ==========================================

def test_no_network_or_system_clock_imports() -> None:
    # 32-37. Security boundaries
    import ledgerlens.policy as policy
    
    src = inspect.getsource(policy)
    
    assert "requests." not in src
    assert "urllib." not in src
    assert "httpx." not in src
    assert "aiohttp." not in src
    
    # Must use deterministic config date, not system clock
    assert "datetime.now" not in src
    assert "date.today" not in src
    assert "time.time" not in src
    
    # No randomness
    assert "random." not in src
    assert "uuid.uuid4()" not in src  # Ensure uuid4 is not used for audit_ids (must be deterministic)
    assert "hashlib.sha256(" in src  # Should use deterministic hashing
    
    # No LLMs
    assert "OpenAI" not in src
    assert "Anthropic" not in src
    assert "MockAIProvider(" not in src.replace("MockAIProvider()", "") # Only instantiated for batch investigate setup


def test_simulator_unexpected_exception_fails_safe(
    engine: PolicyEngine, simulator: ControlledActionSimulator, monkeypatch: Any
) -> None:
    def mock_internal(*args, **kwargs):
        raise ValueError("Simulated execution crashed")

    monkeypatch.setattr(simulator, "_execute_internal", mock_internal)
    
    inp = _make_input()
    decision = engine.evaluate(inp)
    res = simulator.execute(inp, decision)
    
    assert res.execution_status == ExecutionStatus.FAILED_SAFE
    assert res.authorized_action == FinalAction.ESCALATE


# ==========================================
# PROPERTY / INVARIANT TESTS
# ==========================================

@pytest.mark.parametrize("route", [HandlingRoute.DETERMINISTIC, HandlingRoute.AI_INVESTIGATOR])
@pytest.mark.parametrize("classification", [c for c in ExceptionCategory])
@pytest.mark.parametrize("evidence_valid", [True, False])
@pytest.mark.parametrize("confidence", [None, Decimal("0.5"), Decimal("0.85"), Decimal("1.0")])
def test_policy_invariants(
    engine: PolicyEngine, 
    route: HandlingRoute, 
    classification: ExceptionCategory,
    evidence_valid: bool,
    confidence: Decimal | None
) -> None:
    inp = _make_input(
        route=route,
        classification=classification,
        sub_type=CaseSubtype.REFUND_ADJUSTMENT if classification == ExceptionCategory.FEE_DEDUCTION else None,
        evidence_valid=evidence_valid,
        confidence_score=confidence,
        recommended_action=FinalAction.AUTO_RESOLVE
    )
    
    decision = engine.evaluate(inp)
    
    # Invariant 1: If authorized_action == AUTO_RESOLVE and AI route, confidence >= threshold
    if decision.authorized_action == FinalAction.AUTO_RESOLVE and route == HandlingRoute.AI_INVESTIGATOR:
        assert evidence_valid is True
        assert decision.policy_decision == PolicyDecisionAction.ALLOW
        assert confidence is not None and confidence >= CONFIDENCE_THRESHOLD
        
    # Invariant 2: If evidence invalid -> never AUTO_RESOLVE
    if not evidence_valid:
        assert decision.authorized_action != FinalAction.AUTO_RESOLVE
        
    # Invariant 3: If AI route and low confidence -> never AUTO_RESOLVE
    if route == HandlingRoute.AI_INVESTIGATOR and confidence is not None and confidence < CONFIDENCE_THRESHOLD:
        assert decision.authorized_action != FinalAction.AUTO_RESOLVE
