import asyncio
import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Mapping, Any, Sequence

from ledgerlens.config import HandlingRoute, ExceptionCategory, CaseSubtype, FinalAction, InternalProcessingState
from ledgerlens.reconciliation import EngineResult

logger = logging.getLogger(__name__)

@dataclass(frozen=True, slots=True)
class AIInvestigationResult:
    operational_reference_id: str
    route: str
    status: str
    classification: str | None
    sub_type: str | None
    confidence_score: float | None
    recommended_action: str
    reasoning_summary: str
    evidence_references: tuple[str, ...]
    model_metadata: Mapping[str, Any]

class AIProvider(ABC):
    @abstractmethod
    async def investigate(self, prompt: str) -> str:
        """Returns the structured JSON response from the AI model."""
        pass

class MockAIProvider(AIProvider):
    """
    A deterministic mock provider that deduces the correct answer strictly
    from operational arithmetic supplied in the prompt, without any hidden labels.
    """
    def __init__(self, override_behavior: str | None = None):
        self.override_behavior = override_behavior

    async def investigate(self, prompt: str) -> str:
        if self.override_behavior == "timeout":
            raise TimeoutError("Provider timed out")
        elif self.override_behavior == "api_error":
            raise RuntimeError("Internal Server Error")
        elif self.override_behavior == "malformed_json":
            return "{ bad json"
        elif self.override_behavior == "invalid_enum":
            return json.dumps({
                "classification": "MAGIC_CLASS",
                "sub_type": "UNKNOWN",
                "confidence_score": 0.99,
                "recommended_action": "DO_MAGIC",
                "reasoning_summary": "I am a bad mock.",
                "evidence_references": []
            })
        elif self.override_behavior == "low_confidence":
            return self._build_response("FEE_DEDUCTION", "LEDGER_MISMATCH", 0.50, "ESCALATE", "Not sure.", [])
            
        # Normal deductive behavior based ONLY on the evidence in the prompt
        try:
            payload = json.loads(prompt)
            evidence = payload.get("evidence", {})
            
            pay_obj = evidence.get("payment", [])
            payments = [pay_obj] if isinstance(pay_obj, dict) else pay_obj
            
            ledgers = evidence.get("merchant_ledger", [])
            adjustments = evidence.get("adjustments", [])
            settlements = evidence.get("bank_settlements", [])
            
            pay_amt = sum(float(p["amount"]) for p in payments) if payments else 0.0
            led_amt = sum(float(l.get("recorded_amount", l.get("amount", 0))) for l in ledgers) if ledgers else 0.0
            
            evidence_refs = []
            
            # Deduce LEDGER_MISMATCH from arithmetic:
            if ledgers and payments and abs(pay_amt - led_amt) > 0.001:
                for p in payments:
                    evidence_refs.append(p.get("rzp_id", p.get("operational_reference_id")))
                for l in ledgers:
                    evidence_refs.append(l.get("entry_id", l.get("operational_reference_id")))
                return self._build_response("FEE_DEDUCTION", "LEDGER_MISMATCH", 0.95, "ESCALATE", 
                                            "Payment and ledger amounts mismatch.", evidence_refs)
                
            # Deduce REFUND_ADJUSTMENT from arithmetic:
            if adjustments and settlements and payments:
                for a in adjustments:
                    evidence_refs.append(a.get("adjustment_id", a.get("operational_reference_id")))
                for s in settlements:
                    evidence_refs.append(s.get("settlement_id", s.get("operational_reference_id")))
                return self._build_response("FEE_DEDUCTION", "REFUND_ADJUSTMENT", 0.95, "AUTO_RESOLVE", 
                                            "Adjustment accounts for the missing funds.", evidence_refs)
                
            # Fallback if no deduction can be made
            return self._build_response("FEE_DEDUCTION", "LEDGER_MISMATCH", 0.90, "ESCALATE", 
                                        "Could not firmly deduce the situation.", [])
        except Exception as e:
            raise RuntimeError(f"Mock failure: {e}")

    def _build_response(self, cls: str, sub: str, conf: float, action: str, reasoning: str, refs: list[str]) -> str:
        return json.dumps({
            "classification": cls,
            "sub_type": sub,
            "confidence_score": conf,
            "recommended_action": action,
            "reasoning_summary": reasoning,
            "evidence_references": refs
        })

class AIInvestigator:
    def __init__(self, provider: AIProvider, confidence_threshold: float = 0.80, max_retries: int = 2):
        self.provider = provider
        self.confidence_threshold = confidence_threshold
        self.max_retries = max_retries

    def _build_prompt(self, engine_result: EngineResult) -> str:
        import dataclasses
        
        def _to_dict(obj):
            if dataclasses.is_dataclass(obj):
                return dataclasses.asdict(obj)
            elif isinstance(obj, (list, tuple)):
                return [_to_dict(x) for x in obj]
            elif isinstance(obj, dict):
                return {k: _to_dict(v) for k, v in obj.items()}
            return obj

        # STRICT ISOLATION: Explicitly construct a safe evidence package.
        # DO NOT include ground truth or hidden labels.
        safe_evidence = {
            "operational_reference_id": engine_result.operational_reference_id,
            "route": engine_result.route.value,
            "reason_for_routing": engine_result.reason_for_routing,
            "decision_trace": engine_result.decision_trace,
            "evidence": _to_dict(engine_result.evidence),
            "processing_metadata": engine_result.processing_metadata
        }
        return json.dumps(safe_evidence, default=str)

    def _validate_evidence_references(self, refs: Sequence[str], engine_result: EngineResult) -> bool:
        valid_refs = set()
        for category, items in engine_result.evidence.items():
            
            # Handle single objects directly
            if not isinstance(items, (list, tuple)):
                items = [items]
                
            for item in items:
                if hasattr(item, "rzp_id"): valid_refs.add(item.rzp_id)
                if hasattr(item, "settlement_id"): valid_refs.add(item.settlement_id)
                if hasattr(item, "adjustment_id"): valid_refs.add(item.adjustment_id)
                if hasattr(item, "entry_id"): valid_refs.add(item.entry_id)
                if hasattr(item, "operational_reference_id"): valid_refs.add(item.operational_reference_id)
                
                # If they are dicts
                if isinstance(item, dict):
                    for key in ["rzp_id", "settlement_id", "adjustment_id", "entry_id", "operational_reference_id"]:
                        if key in item:
                            valid_refs.add(item[key])
                            
        return all(r in valid_refs for r in refs if r)

    def _fallback_result(self, engine_result: EngineResult, reason: str) -> AIInvestigationResult:
        return AIInvestigationResult(
            operational_reference_id=engine_result.operational_reference_id,
            route=HandlingRoute.AI_INVESTIGATOR.value,
            status="AI_REVIEW_FAILED",
            classification=None,
            sub_type=None,
            confidence_score=None,
            recommended_action=FinalAction.ESCALATE.value,
            reasoning_summary=f"Failed safe: {reason}",
            evidence_references=(),
            model_metadata={"provider": self.provider.__class__.__name__, "attempt": self.max_retries + 1}
        )

    async def investigate_case(self, engine_result: EngineResult) -> AIInvestigationResult:
        if engine_result.route != HandlingRoute.AI_INVESTIGATOR:
            raise ValueError(f"AIInvestigator only accepts AI_INVESTIGATOR cases. Got: {engine_result.route}")

        prompt = self._build_prompt(engine_result)
        
        for attempt in range(1, self.max_retries + 2):
            try:
                response_str = await self.provider.investigate(prompt)
                parsed = json.loads(response_str)
                
                cls = parsed.get("classification")
                sub = parsed.get("sub_type")
                conf = parsed.get("confidence_score", 0.0)
                action = parsed.get("recommended_action")
                refs = parsed.get("evidence_references", [])
                
                if cls != ExceptionCategory.FEE_DEDUCTION.value:
                    raise ValueError(f"Unsupported classification: {cls}")
                if sub not in (CaseSubtype.REFUND_ADJUSTMENT.value, CaseSubtype.LEDGER_MISMATCH.value):
                    raise ValueError(f"Unsupported subtype: {sub}")
                if action not in (FinalAction.AUTO_RESOLVE.value, FinalAction.MONITOR.value, FinalAction.ESCALATE.value):
                    raise ValueError(f"Unsupported action: {action}")
                    
                if not self._validate_evidence_references(refs, engine_result):
                    raise ValueError("AI cited nonexistent evidence references")

                final_action = action
                if conf < self.confidence_threshold:
                    final_action = FinalAction.ESCALATE.value

                if sub == CaseSubtype.LEDGER_MISMATCH.value:
                    final_action = FinalAction.ESCALATE.value

                return AIInvestigationResult(
                    operational_reference_id=engine_result.operational_reference_id,
                    route=HandlingRoute.AI_INVESTIGATOR.value,
                    status="AI_REVIEW_COMPLETE",
                    classification=cls,
                    sub_type=sub,
                    confidence_score=conf,
                    recommended_action=final_action,
                    reasoning_summary=parsed.get("reasoning_summary", ""),
                    evidence_references=tuple(refs),
                    model_metadata={"provider": self.provider.__class__.__name__, "attempt": attempt}
                )

            except (json.JSONDecodeError, ValueError) as e:
                logger.warning(f"Validation error on attempt {attempt}: {e}")
                continue
            except (TimeoutError, RuntimeError) as e:
                logger.warning(f"Provider error on attempt {attempt}: {e}")
                continue

        return self._fallback_result(engine_result, "Exhausted retries due to provider errors or invalid responses.")

    async def batch_investigate(self, cases: Sequence[EngineResult], concurrency: int = 5) -> list[AIInvestigationResult]:
        semaphore = asyncio.Semaphore(concurrency)
        
        sorted_cases = sorted(cases, key=lambda c: c.operational_reference_id)
        
        async def bounded_investigate(case: EngineResult) -> AIInvestigationResult:
            async with semaphore:
                return await self.investigate_case(case)
                
        results = await asyncio.gather(*(bounded_investigate(c) for c in sorted_cases))
        return list(results)
