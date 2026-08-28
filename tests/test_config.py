"""Tests for the Module 1 shared configuration foundation."""

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from ledgerlens.config import (
    ALLOWED_FINAL_ACTIONS,
    APPROVED_SUBTYPES,
    EXCEPTION_TAXONOMY,
    HANDLING_ROUTES,
    SETTINGS,
    CaseSubtype,
    DatasetSplit,
    ExceptionCategory,
    FinalAction,
    HandlingRoute,
    validate_configuration,
)


def test_configuration_imports_and_validates() -> None:
    """The shipped configuration is valid at import time and on explicit validation."""

    validate_configuration(SETTINGS)
    assert SETTINGS.currency == "INR"


def test_monetary_values_are_exact_decimals() -> None:
    """Authoritative monetary configuration never uses binary floating-point values."""

    assert type(SETTINGS.fee_rate) is Decimal
    assert type(SETTINGS.monetary_tolerance) is Decimal
    assert SETTINGS.fee_rate == Decimal("0.02")
    assert SETTINGS.monetary_tolerance == Decimal("0.01")
    assert type(SETTINGS.ai_ambiguity.target_ambiguous_case_rate) is Decimal


def test_evaluation_date_and_settlement_window_are_deterministic() -> None:
    """Time-related evaluation settings have fixed, valid values."""

    assert SETTINGS.evaluation_date == date(2025, 1, 31)
    assert SETTINGS.settlement_window_days > 0


def test_dataset_splits_have_distinct_seeds_and_expected_sizes() -> None:
    """Reproducible split metadata is centralized and complete."""

    assert set(SETTINGS.dataset_seeds) == set(DatasetSplit)
    assert len(set(SETTINGS.dataset_seeds.values())) == len(DatasetSplit)
    assert dict(SETTINGS.dataset_sizes) == {
        DatasetSplit.DEV: 100,
        DatasetSplit.VALIDATION: 500,
        DatasetSplit.HOLDOUT: 1000,
    }
    assert SETTINGS.benchmark_case_sizes == (100, 500, 1000, 5000)


def test_taxonomies_contain_only_the_approved_values() -> None:
    """Final classifications, actions, routes, and subtypes remain constrained."""

    assert EXCEPTION_TAXONOMY == (
        ExceptionCategory.EXACT_MATCH,
        ExceptionCategory.FEE_DEDUCTION,
        ExceptionCategory.TIMING_LAG,
        ExceptionCategory.DUPLICATE,
        ExceptionCategory.MISSING_SETTLEMENT,
        ExceptionCategory.UNKNOWN_TRANSACTION,
    )
    assert ALLOWED_FINAL_ACTIONS == (
        FinalAction.AUTO_RESOLVE,
        FinalAction.MONITOR,
        FinalAction.ESCALATE,
    )
    assert HANDLING_ROUTES == (
        HandlingRoute.DETERMINISTIC,
        HandlingRoute.AI_INVESTIGATOR,
    )
    assert APPROVED_SUBTYPES == (
        CaseSubtype.STANDARD_FEE,
        CaseSubtype.REFUND_ADJUSTMENT,
        CaseSubtype.LEDGER_MISMATCH,
    )


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("fee_rate", Decimal("-0.01")),
        ("fee_rate", Decimal("1.01")),
        ("fee_rate", 0.02),
        ("monetary_tolerance", Decimal("-0.01")),
        ("settlement_window_days", 0),
    ],
)
def test_invalid_configuration_values_are_rejected(field: str, invalid_value: object) -> None:
    """Invalid values fail loudly rather than being corrected or coerced."""

    invalid_configuration = replace(SETTINGS, **{field: invalid_value})

    with pytest.raises(ValueError):
        validate_configuration(invalid_configuration)
