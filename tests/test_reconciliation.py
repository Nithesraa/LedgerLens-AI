"""Behavioral tests for deterministic reconciliation using operational data only."""

from __future__ import annotations

import csv
import hashlib
import inspect
import json
import shutil
from collections import Counter
from decimal import Decimal
from pathlib import Path

import pytest

import ledgerlens.reconciliation as reconciliation_module
from ledgerlens.config import DatasetSplit, ExceptionCategory, FinalAction, HandlingRoute
from ledgerlens.reconciliation import (
    OperationalDataError,
    amounts_within_tolerance,
    calculate_configured_fee,
    load_operational_dataset,
    main,
    reconcile_split,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def dev_run():
    return reconcile_split(DatasetSplit.DEV)


@pytest.fixture
def operational_fixture(tmp_path: Path) -> Path:
    """Create a disposable operational-data copy for malformed-input tests."""

    shutil.copytree(PROJECT_ROOT / "data" / "dev", tmp_path / "data" / "dev")
    return tmp_path


def _result_for_issue(dev_run, issue: ExceptionCategory):
    return next(result for result in dev_run.results if result.detected_issue is issue)


def _data_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted((root / "data").rglob("*"))
        if path.is_file()
    }


def test_dev_results_cover_deterministic_and_ambiguous_operational_paths(dev_run) -> None:
    assert len(dev_run.results) == 100
    assert Counter(result.route for result in dev_run.results) == {
        HandlingRoute.DETERMINISTIC: 95,
        HandlingRoute.AI_INVESTIGATOR: 5,
    }
    assert Counter(
        result.detected_issue.value if result.detected_issue else result.status.value
        for result in dev_run.results
    ) == {
        "EXACT_MATCH": 60,
        "FEE_DEDUCTION": 5,
        "TIMING_LAG": 10,
        "DUPLICATE": 5,
        "MISSING_SETTLEMENT": 10,
        "UNKNOWN_TRANSACTION": 5,
        "PENDING_AI_REVIEW": 5,
    }


def test_exact_match_is_resolved_from_payment_ledger_and_bank_evidence(dev_run) -> None:
    result = _result_for_issue(dev_run, ExceptionCategory.EXACT_MATCH)
    assert result.route is HandlingRoute.DETERMINISTIC
    assert result.recommended_action is FinalAction.AUTO_RESOLVE
    assert result.evidence["payment"]["amount"] == result.evidence["merchant_ledger"][0]["recorded_amount"]
    assert result.evidence["payment"]["amount"] == result.evidence["bank_settlements"][0]["settled_amount"]


def test_standard_fee_is_resolved_with_exact_decimal_fee_evidence(dev_run) -> None:
    result = _result_for_issue(dev_run, ExceptionCategory.FEE_DEDUCTION)
    assert result.route is HandlingRoute.DETERMINISTIC
    assert result.recommended_action is FinalAction.AUTO_RESOLVE
    assert result.sub_type is not None and result.sub_type.value == "STANDARD_FEE"
    calculations = result.evidence["calculations"]
    assert calculations["bank_matches_fee"] is True
    assert calculations["expected_fee_settlement"] == calculations["observed_settlement"]


def test_timing_lag_uses_the_configured_deterministic_date_window(dev_run) -> None:
    result = _result_for_issue(dev_run, ExceptionCategory.TIMING_LAG)
    assert result.route is HandlingRoute.DETERMINISTIC
    assert result.recommended_action is FinalAction.MONITOR
    assert result.evidence["bank_settlements"] == []
    assert result.decision_trace["settlement_within_window"] is True


def test_missing_settlement_uses_age_beyond_the_window(dev_run) -> None:
    result = _result_for_issue(dev_run, ExceptionCategory.MISSING_SETTLEMENT)
    assert result.route is HandlingRoute.DETERMINISTIC
    assert result.recommended_action is FinalAction.ESCALATE
    assert result.evidence["bank_settlements"] == []
    assert result.decision_trace["payment_age_days"] > 3


def test_duplicate_preserves_all_bank_settlement_evidence(dev_run) -> None:
    result = _result_for_issue(dev_run, ExceptionCategory.DUPLICATE)
    assert result.route is HandlingRoute.DETERMINISTIC
    assert result.recommended_action is FinalAction.ESCALATE
    assert result.decision_trace["duplicate_detected"] is True
    assert len(result.evidence["bank_settlements"]) == 2
    assert len({row["settlement_id"] for row in result.evidence["bank_settlements"]}) == 2


def test_unknown_transaction_keeps_reference_with_null_primary_transaction(dev_run) -> None:
    result = _result_for_issue(dev_run, ExceptionCategory.UNKNOWN_TRANSACTION)
    assert result.operational_reference_id
    assert result.primary_txn_id is None
    assert result.route is HandlingRoute.DETERMINISTIC
    assert result.recommended_action is FinalAction.ESCALATE
    assert result.evidence["payment"] is None
    assert result.evidence["bank_settlements"]


def test_refund_adjustment_routes_to_pending_ai_with_operational_arithmetic(dev_run) -> None:
    result = next(
        result
        for result in dev_run.results
        if result.reason_for_routing == "fee_and_adjustment_require_investigation"
    )
    assert result.route is HandlingRoute.AI_INVESTIGATOR
    assert result.status is not None and result.status.value == "PENDING_AI_REVIEW"
    assert result.detected_issue is None
    assert result.recommended_action is None
    assert result.evidence["adjustments"]
    calculations = result.evidence["calculations"]
    assert calculations["expected_adjusted_settlement"] == calculations["observed_settlement"]


def test_ledger_mismatch_routes_to_pending_ai_with_fee_consistent_bank_side(dev_run) -> None:
    result = next(
        result
        for result in dev_run.results
        if result.reason_for_routing == "ledger_mismatch_requires_investigation"
    )
    assert result.route is HandlingRoute.AI_INVESTIGATOR
    assert result.status is not None and result.status.value == "PENDING_AI_REVIEW"
    assert result.evidence["calculations"]["bank_matches_fee"] is True
    assert result.evidence["payment"]["amount"] != result.evidence["merchant_ledger"][0]["recorded_amount"]


def test_exact_decimal_fee_and_explicit_tolerance() -> None:
    fee = calculate_configured_fee(Decimal("10000.00"))
    assert type(fee) is Decimal
    assert fee == Decimal("200.00")
    assert amounts_within_tolerance(Decimal("10.00"), Decimal("10.01")) is True
    assert amounts_within_tolerance(Decimal("10.00"), Decimal("10.02")) is False


@pytest.mark.parametrize(
    ("split", "expected_results"),
    [
        (DatasetSplit.DEV, 100),
        (DatasetSplit.VALIDATION, 500),
        (DatasetSplit.HOLDOUT, 1000),
    ],
)
def test_all_operational_splits_produce_one_valid_result_per_reference(
    split: DatasetSplit, expected_results: int
) -> None:
    run = reconcile_split(split)
    dataset = load_operational_dataset(PROJECT_ROOT / "data" / split.value.lower())
    expected_references = set(dataset.payments) | set(dataset.settlements_by_reference)
    assert len(run.results) == expected_results == len(expected_references)
    assert {result.operational_reference_id for result in run.results} == expected_references
    assert all(result.operational_reference_id for result in run.results)
    assert all(result.route in set(HandlingRoute) for result in run.results)


def test_repeated_runs_are_identical_and_do_not_modify_operational_files() -> None:
    before = _data_hashes(PROJECT_ROOT)
    first = reconcile_split(DatasetSplit.DEV)
    second = reconcile_split(DatasetSplit.DEV)
    after = _data_hashes(PROJECT_ROOT)
    assert first == second
    assert before == after


def test_missing_operational_file_raises_controlled_error(operational_fixture: Path) -> None:
    (operational_fixture / "data" / "dev" / "payments.csv").unlink()
    with pytest.raises(OperationalDataError, match="required operational file is missing"):
        reconcile_split(DatasetSplit.DEV, operational_fixture)


def test_invalid_monetary_input_raises_controlled_error(operational_fixture: Path) -> None:
    path = operational_fixture / "data" / "dev" / "payments.csv"
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        fields = list(reader.fieldnames or [])
    rows[0]["amount"] = "NaN"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    with pytest.raises(OperationalDataError, match="exact monetary representation"):
        reconcile_split(DatasetSplit.DEV, operational_fixture)


def test_engine_source_has_no_hidden_label_or_clock_dependency() -> None:
    source = inspect.getsource(reconciliation_module)
    assert "ground_truth" not in source
    assert '"evaluation/' not in source
    assert '"/evaluation' not in source
    assert "date.today" not in source
    assert "datetime.now" not in source
    assert "ledgerlens.validator" not in source


def test_cli_emits_structured_json(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--split", "dev"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["split"] == "dev"
    assert len(payload["results"]) == 100
    assert payload["results"][0]["operational_reference_id"]
