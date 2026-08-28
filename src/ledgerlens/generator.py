"""Deterministic synthetic operational dataset generation for LedgerLens AI.

The generator writes operational CSV records under ``data/`` and evaluation-only
labels under ``evaluation/``. It never reads ground truth as a runtime input.
"""

from __future__ import annotations

import csv
import hashlib
import json
import random
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Callable, Final, Iterable, Mapping

from ledgerlens.config import (
    SETTINGS,
    CaseSubtype,
    DatasetSplit,
    ExceptionCategory,
    FinalAction,
    HandlingRoute,
)


PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
IST: Final[timezone] = timezone(timedelta(hours=5, minutes=30), name="Asia/Kolkata")
PAYMENT_METHODS: Final[tuple[str, ...]] = ("upi", "card", "netbanking", "wallet")


@dataclass(frozen=True, slots=True)
class PaymentRecord:
    rzp_id: str
    order_id: str
    amount: Decimal
    currency: str
    payment_status: str
    created_at: datetime
    merchant_id: str
    method: str


@dataclass(frozen=True, slots=True)
class BankSettlementRecord:
    settlement_id: str
    rzp_id: str
    settled_amount: Decimal
    settlement_date: date
    batch_id: str
    remarks: str


@dataclass(frozen=True, slots=True)
class MerchantLedgerRecord:
    entry_id: str
    rzp_id: str
    recorded_amount: Decimal
    recorded_at: datetime
    status: str


@dataclass(frozen=True, slots=True)
class AdjustmentRecord:
    adjustment_id: str
    rzp_id: str
    adjustment_type: str
    amount: Decimal
    adjustment_date: date
    reference_id: str


@dataclass(frozen=True, slots=True)
class GroundTruthCase:
    """Evaluation-only label data. It is generated, never used as input."""

    case_id: str
    primary_txn_id: str | None
    operational_reference_id: str
    injected_type: ExceptionCategory
    sub_type: CaseSubtype | None
    expected_action: FinalAction
    expected_route: HandlingRoute
    is_ambiguous: bool


@dataclass(frozen=True, slots=True)
class GeneratedDataset:
    """A complete logical dataset for one reproducible split."""

    split: DatasetSplit
    payments: tuple[PaymentRecord, ...]
    bank_settlements: tuple[BankSettlementRecord, ...]
    merchant_ledger: tuple[MerchantLedgerRecord, ...]
    adjustments: tuple[AdjustmentRecord, ...]
    ground_truth: tuple[GroundTruthCase, ...]

    def content_digest(self) -> str:
        """Return a stable digest of all generated logical content."""

        canonical = json.dumps(_dataset_payload(self), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def allocate_counts[
    Category: (ExceptionCategory, CaseSubtype)
](total_cases: int, weights: Mapping[Category, int]) -> dict[Category, int]:
    """Allocate integer case counts by largest remainder with stable tie-breaking."""

    if type(total_cases) is not int or total_cases <= 0:
        raise ValueError("total_cases must be a positive integer")
    if not weights or any(type(weight) is not int or weight <= 0 for weight in weights.values()):
        raise ValueError("weights must be non-empty positive integers")

    ordered_weights = tuple(weights.items())
    total_weight = sum(weight for _, weight in ordered_weights)
    allocations = {
        category: total_cases * weight // total_weight for category, weight in ordered_weights
    }
    remaining = total_cases - sum(allocations.values())
    ranked_remainders = sorted(
        enumerate(ordered_weights),
        key=lambda item: (-(total_cases * item[1][1] % total_weight), item[0]),
    )
    for index, _ in ranked_remainders[:remaining]:
        allocations[ordered_weights[index][0]] += 1
    return allocations


def category_allocation(total_cases: int) -> dict[ExceptionCategory, int]:
    """Return the configured top-level category allocation for a split size."""

    return allocate_counts(total_cases, SETTINGS.case_distribution_weights)


def fee_subtype_allocation(total_fee_cases: int) -> dict[CaseSubtype, int]:
    """Return the configured standard-versus-ambiguous fee-case allocation."""

    return allocate_counts(total_fee_cases, SETTINGS.fee_subtype_weights)


def calculate_fee(payment_amount: Decimal) -> Decimal:
    """Calculate the configured processing fee in exact INR minor-unit precision."""

    _validate_money(payment_amount, "payment_amount")
    return (payment_amount * SETTINGS.fee_rate).quantize(
        SETTINGS.monetary_tolerance, rounding=ROUND_HALF_UP
    )


def generate_split(split: DatasetSplit) -> GeneratedDataset:
    """Build and validate one in-memory dataset from the configured split seed."""

    if not isinstance(split, DatasetSplit):
        raise ValueError("split must be a DatasetSplit")

    rng = random.Random(SETTINGS.dataset_seeds[split])
    total_cases = SETTINGS.dataset_sizes[split]
    counts = category_allocation(total_cases)
    categories = [
        category for category, count in counts.items() for _ in range(count)
    ]
    rng.shuffle(categories)

    fee_subtypes = [
        subtype
        for subtype, count in fee_subtype_allocation(counts[ExceptionCategory.FEE_DEDUCTION]).items()
        for _ in range(count)
    ]
    rng.shuffle(fee_subtypes)
    fee_subtype_iterator = iter(fee_subtypes)

    payments: list[PaymentRecord] = []
    bank_settlements: list[BankSettlementRecord] = []
    merchant_ledger: list[MerchantLedgerRecord] = []
    adjustments: list[AdjustmentRecord] = []
    ground_truth: list[GroundTruthCase] = []

    for case_number, category in enumerate(categories, start=1):
        subtype = (
            next(fee_subtype_iterator)
            if category is ExceptionCategory.FEE_DEDUCTION
            else None
        )
        case_records = _generate_case(split, case_number, category, subtype, rng)
        payments.extend(case_records.payments)
        bank_settlements.extend(case_records.bank_settlements)
        merchant_ledger.extend(case_records.merchant_ledger)
        adjustments.extend(case_records.adjustments)
        ground_truth.append(case_records.ground_truth)

    dataset = GeneratedDataset(
        split=split,
        payments=tuple(payments),
        bank_settlements=tuple(bank_settlements),
        merchant_ledger=tuple(merchant_ledger),
        adjustments=tuple(adjustments),
        ground_truth=tuple(ground_truth),
    )
    validate_generated_dataset(dataset)
    return dataset


def generate_all(output_root: Path = PROJECT_ROOT) -> dict[DatasetSplit, GeneratedDataset]:
    """Generate, validate, reproducibility-check, and write every configured split."""

    datasets: dict[DatasetSplit, GeneratedDataset] = {}
    for split in DatasetSplit:
        dataset = generate_split(split)
        if dataset.content_digest() != generate_split(split).content_digest():
            raise RuntimeError(f"generation for {split.value} was not reproducible")
        write_dataset(dataset, output_root)
        datasets[split] = dataset
    return datasets


def write_dataset(dataset: GeneratedDataset, output_root: Path = PROJECT_ROOT) -> None:
    """Write operational records and isolated evaluation labels for one split."""

    validate_generated_dataset(dataset)
    split_name = dataset.split.value.lower()
    data_directory = output_root / "data" / split_name
    evaluation_directory = output_root / "evaluation" / split_name
    data_directory.mkdir(parents=True, exist_ok=True)
    evaluation_directory.mkdir(parents=True, exist_ok=True)

    _write_csv(
        data_directory / "payments.csv",
        ("rzp_id", "order_id", "amount", "currency", "payment_status", "created_at", "merchant_id", "method"),
        (_payment_payload(record) for record in dataset.payments),
    )
    _write_csv(
        data_directory / "bank_settlements.csv",
        ("settlement_id", "rzp_id", "settled_amount", "settlement_date", "batch_id", "remarks"),
        (_settlement_payload(record) for record in dataset.bank_settlements),
    )
    _write_csv(
        data_directory / "merchant_ledger.csv",
        ("entry_id", "rzp_id", "recorded_amount", "recorded_at", "status"),
        (_ledger_payload(record) for record in dataset.merchant_ledger),
    )
    _write_csv(
        data_directory / "adjustments.csv",
        ("adjustment_id", "rzp_id", "adjustment_type", "amount", "adjustment_date", "reference_id"),
        (_adjustment_payload(record) for record in dataset.adjustments),
    )
    ground_truth_path = evaluation_directory / "ground_truth.json"
    ground_truth_path.write_text(
        json.dumps(
            [_ground_truth_payload(record) for record in dataset.ground_truth],
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


@dataclass(frozen=True, slots=True)
class _CaseRecords:
    payments: tuple[PaymentRecord, ...]
    bank_settlements: tuple[BankSettlementRecord, ...]
    merchant_ledger: tuple[MerchantLedgerRecord, ...]
    adjustments: tuple[AdjustmentRecord, ...]
    ground_truth: GroundTruthCase


def _generate_case(
    split: DatasetSplit,
    case_number: int,
    category: ExceptionCategory,
    subtype: CaseSubtype | None,
    rng: random.Random,
) -> _CaseRecords:
    """Generate operational evidence and evaluation metadata for one logical case."""

    case_id = f"{split.value}_CASE_{case_number:06d}"
    if category is ExceptionCategory.UNKNOWN_TRANSACTION:
        return _generate_unknown_transaction(split, case_number, case_id, rng)

    rzp_id = f"RZP_{split.value}_{case_number:06d}"
    created_date = _created_date_for_category(category, rng)
    payment = _make_payment(split, case_number, rzp_id, created_date, rng)
    ledger_amount = payment.amount
    settlements: tuple[BankSettlementRecord, ...] = ()
    adjustment_records: tuple[AdjustmentRecord, ...] = ()
    expected_action, expected_route, is_ambiguous = _case_outcome(category, subtype)

    if category is ExceptionCategory.EXACT_MATCH:
        settlements = (_make_settlement(split, case_number, rzp_id, payment.amount, created_date, "A"),)
    elif category is ExceptionCategory.FEE_DEDUCTION:
        if subtype is None:
            raise RuntimeError("fee deduction cases require an approved subtype")
        fee = calculate_fee(payment.amount)
        if subtype is CaseSubtype.REFUND_ADJUSTMENT:
            adjustment = _make_adjustment(split, case_number, rzp_id, payment, fee, rng)
            adjustment_records = (adjustment,)
            settled_amount = payment.amount - fee - adjustment.amount
        else:
            settled_amount = payment.amount - fee
            if subtype is CaseSubtype.LEDGER_MISMATCH:
                ledger_amount = payment.amount - _ledger_difference(payment.amount, rng)
        settlements = (
            _make_settlement(split, case_number, rzp_id, settled_amount, created_date, "A"),
        )
    elif category is ExceptionCategory.DUPLICATE:
        settlements = (
            _make_settlement(split, case_number, rzp_id, payment.amount, created_date, "A"),
            _make_settlement(split, case_number, rzp_id, payment.amount, created_date, "B"),
        )
    elif category in (ExceptionCategory.TIMING_LAG, ExceptionCategory.MISSING_SETTLEMENT):
        settlements = ()
    else:
        raise RuntimeError(f"unsupported generated category: {category}")

    ledger = _make_ledger(split, case_number, rzp_id, ledger_amount, payment.created_at)
    ground_truth = GroundTruthCase(
        case_id=case_id,
        primary_txn_id=rzp_id,
        operational_reference_id=rzp_id,
        injected_type=category,
        sub_type=subtype,
        expected_action=expected_action,
        expected_route=expected_route,
        is_ambiguous=is_ambiguous,
    )
    return _CaseRecords(
        payments=(payment,),
        bank_settlements=settlements,
        merchant_ledger=(ledger,),
        adjustments=adjustment_records,
        ground_truth=ground_truth,
    )


def _generate_unknown_transaction(
    split: DatasetSplit, case_number: int, case_id: str, rng: random.Random
) -> _CaseRecords:
    """Generate a valid bank-only record with a stable phantom reference."""

    phantom_reference = f"UNK_{split.value}_{case_number:06d}"
    amount = _random_inr_amount(rng)
    settlement_date = SETTINGS.evaluation_date - timedelta(days=rng.randint(1, 20))
    bank_record = BankSettlementRecord(
        settlement_id=f"STL_{split.value}_{case_number:06d}_A",
        rzp_id=phantom_reference,
        settled_amount=amount,
        settlement_date=settlement_date,
        batch_id=f"BATCH_{split.value}_{settlement_date:%Y%m%d}",
        remarks="Bank settlement received without a payment reference match",
    )
    ground_truth = GroundTruthCase(
        case_id=case_id,
        primary_txn_id=None,
        operational_reference_id=phantom_reference,
        injected_type=ExceptionCategory.UNKNOWN_TRANSACTION,
        sub_type=None,
        expected_action=FinalAction.ESCALATE,
        expected_route=HandlingRoute.DETERMINISTIC,
        is_ambiguous=False,
    )
    return _CaseRecords((), (bank_record,), (), (), ground_truth)


def _case_outcome(
    category: ExceptionCategory, subtype: CaseSubtype | None
) -> tuple[FinalAction, HandlingRoute, bool]:
    """Define labels for generated cases without introducing additional categories."""

    if category is ExceptionCategory.EXACT_MATCH:
        return FinalAction.AUTO_RESOLVE, HandlingRoute.DETERMINISTIC, False
    if category is ExceptionCategory.FEE_DEDUCTION:
        if subtype is CaseSubtype.STANDARD_FEE:
            return FinalAction.AUTO_RESOLVE, HandlingRoute.DETERMINISTIC, False
        if subtype is CaseSubtype.REFUND_ADJUSTMENT:
            return FinalAction.AUTO_RESOLVE, HandlingRoute.AI_INVESTIGATOR, True
        if subtype is CaseSubtype.LEDGER_MISMATCH:
            return FinalAction.ESCALATE, HandlingRoute.AI_INVESTIGATOR, True
        raise ValueError("fee deduction must use an approved subtype")
    if category is ExceptionCategory.TIMING_LAG:
        return FinalAction.MONITOR, HandlingRoute.DETERMINISTIC, False
    if category in (
        ExceptionCategory.DUPLICATE,
        ExceptionCategory.MISSING_SETTLEMENT,
        ExceptionCategory.UNKNOWN_TRANSACTION,
    ):
        return FinalAction.ESCALATE, HandlingRoute.DETERMINISTIC, False
    raise ValueError(f"unsupported category: {category}")


def _created_date_for_category(category: ExceptionCategory, rng: random.Random) -> date:
    """Produce dates whose relationship to the evaluation date proves time cases."""

    window = SETTINGS.settlement_window_days
    if category is ExceptionCategory.TIMING_LAG:
        return SETTINGS.evaluation_date - timedelta(days=rng.randint(1, window))
    if category is ExceptionCategory.MISSING_SETTLEMENT:
        return SETTINGS.evaluation_date - timedelta(days=window + rng.randint(1, 30))
    return SETTINGS.evaluation_date - timedelta(days=window + 10 + rng.randint(1, 60))


def _make_payment(
    split: DatasetSplit,
    case_number: int,
    rzp_id: str,
    created_date: date,
    rng: random.Random,
) -> PaymentRecord:
    """Create one captured, valid payment record."""

    created_at = datetime.combine(
        created_date,
        time(hour=9 + case_number % 8, minute=(case_number * 7) % 60),
        tzinfo=IST,
    )
    return PaymentRecord(
        rzp_id=rzp_id,
        order_id=f"ORDER_{split.value}_{case_number:06d}",
        amount=_random_inr_amount(rng),
        currency=SETTINGS.currency.value,
        payment_status="captured",
        created_at=created_at,
        merchant_id=f"MERCHANT_{1 + rng.randrange(25):03d}",
        method=rng.choice(PAYMENT_METHODS),
    )


def _make_settlement(
    split: DatasetSplit,
    case_number: int,
    rzp_id: str,
    settled_amount: Decimal,
    created_date: date,
    suffix: str,
) -> BankSettlementRecord:
    """Create a valid bank-settlement row for an existing payment."""

    _validate_money(settled_amount, "settled_amount")
    settlement_date = created_date + timedelta(days=1 if suffix == "A" else 2)
    return BankSettlementRecord(
        settlement_id=f"STL_{split.value}_{case_number:06d}_{suffix}",
        rzp_id=rzp_id,
        settled_amount=settled_amount,
        settlement_date=settlement_date,
        batch_id=f"BATCH_{split.value}_{settlement_date:%Y%m%d}",
        remarks="Captured payment settlement",
    )


def _make_ledger(
    split: DatasetSplit,
    case_number: int,
    rzp_id: str,
    recorded_amount: Decimal,
    created_at: datetime,
) -> MerchantLedgerRecord:
    """Create a merchant-ledger row linked to a payment."""

    _validate_money(recorded_amount, "recorded_amount")
    return MerchantLedgerRecord(
        entry_id=f"LEDGER_{split.value}_{case_number:06d}",
        rzp_id=rzp_id,
        recorded_amount=recorded_amount,
        recorded_at=created_at + timedelta(minutes=5),
        status="posted",
    )


def _make_adjustment(
    split: DatasetSplit,
    case_number: int,
    rzp_id: str,
    payment: PaymentRecord,
    fee: Decimal,
    rng: random.Random,
) -> AdjustmentRecord:
    """Create an operational refund adjustment that closes settlement arithmetic."""

    maximum_adjustment = min(Decimal("500.00"), payment.amount - fee - Decimal("1.00"))
    maximum_minor_units = int(maximum_adjustment * 100)
    if maximum_minor_units < 100:
        raise RuntimeError("payment amount is too small for a refund adjustment")
    amount = Decimal(rng.randint(100, maximum_minor_units)) / Decimal(100)
    return AdjustmentRecord(
        adjustment_id=f"ADJ_{split.value}_{case_number:06d}",
        rzp_id=rzp_id,
        adjustment_type="refund",
        amount=amount,
        adjustment_date=payment.created_at.date() + timedelta(days=1),
        reference_id=f"REFUND_{split.value}_{case_number:06d}",
    )


def _ledger_difference(payment_amount: Decimal, rng: random.Random) -> Decimal:
    """Return a non-zero amount that keeps a ledger mismatch financially valid."""

    maximum_minor_units = min(10_000, int((payment_amount - Decimal("1.00")) * 100))
    return Decimal(rng.randint(1, maximum_minor_units)) / Decimal(100)


def _random_inr_amount(rng: random.Random) -> Decimal:
    """Generate a two-decimal INR amount from integer minor units only."""

    return Decimal(rng.randint(100_000, 10_000_000)) / Decimal(100)


def validate_generated_dataset(dataset: GeneratedDataset) -> None:
    """Perform generator-level integrity checks and fail loudly on any violation."""

    expected_cases = SETTINGS.dataset_sizes[dataset.split]
    if len(dataset.ground_truth) != expected_cases:
        raise ValueError(f"{dataset.split.value} has an incorrect logical case count")

    expected_distribution = category_allocation(expected_cases)
    actual_distribution = Counter(case.injected_type for case in dataset.ground_truth)
    if actual_distribution != expected_distribution:
        raise ValueError("generated category distribution does not match configuration")

    expected_subtypes = fee_subtype_allocation(
        expected_distribution[ExceptionCategory.FEE_DEDUCTION]
    )
    actual_subtypes = Counter(
        case.sub_type
        for case in dataset.ground_truth
        if case.injected_type is ExceptionCategory.FEE_DEDUCTION
    )
    if actual_subtypes != expected_subtypes:
        raise ValueError("generated fee subtype distribution does not match configuration")

    _require_unique((case.case_id for case in dataset.ground_truth), "case IDs")
    _require_unique(
        (case.operational_reference_id for case in dataset.ground_truth),
        "operational reference IDs",
    )
    _require_unique((record.rzp_id for record in dataset.payments), "payment references")
    _require_unique((record.entry_id for record in dataset.merchant_ledger), "ledger entry IDs")
    _require_unique((record.settlement_id for record in dataset.bank_settlements), "settlement IDs")
    _require_unique((record.adjustment_id for record in dataset.adjustments), "adjustment IDs")

    payments_by_id = {record.rzp_id: record for record in dataset.payments}
    ledgers_by_id = _group_by(dataset.merchant_ledger, lambda record: record.rzp_id)
    settlements_by_id = _group_by(dataset.bank_settlements, lambda record: record.rzp_id)
    adjustments_by_id = _group_by(dataset.adjustments, lambda record: record.rzp_id)

    for record in dataset.payments:
        _validate_money(record.amount, "payment amount")
        if record.currency != SETTINGS.currency.value or record.payment_status != "captured":
            raise ValueError("payment contains invalid configured operational values")
    for record in dataset.bank_settlements:
        _validate_money(record.settled_amount, "settled amount")
    for record in dataset.merchant_ledger:
        _validate_money(record.recorded_amount, "ledger amount")
        if record.rzp_id not in payments_by_id:
            raise ValueError("ledger record has no related payment")
    for record in dataset.adjustments:
        _validate_money(record.amount, "adjustment amount")
        if record.rzp_id not in payments_by_id:
            raise ValueError("adjustment has no related payment")

    for case in dataset.ground_truth:
        if not case.operational_reference_id:
            raise ValueError("ground-truth case has no operational reference ID")
        _validate_case_evidence(
            case,
            payments_by_id,
            ledgers_by_id,
            settlements_by_id,
            adjustments_by_id,
        )

    known_references = set(payments_by_id) | {
        case.operational_reference_id
        for case in dataset.ground_truth
        if case.injected_type is ExceptionCategory.UNKNOWN_TRANSACTION
    }
    if any(record.rzp_id not in known_references for record in dataset.bank_settlements):
        raise ValueError("bank settlement has an accidental cross-case reference")


def _validate_case_evidence(
    case: GroundTruthCase,
    payments_by_id: Mapping[str, PaymentRecord],
    ledgers_by_id: Mapping[str, list[MerchantLedgerRecord]],
    settlements_by_id: Mapping[str, list[BankSettlementRecord]],
    adjustments_by_id: Mapping[str, list[AdjustmentRecord]],
) -> None:
    """Check that every injected outcome is directly observable in source records."""

    reference = case.operational_reference_id
    settlements = settlements_by_id.get(reference, [])
    if case.injected_type is ExceptionCategory.UNKNOWN_TRANSACTION:
        if case.primary_txn_id is not None or reference in payments_by_id or not settlements:
            raise ValueError("unknown transaction lacks the required bank-only evidence")
        return

    payment = payments_by_id.get(reference)
    ledgers = ledgers_by_id.get(reference, [])
    adjustments = adjustments_by_id.get(reference, [])
    if case.primary_txn_id != reference or payment is None or len(ledgers) != 1:
        raise ValueError("normal case has incomplete payment or ledger evidence")
    ledger = ledgers[0]

    if case.injected_type is ExceptionCategory.EXACT_MATCH:
        if len(settlements) != 1 or adjustments or ledger.recorded_amount != payment.amount:
            raise ValueError("exact match evidence is inconsistent")
        if settlements[0].settled_amount != payment.amount:
            raise ValueError("exact match settlement does not agree with payment")
        return

    if case.injected_type is ExceptionCategory.TIMING_LAG:
        age = SETTINGS.evaluation_date - payment.created_at.date()
        if settlements or not (timedelta(0) < age <= timedelta(days=SETTINGS.settlement_window_days)):
            raise ValueError("timing lag does not satisfy the configured settlement window")
        return

    if case.injected_type is ExceptionCategory.MISSING_SETTLEMENT:
        age = SETTINGS.evaluation_date - payment.created_at.date()
        if settlements or age <= timedelta(days=SETTINGS.settlement_window_days):
            raise ValueError("missing settlement has not exceeded the configured window")
        return

    if case.injected_type is ExceptionCategory.DUPLICATE:
        if len(settlements) != 2 or any(item.settled_amount != payment.amount for item in settlements):
            raise ValueError("duplicate settlement evidence is not observable")
        return

    if case.injected_type is not ExceptionCategory.FEE_DEDUCTION or case.sub_type is None:
        raise ValueError("generated case has an unsupported classification/subtype combination")

    if len(settlements) != 1:
        raise ValueError("fee deduction must have exactly one settlement")
    fee = calculate_fee(payment.amount)
    settlement = settlements[0]
    adjustment_total = sum((record.amount for record in adjustments), Decimal("0"))
    if settlement.settled_amount != payment.amount - fee - adjustment_total:
        raise ValueError("fee deduction arithmetic does not close")

    if case.sub_type is CaseSubtype.STANDARD_FEE:
        if case.is_ambiguous or case.expected_route is not HandlingRoute.DETERMINISTIC:
            raise ValueError("standard fee case has an invalid route")
        if adjustments or ledger.recorded_amount != payment.amount:
            raise ValueError("standard fee case has unexplained operational evidence")
    elif case.sub_type is CaseSubtype.REFUND_ADJUSTMENT:
        if not case.is_ambiguous or case.expected_route is not HandlingRoute.AI_INVESTIGATOR:
            raise ValueError("refund adjustment case has an invalid route")
        if len(adjustments) != 1 or ledger.recorded_amount != payment.amount:
            raise ValueError("refund adjustment lacks direct operational evidence")
    elif case.sub_type is CaseSubtype.LEDGER_MISMATCH:
        if not case.is_ambiguous or case.expected_route is not HandlingRoute.AI_INVESTIGATOR:
            raise ValueError("ledger mismatch case has an invalid route")
        if adjustments or ledger.recorded_amount == payment.amount:
            raise ValueError("ledger mismatch lacks direct operational evidence")
    else:
        raise ValueError("fee deduction has an unapproved subtype")


def _validate_money(value: Decimal, name: str) -> None:
    """Require finite, non-negative, configured-minor-unit Decimal amounts."""

    if type(value) is not Decimal or not value.is_finite() or value < Decimal("0"):
        raise ValueError(f"{name} must be a non-negative finite Decimal")
    if value != value.quantize(SETTINGS.monetary_tolerance):
        raise ValueError(f"{name} exceeds configured monetary precision")


def _group_by[Record, Key](
    records: Iterable[Record], key: Callable[[Record], Key]
) -> dict[Key, list[Record]]:
    """Create a linear-time index while preserving source-record grouping."""

    grouped: dict[Key, list[Record]] = defaultdict(list)
    for record in records:
        grouped[key(record)].append(record)
    return dict(grouped)


def _require_unique(values: Iterable[str], label: str) -> None:
    """Fail if any generated source identifier is duplicated."""

    values_tuple = tuple(values)
    if len(values_tuple) != len(set(values_tuple)):
        raise ValueError(f"duplicate {label} detected")


def _write_csv(path: Path, fieldnames: tuple[str, ...], rows: Iterable[dict[str, str]]) -> None:
    """Write a deterministic UTF-8 operational CSV file."""

    with path.open("w", newline="", encoding="utf-8") as file_handle:
        writer = csv.DictWriter(file_handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _dataset_payload(dataset: GeneratedDataset) -> dict[str, object]:
    """Serialize in-memory records into a stable JSON-compatible representation."""

    return {
        "split": dataset.split.value,
        "payments": [_payment_payload(record) for record in dataset.payments],
        "bank_settlements": [_settlement_payload(record) for record in dataset.bank_settlements],
        "merchant_ledger": [_ledger_payload(record) for record in dataset.merchant_ledger],
        "adjustments": [_adjustment_payload(record) for record in dataset.adjustments],
        "ground_truth": [_ground_truth_payload(record) for record in dataset.ground_truth],
    }


def _payment_payload(record: PaymentRecord) -> dict[str, str]:
    return {
        "rzp_id": record.rzp_id,
        "order_id": record.order_id,
        "amount": _money_text(record.amount),
        "currency": record.currency,
        "payment_status": record.payment_status,
        "created_at": record.created_at.isoformat(),
        "merchant_id": record.merchant_id,
        "method": record.method,
    }


def _settlement_payload(record: BankSettlementRecord) -> dict[str, str]:
    return {
        "settlement_id": record.settlement_id,
        "rzp_id": record.rzp_id,
        "settled_amount": _money_text(record.settled_amount),
        "settlement_date": record.settlement_date.isoformat(),
        "batch_id": record.batch_id,
        "remarks": record.remarks,
    }


def _ledger_payload(record: MerchantLedgerRecord) -> dict[str, str]:
    return {
        "entry_id": record.entry_id,
        "rzp_id": record.rzp_id,
        "recorded_amount": _money_text(record.recorded_amount),
        "recorded_at": record.recorded_at.isoformat(),
        "status": record.status,
    }


def _adjustment_payload(record: AdjustmentRecord) -> dict[str, str]:
    return {
        "adjustment_id": record.adjustment_id,
        "rzp_id": record.rzp_id,
        "adjustment_type": record.adjustment_type,
        "amount": _money_text(record.amount),
        "adjustment_date": record.adjustment_date.isoformat(),
        "reference_id": record.reference_id,
    }


def _ground_truth_payload(record: GroundTruthCase) -> dict[str, object]:
    return {
        "case_id": record.case_id,
        "primary_txn_id": record.primary_txn_id,
        "operational_reference_id": record.operational_reference_id,
        "injected_type": record.injected_type.value,
        "sub_type": record.sub_type.value if record.sub_type is not None else None,
        "expected_action": record.expected_action.value,
        "expected_route": record.expected_route.value,
        "is_ambiguous": record.is_ambiguous,
    }


def _money_text(value: Decimal) -> str:
    """Serialize exact monetary values at configured INR minor-unit precision."""

    _validate_money(value, "monetary value")
    return format(value.quantize(SETTINGS.monetary_tolerance), "f")


if __name__ == "__main__":
    generated = generate_all()
    for split, dataset in generated.items():
        print(
            f"{split.value}: {len(dataset.ground_truth)} cases, "
            f"{len(dataset.payments)} payments, {len(dataset.bank_settlements)} settlements, "
            f"{len(dataset.merchant_ledger)} ledger rows, {len(dataset.adjustments)} adjustments"
        )
