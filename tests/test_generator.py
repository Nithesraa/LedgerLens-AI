"""Focused tests for deterministic, multi-source operational data generation."""

from __future__ import annotations

import inspect
from collections import Counter, defaultdict
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import ledgerlens.generator as generator_module
import pytest

from ledgerlens.config import (
    SETTINGS,
    CaseSubtype,
    DatasetSplit,
    ExceptionCategory,
    HandlingRoute,
)
from ledgerlens.generator import (
    GeneratedDataset,
    category_allocation,
    calculate_fee,
    fee_subtype_allocation,
    generate_all,
    generate_split,
)


@pytest.fixture(scope="module")
def datasets() -> dict[DatasetSplit, GeneratedDataset]:
    """Build every configured split once; each build performs generator validation."""

    return {split: generate_split(split) for split in DatasetSplit}


def _by_reference(records: object) -> dict[str, list[object]]:
    grouped: dict[str, list[object]] = defaultdict(list)
    for record in records:  # type: ignore[union-attr]
        grouped[record.rzp_id].append(record)  # type: ignore[union-attr]
    return dict(grouped)


def test_all_splits_generate_the_configured_number_of_logical_cases(
    datasets: dict[DatasetSplit, GeneratedDataset],
) -> None:
    assert {split: len(dataset.ground_truth) for split, dataset in datasets.items()} == {
        DatasetSplit.DEV: 100,
        DatasetSplit.VALIDATION: 500,
        DatasetSplit.HOLDOUT: 1000,
    }


def test_dev_distribution_matches_the_agreed_case_mix(
    datasets: dict[DatasetSplit, GeneratedDataset],
) -> None:
    distribution = Counter(case.injected_type for case in datasets[DatasetSplit.DEV].ground_truth)
    assert distribution == {
        ExceptionCategory.EXACT_MATCH: 60,
        ExceptionCategory.FEE_DEDUCTION: 10,
        ExceptionCategory.TIMING_LAG: 10,
        ExceptionCategory.DUPLICATE: 5,
        ExceptionCategory.MISSING_SETTLEMENT: 10,
        ExceptionCategory.UNKNOWN_TRANSACTION: 5,
    }


def test_larger_category_and_fee_subtype_allocations_are_deterministic() -> None:
    assert category_allocation(500) == {
        ExceptionCategory.EXACT_MATCH: 300,
        ExceptionCategory.FEE_DEDUCTION: 50,
        ExceptionCategory.TIMING_LAG: 50,
        ExceptionCategory.DUPLICATE: 25,
        ExceptionCategory.MISSING_SETTLEMENT: 50,
        ExceptionCategory.UNKNOWN_TRANSACTION: 25,
    }
    assert category_allocation(1000)[ExceptionCategory.FEE_DEDUCTION] == 100
    assert fee_subtype_allocation(100) == {
        CaseSubtype.STANDARD_FEE: 50,
        CaseSubtype.REFUND_ADJUSTMENT: 25,
        CaseSubtype.LEDGER_MISMATCH: 25,
    }


def test_case_and_operational_reference_ids_are_unique_and_cross_split_isolated(
    datasets: dict[DatasetSplit, GeneratedDataset],
) -> None:
    reference_sets: list[set[str]] = []
    for dataset in datasets.values():
        case_ids = [case.case_id for case in dataset.ground_truth]
        references = [case.operational_reference_id for case in dataset.ground_truth]
        assert len(case_ids) == len(set(case_ids))
        assert len(references) == len(set(references))
        reference_sets.append(set(references))

    assert reference_sets[0].isdisjoint(reference_sets[1])
    assert reference_sets[0].isdisjoint(reference_sets[2])
    assert reference_sets[1].isdisjoint(reference_sets[2])


def test_unknown_transactions_have_null_primary_ids_and_bank_only_evidence(
    datasets: dict[DatasetSplit, GeneratedDataset],
) -> None:
    for dataset in datasets.values():
        payment_ids = {payment.rzp_id for payment in dataset.payments}
        settlement_ids = {settlement.rzp_id for settlement in dataset.bank_settlements}
        unknown_cases = [
            case
            for case in dataset.ground_truth
            if case.injected_type is ExceptionCategory.UNKNOWN_TRANSACTION
        ]
        assert unknown_cases
        for case in unknown_cases:
            assert case.primary_txn_id is None
            assert case.operational_reference_id
            assert case.operational_reference_id not in payment_ids
            assert case.operational_reference_id in settlement_ids


def test_duplicate_and_missing_settlement_evidence_is_observable(
    datasets: dict[DatasetSplit, GeneratedDataset],
) -> None:
    for dataset in datasets.values():
        settlements = _by_reference(dataset.bank_settlements)
        for case in dataset.ground_truth:
            if case.injected_type is ExceptionCategory.DUPLICATE:
                assert len(settlements[case.operational_reference_id]) == 2
            if case.injected_type is ExceptionCategory.MISSING_SETTLEMENT:
                assert not settlements.get(case.operational_reference_id)


def test_fee_and_refund_adjustment_arithmetic_close_exactly(
    datasets: dict[DatasetSplit, GeneratedDataset],
) -> None:
    for dataset in datasets.values():
        payments = {record.rzp_id: record for record in dataset.payments}
        settlements = _by_reference(dataset.bank_settlements)
        adjustments = _by_reference(dataset.adjustments)
        for case in dataset.ground_truth:
            if case.injected_type is not ExceptionCategory.FEE_DEDUCTION:
                continue
            payment = payments[case.operational_reference_id]
            adjustment_total = sum(
                (record.amount for record in adjustments.get(payment.rzp_id, [])), Decimal("0")
            )
            assert settlements[payment.rzp_id][0].settled_amount == (
                payment.amount - calculate_fee(payment.amount) - adjustment_total
            )


def test_refund_adjustments_and_ledger_mismatches_exist_in_operational_data(
    datasets: dict[DatasetSplit, GeneratedDataset],
) -> None:
    for dataset in datasets.values():
        payments = {record.rzp_id: record for record in dataset.payments}
        ledgers = _by_reference(dataset.merchant_ledger)
        adjustments = _by_reference(dataset.adjustments)
        for case in dataset.ground_truth:
            if case.sub_type is CaseSubtype.REFUND_ADJUSTMENT:
                assert case.is_ambiguous is True
                assert case.expected_route is HandlingRoute.AI_INVESTIGATOR
                assert len(adjustments[case.operational_reference_id]) == 1
                assert ledgers[case.operational_reference_id][0].recorded_amount == payments[
                    case.operational_reference_id
                ].amount
            if case.sub_type is CaseSubtype.LEDGER_MISMATCH:
                assert case.is_ambiguous is True
                assert case.expected_route is HandlingRoute.AI_INVESTIGATOR
                assert not adjustments.get(case.operational_reference_id)
                assert ledgers[case.operational_reference_id][0].recorded_amount != payments[
                    case.operational_reference_id
                ].amount


def test_timing_cases_are_within_and_missing_cases_exceed_the_settlement_window(
    datasets: dict[DatasetSplit, GeneratedDataset],
) -> None:
    for dataset in datasets.values():
        payments = {record.rzp_id: record for record in dataset.payments}
        for case in dataset.ground_truth:
            if case.injected_type not in {
                ExceptionCategory.TIMING_LAG,
                ExceptionCategory.MISSING_SETTLEMENT,
            }:
                continue
            age = SETTINGS.evaluation_date - payments[case.operational_reference_id].created_at.date()
            if case.injected_type is ExceptionCategory.TIMING_LAG:
                assert timedelta(0) < age <= timedelta(days=SETTINGS.settlement_window_days)
            else:
                assert age > timedelta(days=SETTINGS.settlement_window_days)


def test_holdout_has_a_statistically_meaningful_ambiguous_population(
    datasets: dict[DatasetSplit, GeneratedDataset],
) -> None:
    holdout_cases = datasets[DatasetSplit.HOLDOUT].ground_truth
    ambiguous_cases = [case for case in holdout_cases if case.is_ambiguous]
    assert len(ambiguous_cases) == 50
    assert 40 <= len(ambiguous_cases) <= 60
    assert Counter(case.sub_type for case in ambiguous_cases) == {
        CaseSubtype.REFUND_ADJUSTMENT: 25,
        CaseSubtype.LEDGER_MISMATCH: 25,
    }


def test_repeated_generation_has_identical_logical_content() -> None:
    first = generate_split(DatasetSplit.DEV)
    second = generate_split(DatasetSplit.DEV)
    assert first == second
    assert first.content_digest() == second.content_digest()


def test_writer_keeps_operational_and_ground_truth_files_physically_separate(
    tmp_path: Path,
) -> None:
    generated = generate_all(tmp_path)
    assert set(generated) == set(DatasetSplit)
    for split in DatasetSplit:
        split_name = split.value.lower()
        data_directory = tmp_path / "data" / split_name
        evaluation_directory = tmp_path / "evaluation" / split_name
        assert {path.name for path in data_directory.iterdir()} == {
            "payments.csv",
            "bank_settlements.csv",
            "merchant_ledger.csv",
            "adjustments.csv",
        }
        assert {path.name for path in evaluation_directory.iterdir()} == {"ground_truth.json"}

    assert not list((tmp_path / "data").rglob("ground_truth.json"))
    assert not list((tmp_path / "evaluation").rglob("*.csv"))


def test_generator_never_reads_ground_truth_as_an_input() -> None:
    source = inspect.getsource(generator_module)
    assert "json.load(" not in source
    assert "read_text(" not in source
