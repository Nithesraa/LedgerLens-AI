"""Read-only deterministic reconciliation over LedgerLens operational CSV data."""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Final

from ledgerlens.config import (
    SETTINGS,
    CaseSubtype,
    DatasetSplit,
    ExceptionCategory,
    FinalAction,
    HandlingRoute,
    InternalProcessingState,
)


PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
IDENTIFIER_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{2,127}$")
MONEY_DECIMAL_PLACES: Final[int] = -SETTINGS.monetary_tolerance.as_tuple().exponent
MONEY_PATTERN: Final[re.Pattern[str]] = re.compile(
    rf"^(?:0|[1-9]\d*)\.\d{{{MONEY_DECIMAL_PLACES}}}$"
)
CSV_FIELDS: Final[Mapping[str, tuple[str, ...]]] = {
    "payments.csv": (
        "rzp_id",
        "order_id",
        "amount",
        "currency",
        "payment_status",
        "created_at",
        "merchant_id",
        "method",
    ),
    "bank_settlements.csv": (
        "settlement_id",
        "rzp_id",
        "settled_amount",
        "settlement_date",
        "batch_id",
        "remarks",
    ),
    "merchant_ledger.csv": (
        "entry_id",
        "rzp_id",
        "recorded_amount",
        "recorded_at",
        "status",
    ),
    "adjustments.csv": (
        "adjustment_id",
        "rzp_id",
        "adjustment_type",
        "amount",
        "adjustment_date",
        "reference_id",
    ),
}


class OperationalDataError(ValueError):
    """Controlled failure for malformed operational input."""

    def __init__(self, errors: Iterable[str]) -> None:
        self.errors = tuple(errors)
        super().__init__("; ".join(self.errors))


@dataclass(frozen=True, slots=True)
class Payment:
    rzp_id: str
    order_id: str
    amount: Decimal
    currency: str
    payment_status: str
    created_at: datetime
    merchant_id: str
    method: str


@dataclass(frozen=True, slots=True)
class BankSettlement:
    settlement_id: str
    rzp_id: str
    settled_amount: Decimal
    settlement_date: date
    batch_id: str
    remarks: str


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    entry_id: str
    rzp_id: str
    recorded_amount: Decimal
    recorded_at: datetime
    status: str


@dataclass(frozen=True, slots=True)
class Adjustment:
    adjustment_id: str
    rzp_id: str
    adjustment_type: str
    amount: Decimal
    adjustment_date: date
    reference_id: str


@dataclass(frozen=True, slots=True)
class OperationalDataset:
    """Normalized operational records and linear-time lookup indexes."""

    payments: Mapping[str, Payment]
    settlements_by_reference: Mapping[str, tuple[BankSettlement, ...]]
    ledgers_by_reference: Mapping[str, tuple[LedgerEntry, ...]]
    adjustments_by_reference: Mapping[str, tuple[Adjustment, ...]]


@dataclass(frozen=True, slots=True)
class EngineResult:
    """One deterministic reasoning result, ready for later bounded processing."""

    operational_reference_id: str
    primary_txn_id: str | None
    route: HandlingRoute
    status: InternalProcessingState | None
    detected_issue: ExceptionCategory | None
    sub_type: CaseSubtype | None
    recommended_action: FinalAction | None
    reason_for_routing: str | None
    evidence: Mapping[str, object]
    decision_trace: Mapping[str, bool | int | None]
    processing_metadata: Mapping[str, str]

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-safe, structured result without labels external to operations."""

        return {
            "operational_reference_id": self.operational_reference_id,
            "primary_txn_id": self.primary_txn_id,
            "route": self.route.value,
            "status": self.status.value if self.status is not None else None,
            "detected_issue": self.detected_issue.value if self.detected_issue is not None else None,
            "sub_type": self.sub_type.value if self.sub_type is not None else None,
            "recommended_action": (
                self.recommended_action.value if self.recommended_action is not None else None
            ),
            "reason_for_routing": self.reason_for_routing,
            "evidence": dict(self.evidence),
            "decision_trace": dict(self.decision_trace),
            "processing_metadata": dict(self.processing_metadata),
        }


@dataclass(frozen=True, slots=True)
class ReconciliationRun:
    """The deterministic output of processing one operational split."""

    split: str
    results: tuple[EngineResult, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "split": self.split,
            "results": [result.to_dict() for result in self.results],
        }


def reconcile_split(split: DatasetSplit, root: Path = PROJECT_ROOT) -> ReconciliationRun:
    """Read operational files for one split and produce deterministic case results."""

    if not isinstance(split, DatasetSplit):
        raise ValueError("split must be a DatasetSplit")
    dataset = load_operational_dataset(root / "data" / split.value.lower())
    references = sorted(set(dataset.payments) | set(dataset.settlements_by_reference))
    results = tuple(_reconcile_reference(reference, dataset) for reference in references)
    return ReconciliationRun(split=split.value.lower(), results=results)


def reconcile_all(root: Path = PROJECT_ROOT) -> tuple[ReconciliationRun, ...]:
    """Reconcile each configured split without mutating any operational file."""

    return tuple(reconcile_split(split, root) for split in DatasetSplit)


def load_operational_dataset(data_directory: Path) -> OperationalDataset:
    """Strictly parse and normalize operational CSV inputs before reasoning begins."""

    errors: list[str] = []
    raw_sources = {
        filename: _read_csv(data_directory / filename, fields, errors)
        for filename, fields in CSV_FIELDS.items()
    }
    if errors:
        raise OperationalDataError(errors)

    payments = _parse_rows(raw_sources["payments.csv"], "payments.csv", _payment_from_row, errors)
    settlements = _parse_rows(
        raw_sources["bank_settlements.csv"], "bank_settlements.csv", _settlement_from_row, errors
    )
    ledgers = _parse_rows(
        raw_sources["merchant_ledger.csv"], "merchant_ledger.csv", _ledger_from_row, errors
    )
    adjustments = _parse_rows(
        raw_sources["adjustments.csv"], "adjustments.csv", _adjustment_from_row, errors
    )
    if errors:
        raise OperationalDataError(errors)

    payment_index = _unique_index(payments, lambda record: record.rzp_id, "payment rzp_id", errors)
    _unique_index(settlements, lambda record: record.settlement_id, "settlement_id", errors)
    _unique_index(ledgers, lambda record: record.entry_id, "ledger entry_id", errors)
    _unique_index(adjustments, lambda record: record.adjustment_id, "adjustment_id", errors)
    settlements_by_reference = _group_records(settlements, lambda record: record.rzp_id)
    ledgers_by_reference = _group_records(ledgers, lambda record: record.rzp_id)
    adjustments_by_reference = _group_records(adjustments, lambda record: record.rzp_id)

    for reference in sorted(ledgers_by_reference):
        if reference not in payment_index:
            errors.append(f"ledger reference has no payment: {reference}")
        elif len(ledgers_by_reference[reference]) != 1:
            errors.append(f"payment has conflicting ledger entries: {reference}")
    for reference in sorted(adjustments_by_reference):
        if reference not in payment_index:
            errors.append(f"adjustment reference has no payment: {reference}")
    for reference in sorted(payment_index):
        if len(ledgers_by_reference.get(reference, ())) != 1:
            errors.append(f"payment must have exactly one ledger entry: {reference}")
    if errors:
        raise OperationalDataError(errors)

    return OperationalDataset(
        payments=payment_index,
        settlements_by_reference=settlements_by_reference,
        ledgers_by_reference=ledgers_by_reference,
        adjustments_by_reference=adjustments_by_reference,
    )


def calculate_configured_fee(payment_amount: Decimal) -> Decimal:
    """Calculate a fee using only the centralized exact-money configuration."""

    if type(payment_amount) is not Decimal or not payment_amount.is_finite() or payment_amount <= 0:
        raise ValueError("payment_amount must be a positive finite Decimal")
    return (payment_amount * SETTINGS.fee_rate).quantize(
        SETTINGS.monetary_tolerance, rounding=ROUND_HALF_UP
    )


def amounts_within_tolerance(first: Decimal, second: Decimal) -> bool:
    """Compare two exact monetary values using the configured explicit tolerance."""

    if type(first) is not Decimal or type(second) is not Decimal:
        raise ValueError("monetary comparisons require Decimal values")
    return abs(first - second) <= SETTINGS.monetary_tolerance


def _reconcile_reference(reference: str, dataset: OperationalDataset) -> EngineResult:
    payment = dataset.payments.get(reference)
    settlements = dataset.settlements_by_reference.get(reference, ())
    ledger_entries = dataset.ledgers_by_reference.get(reference, ())
    adjustments = dataset.adjustments_by_reference.get(reference, ())
    evidence = _evidence(payment, settlements, ledger_entries, adjustments)
    trace = _decision_trace(payment, settlements, ledger_entries, adjustments)

    if payment is None:
        return _deterministic_result(
            reference,
            None,
            ExceptionCategory.UNKNOWN_TRANSACTION,
            None,
            FinalAction.ESCALATE,
            evidence,
            trace,
        )

    ledger = ledger_entries[0]
    if len(settlements) > 1:
        return _deterministic_result(
            reference,
            payment.rzp_id,
            ExceptionCategory.DUPLICATE,
            None,
            FinalAction.ESCALATE,
            evidence,
            trace,
        )

    if not settlements:
        age = SETTINGS.evaluation_date - payment.created_at.date()
        if age > timedelta(days=SETTINGS.settlement_window_days):
            return _deterministic_result(
                reference,
                payment.rzp_id,
                ExceptionCategory.MISSING_SETTLEMENT,
                None,
                FinalAction.ESCALATE,
                evidence,
                trace,
            )
        return _deterministic_result(
            reference,
            payment.rzp_id,
            ExceptionCategory.TIMING_LAG,
            None,
            FinalAction.MONITOR,
            evidence,
            trace,
        )

    settlement = settlements[0]
    expected_fee = calculate_configured_fee(payment.amount)
    fee_settlement = payment.amount - expected_fee
    ledger_matches = amounts_within_tolerance(payment.amount, ledger.recorded_amount)
    bank_matches_fee = amounts_within_tolerance(settlement.settled_amount, fee_settlement)

    if not ledger_matches:
        return _ai_review_result(
            reference,
            payment.rzp_id,
            "ledger_mismatch_requires_investigation",
            evidence,
            trace,
        )

    if adjustments:
        adjusted_settlement = payment.amount - expected_fee - sum(
            (adjustment.amount for adjustment in adjustments), Decimal("0")
        )
        reason = (
            "fee_and_adjustment_require_investigation"
            if amounts_within_tolerance(settlement.settled_amount, adjusted_settlement)
            else "adjustment_and_settlement_difference_require_investigation"
        )
        return _ai_review_result(reference, payment.rzp_id, reason, evidence, trace)

    if amounts_within_tolerance(settlement.settled_amount, payment.amount):
        return _deterministic_result(
            reference,
            payment.rzp_id,
            ExceptionCategory.EXACT_MATCH,
            None,
            FinalAction.AUTO_RESOLVE,
            evidence,
            trace,
        )
    if bank_matches_fee:
        return _deterministic_result(
            reference,
            payment.rzp_id,
            ExceptionCategory.FEE_DEDUCTION,
            CaseSubtype.STANDARD_FEE,
            FinalAction.AUTO_RESOLVE,
            evidence,
            trace,
        )
    return _ai_review_result(
        reference,
        payment.rzp_id,
        "unexplained_financial_difference_requires_investigation",
        evidence,
        trace,
    )


def _deterministic_result(
    reference: str,
    primary_txn_id: str | None,
    issue: ExceptionCategory,
    subtype: CaseSubtype | None,
    action: FinalAction,
    evidence: Mapping[str, object],
    trace: Mapping[str, bool | int | None],
) -> EngineResult:
    return EngineResult(
        operational_reference_id=reference,
        primary_txn_id=primary_txn_id,
        route=HandlingRoute.DETERMINISTIC,
        status=None,
        detected_issue=issue,
        sub_type=subtype,
        recommended_action=action,
        reason_for_routing=None,
        evidence=evidence,
        decision_trace=trace,
        processing_metadata=_processing_metadata(),
    )


def _ai_review_result(
    reference: str,
    primary_txn_id: str,
    reason: str,
    evidence: Mapping[str, object],
    trace: Mapping[str, bool | int | None],
) -> EngineResult:
    return EngineResult(
        operational_reference_id=reference,
        primary_txn_id=primary_txn_id,
        route=HandlingRoute.AI_INVESTIGATOR,
        status=InternalProcessingState.PENDING_AI_REVIEW,
        detected_issue=None,
        sub_type=None,
        recommended_action=None,
        reason_for_routing=reason,
        evidence=evidence,
        decision_trace=trace,
        processing_metadata=_processing_metadata(),
    )


def _evidence(
    payment: Payment | None,
    settlements: tuple[BankSettlement, ...],
    ledger_entries: tuple[LedgerEntry, ...],
    adjustments: tuple[Adjustment, ...],
) -> dict[str, object]:
    """Build only traceable operational/configuration evidence for a result."""

    ledger = ledger_entries[0] if ledger_entries else None
    settlement = settlements[0] if len(settlements) == 1 else None
    evidence: dict[str, object] = {
        "payment": _payment_evidence(payment),
        "merchant_ledger": [_ledger_evidence(entry) for entry in ledger_entries],
        "bank_settlements": [_settlement_evidence(entry) for entry in settlements],
        "adjustments": [_adjustment_evidence(entry) for entry in adjustments],
        "configuration": {
            "currency": SETTINGS.currency.value,
            "fee_rate": _money_text(SETTINGS.fee_rate),
            "monetary_tolerance": _money_text(SETTINGS.monetary_tolerance),
            "evaluation_date": SETTINGS.evaluation_date.isoformat(),
            "settlement_window_days": SETTINGS.settlement_window_days,
        },
    }
    if payment is None:
        evidence["calculations"] = None
        return evidence

    fee = calculate_configured_fee(payment.amount)
    adjustment_total = sum((adjustment.amount for adjustment in adjustments), Decimal("0"))
    fee_settlement = payment.amount - fee
    adjusted_settlement = fee_settlement - adjustment_total
    observed_settlement = settlement.settled_amount if settlement is not None else None
    evidence["calculations"] = {
        "payment_amount": _money_text(payment.amount),
        "configured_fee_amount": _money_text(fee),
        "expected_fee_settlement": _money_text(fee_settlement),
        "adjustment_total": _money_text(adjustment_total),
        "expected_adjusted_settlement": _money_text(adjusted_settlement),
        "observed_settlement": _money_text(observed_settlement) if observed_settlement else None,
        "ledger_difference": _money_text(payment.amount - ledger.recorded_amount) if ledger else None,
        "bank_matches_fee": (
            amounts_within_tolerance(observed_settlement, fee_settlement)
            if observed_settlement is not None
            else None
        ),
    }
    return evidence


def _decision_trace(
    payment: Payment | None,
    settlements: tuple[BankSettlement, ...],
    ledger_entries: tuple[LedgerEntry, ...],
    adjustments: tuple[Adjustment, ...],
) -> dict[str, bool | int | None]:
    ledger = ledger_entries[0] if ledger_entries else None
    age: timedelta | None = None
    if payment is not None:
        age = SETTINGS.evaluation_date - payment.created_at.date()
    return {
        "payment_exists": payment is not None,
        "merchant_ledger_exists": ledger is not None,
        "settlement_exists": bool(settlements),
        "settlement_count": len(settlements),
        "duplicate_detected": len(settlements) > 1,
        "payment_age_days": age.days if age is not None else None,
        "settlement_within_window": (
            timedelta(0) <= age <= timedelta(days=SETTINGS.settlement_window_days)
            if age is not None and not settlements
            else None
        ),
        "ledger_matches_payment": (
            amounts_within_tolerance(payment.amount, ledger.recorded_amount)
            if payment is not None and ledger is not None
            else None
        ),
        "adjustment_count": len(adjustments),
    }


def _processing_metadata() -> dict[str, str]:
    return {
        "engine_version": "1",
        "currency": SETTINGS.currency.value,
        "fee_rate": _money_text(SETTINGS.fee_rate),
        "evaluation_date": SETTINGS.evaluation_date.isoformat(),
    }


def _payment_evidence(payment: Payment | None) -> dict[str, str] | None:
    if payment is None:
        return None
    return {
        "rzp_id": payment.rzp_id,
        "order_id": payment.order_id,
        "amount": _money_text(payment.amount),
        "currency": payment.currency,
        "payment_status": payment.payment_status,
        "created_at": payment.created_at.isoformat(),
        "merchant_id": payment.merchant_id,
        "method": payment.method,
    }


def _settlement_evidence(settlement: BankSettlement) -> dict[str, str]:
    return {
        "settlement_id": settlement.settlement_id,
        "rzp_id": settlement.rzp_id,
        "settled_amount": _money_text(settlement.settled_amount),
        "settlement_date": settlement.settlement_date.isoformat(),
        "batch_id": settlement.batch_id,
        "remarks": settlement.remarks,
    }


def _ledger_evidence(ledger: LedgerEntry) -> dict[str, str]:
    return {
        "entry_id": ledger.entry_id,
        "rzp_id": ledger.rzp_id,
        "recorded_amount": _money_text(ledger.recorded_amount),
        "recorded_at": ledger.recorded_at.isoformat(),
        "status": ledger.status,
    }


def _adjustment_evidence(adjustment: Adjustment) -> dict[str, str]:
    return {
        "adjustment_id": adjustment.adjustment_id,
        "rzp_id": adjustment.rzp_id,
        "adjustment_type": adjustment.adjustment_type,
        "amount": _money_text(adjustment.amount),
        "adjustment_date": adjustment.adjustment_date.isoformat(),
        "reference_id": adjustment.reference_id,
    }


def _read_csv(
    path: Path, required_fields: tuple[str, ...], errors: list[str]
) -> list[dict[str | None, str | list[str] | None]]:
    if not path.is_file():
        errors.append(f"required operational file is missing: {path.as_posix()}")
        return []
    try:
        with path.open(newline="", encoding="utf-8") as file_handle:
            reader = csv.DictReader(file_handle)
            header = tuple(reader.fieldnames or ())
            missing = [field for field in required_fields if field not in header]
            if missing:
                errors.append(f"{path.name} is missing required columns: {', '.join(missing)}")
            rows = list(reader)
            if any(None in row for row in rows):
                errors.append(f"{path.name} contains values without a header")
            return rows
    except (OSError, UnicodeDecodeError, csv.Error) as error:
        errors.append(f"unable to read {path.name}: {error}")
        return []


def _parse_rows[Record](
    rows: list[dict[str | None, str | list[str] | None]],
    filename: str,
    parser: Callable[[Mapping[str | None, object]], Record],
    errors: list[str],
) -> list[Record]:
    parsed: list[Record] = []
    for row_number, row in enumerate(rows, start=2):
        try:
            parsed.append(parser(row))
        except ValueError as error:
            errors.append(f"{filename} row {row_number}: {error}")
    return parsed


def _payment_from_row(row: Mapping[str | None, object]) -> Payment:
    currency = _text(row.get("currency"), "currency")
    if currency != SETTINGS.currency.value:
        raise ValueError(f"currency must be {SETTINGS.currency.value}")
    payment_status = _text(row.get("payment_status"), "payment_status")
    if payment_status != "captured":
        raise ValueError("payment_status must be captured")
    return Payment(
        rzp_id=_identifier(row.get("rzp_id"), "rzp_id"),
        order_id=_identifier(row.get("order_id"), "order_id"),
        amount=_money(row.get("amount"), "amount"),
        currency=currency,
        payment_status=payment_status,
        created_at=_timestamp(row.get("created_at"), "created_at"),
        merchant_id=_identifier(row.get("merchant_id"), "merchant_id"),
        method=_text(row.get("method"), "method"),
    )


def _settlement_from_row(row: Mapping[str | None, object]) -> BankSettlement:
    return BankSettlement(
        settlement_id=_identifier(row.get("settlement_id"), "settlement_id"),
        rzp_id=_identifier(row.get("rzp_id"), "rzp_id"),
        settled_amount=_money(row.get("settled_amount"), "settled_amount"),
        settlement_date=_calendar_date(row.get("settlement_date"), "settlement_date"),
        batch_id=_identifier(row.get("batch_id"), "batch_id"),
        remarks=_text(row.get("remarks"), "remarks"),
    )


def _ledger_from_row(row: Mapping[str | None, object]) -> LedgerEntry:
    status = _text(row.get("status"), "status")
    if status != "posted":
        raise ValueError("status must be posted")
    return LedgerEntry(
        entry_id=_identifier(row.get("entry_id"), "entry_id"),
        rzp_id=_identifier(row.get("rzp_id"), "rzp_id"),
        recorded_amount=_money(row.get("recorded_amount"), "recorded_amount"),
        recorded_at=_timestamp(row.get("recorded_at"), "recorded_at"),
        status=status,
    )


def _adjustment_from_row(row: Mapping[str | None, object]) -> Adjustment:
    adjustment_type = _text(row.get("adjustment_type"), "adjustment_type")
    if adjustment_type != "refund":
        raise ValueError("adjustment_type must be refund")
    return Adjustment(
        adjustment_id=_identifier(row.get("adjustment_id"), "adjustment_id"),
        rzp_id=_identifier(row.get("rzp_id"), "rzp_id"),
        adjustment_type=adjustment_type,
        amount=_money(row.get("amount"), "amount"),
        adjustment_date=_calendar_date(row.get("adjustment_date"), "adjustment_date"),
        reference_id=_identifier(row.get("reference_id"), "reference_id"),
    )


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or value != value.strip() or not value:
        raise ValueError(f"{field} must be a non-empty trimmed string")
    return value


def _identifier(value: object, field: str) -> str:
    parsed = _text(value, field)
    if not IDENTIFIER_PATTERN.fullmatch(parsed):
        raise ValueError(f"{field} is not a valid identifier")
    return parsed


def _money(value: object, field: str) -> Decimal:
    parsed = _text(value, field)
    if not MONEY_PATTERN.fullmatch(parsed):
        raise ValueError(f"{field} is not a supported exact monetary representation")
    try:
        amount = Decimal(parsed)
    except InvalidOperation as error:
        raise ValueError(f"{field} is not a valid Decimal") from error
    if not amount.is_finite() or amount <= 0:
        raise ValueError(f"{field} must be a positive finite Decimal")
    if amount != amount.quantize(SETTINGS.monetary_tolerance):
        raise ValueError(f"{field} exceeds configured monetary precision")
    return amount


def _calendar_date(value: object, field: str) -> date:
    try:
        return date.fromisoformat(_text(value, field))
    except ValueError as error:
        raise ValueError(f"{field} is not an ISO date") from error


def _timestamp(value: object, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(_text(value, field))
    except ValueError as error:
        raise ValueError(f"{field} is not an ISO timestamp") from error
    if parsed.date() > SETTINGS.evaluation_date:
        raise ValueError(f"{field} cannot be after the configured evaluation date")
    return parsed


def _unique_index[Record](
    records: Iterable[Record], key: Callable[[Record], str], label: str, errors: list[str]
) -> dict[str, Record]:
    indexed: dict[str, Record] = {}
    for record in records:
        identifier = key(record)
        if identifier in indexed:
            errors.append(f"duplicate {label}: {identifier}")
        else:
            indexed[identifier] = record
    return indexed


def _group_records[Record](
    records: Iterable[Record], key: Callable[[Record], str]
) -> dict[str, tuple[Record, ...]]:
    grouped: dict[str, list[Record]] = defaultdict(list)
    for record in records:
        grouped[key(record)].append(record)
    return {
        reference: tuple(sorted(items, key=lambda item: str(item)))
        for reference, items in sorted(grouped.items())
    }


def _money_text(value: Decimal) -> str:
    return format(value.quantize(SETTINGS.monetary_tolerance), "f")


def _split_from_argument(value: str) -> DatasetSplit:
    for split in DatasetSplit:
        if split.value.lower() == value:
            return split
    raise ValueError(f"unknown split: {value}")


def main(arguments: list[str] | None = None) -> int:
    """Print JSON reconciliation output and return a non-zero code for invalid inputs."""

    parser = argparse.ArgumentParser(description="Run deterministic LedgerLens reconciliation.")
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--split", choices=[split.value.lower() for split in DatasetSplit])
    selection.add_argument("--all", action="store_true", help="process all configured operational splits")
    options = parser.parse_args(arguments)
    try:
        runs = reconcile_all() if options.all else (reconcile_split(_split_from_argument(options.split)),)
    except OperationalDataError as error:
        print(json.dumps({"valid": False, "errors": list(error.errors)}, indent=2, sort_keys=True))
        return 1

    payload: dict[str, object]
    if options.all:
        payload = {"runs": [run.to_dict() for run in runs]}
    else:
        payload = runs[0].to_dict()
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
