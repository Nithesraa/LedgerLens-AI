"""Independent, read-only validation of LedgerLens operational datasets.

This module validates existing CSV and ground-truth files against the data
contract. It intentionally does not import the generator or reuse its internal
validation routines.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from enum import StrEnum
from pathlib import Path
from typing import Final

from ledgerlens.config import (
    SETTINGS,
    CaseSubtype,
    DatasetSplit,
    ExceptionCategory,
    FinalAction,
    HandlingRoute,
)


PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
RECOGNIZED_ADJUSTMENT_TYPES: Final[frozenset[str]] = frozenset({"refund"})
IDENTIFIER_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{2,127}$")
MONEY_DECIMAL_PLACES: Final[int] = -SETTINGS.monetary_tolerance.as_tuple().exponent
MONEY_PATTERN: Final[re.Pattern[str]] = re.compile(
    rf"^(?:0|[1-9]\d*)\.\d{{{MONEY_DECIMAL_PLACES}}}$"
)

CSV_CONTRACTS: Final[Mapping[str, tuple[str, tuple[str, ...]]]] = {
    "payments": (
        "payments.csv",
        (
            "rzp_id",
            "order_id",
            "amount",
            "currency",
            "payment_status",
            "created_at",
            "merchant_id",
            "method",
        ),
    ),
    "bank_settlements": (
        "bank_settlements.csv",
        ("settlement_id", "rzp_id", "settled_amount", "settlement_date", "batch_id", "remarks"),
    ),
    "merchant_ledger": (
        "merchant_ledger.csv",
        ("entry_id", "rzp_id", "recorded_amount", "recorded_at", "status"),
    ),
    "adjustments": (
        "adjustments.csv",
        ("adjustment_id", "rzp_id", "adjustment_type", "amount", "adjustment_date", "reference_id"),
    ),
}
GROUND_TRUTH_FIELDS: Final[tuple[str, ...]] = (
    "case_id",
    "primary_txn_id",
    "operational_reference_id",
    "injected_type",
    "sub_type",
    "expected_action",
    "expected_route",
    "is_ambiguous",
)


class CheckStatus(StrEnum):
    """A report status for one validation stage."""

    PASS = "PASS"
    WARNING = "WARNING"
    FAIL = "FAIL"


@dataclass(frozen=True, slots=True)
class ValidationCheck:
    """A summarized validation stage with an explicit result."""

    name: str
    status: CheckStatus
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "status": self.status.value, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """Machine-readable, deterministic result of validating one split."""

    split: str
    valid: bool
    case_count: int
    checks: tuple[ValidationCheck, ...]
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    counts: Mapping[str, int]
    category_distribution: Mapping[str, int]
    ambiguous_count: int
    subtype_counts: Mapping[str, int]
    file_hashes: Mapping[str, str]

    def to_dict(self) -> dict[str, object]:
        """Convert the report to JSON-safe primitive values."""

        return {
            "split": self.split,
            "valid": self.valid,
            "case_count": self.case_count,
            "checks": [check.to_dict() for check in self.checks],
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "counts": dict(self.counts),
            "category_distribution": dict(self.category_distribution),
            "ambiguous_count": self.ambiguous_count,
            "subtype_counts": dict(self.subtype_counts),
            "file_hashes": dict(self.file_hashes),
        }


class _ValidationContext:
    """Collect independent validation findings without stopping at one defect."""

    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.checks: list[ValidationCheck] = []

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warning(self, message: str) -> None:
        self.warnings.append(message)

    def stage(self, name: str, check: Callable[[], None]) -> None:
        """Run a stage, record a summary, and prevent malformed input from crashing validation."""

        error_count = len(self.errors)
        warning_count = len(self.warnings)
        try:
            check()
        except Exception as error:  # Defensive boundary for untrusted input.
            self.error(f"{name}: unexpected validation error: {error}")
        new_errors = len(self.errors) - error_count
        new_warnings = len(self.warnings) - warning_count
        if new_errors:
            status = CheckStatus.FAIL
            detail = f"{new_errors} error(s) detected"
        elif new_warnings:
            status = CheckStatus.WARNING
            detail = f"{new_warnings} warning(s) detected"
        else:
            status = CheckStatus.PASS
            detail = "passed"
        self.checks.append(ValidationCheck(name=name, status=status, detail=detail))


@dataclass(frozen=True, slots=True)
class _Payment:
    row: int
    rzp_id: str | None
    amount: Decimal | None
    currency: str | None
    created_at: datetime | None


@dataclass(frozen=True, slots=True)
class _BankSettlement:
    row: int
    settlement_id: str | None
    rzp_id: str | None
    settled_amount: Decimal | None
    settlement_date: date | None


@dataclass(frozen=True, slots=True)
class _LedgerEntry:
    row: int
    entry_id: str | None
    rzp_id: str | None
    recorded_amount: Decimal | None


@dataclass(frozen=True, slots=True)
class _Adjustment:
    row: int
    adjustment_id: str | None
    rzp_id: str | None
    adjustment_type: str | None
    amount: Decimal | None


@dataclass(frozen=True, slots=True)
class _GroundTruthCase:
    index: int
    case_id: str | None
    primary_txn_id: str | None
    operational_reference_id: str | None
    injected_type: ExceptionCategory | None
    sub_type: CaseSubtype | None
    expected_action: FinalAction | None
    expected_route: HandlingRoute | None
    is_ambiguous: bool | None


def validate_split(split: DatasetSplit, root: Path = PROJECT_ROOT) -> ValidationReport:
    """Independently validate one split without generating or modifying any file."""

    if not isinstance(split, DatasetSplit):
        raise ValueError("split must be a DatasetSplit")

    context = _ValidationContext()
    split_name = split.value.lower()
    data_directory = root / "data" / split_name
    evaluation_directory = root / "evaluation" / split_name
    csv_paths = {
        source: data_directory / filename for source, (filename, _) in CSV_CONTRACTS.items()
    }
    ground_truth_path = evaluation_directory / "ground_truth.json"
    required_paths = (*csv_paths.values(), ground_truth_path)

    context.stage("required files", lambda: _check_required_files(required_paths, context))
    context.stage("ground-truth isolation", lambda: _check_ground_truth_isolation(root, context))

    raw_csv: dict[str, list[dict[str | None, str | list[str] | None]]] = {}
    context.stage(
        "CSV readability and schema",
        lambda: _load_csv_sources(raw_csv, csv_paths, context),
    )
    raw_ground_truth: list[object] = []
    context.stage(
        "ground-truth readability and schema",
        lambda: _load_ground_truth_rows(raw_ground_truth, ground_truth_path, context),
    )

    parsed: dict[str, list[object]] = {}
    context.stage(
        "operational value schema",
        lambda: parsed.update(
            {
                "payments": _parse_payments(raw_csv["payments"], context),
                "bank_settlements": _parse_bank_settlements(raw_csv["bank_settlements"], context),
                "merchant_ledger": _parse_ledger(raw_csv["merchant_ledger"], context),
                "adjustments": _parse_adjustments(raw_csv["adjustments"], context),
            }
        ),
    )
    ground_truth: list[_GroundTruthCase] = []
    context.stage(
        "ground-truth values",
        lambda: ground_truth.extend(_parse_ground_truth(raw_ground_truth, context)),
    )

    payments = _as_records(parsed.get("payments", []), _Payment)
    settlements = _as_records(parsed.get("bank_settlements", []), _BankSettlement)
    ledgers = _as_records(parsed.get("merchant_ledger", []), _LedgerEntry)
    adjustments = _as_records(parsed.get("adjustments", []), _Adjustment)

    context.stage(
        "source identifiers and relationships",
        lambda: _validate_source_relationships(payments, settlements, ledgers, adjustments, context),
    )
    context.stage(
        "case count, joins, taxonomy, and distribution",
        lambda: _validate_case_structure(split, len(raw_ground_truth), ground_truth, payments, settlements, ledgers, adjustments, context),
    )
    context.stage(
        "operational category invariants",
        lambda: _validate_case_invariants(ground_truth, payments, settlements, ledgers, adjustments, context),
    )

    category_distribution = {
        category.value: sum(case.injected_type is category for case in ground_truth)
        for category in ExceptionCategory
    }
    subtype_counts = {
        subtype.value: sum(case.sub_type is subtype for case in ground_truth)
        for subtype in CaseSubtype
    }
    counts = {
        "payments": len(raw_csv["payments"]),
        "bank_settlements": len(raw_csv["bank_settlements"]),
        "merchant_ledger": len(raw_csv["merchant_ledger"]),
        "adjustments": len(raw_csv["adjustments"]),
        "ground_truth_entries": len(raw_ground_truth),
    }
    return ValidationReport(
        split=split_name,
        valid=not context.errors,
        case_count=len(raw_ground_truth),
        checks=tuple(context.checks),
        errors=tuple(context.errors),
        warnings=tuple(context.warnings),
        counts=counts,
        category_distribution=category_distribution,
        ambiguous_count=sum(case.is_ambiguous is True for case in ground_truth),
        subtype_counts=subtype_counts,
        file_hashes=_file_hashes(required_paths),
    )


def validate_all(root: Path = PROJECT_ROOT) -> tuple[ValidationReport, ...]:
    """Validate all configured data splits without writing reports or datasets."""

    return tuple(validate_split(split, root) for split in DatasetSplit)


def _check_required_files(paths: Iterable[Path], context: _ValidationContext) -> None:
    for path in paths:
        if not path.is_file():
            context.error(f"required file is missing: {path.as_posix()}")


def _check_ground_truth_isolation(root: Path, context: _ValidationContext) -> None:
    data_directory = root / "data"
    if not data_directory.exists():
        return
    for path in data_directory.rglob("ground_truth.json"):
        context.error(f"ground truth is incorrectly stored under data/: {path.as_posix()}")


def _load_csv_sources(
    destination: dict[str, list[dict[str | None, str | list[str] | None]]],
    paths: Mapping[str, Path],
    context: _ValidationContext,
) -> None:
    for source, path in paths.items():
        _, required_fields = CSV_CONTRACTS[source]
        destination[source] = _read_csv(path, source, required_fields, context)


def _load_ground_truth_rows(
    destination: list[object], path: Path, context: _ValidationContext
) -> None:
    destination.extend(_read_ground_truth(path, context))
    _check_ground_truth_field_sets(destination, context)


def _read_csv(
    path: Path,
    source: str,
    required_fields: tuple[str, ...],
    context: _ValidationContext,
) -> list[dict[str | None, str | list[str] | None]]:
    if not path.is_file():
        return []
    try:
        with path.open(newline="", encoding="utf-8") as file_handle:
            reader = csv.DictReader(file_handle)
            header = tuple(reader.fieldnames or ())
            missing = [field for field in required_fields if field not in header]
            if missing:
                context.error(f"{source}.csv is missing required columns: {', '.join(missing)}")
            extras = [field for field in header if field not in required_fields]
            if extras:
                context.warning(f"{source}.csv has unexpected columns: {', '.join(extras)}")
            rows = list(reader)
            for number, row in enumerate(rows, start=2):
                if None in row:
                    context.error(f"{source}.csv row {number} contains extra unheaded values")
            return rows
    except (OSError, UnicodeDecodeError, csv.Error) as error:
        context.error(f"unable to read {source}.csv: {error}")
        return []


def _read_ground_truth(path: Path, context: _ValidationContext) -> list[object]:
    if not path.is_file():
        return []
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        context.error(f"unable to read ground_truth.json: {error}")
        return []
    if not isinstance(loaded, list):
        context.error("ground_truth.json must contain a JSON array")
        return []
    return loaded


def _check_ground_truth_field_sets(rows: list[object], context: _ValidationContext) -> None:
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            context.error(f"ground_truth entry {index} must be an object")
            continue
        missing = [field for field in GROUND_TRUTH_FIELDS if field not in row]
        if missing:
            context.error(f"ground_truth entry {index} is missing fields: {', '.join(missing)}")
        extras = [field for field in row if field not in GROUND_TRUTH_FIELDS]
        if extras:
            context.warning(f"ground_truth entry {index} has unexpected fields: {', '.join(extras)}")


def _parse_payments(
    rows: list[dict[str | None, str | list[str] | None]], context: _ValidationContext
) -> list[_Payment]:
    parsed: list[_Payment] = []
    for row_number, row in enumerate(rows, start=2):
        rzp_id = _identifier(row.get("rzp_id"), f"payments row {row_number}.rzp_id", context)
        _required_text(row.get("order_id"), f"payments row {row_number}.order_id", context)
        amount = _money(row.get("amount"), f"payments row {row_number}.amount", context)
        currency = _required_text(row.get("currency"), f"payments row {row_number}.currency", context)
        if currency is not None and currency != SETTINGS.currency.value:
            context.error(f"payments row {row_number}.currency must be {SETTINGS.currency.value}")
        status = _required_text(row.get("payment_status"), f"payments row {row_number}.payment_status", context)
        if status is not None and status != "captured":
            context.error(f"payments row {row_number}.payment_status must be captured")
        created_at = _timestamp(row.get("created_at"), f"payments row {row_number}.created_at", context)
        _identifier(row.get("merchant_id"), f"payments row {row_number}.merchant_id", context)
        _required_text(row.get("method"), f"payments row {row_number}.method", context)
        parsed.append(_Payment(row_number, rzp_id, amount, currency, created_at))
    return parsed


def _parse_bank_settlements(
    rows: list[dict[str | None, str | list[str] | None]], context: _ValidationContext
) -> list[_BankSettlement]:
    parsed: list[_BankSettlement] = []
    for row_number, row in enumerate(rows, start=2):
        settlement_id = _identifier(
            row.get("settlement_id"), f"bank_settlements row {row_number}.settlement_id", context
        )
        rzp_id = _identifier(row.get("rzp_id"), f"bank_settlements row {row_number}.rzp_id", context)
        amount = _money(row.get("settled_amount"), f"bank_settlements row {row_number}.settled_amount", context)
        settlement_date = _calendar_date(
            row.get("settlement_date"), f"bank_settlements row {row_number}.settlement_date", context
        )
        _identifier(row.get("batch_id"), f"bank_settlements row {row_number}.batch_id", context)
        _required_text(row.get("remarks"), f"bank_settlements row {row_number}.remarks", context)
        parsed.append(_BankSettlement(row_number, settlement_id, rzp_id, amount, settlement_date))
    return parsed


def _parse_ledger(
    rows: list[dict[str | None, str | list[str] | None]], context: _ValidationContext
) -> list[_LedgerEntry]:
    parsed: list[_LedgerEntry] = []
    for row_number, row in enumerate(rows, start=2):
        entry_id = _identifier(row.get("entry_id"), f"merchant_ledger row {row_number}.entry_id", context)
        rzp_id = _identifier(row.get("rzp_id"), f"merchant_ledger row {row_number}.rzp_id", context)
        amount = _money(row.get("recorded_amount"), f"merchant_ledger row {row_number}.recorded_amount", context)
        _timestamp(row.get("recorded_at"), f"merchant_ledger row {row_number}.recorded_at", context)
        status = _required_text(row.get("status"), f"merchant_ledger row {row_number}.status", context)
        if status is not None and status != "posted":
            context.error(f"merchant_ledger row {row_number}.status must be posted")
        parsed.append(_LedgerEntry(row_number, entry_id, rzp_id, amount))
    return parsed


def _parse_adjustments(
    rows: list[dict[str | None, str | list[str] | None]], context: _ValidationContext
) -> list[_Adjustment]:
    parsed: list[_Adjustment] = []
    for row_number, row in enumerate(rows, start=2):
        adjustment_id = _identifier(row.get("adjustment_id"), f"adjustments row {row_number}.adjustment_id", context)
        rzp_id = _identifier(row.get("rzp_id"), f"adjustments row {row_number}.rzp_id", context)
        adjustment_type = _required_text(
            row.get("adjustment_type"), f"adjustments row {row_number}.adjustment_type", context
        )
        if adjustment_type is not None and adjustment_type not in RECOGNIZED_ADJUSTMENT_TYPES:
            context.error(f"adjustments row {row_number}.adjustment_type is not recognized")
        amount = _money(row.get("amount"), f"adjustments row {row_number}.amount", context)
        _calendar_date(row.get("adjustment_date"), f"adjustments row {row_number}.adjustment_date", context)
        _identifier(row.get("reference_id"), f"adjustments row {row_number}.reference_id", context)
        parsed.append(_Adjustment(row_number, adjustment_id, rzp_id, adjustment_type, amount))
    return parsed


def _parse_ground_truth(rows: list[object], context: _ValidationContext) -> list[_GroundTruthCase]:
    parsed: list[_GroundTruthCase] = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            continue
        case_id = _identifier(row.get("case_id"), f"ground_truth entry {index}.case_id", context)
        primary_raw = row.get("primary_txn_id")
        primary_txn_id = (
            None
            if primary_raw is None
            else _identifier(primary_raw, f"ground_truth entry {index}.primary_txn_id", context)
        )
        operational_reference_id = _identifier(
            row.get("operational_reference_id"),
            f"ground_truth entry {index}.operational_reference_id",
            context,
        )
        injected_type = _enum_value(
            row.get("injected_type"), ExceptionCategory, f"ground_truth entry {index}.injected_type", context
        )
        subtype_raw = row.get("sub_type")
        sub_type = (
            None
            if subtype_raw is None
            else _enum_value(subtype_raw, CaseSubtype, f"ground_truth entry {index}.sub_type", context)
        )
        expected_action = _enum_value(
            row.get("expected_action"), FinalAction, f"ground_truth entry {index}.expected_action", context
        )
        expected_route = _enum_value(
            row.get("expected_route"), HandlingRoute, f"ground_truth entry {index}.expected_route", context
        )
        is_ambiguous = _boolean(row.get("is_ambiguous"), f"ground_truth entry {index}.is_ambiguous", context)
        parsed.append(
            _GroundTruthCase(
                index,
                case_id,
                primary_txn_id,
                operational_reference_id,
                injected_type,
                sub_type,
                expected_action,
                expected_route,
                is_ambiguous,
            )
        )
    return parsed


def _validate_source_relationships(
    payments: list[_Payment],
    settlements: list[_BankSettlement],
    ledgers: list[_LedgerEntry],
    adjustments: list[_Adjustment],
    context: _ValidationContext,
) -> None:
    _unique((item.rzp_id for item in payments), "payment rzp_id", context)
    _unique((item.settlement_id for item in settlements), "settlement_id", context)
    _unique((item.entry_id for item in ledgers), "merchant ledger entry_id", context)
    _unique((item.adjustment_id for item in adjustments), "adjustment_id", context)

    payment_ids = {item.rzp_id for item in payments if item.rzp_id is not None}
    ledgers_by_reference = _group(ledgers, lambda item: item.rzp_id)
    for reference, entries in ledgers_by_reference.items():
        if reference is not None and len(entries) > 1:
            context.error(f"multiple merchant ledger entries exist for payment {reference}")
        if reference is not None and reference not in payment_ids:
            context.error(f"merchant ledger reference has no payment: {reference}")
    for adjustment in adjustments:
        if adjustment.rzp_id is not None and adjustment.rzp_id not in payment_ids:
            context.error(f"adjustment reference has no payment: {adjustment.rzp_id}")


def _validate_case_structure(
    split: DatasetSplit,
    raw_case_count: int,
    cases: list[_GroundTruthCase],
    payments: list[_Payment],
    settlements: list[_BankSettlement],
    ledgers: list[_LedgerEntry],
    adjustments: list[_Adjustment],
    context: _ValidationContext,
) -> None:
    expected_count = SETTINGS.dataset_sizes[split]
    if raw_case_count != expected_count:
        context.error(f"expected {expected_count} logical cases, found {raw_case_count}")
    _unique((case.case_id for case in cases), "ground-truth case_id", context)
    _unique((case.operational_reference_id for case in cases), "operational_reference_id", context)

    expected_distribution = _allocate_counts(expected_count, SETTINGS.case_distribution_weights)
    actual_distribution = Counter(case.injected_type for case in cases if case.injected_type is not None)
    if actual_distribution != expected_distribution:
        context.error("ground-truth category distribution differs from the configured allocation")

    expected_fee_subtypes = _allocate_counts(
        expected_distribution[ExceptionCategory.FEE_DEDUCTION], SETTINGS.fee_subtype_weights
    )
    actual_fee_subtypes = Counter(
        case.sub_type
        for case in cases
        if case.injected_type is ExceptionCategory.FEE_DEDUCTION and case.sub_type is not None
    )
    if actual_fee_subtypes != expected_fee_subtypes:
        context.error("fee subtype distribution differs from the configured allocation")

    payment_by_reference = _single_index(payments, lambda item: item.rzp_id)
    settlements_by_reference = _group(settlements, lambda item: item.rzp_id)
    ledgers_by_reference = _group(ledgers, lambda item: item.rzp_id)
    adjustments_by_reference = _group(adjustments, lambda item: item.rzp_id)
    normal_references: set[str] = set()
    unknown_references: set[str] = set()

    for case in cases:
        if case.operational_reference_id is None or case.injected_type is None:
            continue
        reference = case.operational_reference_id
        _validate_expected_outcome(case, context)
        if case.injected_type is ExceptionCategory.UNKNOWN_TRANSACTION:
            unknown_references.add(reference)
            if case.primary_txn_id is not None:
                context.error(f"unknown transaction {reference} must have null primary_txn_id")
            if reference in payment_by_reference:
                context.error(f"unknown transaction {reference} incorrectly appears in payments.csv")
            if not settlements_by_reference.get(reference):
                context.error(f"unknown transaction {reference} has no bank settlement")
            if ledgers_by_reference.get(reference) or adjustments_by_reference.get(reference):
                context.error(f"unknown transaction {reference} has unexpected payment-side records")
        else:
            normal_references.add(reference)
            if case.primary_txn_id != reference:
                context.error(f"normal case {reference} must use its payment ID as primary_txn_id")
            if reference not in payment_by_reference:
                context.error(f"normal case {reference} has no payment")
            if len(ledgers_by_reference.get(reference, [])) != 1:
                context.error(f"normal case {reference} must have exactly one merchant ledger entry")

    actual_payment_references = set(payment_by_reference)
    if actual_payment_references != normal_references:
        context.error("payments.csv contains references that do not map one-to-one to normal cases")
    allowed_bank_references = normal_references | unknown_references
    actual_bank_references = {item.rzp_id for item in settlements if item.rzp_id is not None}
    if not actual_bank_references.issubset(allowed_bank_references):
        context.error("bank settlements contain references that belong to no case")
    actual_ledger_references = {item.rzp_id for item in ledgers if item.rzp_id is not None}
    if actual_ledger_references != normal_references:
        context.error("merchant ledger contains references that do not map one-to-one to normal cases")
    actual_adjustment_references = {item.rzp_id for item in adjustments if item.rzp_id is not None}
    if not actual_adjustment_references.issubset(normal_references):
        context.error("adjustments contain references that belong to no normal case")


def _validate_expected_outcome(case: _GroundTruthCase, context: _ValidationContext) -> None:
    """Validate taxonomy/action/route consistency without consulting the generator."""

    category = case.injected_type
    if category is None:
        return
    if case.is_ambiguous is True and case.expected_route is not HandlingRoute.AI_INVESTIGATOR:
        context.error(f"ambiguous case {case.index} must route to AI_INVESTIGATOR")
    if case.is_ambiguous is False and case.expected_route is not HandlingRoute.DETERMINISTIC:
        context.error(f"non-ambiguous case {case.index} must route to DETERMINISTIC")

    if category is not ExceptionCategory.FEE_DEDUCTION:
        if case.sub_type is not None:
            context.error(f"non-fee case {case.index} must not define a subtype")
        expected_actions = {
            ExceptionCategory.EXACT_MATCH: FinalAction.AUTO_RESOLVE,
            ExceptionCategory.TIMING_LAG: FinalAction.MONITOR,
            ExceptionCategory.DUPLICATE: FinalAction.ESCALATE,
            ExceptionCategory.MISSING_SETTLEMENT: FinalAction.ESCALATE,
            ExceptionCategory.UNKNOWN_TRANSACTION: FinalAction.ESCALATE,
        }
        if case.expected_action is not expected_actions[category]:
            context.error(f"case {case.index} has an invalid action for {category.value}")
        return

    if case.sub_type is None:
        context.error(f"fee deduction case {case.index} must define a subtype")
        return
    subtype_expectations = {
        CaseSubtype.STANDARD_FEE: (False, HandlingRoute.DETERMINISTIC, FinalAction.AUTO_RESOLVE),
        CaseSubtype.REFUND_ADJUSTMENT: (True, HandlingRoute.AI_INVESTIGATOR, FinalAction.AUTO_RESOLVE),
        CaseSubtype.LEDGER_MISMATCH: (True, HandlingRoute.AI_INVESTIGATOR, FinalAction.ESCALATE),
    }
    expected = subtype_expectations[case.sub_type]
    actual = (case.is_ambiguous, case.expected_route, case.expected_action)
    if actual != expected:
        context.error(f"fee deduction case {case.index} has inconsistent subtype/action/route values")


def _validate_case_invariants(
    cases: list[_GroundTruthCase],
    payments: list[_Payment],
    settlements: list[_BankSettlement],
    ledgers: list[_LedgerEntry],
    adjustments: list[_Adjustment],
    context: _ValidationContext,
) -> None:
    payment_by_reference = _single_index(payments, lambda item: item.rzp_id)
    settlements_by_reference = _group(settlements, lambda item: item.rzp_id)
    ledgers_by_reference = _group(ledgers, lambda item: item.rzp_id)
    adjustments_by_reference = _group(adjustments, lambda item: item.rzp_id)

    for case in cases:
        if case.operational_reference_id is None or case.injected_type is None:
            continue
        reference = case.operational_reference_id
        if case.injected_type is ExceptionCategory.UNKNOWN_TRANSACTION:
            if reference in payment_by_reference or not settlements_by_reference.get(reference):
                context.error(f"unknown transaction invariant failed for {reference}")
            continue

        payment = payment_by_reference.get(reference)
        ledger_entries = ledgers_by_reference.get(reference, [])
        settlement_entries = settlements_by_reference.get(reference, [])
        adjustment_entries = adjustments_by_reference.get(reference, [])
        if payment is None or payment.amount is None or len(ledger_entries) != 1:
            continue
        ledger = ledger_entries[0]
        if ledger.recorded_amount is None:
            continue

        if case.injected_type is ExceptionCategory.EXACT_MATCH:
            if len(settlement_entries) != 1 or adjustment_entries:
                context.error(f"exact-match invariant failed for {reference}: invalid source row count")
                continue
            settlement = settlement_entries[0]
            if settlement.settled_amount != payment.amount or ledger.recorded_amount != payment.amount:
                context.error(f"exact-match invariant failed for {reference}: amounts disagree")
        elif case.injected_type is ExceptionCategory.FEE_DEDUCTION:
            _validate_fee_invariant(
                case, payment, ledger, settlement_entries, adjustment_entries, context
            )
        elif case.injected_type is ExceptionCategory.TIMING_LAG:
            age = _age_at_evaluation(payment)
            if settlement_entries or age is None or not (timedelta(0) < age <= timedelta(days=SETTINGS.settlement_window_days)):
                context.error(f"timing-lag invariant failed for {reference}")
        elif case.injected_type is ExceptionCategory.MISSING_SETTLEMENT:
            age = _age_at_evaluation(payment)
            if settlement_entries or age is None or age <= timedelta(days=SETTINGS.settlement_window_days):
                context.error(f"missing-settlement invariant failed for {reference}")
        elif case.injected_type is ExceptionCategory.DUPLICATE:
            if len(settlement_entries) < 2:
                context.error(f"duplicate invariant failed for {reference}: fewer than two settlements")
            elif any(entry.settled_amount != payment.amount for entry in settlement_entries):
                context.error(f"duplicate invariant failed for {reference}: settlement amounts disagree")


def _validate_fee_invariant(
    case: _GroundTruthCase,
    payment: _Payment,
    ledger: _LedgerEntry,
    settlements: list[_BankSettlement],
    adjustments: list[_Adjustment],
    context: _ValidationContext,
) -> None:
    reference = case.operational_reference_id or f"case-{case.index}"
    if len(settlements) != 1 or settlements[0].settled_amount is None or payment.amount is None:
        context.error(f"fee deduction invariant failed for {reference}: invalid settlement structure")
        return
    adjustment_amounts = [item.amount for item in adjustments]
    if any(amount is None for amount in adjustment_amounts):
        return
    adjustment_total = sum((amount for amount in adjustment_amounts if amount is not None), Decimal("0"))
    fee = _configured_fee(payment.amount)
    expected_settlement = payment.amount - fee - adjustment_total
    if settlements[0].settled_amount != expected_settlement:
        context.error(f"fee deduction invariant failed for {reference}: arithmetic does not close")
        return

    if case.sub_type is CaseSubtype.STANDARD_FEE:
        if adjustments or ledger.recorded_amount != payment.amount:
            context.error(f"standard-fee invariant failed for {reference}")
    elif case.sub_type is CaseSubtype.REFUND_ADJUSTMENT:
        if not adjustments or ledger.recorded_amount != payment.amount:
            context.error(f"refund-adjustment invariant failed for {reference}")
    elif case.sub_type is CaseSubtype.LEDGER_MISMATCH:
        if adjustments or ledger.recorded_amount == payment.amount:
            context.error(f"ledger-mismatch invariant failed for {reference}")


def _configured_fee(amount: Decimal) -> Decimal:
    return (amount * SETTINGS.fee_rate).quantize(
        SETTINGS.monetary_tolerance, rounding=ROUND_HALF_UP
    )


def _age_at_evaluation(payment: _Payment) -> timedelta | None:
    if payment.created_at is None:
        return None
    return SETTINGS.evaluation_date - payment.created_at.date()


def _required_text(value: object, location: str, context: _ValidationContext) -> str | None:
    if not isinstance(value, str) or not value.strip():
        context.error(f"{location} must be a non-empty string")
        return None
    if value != value.strip():
        context.error(f"{location} must not contain surrounding whitespace")
        return None
    return value


def _identifier(value: object, location: str, context: _ValidationContext) -> str | None:
    parsed = _required_text(value, location, context)
    if parsed is not None and not IDENTIFIER_PATTERN.fullmatch(parsed):
        context.error(f"{location} is not a valid identifier")
        return None
    return parsed


def _money(value: object, location: str, context: _ValidationContext) -> Decimal | None:
    parsed = _required_text(value, location, context)
    if parsed is None:
        return None
    if not MONEY_PATTERN.fullmatch(parsed):
        context.error(f"{location} is not a supported exact monetary representation")
        return None
    try:
        amount = Decimal(parsed)
    except InvalidOperation:
        context.error(f"{location} is not a valid Decimal")
        return None
    if not amount.is_finite() or amount <= Decimal("0"):
        context.error(f"{location} must be a positive finite Decimal")
        return None
    if amount != amount.quantize(SETTINGS.monetary_tolerance):
        context.error(f"{location} exceeds configured monetary precision")
        return None
    return amount


def _calendar_date(value: object, location: str, context: _ValidationContext) -> date | None:
    parsed = _required_text(value, location, context)
    if parsed is None:
        return None
    try:
        return date.fromisoformat(parsed)
    except ValueError:
        context.error(f"{location} is not an ISO date")
        return None


def _timestamp(value: object, location: str, context: _ValidationContext) -> datetime | None:
    parsed = _required_text(value, location, context)
    if parsed is None:
        return None
    try:
        return datetime.fromisoformat(parsed)
    except ValueError:
        context.error(f"{location} is not an ISO timestamp")
        return None


def _enum_value[EnumValue: (ExceptionCategory, CaseSubtype, FinalAction, HandlingRoute)](
    value: object,
    enum_type: type[EnumValue],
    location: str,
    context: _ValidationContext,
) -> EnumValue | None:
    if not isinstance(value, str):
        context.error(f"{location} must be a string enum value")
        return None
    try:
        return enum_type(value)
    except ValueError:
        context.error(f"{location} is not an approved {enum_type.__name__}")
        return None


def _boolean(value: object, location: str, context: _ValidationContext) -> bool | None:
    if type(value) is not bool:
        context.error(f"{location} must be a boolean")
        return None
    return value


def _unique(values: Iterable[str | None], label: str, context: _ValidationContext) -> None:
    present = [value for value in values if value is not None]
    duplicates = sorted(value for value, count in Counter(present).items() if count > 1)
    if duplicates:
        context.error(f"duplicate {label}: {', '.join(duplicates)}")


def _group[Record](records: Iterable[Record], key: Callable[[Record], str | None]) -> dict[str | None, list[Record]]:
    grouped: dict[str | None, list[Record]] = defaultdict(list)
    for record in records:
        grouped[key(record)].append(record)
    return dict(grouped)


def _single_index[Record](records: Iterable[Record], key: Callable[[Record], str | None]) -> dict[str, Record]:
    indexed: dict[str, Record] = {}
    for record in records:
        value = key(record)
        if value is not None and value not in indexed:
            indexed[value] = record
    return indexed


def _as_records[Record](records: list[object], record_type: type[Record]) -> list[Record]:
    return [record for record in records if isinstance(record, record_type)]


def _allocate_counts[Category](total: int, weights: Mapping[Category, int]) -> dict[Category, int]:
    """Independently reproduce the configured largest-remainder allocation contract."""

    ordered = tuple(weights.items())
    weight_total = sum(weight for _, weight in ordered)
    allocations = {category: total * weight // weight_total for category, weight in ordered}
    remaining = total - sum(allocations.values())
    remainders = sorted(
        enumerate(ordered),
        key=lambda item: (-(total * item[1][1] % weight_total), item[0]),
    )
    for index, _ in remainders[:remaining]:
        allocations[ordered[index][0]] += 1
    return allocations


def _file_hashes(paths: Iterable[Path]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in paths:
        if path.is_file():
            hashes[path.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def _split_from_argument(value: str) -> DatasetSplit:
    for split in DatasetSplit:
        if split.value.lower() == value:
            return split
    raise ValueError(f"unknown split: {value}")


def main(arguments: list[str] | None = None) -> int:
    """Print a machine-readable report and return a meaningful process exit code."""

    parser = argparse.ArgumentParser(description="Validate existing LedgerLens datasets.")
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--split", choices=[split.value.lower() for split in DatasetSplit])
    selection.add_argument("--all", action="store_true", help="validate DEV, VALIDATION, and HOLDOUT")
    options = parser.parse_args(arguments)

    reports = validate_all() if options.all else (validate_split(_split_from_argument(options.split)),)
    payload: dict[str, object]
    if options.all:
        payload = {"valid": all(report.valid for report in reports), "reports": [report.to_dict() for report in reports]}
    else:
        payload = reports[0].to_dict()
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if all(report.valid for report in reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
