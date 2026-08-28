import csv
import json
import shutil
import hashlib
from pathlib import Path
from decimal import Decimal
import time
import random
import copy
from datetime import datetime, date

import pytest
from ledgerlens.config import DatasetSplit, ExceptionCategory, FinalAction, HandlingRoute, InternalProcessingState, CaseSubtype
from ledgerlens.reconciliation import (
    reconcile_split,
    OperationalDataError,
    EngineResult,
    load_operational_dataset,
    _reconcile_reference,
    amounts_within_tolerance,
    calculate_configured_fee,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]

@pytest.fixture
def op_fixture(tmp_path: Path) -> Path:
    shutil.copytree(PROJECT_ROOT / "data" / "dev", tmp_path / "data" / "dev")
    return tmp_path

def _csv_rows(root: Path, filename: str) -> tuple[list[dict[str, str]], list[str]]:
    path = root / "data" / "dev" / filename
    if not path.exists():
        return [], []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return list(reader), list(reader.fieldnames or [])

def _write_csv(root: Path, filename: str, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    path = root / "data" / "dev" / filename
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

def _get_case(root: Path, category: str = None, subtype: str = None) -> dict[str, object]:
    rows = json.loads((PROJECT_ROOT / "evaluation" / "dev" / "ground_truth.json").read_text(encoding="utf-8"))
    return next(
        row for row in rows
        if (category is None or row["injected_type"] == category)
        and (subtype is None or row["sub_type"] == subtype)
    )

def _get_reference(root: Path, category: str = None, subtype: str = None) -> str:
    return str(_get_case(root, category, subtype)["operational_reference_id"])

def _update_csv(root: Path, filename: str, reference: str, **kwargs) -> None:
    rows, fields = _csv_rows(root, filename)
    for row in rows:
        if row.get("rzp_id") == reference or (filename == "bank_settlements.csv" and row.get("rzp_id") == reference):
            for k, v in kwargs.items():
                row[k] = v
    _write_csv(root, filename, rows, fields)

def _add_csv_row(root: Path, filename: str, row: dict[str, str]) -> None:
    rows, fields = _csv_rows(root, filename)
    rows.append(row)
    _write_csv(root, filename, rows, fields)

def _remove_csv_row(root: Path, filename: str, reference: str) -> None:
    rows, fields = _csv_rows(root, filename)
    rows = [r for r in rows if r.get("rzp_id") != reference]
    _write_csv(root, filename, rows, fields)

def _result(root: Path, reference: str) -> EngineResult:
    run = reconcile_split(DatasetSplit.DEV, root)
    return next(r for r in run.results if r.operational_reference_id == reference)

# --- TEST GROUP 4: PRIORITY ORDER (ADVERSARIAL CASES) ---

def test_priority_ledger_mismatch_plus_adjustment(op_fixture: Path) -> None:
    # 1. ledger mismatch + adjustment -> AI_INVESTIGATOR (ledger_mismatch_requires_investigation)
    # Actually wait, let's see which one takes priority. 
    # If both ledger mismatch and adjustment exist, we expect AI_INVESTIGATOR.
    # The reason_for_routing could be ledger_mismatch since it's checked first in _reconcile_reference.
    reference = _get_reference(op_fixture, subtype='REFUND_ADJUSTMENT')
    # Introduce ledger mismatch
    _update_csv(op_fixture, 'merchant_ledger.csv', reference, recorded_amount='99999.99')
    r = _result(op_fixture, reference)
    assert r.route == HandlingRoute.AI_INVESTIGATOR
    assert r.reason_for_routing == 'ledger_mismatch_requires_investigation'

def test_priority_duplicate_plus_ledger_mismatch(op_fixture: Path) -> None:
    # 2. duplicate settlement + ledger mismatch -> DUPLICATE
    reference = _get_reference(op_fixture, category='DUPLICATE')
    _update_csv(op_fixture, 'merchant_ledger.csv', reference, recorded_amount='99999.99')
    r = _result(op_fixture, reference)
    assert r.route == HandlingRoute.DETERMINISTIC
    assert r.detected_issue == ExceptionCategory.DUPLICATE
    assert r.recommended_action == FinalAction.ESCALATE

def test_priority_unknown_transaction_plus_duplicate_settlements(op_fixture: Path) -> None:
    # 3. unknown transaction + duplicate bank settlements -> UNKNOWN_TRANSACTION
    # Note: wait, if payment doesn't exist, it's UNKNOWN. If there are multiple settlements, does it become DUPLICATE?
    # According to priority: Unknown transaction (payment is None) is checked before DUPLICATE.
    reference = _get_reference(op_fixture, category='UNKNOWN_TRANSACTION')

    # Add a duplicate settlement
    rows, fields = _csv_rows(op_fixture, 'bank_settlements.csv')
    base_row = next(r for r in rows if r['rzp_id'] == reference)
    dup_row = base_row.copy()
    dup_row['settlement_id'] = dup_row['settlement_id'] + '_DUP'
    _add_csv_row(op_fixture, 'bank_settlements.csv', dup_row)

    r = _result(op_fixture, reference)
    assert r.route == HandlingRoute.DETERMINISTIC
    assert r.detected_issue == ExceptionCategory.UNKNOWN_TRANSACTION
    assert r.recommended_action == FinalAction.ESCALATE


# --- TEST GROUP 1: MONETARY EDGE CASES ---

def test_monetary_exact_tolerance_boundary(op_fixture: Path) -> None:
    # 3. Amounts exactly at monetary tolerance.
    reference = _get_reference(op_fixture, category='EXACT_MATCH')
    # EXACT_MATCH has payment == ledger == settlement.
    # We will modify settlement by exactly +0.01 (tolerance)
    rows, _ = _csv_rows(op_fixture, 'payments.csv')
    payment_amt = Decimal(next(r['amount'] for r in rows if r['rzp_id'] == reference))
    new_settlement = str(payment_amt + Decimal('0.01'))

    _update_csv(op_fixture, 'bank_settlements.csv', reference, settled_amount=new_settlement)
    r = _result(op_fixture, reference)
    assert r.detected_issue == ExceptionCategory.EXACT_MATCH

def test_monetary_just_above_tolerance_boundary(op_fixture: Path) -> None:
    # 5. Amounts just above tolerance.
    reference = _get_reference(op_fixture, category='EXACT_MATCH')
    rows, _ = _csv_rows(op_fixture, 'payments.csv')
    payment_amt = Decimal(next(r['amount'] for r in rows if r['rzp_id'] == reference))
    new_settlement = str(payment_amt + Decimal('0.02'))

    _update_csv(op_fixture, 'bank_settlements.csv', reference, settled_amount=new_settlement)
    r = _result(op_fixture, reference)
    # This should be unexplained financial difference -> AI_INVESTIGATOR
    assert r.route == HandlingRoute.AI_INVESTIGATOR
    assert r.reason_for_routing == 'unexplained_financial_difference_requires_investigation'

def test_monetary_fee_rounding_boundaries(op_fixture: Path) -> None:
    # 6. Fee rounding boundaries.
    # If payment amount is 1.25, 2% fee is 0.025. ROUND_HALF_UP gives 0.03
    # 1.25 - 0.03 = 1.22 expected settlement.
    reference = _get_reference(op_fixture, category='EXACT_MATCH')
    _update_csv(op_fixture, 'payments.csv', reference, amount='1.25')
    _update_csv(op_fixture, 'merchant_ledger.csv', reference, recorded_amount='1.25')
    _update_csv(op_fixture, 'bank_settlements.csv', reference, settled_amount='1.22')

    r = _result(op_fixture, reference)
    assert r.detected_issue == ExceptionCategory.FEE_DEDUCTION
    assert r.sub_type == CaseSubtype.STANDARD_FEE

def test_monetary_excessive_precision_fails(op_fixture: Path) -> None:
    # 8. Decimal values with excessive precision.
    reference = _get_reference(op_fixture, category='EXACT_MATCH')
    _update_csv(op_fixture, 'payments.csv', reference, amount='10.123')

    with pytest.raises(OperationalDataError, match='exact monetary representation'):
        _result(op_fixture, reference)

def test_monetary_negative_fails(op_fixture: Path) -> None:
    # 11. Negative/invalid monetary input.
    reference = _get_reference(op_fixture, category='EXACT_MATCH')
    _update_csv(op_fixture, 'payments.csv', reference, amount='-10.00')

    with pytest.raises(OperationalDataError, match='exact monetary representation|must be a positive'):
        _result(op_fixture, reference)

def test_monetary_multiple_adjustments_exact(op_fixture: Path) -> None:
    # 10. Multiple adjustments whose total must be calculated exactly.
    reference = _get_reference(op_fixture, category='EXACT_MATCH')

    # Let's say payment is 100.00. Fee is 2.00.
    # If we add 3 adjustments: 1.00, 1.00, 1.00 -> total 3.00.
    # Expected settlement = 100.00 - 2.00 - 3.00 = 95.00
    _update_csv(op_fixture, 'payments.csv', reference, amount='100.00')
    _update_csv(op_fixture, 'merchant_ledger.csv', reference, recorded_amount='100.00')
    _update_csv(op_fixture, 'bank_settlements.csv', reference, settled_amount='95.00')

    _add_csv_row(op_fixture, 'adjustments.csv', {'adjustment_id': 'ADJ_1', 'rzp_id': reference, 'adjustment_type': 'refund', 'amount': '1.00', 'adjustment_date': '2025-01-01', 'reference_id': 'REF_1'})
    _add_csv_row(op_fixture, 'adjustments.csv', {'adjustment_id': 'ADJ_2', 'rzp_id': reference, 'adjustment_type': 'refund', 'amount': '1.00', 'adjustment_date': '2025-01-01', 'reference_id': 'REF_2'})
    _add_csv_row(op_fixture, 'adjustments.csv', {'adjustment_id': 'ADJ_3', 'rzp_id': reference, 'adjustment_type': 'refund', 'amount': '1.00', 'adjustment_date': '2025-01-01', 'reference_id': 'REF_3'})

    r = _result(op_fixture, reference)
    assert r.route == HandlingRoute.AI_INVESTIGATOR
    assert r.reason_for_routing == 'fee_and_adjustment_require_investigation'
    assert r.decision_trace['adjustment_count'] == 3


# --- TEST GROUP 2: DATE/TIME EDGE CASES ---

def test_date_boundary_exactly_on_window(op_fixture: Path) -> None:
    # 1. Payment age exactly equal to settlement window.
    reference = _get_reference(op_fixture, category='MISSING_SETTLEMENT')
    _remove_csv_row(op_fixture, 'bank_settlements.csv', reference)
    # Window is 3 days. Evaluation date is 2025-01-31.
    # 2025-01-31 - 3 days = 2025-01-28.
    _update_csv(op_fixture, 'payments.csv', reference, created_at='2025-01-28T10:00:00+05:30')
    r = _result(op_fixture, reference)
    assert r.detected_issue == ExceptionCategory.TIMING_LAG

def test_date_boundary_one_day_above(op_fixture: Path) -> None:
    # 3. Payment age one day above the window.
    reference = _get_reference(op_fixture, category='MISSING_SETTLEMENT')
    _remove_csv_row(op_fixture, 'bank_settlements.csv', reference)
    _update_csv(op_fixture, 'payments.csv', reference, created_at='2025-01-27T10:00:00+05:30')
    r = _result(op_fixture, reference)
    assert r.detected_issue == ExceptionCategory.MISSING_SETTLEMENT

def test_date_invalid_timestamp_fails(op_fixture: Path) -> None:
    # 6. Invalid timestamp.
    reference = _get_reference(op_fixture, category='EXACT_MATCH')
    _update_csv(op_fixture, 'payments.csv', reference, created_at='NOT_A_DATE')
    with pytest.raises(OperationalDataError):
        _result(op_fixture, reference)

# --- TEST GROUP 3: STRUCTURAL EDGE CASES ---

def test_structural_missing_ledger_fails(op_fixture: Path) -> None:
    reference = _get_reference(op_fixture, category='EXACT_MATCH')
    _remove_csv_row(op_fixture, 'merchant_ledger.csv', reference)
    with pytest.raises(OperationalDataError, match='ledger reference has no payment|payment must have exactly one ledger entry'):
        _result(op_fixture, reference)

def test_structural_duplicate_ledger_fails(op_fixture: Path) -> None:
    reference = _get_reference(op_fixture, category='EXACT_MATCH')
    rows, _ = _csv_rows(op_fixture, 'merchant_ledger.csv')
    base_row = next(r for r in rows if r['rzp_id'] == reference)
    dup = base_row.copy()
    dup['entry_id'] = dup['entry_id'] + '_DUP'
    _add_csv_row(op_fixture, 'merchant_ledger.csv', dup)
    with pytest.raises(OperationalDataError, match='payment has conflicting ledger entries'):
        _result(op_fixture, reference)

# --- TEST GROUP 5: RECORD ORDER INDEPENDENCE & DETERMINISM ---

def test_record_order_independence(op_fixture: Path) -> None:
    # Read normal output
    run1 = reconcile_split(DatasetSplit.DEV, op_fixture)
    out1 = json.dumps([r.to_dict() for r in run1.results], sort_keys=True)

    # Shuffle all CSVs
    for f in ['payments.csv', 'bank_settlements.csv', 'merchant_ledger.csv', 'adjustments.csv']:
        rows, fields = _csv_rows(op_fixture, f)
        random.seed(42)
        random.shuffle(rows)
        _write_csv(op_fixture, f, rows, fields)

    run2 = reconcile_split(DatasetSplit.DEV, op_fixture)
    out2 = json.dumps([r.to_dict() for r in run2.results], sort_keys=True)

    assert out1 == out2, "Order of input rows should not affect complete serialized EngineResult"

# --- TEST GROUP 6: CROSS-SOURCE CONSISTENCY ---

def test_adjustment_without_payment_fails(op_fixture: Path) -> None:
    _add_csv_row(op_fixture, 'adjustments.csv', {'adjustment_id': 'ADJ_X', 'rzp_id': 'RZP_NO_EXIST', 'adjustment_type': 'refund', 'amount': '1.00', 'adjustment_date': '2025-01-01', 'reference_id': 'REF_X'})
    with pytest.raises(OperationalDataError, match='adjustment reference has no payment'):
        reconcile_split(DatasetSplit.DEV, op_fixture)

# --- TEST GROUP 7: UNKNOWN TRANSACTION HARDENING ---

def test_unknown_txn_duplicate_rows(op_fixture: Path) -> None:
    reference = _get_reference(op_fixture, category='UNKNOWN_TRANSACTION')
    rows, _ = _csv_rows(op_fixture, 'bank_settlements.csv')
    base_row = next(r for r in rows if r['rzp_id'] == reference)
    dup = base_row.copy()
    dup['settlement_id'] = dup['settlement_id'] + '_DUP'
    _add_csv_row(op_fixture, 'bank_settlements.csv', dup)

    r = _result(op_fixture, reference)
    # Structural checks say Unknown takes priority over duplicate
    assert r.detected_issue == ExceptionCategory.UNKNOWN_TRANSACTION

# --- TEST GROUP 8: DUPLICATE HARDENING ---

def test_duplicate_different_amounts(op_fixture: Path) -> None:
    reference = _get_reference(op_fixture, category='DUPLICATE')
    rows, _ = _csv_rows(op_fixture, 'bank_settlements.csv')
    dups = [r for r in rows if r['rzp_id'] == reference]
    assert len(dups) >= 2

    # Change amount of second duplicate
    dups[1]['settled_amount'] = '999.99'

    # Write back
    new_rows = [r for r in rows if r['rzp_id'] != reference] + dups
    _update_csv(op_fixture, 'bank_settlements.csv', reference) # dummy
    _write_csv(op_fixture, 'bank_settlements.csv', new_rows, _csv_rows(op_fixture, 'bank_settlements.csv')[1])

    r = _result(op_fixture, reference)
    assert r.detected_issue == ExceptionCategory.DUPLICATE
    assert len(r.evidence['bank_settlements']) >= 2
    assert r.evidence['bank_settlements'][1]['settled_amount'] == '999.99'

# --- TEST GROUP 9: AMBIGUITY HARDENING ---

def test_ambiguity_refund_adjustment_preserves_math(op_fixture: Path) -> None:
    reference = _get_reference(op_fixture, subtype='REFUND_ADJUSTMENT')
    r = _result(op_fixture, reference)
    assert r.route == HandlingRoute.AI_INVESTIGATOR
    assert r.status == InternalProcessingState.PENDING_AI_REVIEW
    c = r.evidence['calculations']
    assert Decimal(c['expected_adjusted_settlement']) == Decimal(c['observed_settlement'])

# --- TEST GROUP 11: INPUT IMMUTABILITY ---

def test_input_immutability(op_fixture: Path) -> None:
    hashes_before = {f: hashlib.sha256((op_fixture / 'data' / 'dev' / f).read_bytes()).hexdigest() 
                     for f in ['payments.csv', 'bank_settlements.csv', 'merchant_ledger.csv', 'adjustments.csv']}

    reconcile_split(DatasetSplit.DEV, op_fixture)
    reconcile_split(DatasetSplit.DEV, op_fixture)

    hashes_after = {f: hashlib.sha256((op_fixture / 'data' / 'dev' / f).read_bytes()).hexdigest() 
                    for f in ['payments.csv', 'bank_settlements.csv', 'merchant_ledger.csv', 'adjustments.csv']}

    assert hashes_before == hashes_after

# --- TEST GROUP 14 & 15: OUTPUT CONTRACT & SERIALIZATION ---

def test_output_contract_and_serialization(op_fixture: Path) -> None:
    run = reconcile_split(DatasetSplit.DEV, op_fixture)
    for r in run.results:
        assert r.operational_reference_id
        assert r.route in (HandlingRoute.DETERMINISTIC, HandlingRoute.AI_INVESTIGATOR)
        if r.route == HandlingRoute.DETERMINISTIC:
            assert r.detected_issue is not None
            assert r.recommended_action is not None
        else:
            assert r.status == InternalProcessingState.PENDING_AI_REVIEW
            assert r.reason_for_routing

        # Serialize to JSON and parse back
        d = r.to_dict()
        s = json.dumps(d)
        d2 = json.loads(s)
        assert d2['operational_reference_id'] == r.operational_reference_id

# --- TEST GROUP 18: PROPERTY/INVARIANT TESTING ---

def test_property_exact_match(op_fixture: Path) -> None:
    run = reconcile_split(DatasetSplit.DEV, op_fixture)
    for r in run.results:
        if r.detected_issue == ExceptionCategory.EXACT_MATCH:
            pay_amt = Decimal(r.evidence['payment']['amount'])
            ledg_amt = Decimal(r.evidence['merchant_ledger'][0]['recorded_amount'])
            stl_amt = Decimal(r.evidence['bank_settlements'][0]['settled_amount'])

            assert amounts_within_tolerance(pay_amt, ledg_amt)
            assert amounts_within_tolerance(pay_amt, stl_amt)
            assert not r.evidence['adjustments']

def test_property_duplicate(op_fixture: Path) -> None:
    run = reconcile_split(DatasetSplit.DEV, op_fixture)
    for r in run.results:
        if r.detected_issue == ExceptionCategory.DUPLICATE:
            assert len(r.evidence['bank_settlements']) >= 2

