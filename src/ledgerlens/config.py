"""Central, deterministic configuration for LedgerLens AI.

This module is the single source of shared constants for later generator,
reconciliation, and evaluation modules. It deliberately contains no I/O,
environment-secret handling, or business-processing logic.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Final


class Currency(StrEnum):
    """Currencies supported by the initial LedgerLens configuration."""

    INR = "INR"


class DatasetSplit(StrEnum):
    """Named reproducible dataset splits."""

    DEV = "DEV"
    VALIDATION = "VALIDATION"
    HOLDOUT = "HOLDOUT"


class ExceptionCategory(StrEnum):
    """The six allowed top-level business exception categories."""

    EXACT_MATCH = "EXACT_MATCH"
    FEE_DEDUCTION = "FEE_DEDUCTION"
    TIMING_LAG = "TIMING_LAG"
    DUPLICATE = "DUPLICATE"
    MISSING_SETTLEMENT = "MISSING_SETTLEMENT"
    UNKNOWN_TRANSACTION = "UNKNOWN_TRANSACTION"


class CaseSubtype(StrEnum):
    """Approved subtypes for evidence-based, ambiguous cases."""

    STANDARD_FEE = "STANDARD_FEE"
    REFUND_ADJUSTMENT = "REFUND_ADJUSTMENT"
    LEDGER_MISMATCH = "LEDGER_MISMATCH"


class FinalAction(StrEnum):
    """The only allowed final actions."""

    AUTO_RESOLVE = "AUTO_RESOLVE"
    MONITOR = "MONITOR"
    ESCALATE = "ESCALATE"


class HandlingRoute(StrEnum):
    """Actual runtime handling paths, distinct from outcome classifications."""

    DETERMINISTIC = "DETERMINISTIC"
    AI_INVESTIGATOR = "AI_INVESTIGATOR"


class InternalProcessingState(StrEnum):
    """Internal states which are never final business classifications."""

    AMOUNT_MISMATCH = "AMOUNT_MISMATCH"
    PENDING_AI_REVIEW = "PENDING_AI_REVIEW"
    DATA_QUALITY_ERROR = "DATA_QUALITY_ERROR"


EXCEPTION_TAXONOMY: Final[tuple[ExceptionCategory, ...]] = tuple(ExceptionCategory)
APPROVED_SUBTYPES: Final[tuple[CaseSubtype, ...]] = tuple(CaseSubtype)
ALLOWED_FINAL_ACTIONS: Final[tuple[FinalAction, ...]] = tuple(FinalAction)
HANDLING_ROUTES: Final[tuple[HandlingRoute, ...]] = tuple(HandlingRoute)

SUPPORTED_CURRENCIES: Final[frozenset[Currency]] = frozenset({Currency.INR})
MAX_FEE_RATE: Final[Decimal] = Decimal("1")


@dataclass(frozen=True, slots=True)
class AiAmbiguityConfig:
    """Non-secret, future-facing limits for selective AI routing.

    This is a planning target only; no AI routing is implemented in Module 1.
    """

    target_ambiguous_case_rate: Decimal


@dataclass(frozen=True, slots=True)
class LedgerLensConfig:
    """Immutable configuration shared by all future LedgerLens modules."""

    currency: Currency
    fee_rate: Decimal
    settlement_window_days: int
    evaluation_date: date
    monetary_tolerance: Decimal
    dataset_seeds: Mapping[DatasetSplit, int]
    dataset_sizes: Mapping[DatasetSplit, int]
    benchmark_case_sizes: tuple[int, ...]
    ai_ambiguity: AiAmbiguityConfig
    case_distribution_weights: Mapping[ExceptionCategory, int]
    fee_subtype_weights: Mapping[CaseSubtype, int]


DEFAULT_DATASET_SEEDS: Final[Mapping[DatasetSplit, int]] = MappingProxyType(
    {
        DatasetSplit.DEV: 42,
        DatasetSplit.VALIDATION: 123,
        DatasetSplit.HOLDOUT: 999,
    }
)

DEFAULT_DATASET_SIZES: Final[Mapping[DatasetSplit, int]] = MappingProxyType(
    {
        DatasetSplit.DEV: 100,
        DatasetSplit.VALIDATION: 500,
        DatasetSplit.HOLDOUT: 1000,
    }
)

DEFAULT_BENCHMARK_CASE_SIZES: Final[tuple[int, ...]] = (100, 500, 1000, 5000)

# Integer weights avoid floating-point allocation and scale deterministically.
# They reproduce the agreed 100-case DEV distribution exactly.
DEFAULT_CASE_DISTRIBUTION_WEIGHTS: Final[Mapping[ExceptionCategory, int]] = MappingProxyType(
    {
        ExceptionCategory.EXACT_MATCH: 60,
        ExceptionCategory.FEE_DEDUCTION: 10,
        ExceptionCategory.TIMING_LAG: 10,
        ExceptionCategory.DUPLICATE: 5,
        ExceptionCategory.MISSING_SETTLEMENT: 10,
        ExceptionCategory.UNKNOWN_TRANSACTION: 5,
    }
)

# Half of fee-deduction cases are deliberately ambiguous. At 1,000 cases this
# yields 50 AI-routed cases: 25 refund adjustments and 25 ledger mismatches.
DEFAULT_FEE_SUBTYPE_WEIGHTS: Final[Mapping[CaseSubtype, int]] = MappingProxyType(
    {
        CaseSubtype.STANDARD_FEE: 50,
        CaseSubtype.REFUND_ADJUSTMENT: 25,
        CaseSubtype.LEDGER_MISMATCH: 25,
    }
)

SETTINGS: Final[LedgerLensConfig] = LedgerLensConfig(
    currency=Currency.INR,
    fee_rate=Decimal("0.02"),
    settlement_window_days=3,
    evaluation_date=date(2025, 1, 31),
    monetary_tolerance=Decimal("0.01"),
    dataset_seeds=DEFAULT_DATASET_SEEDS,
    dataset_sizes=DEFAULT_DATASET_SIZES,
    benchmark_case_sizes=DEFAULT_BENCHMARK_CASE_SIZES,
    ai_ambiguity=AiAmbiguityConfig(target_ambiguous_case_rate=Decimal("0.05")),
    case_distribution_weights=DEFAULT_CASE_DISTRIBUTION_WEIGHTS,
    fee_subtype_weights=DEFAULT_FEE_SUBTYPE_WEIGHTS,
)


def validate_configuration(configuration: LedgerLensConfig) -> None:
    """Fail loudly when deterministic shared configuration is invalid.

    Monetary values must be finite ``Decimal`` instances. Dataset mappings must
    define each split exactly once so later modules cannot silently omit a split.
    """

    if not isinstance(configuration.currency, Currency):
        raise ValueError("currency must be a Currency value")
    if configuration.currency not in SUPPORTED_CURRENCIES:
        raise ValueError(f"unsupported currency: {configuration.currency}")

    _validate_decimal(
        "fee_rate", configuration.fee_rate, minimum=Decimal("0"), maximum=MAX_FEE_RATE
    )
    _validate_decimal(
        "monetary_tolerance", configuration.monetary_tolerance, minimum=Decimal("0")
    )
    _validate_decimal(
        "ai_ambiguity.target_ambiguous_case_rate",
        configuration.ai_ambiguity.target_ambiguous_case_rate,
        minimum=Decimal("0"),
        maximum=Decimal("1"),
    )

    if type(configuration.settlement_window_days) is not int or configuration.settlement_window_days <= 0:
        raise ValueError("settlement_window_days must be a positive integer")
    if type(configuration.evaluation_date) is not date:
        raise ValueError("evaluation_date must be a datetime.date")

    _validate_split_mapping("dataset_seeds", configuration.dataset_seeds, positive=False)
    _validate_split_mapping("dataset_sizes", configuration.dataset_sizes, positive=True)
    _validate_weight_mapping(
        "case_distribution_weights",
        configuration.case_distribution_weights,
        ExceptionCategory,
    )
    _validate_weight_mapping(
        "fee_subtype_weights", configuration.fee_subtype_weights, CaseSubtype
    )

    if not configuration.benchmark_case_sizes:
        raise ValueError("benchmark_case_sizes must not be empty")
    if any(type(size) is not int or size <= 0 for size in configuration.benchmark_case_sizes):
        raise ValueError("benchmark_case_sizes must contain positive integers")


def _validate_decimal(
    name: str,
    value: Decimal,
    *,
    minimum: Decimal,
    maximum: Decimal | None = None,
) -> None:
    """Validate an exact, finite decimal value within explicit bounds."""

    if type(value) is not Decimal or not value.is_finite():
        raise ValueError(f"{name} must be a finite Decimal")
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name} must be at most {maximum}")


def _validate_split_mapping(
    name: str, values: Mapping[DatasetSplit, int], *, positive: bool
) -> None:
    """Validate complete integer values for every named dataset split."""

    if not isinstance(values, Mapping) or set(values) != set(DatasetSplit):
        raise ValueError(f"{name} must define exactly DEV, VALIDATION, and HOLDOUT")
    for split, value in values.items():
        if not isinstance(split, DatasetSplit) or type(value) is not int:
            raise ValueError(f"{name} values must be integers keyed by DatasetSplit")
        if positive and value <= 0:
            raise ValueError(f"{name} values must be positive")


def _validate_weight_mapping[
    EnumValue: (ExceptionCategory, CaseSubtype)
](
    name: str,
    values: Mapping[EnumValue, int],
    enum_type: type[EnumValue],
) -> None:
    """Validate a complete positive integer allocation for a fixed taxonomy."""

    if not isinstance(values, Mapping) or set(values) != set(enum_type):
        raise ValueError(f"{name} must define every approved {enum_type.__name__}")
    if any(type(weight) is not int or weight <= 0 for weight in values.values()):
        raise ValueError(f"{name} must contain only positive integer weights")


validate_configuration(SETTINGS)
