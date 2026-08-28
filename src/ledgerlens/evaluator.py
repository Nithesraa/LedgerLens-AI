import argparse
import asyncio
import json
from pathlib import Path
from dataclasses import dataclass
from typing import Any

from ledgerlens.config import DatasetSplit, ExceptionCategory, HandlingRoute, FinalAction
from ledgerlens.reconciliation import reconcile_split
from ledgerlens.ai_investigator import AIInvestigator, MockAIProvider, AIInvestigationResult

PROJECT_ROOT = Path(__file__).resolve().parents[2]

CLASSES = [
    ExceptionCategory.EXACT_MATCH.value,
    ExceptionCategory.FEE_DEDUCTION.value,
    ExceptionCategory.TIMING_LAG.value,
    ExceptionCategory.DUPLICATE.value,
    ExceptionCategory.MISSING_SETTLEMENT.value,
    ExceptionCategory.UNKNOWN_TRANSACTION.value,
]

class EvaluationError(ValueError):
    pass

def _safe_div(n: float | int, d: float | int) -> float:
    return float(n / d) if d > 0 else 0.0

@dataclass(frozen=True)
class FinalPrediction:
    operational_reference_id: str
    is_ai_routed: bool
    classification: str | None
    sub_type: str | None
    recommended_action: str | None
    ai_status: str | None
    ai_confidence: float | None

async def evaluate_split(split: DatasetSplit, concurrency: int = 5, root: Path = PROJECT_ROOT) -> dict[str, Any]:
    run = reconcile_split(split, root)
    engine_results = {r.operational_reference_id: r for r in run.results}
    
    ai_cases = [r for r in run.results if r.route == HandlingRoute.AI_INVESTIGATOR]
    
    # Run AI Investigator BEFORE touching ground truth
    investigator = AIInvestigator(MockAIProvider())
    ai_results_list = await investigator.batch_investigate(ai_cases, concurrency=concurrency)
    ai_results = {r.operational_reference_id: r for r in ai_results_list}
    
    # LOAD GROUND TRUTH
    gt_path = root / "evaluation" / split.value.lower() / "ground_truth.json"
    if not gt_path.is_file():
        raise EvaluationError(f"Ground truth file missing: {gt_path}")
        
    with gt_path.open("r", encoding="utf-8") as f:
        ground_truth = json.load(f)
    
    gt_cases = {}
    for case in ground_truth:
        ref_id = case.get("operational_reference_id")
        if not ref_id:
            raise EvaluationError("Missing operational_reference_id in ground truth")
        if ref_id in gt_cases:
            raise EvaluationError(f"Duplicate operational_reference_id in ground truth: {ref_id}")
        gt_cases[ref_id] = case
        
    engine_refs = set(engine_results.keys())
    gt_refs = set(gt_cases.keys())
    
    unmatched_engine = engine_refs - gt_refs
    unmatched_gt = gt_refs - engine_refs
    
    if unmatched_engine or unmatched_gt:
        raise EvaluationError(
            f"Join integrity failed. Unmatched engine: {len(unmatched_engine)}, "
            f"Unmatched GT: {len(unmatched_gt)}"
        )
        
    total_cases = len(engine_refs)
    
    predictions = {}
    for ref_id in engine_refs:
        engine = engine_results[ref_id]
        if engine.route == HandlingRoute.AI_INVESTIGATOR:
            ai_res = ai_results[ref_id]
            predictions[ref_id] = FinalPrediction(
                operational_reference_id=ref_id,
                is_ai_routed=True,
                classification=ai_res.classification,
                sub_type=ai_res.sub_type,
                recommended_action=ai_res.recommended_action,
                ai_status=ai_res.status,
                ai_confidence=ai_res.confidence_score
            )
        else:
            predictions[ref_id] = FinalPrediction(
                operational_reference_id=ref_id,
                is_ai_routed=False,
                classification=engine.detected_issue.value if engine.detected_issue else None,
                sub_type=engine.sub_type.value if engine.sub_type else None,
                recommended_action=engine.recommended_action.value if engine.recommended_action else None,
                ai_status=None,
                ai_confidence=None
            )
            
    det_evaluated, det_correct = 0, 0
    det_tp_fp_fn = {c: {"tp": 0, "fp": 0, "fn": 0} for c in CLASSES}
    
    ai_total, ai_success, ai_failed, ai_low_conf, ai_retries = len(ai_cases), 0, 0, 0, 0
    ai_class_correct = 0
    ai_subtype_metrics = {
        "REFUND_ADJUSTMENT": {"support": 0, "correct": 0, "action_correct": 0},
        "LEDGER_MISMATCH": {"support": 0, "correct": 0, "action_correct": 0}
    }
    ai_action_correct = 0
    ai_confidences = []
    
    e2e_class_correct, e2e_action_correct = 0, 0
    e2e_tp_fp_fn = {c: {"tp": 0, "fp": 0, "fn": 0} for c in CLASSES}
    e2e_cm = {t: {p: 0 for p in CLASSES} for t in CLASSES}
    ai_subtype_cm = {
        "REFUND_ADJUSTMENT": {"REFUND_ADJUSTMENT": 0, "LEDGER_MISMATCH": 0, "NONE": 0},
        "LEDGER_MISMATCH": {"REFUND_ADJUSTMENT": 0, "LEDGER_MISMATCH": 0, "NONE": 0}
    }
    action_cm = {
        "AUTO_RESOLVE": {"AUTO_RESOLVE": 0, "MONITOR": 0, "ESCALATE": 0, "NONE": 0},
        "MONITOR": {"AUTO_RESOLVE": 0, "MONITOR": 0, "ESCALATE": 0, "NONE": 0},
        "ESCALATE": {"AUTO_RESOLVE": 0, "MONITOR": 0, "ESCALATE": 0, "NONE": 0}
    }
    
    exact_match_total, exact_match_fp = 0, 0
    false_esc_evaluated, false_esc_count = 0, 0
    ai_auto_resolve_evaluated, ai_auto_resolve_err = 0, 0
    
    baseline_resolved = 0
    full_system_resolved = 0

    for ref_id in engine_refs:
        gt = gt_cases[ref_id]
        pred = predictions[ref_id]
        
        expected_class = gt["injected_type"]
        expected_subtype = gt.get("sub_type")
        expected_action = gt.get("expected_action")
        
        if not pred.is_ai_routed:
            baseline_resolved += 1
            full_system_resolved += 1
            det_evaluated += 1
            if pred.classification == expected_class:
                det_correct += 1
                if expected_class in det_tp_fp_fn:
                    det_tp_fp_fn[expected_class]["tp"] += 1
            else:
                if pred.classification in det_tp_fp_fn:
                    det_tp_fp_fn[pred.classification]["fp"] += 1
                if expected_class in det_tp_fp_fn:
                    det_tp_fp_fn[expected_class]["fn"] += 1
                    
        if pred.is_ai_routed:
            if pred.ai_status == "AI_REVIEW_COMPLETE":
                ai_success += 1
                full_system_resolved += 1
                if pred.ai_confidence is not None:
                    ai_confidences.append(pred.ai_confidence)
                    if pred.ai_confidence < investigator.confidence_threshold:
                        ai_low_conf += 1
            else:
                ai_failed += 1
                
            if pred.classification == expected_class:
                ai_class_correct += 1
                
            if expected_subtype in ai_subtype_metrics:
                ai_subtype_metrics[expected_subtype]["support"] += 1
                
                pred_subtype = pred.sub_type if pred.sub_type else "NONE"
                if pred_subtype in ai_subtype_cm[expected_subtype]:
                    ai_subtype_cm[expected_subtype][pred_subtype] += 1
                
                if pred.sub_type == expected_subtype:
                    ai_subtype_metrics[expected_subtype]["correct"] += 1
                    if pred.recommended_action == expected_action:
                        ai_subtype_metrics[expected_subtype]["action_correct"] += 1
                        
            if pred.recommended_action == expected_action:
                ai_action_correct += 1
                
            if pred.recommended_action == FinalAction.AUTO_RESOLVE.value:
                ai_auto_resolve_evaluated += 1
                if expected_action != FinalAction.AUTO_RESOLVE.value:
                    ai_auto_resolve_err += 1

        pred_class = pred.classification
        
        if expected_class in CLASSES and pred_class in CLASSES:
            e2e_cm[expected_class][pred_class] += 1
            
        if pred_class == expected_class:
            e2e_class_correct += 1
            if expected_class in e2e_tp_fp_fn:
                e2e_tp_fp_fn[expected_class]["tp"] += 1
        else:
            if pred_class in e2e_tp_fp_fn:
                e2e_tp_fp_fn[pred_class]["fp"] += 1
            if expected_class in e2e_tp_fp_fn:
                e2e_tp_fp_fn[expected_class]["fn"] += 1
                
        if pred.recommended_action == expected_action:
            e2e_action_correct += 1
            
        action_pred_key = pred.recommended_action if pred.recommended_action else "NONE"
        if expected_action in action_cm and action_pred_key in action_cm[expected_action]:
            action_cm[expected_action][action_pred_key] += 1
            
        if expected_class == ExceptionCategory.EXACT_MATCH.value:
            exact_match_total += 1
            if pred_class != ExceptionCategory.EXACT_MATCH.value:
                exact_match_fp += 1
                
        if expected_action == FinalAction.AUTO_RESOLVE.value:
            false_esc_evaluated += 1
            if pred.recommended_action == FinalAction.ESCALATE.value:
                false_esc_count += 1

    det_per_class = {}
    for c in CLASSES:
        tp, fp, fn = det_tp_fp_fn[c]["tp"], det_tp_fp_fn[c]["fp"], det_tp_fp_fn[c]["fn"]
        support = tp + fn
        precision = _safe_div(tp, tp + fp)
        recall = _safe_div(tp, tp + fn)
        f1 = _safe_div(2 * precision * recall, precision + recall)
        det_per_class[c] = {
            "support": support,
            "precision": precision,
            "recall": recall,
            "f1": f1
        }
        
    det_macro_p = _safe_div(sum(p["precision"] for p in det_per_class.values() if p["support"] > 0), sum(1 for p in det_per_class.values() if p["support"] > 0))
    det_macro_r = _safe_div(sum(p["recall"] for p in det_per_class.values() if p["support"] > 0), sum(1 for p in det_per_class.values() if p["support"] > 0))
    det_macro_f1 = _safe_div(sum(p["f1"] for p in det_per_class.values() if p["support"] > 0), sum(1 for p in det_per_class.values() if p["support"] > 0))

    e2e_per_class = {}
    for c in CLASSES:
        tp, fp, fn = e2e_tp_fp_fn[c]["tp"], e2e_tp_fp_fn[c]["fp"], e2e_tp_fp_fn[c]["fn"]
        support = tp + fn
        precision = _safe_div(tp, tp + fp)
        recall = _safe_div(tp, tp + fn)
        f1 = _safe_div(2 * precision * recall, precision + recall)
        e2e_per_class[c] = {
            "support": support,
            "precision": precision,
            "recall": recall,
            "f1": f1
        }
        
    e2e_macro_p = _safe_div(sum(p["precision"] for p in e2e_per_class.values() if p["support"] > 0), sum(1 for p in e2e_per_class.values() if p["support"] > 0))
    e2e_macro_r = _safe_div(sum(p["recall"] for p in e2e_per_class.values() if p["support"] > 0), sum(1 for p in e2e_per_class.values() if p["support"] > 0))
    e2e_macro_f1 = _safe_div(sum(p["f1"] for p in e2e_per_class.values() if p["support"] > 0), sum(1 for p in e2e_per_class.values() if p["support"] > 0))

    ai_conf_mean = sum(ai_confidences) / len(ai_confidences) if ai_confidences else 0.0
    ai_conf_median = sorted(ai_confidences)[len(ai_confidences)//2] if ai_confidences else 0.0
    ai_conf_min = min(ai_confidences) if ai_confidences else 0.0
    ai_conf_max = max(ai_confidences) if ai_confidences else 0.0

    return {
        "split": split.value.lower(),
        "total_cases": total_cases,
        "join_integrity": {
            "matched": total_cases,
            "unmatched_engine": 0,
            "unmatched_ground_truth": 0
        },
        "deterministic": {
            "cases": det_evaluated,
            "accuracy": _safe_div(det_correct, det_evaluated),
            "precision": det_macro_p,
            "recall": det_macro_r,
            "f1": det_macro_f1
        },
        "ai": {
            "cases": ai_total,
            "successful": ai_success,
            "failed": ai_failed,
            "low_confidence": ai_low_conf,
            "retries": ai_retries,
            "classification_accuracy": _safe_div(ai_class_correct, ai_total),
            "subtype_accuracy": _safe_div(
                sum(ai_subtype_metrics[s]["correct"] for s in ai_subtype_metrics), 
                sum(ai_subtype_metrics[s]["support"] for s in ai_subtype_metrics)
            ),
            "action_accuracy": _safe_div(ai_action_correct, ai_total),
            "failure_rate": _safe_div(ai_failed, ai_total),
            "low_confidence_rate": _safe_div(ai_low_conf, ai_total),
            "confidence_stats": {
                "mean": ai_conf_mean,
                "median": ai_conf_median,
                "min": ai_conf_min,
                "max": ai_conf_max,
                "below_threshold": ai_low_conf,
                "at_or_above_threshold": len(ai_confidences) - ai_low_conf
            },
            "subtypes": {
                s: {
                    "support": ai_subtype_metrics[s]["support"],
                    "correct": ai_subtype_metrics[s]["correct"],
                    "accuracy": _safe_div(ai_subtype_metrics[s]["correct"], ai_subtype_metrics[s]["support"]),
                    "action_accuracy": _safe_div(ai_subtype_metrics[s]["action_correct"], ai_subtype_metrics[s]["support"])
                } for s in ai_subtype_metrics
            },
            "subtype_confusion_matrix": ai_subtype_cm
        },
        "end_to_end": {
            "accuracy": _safe_div(e2e_class_correct, total_cases),
            "macro_precision": e2e_macro_p,
            "macro_recall": e2e_macro_r,
            "macro_f1": e2e_macro_f1,
            "action_accuracy": _safe_div(e2e_action_correct, total_cases),
            "classification_confusion_matrix": e2e_cm,
            "action_confusion_matrix": action_cm
        },
        "coverage": {
            "deterministic": _safe_div(baseline_resolved, total_cases),
            "ai": _safe_div(ai_success, total_cases),
            "overall": _safe_div(full_system_resolved, total_cases)
        },
        "safety": {
            "exact_match_false_positive_rate": _safe_div(exact_match_fp, exact_match_total),
            "false_escalation_rate": _safe_div(false_esc_count, false_esc_evaluated),
            "ai_auto_resolve_error_rate": _safe_div(ai_auto_resolve_err, ai_auto_resolve_evaluated)
        },
        "ai_value_add": {
            "baseline_resolved": baseline_resolved,
            "full_system_resolved": full_system_resolved,
            "additional_resolutions": ai_success,
            "additional_resolution_rate": _safe_div(ai_success, total_cases),
            "coverage_improvement": _safe_div(full_system_resolved, total_cases) - _safe_div(baseline_resolved, total_cases)
        }
    }

def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run evaluation framework.")
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--split", choices=[split.value.lower() for split in DatasetSplit])
    selection.add_argument("--all", action="store_true")
    parser.add_argument("--concurrency", type=int, default=5, help="Concurrency for AI investigator")
    options = parser.parse_args(arguments)
    
    if options.concurrency <= 0:
        print(json.dumps({"valid": False, "error": "Concurrency must be positive"}))
        return 1
    
    try:
        splits = DatasetSplit if options.all else [DatasetSplit(options.split.upper())]
        
        async def run_evals():
            return [await evaluate_split(s, options.concurrency) for s in splits]
            
        results = asyncio.run(run_evals())
        
        if options.all:
            payload = {"evaluations": results}
        else:
            payload = results[0]
            
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    except EvaluationError as e:
        print(json.dumps({"valid": False, "error": str(e)}))
        return 1

if __name__ == "__main__":
    import sys
    sys.exit(main())
