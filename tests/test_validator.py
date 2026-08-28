"""Independent corruption tests for the read-only dataset validator."""

from __future__ import annotations

import csv
import hashlib
import inspect
import json
import shutil
from pathlib import Path

import ledgerlens.validator as validator_module
import pytest

from ledgerlens.config import DatasetSplit
from ledgerlens.validator import validate_all, validate_split


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def dev_fixture(tmp_path: Path) -> Path:
    """Copy DEV inputs so every corruption test leaves approved data untouched."""

    shutil.copytree(PROJECT_ROOT / "data" / "dev", tmp_path / "data" / "dev")
    shutil.copytree(PROJECT_ROOT / "evaluation" / "dev", tmp_path / "evaluation" / "dev")
    return tmp_path


def _ground_truth(root: Path) -> list[dict[str, object]]:
    return json.loads((root / "evaluation" / "dev" / "ground_truth.json").read_text(encoding="utf-8"))


def _write_ground_truth(root: Path, rows: list[dict[str, object]]) -> None:
    (root / "evaluation" / "dev" / "ground_truth.json").write_text(
        json.dumps(rows, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _csv_rows(root: Path, filename: str) -> tuple[list[dict[str, str]], list[str]]:
    path = root / "data" / "dev" / filename
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return list(reader), list(reader.fieldnames or [])


def _write_csv(root: Path, filename: str, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    path = root / "data" / "dev" / filename
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _case(
    rows: list[dict[str, object]], *, category: str | None = None, subtype: str | None = None
) -> dict[str, object]:
    return next(
        row
        for row in rows
        if (category is None or row["injected_type"] == category)
        and (subtype is None or row["sub_type"] == subtype)
    )


def _replace_csv_value(
    root: Path, filename: str, reference: str, field: str, value: str
) -> None:
    rows, fieldnames = _csv_rows(root, filename)
    matching = [row for row in rows if row.get("rzp_id") == reference]
    assert matching
    matching[0][field] = value
    _write_csv(root, filename, rows, fieldnames)


def _file_hashes(root: Path) -> dict[str, str]:
    files = sorted((root / "data").rglob("*")) + sorted((root / "evaluation").rglob("*"))
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in files
        if path.is_file()
    }


@pytest.mark.parametrize(
    ("split", "case_count"),
    [
        (DatasetSplit.DEV, 100),
        (DatasetSplit.VALIDATION, 500),
        (DatasetSplit.HOLDOUT, 1000),
    ],
)
def test_real_generated_splits_pass_independent_validation(
    split: DatasetSplit, case_count: int
) -> None:
    report = validate_split(split)
    assert report.valid is True
    assert report.case_count == case_count
    assert not report.errors
    assert all(check.status == "PASS" for check in report.checks)


def test_unknown_transaction_with_null_primary_id_is_accepted() -> None:
    report = validate_split(DatasetSplit.DEV)
    assert report.valid
    assert report.category_distribution["UNKNOWN_TRANSACTION"] == 5


def test_missing_required_file_fails(dev_fixture: Path) -> None:
    (dev_fixture / "data" / "dev" / "payments.csv").unlink()
    report = validate_split(DatasetSplit.DEV, dev_fixture)
    assert not report.valid
    assert any("required file is missing" in error for error in report.errors)


def test_missing_required_csv_column_fails(dev_fixture: Path) -> None:
    rows, fields = _csv_rows(dev_fixture, "payments.csv")
    for row in rows:
        row.pop("amount")
    _write_csv(dev_fixture, "payments.csv", rows, [field for field in fields if field != "amount"])
    report = validate_split(DatasetSplit.DEV, dev_fixture)
    assert not report.valid
    assert any("missing required columns" in error for error in report.errors)


def test_duplicate_case_id_fails(dev_fixture: Path) -> None:
    rows = _ground_truth(dev_fixture)
    rows[1]["case_id"] = rows[0]["case_id"]
    _write_ground_truth(dev_fixture, rows)
    report = validate_split(DatasetSplit.DEV, dev_fixture)
    assert not report.valid
    assert any("duplicate ground-truth case_id" in error for error in report.errors)


def test_duplicate_operational_reference_id_fails(dev_fixture: Path) -> None:
    rows = _ground_truth(dev_fixture)
    rows[1]["operational_reference_id"] = rows[0]["operational_reference_id"]
    _write_ground_truth(dev_fixture, rows)
    report = validate_split(DatasetSplit.DEV, dev_fixture)
    assert not report.valid
    assert any("duplicate operational_reference_id" in error for error in report.errors)


def test_missing_operational_reference_id_fails(dev_fixture: Path) -> None:
    rows = _ground_truth(dev_fixture)
    rows[0]["operational_reference_id"] = ""
    _write_ground_truth(dev_fixture, rows)
    report = validate_split(DatasetSplit.DEV, dev_fixture)
    assert not report.valid
    assert any("operational_reference_id must be a non-empty string" in error for error in report.errors)


def test_unknown_transaction_without_operational_reference_fails(dev_fixture: Path) -> None:
    rows = _ground_truth(dev_fixture)
    _case(rows, category="UNKNOWN_TRANSACTION")["operational_reference_id"] = ""
    _write_ground_truth(dev_fixture, rows)
    report = validate_split(DatasetSplit.DEV, dev_fixture)
    assert not report.valid
    assert any("operational_reference_id" in error for error in report.errors)


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("injected_type", "UNAPPROVED_CATEGORY"),
        ("expected_action", "UNAPPROVED_ACTION"),
        ("expected_route", "UNAPPROVED_ROUTE"),
    ],
)
def test_invalid_ground_truth_enum_values_fail(
    dev_fixture: Path, field: str, invalid_value: str
) -> None:
    rows = _ground_truth(dev_fixture)
    rows[0][field] = invalid_value
    _write_ground_truth(dev_fixture, rows)
    report = validate_split(DatasetSplit.DEV, dev_fixture)
    assert not report.valid
    assert any("not an approved" in error for error in report.errors)


def test_invalid_monetary_value_fails(dev_fixture: Path) -> None:
    rows, fields = _csv_rows(dev_fixture, "payments.csv")
    rows[0]["amount"] = "NaN"
    _write_csv(dev_fixture, "payments.csv", rows, fields)
    report = validate_split(DatasetSplit.DEV, dev_fixture)
    assert not report.valid
    assert any("exact monetary representation" in error for error in report.errors)


def test_incorrect_exact_match_arithmetic_fails(dev_fixture: Path) -> None:
    case = _case(_ground_truth(dev_fixture), category="EXACT_MATCH")
    _replace_csv_value(
        dev_fixture, "bank_settlements.csv", str(case["operational_reference_id"]), "settled_amount", "1.00"
    )
    report = validate_split(DatasetSplit.DEV, dev_fixture)
    assert not report.valid
    assert any("exact-match invariant" in error for error in report.errors)


def test_incorrect_standard_fee_arithmetic_fails(dev_fixture: Path) -> None:
    case = _case(_ground_truth(dev_fixture), subtype="STANDARD_FEE")
    _replace_csv_value(
        dev_fixture, "bank_settlements.csv", str(case["operational_reference_id"]), "settled_amount", "1.00"
    )
    report = validate_split(DatasetSplit.DEV, dev_fixture)
    assert not report.valid
    assert any("fee deduction invariant" in error for error in report.errors)


def test_incorrect_refund_adjustment_arithmetic_fails(dev_fixture: Path) -> None:
    case = _case(_ground_truth(dev_fixture), subtype="REFUND_ADJUSTMENT")
    _replace_csv_value(
        dev_fixture, "adjustments.csv", str(case["operational_reference_id"]), "amount", "1.00"
    )
    report = validate_split(DatasetSplit.DEV, dev_fixture)
    assert not report.valid
    assert any("fee deduction invariant" in error for error in report.errors)


def test_missing_operational_ledger_mismatch_fails(dev_fixture: Path) -> None:
    case = _case(_ground_truth(dev_fixture), subtype="LEDGER_MISMATCH")
    reference = str(case["operational_reference_id"])
    payment_rows, _ = _csv_rows(dev_fixture, "payments.csv")
    payment_amount = next(row["amount"] for row in payment_rows if row["rzp_id"] == reference)
    _replace_csv_value(dev_fixture, "merchant_ledger.csv", reference, "recorded_amount", payment_amount)
    report = validate_split(DatasetSplit.DEV, dev_fixture)
    assert not report.valid
    assert any("ledger-mismatch invariant" in error for error in report.errors)


def test_incorrect_timing_window_fails(dev_fixture: Path) -> None:
    case = _case(_ground_truth(dev_fixture), category="TIMING_LAG")
    _replace_csv_value(
        dev_fixture,
        "payments.csv",
        str(case["operational_reference_id"]),
        "created_at",
        "2025-01-01T10:00:00+05:30",
    )
    report = validate_split(DatasetSplit.DEV, dev_fixture)
    assert not report.valid
    assert any("timing-lag invariant" in error for error in report.errors)


def test_incorrect_missing_settlement_window_fails(dev_fixture: Path) -> None:
    case = _case(_ground_truth(dev_fixture), category="MISSING_SETTLEMENT")
    _replace_csv_value(
        dev_fixture,
        "payments.csv",
        str(case["operational_reference_id"]),
        "created_at",
        "2025-01-30T10:00:00+05:30",
    )
    report = validate_split(DatasetSplit.DEV, dev_fixture)
    assert not report.valid
    assert any("missing-settlement invariant" in error for error in report.errors)


def test_invalid_duplicate_structure_fails(dev_fixture: Path) -> None:
    case = _case(_ground_truth(dev_fixture), category="DUPLICATE")
    reference = str(case["operational_reference_id"])
    rows, fields = _csv_rows(dev_fixture, "bank_settlements.csv")
    removed = False
    retained: list[dict[str, str]] = []
    for row in rows:
        if row["rzp_id"] == reference and not removed:
            removed = True
            continue
        retained.append(row)
    _write_csv(dev_fixture, "bank_settlements.csv", retained, fields)
    report = validate_split(DatasetSplit.DEV, dev_fixture)
    assert not report.valid
    assert any("duplicate invariant" in error for error in report.errors)


def test_invalid_unknown_transaction_structure_fails(dev_fixture: Path) -> None:
    case = _case(_ground_truth(dev_fixture), category="UNKNOWN_TRANSACTION")
    reference = str(case["operational_reference_id"])
    rows, fields = _csv_rows(dev_fixture, "bank_settlements.csv")
    for row in rows:
        if row["rzp_id"] == reference:
            row["rzp_id"] = "RZP_DEV_000001"
    _write_csv(dev_fixture, "bank_settlements.csv", rows, fields)
    report = validate_split(DatasetSplit.DEV, dev_fixture)
    assert not report.valid
    assert any("unknown transaction" in error for error in report.errors)


def test_ground_truth_under_data_is_a_safety_failure(dev_fixture: Path) -> None:
    (dev_fixture / "data" / "dev" / "ground_truth.json").write_text("[]\n", encoding="utf-8")
    report = validate_split(DatasetSplit.DEV, dev_fixture)
    assert not report.valid
    assert any("incorrectly stored under data" in error for error in report.errors)


def test_repeated_validation_is_identical_and_real_inputs_are_not_modified() -> None:
    before = _file_hashes(PROJECT_ROOT)
    first = validate_all()
    second = validate_all()
    after = _file_hashes(PROJECT_ROOT)
    assert [report.to_dict() for report in first] == [report.to_dict() for report in second]
    assert before == after


def test_validator_is_independent_of_generator_implementation() -> None:
    source = inspect.getsource(validator_module)
    assert "ledgerlens.generator" not in source
    assert "generate_split" not in source
