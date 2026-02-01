#!/usr/bin/env python3
"""
Openbot Self-Test Module

Runs basic sanity checks to verify receipt validation and core functionality.

Usage:
    python -m openbot.selftest
"""

import json
import sys
import tempfile
from pathlib import Path

from openbot.receipts import Receipt, ReceiptWriter, validate_receipt
from openbot.policy import PolicyLoader
from openbot.utils import generate_run_id, get_timestamp


def test_receipt_creation():
    """Test that receipts can be created correctly."""
    print("TEST: Receipt creation... ", end="")

    receipt = Receipt()
    receipt.set_target(
        repo="https://github.com/test/repo",
        branch="main",
        commit_sha="a" * 40
    )
    receipt.set_test_result(
        command="echo test",
        exit_code=0,
        log_path="/tmp/test.log"
    )

    data = receipt.finalize()

    assert data["receipt_version"] == "v1"
    assert data["target_repo"] == "https://github.com/test/repo"
    assert data["target_branch"] == "main"
    assert data["commit_sha"] == "a" * 40
    assert data["test"]["command"] == "echo test"
    assert data["test"]["exit_code"] == 0
    assert data["test"]["summary"] == "passed"
    assert data["overall_status"] == "SUCCESS"
    assert data["errors"] == []

    print("PASSED")
    return True


def test_receipt_with_errors():
    """Test that receipts with errors are marked as FAILED."""
    print("TEST: Receipt with errors... ", end="")

    receipt = Receipt()
    receipt.set_target(
        repo="https://github.com/test/repo",
        branch="main",
        commit_sha="b" * 40
    )
    receipt.set_test_result(
        command="exit 1",
        exit_code=1,
        log_path="/tmp/test.log"
    )
    receipt.add_error("Test failed with exit code 1")

    data = receipt.finalize()

    assert data["test"]["summary"] == "failed"
    assert data["overall_status"] == "FAILED"
    assert len(data["errors"]) == 1

    print("PASSED")
    return True


def test_schema_loading():
    """Test that the receipt schema can be loaded."""
    print("TEST: Schema loading... ", end="")

    loader = PolicyLoader()
    success = loader.load_all()

    if not success:
        errors = loader.get_load_errors()
        print(f"FAILED: {errors}")
        return False

    schema = loader.get_receipt_schema()
    if schema is None:
        print("FAILED: Schema not loaded")
        return False

    assert schema.get("$schema") is not None
    assert schema.get("properties") is not None
    assert "receipt_version" in schema.get("properties", {})

    print("PASSED")
    return True


def test_receipt_validation_valid():
    """Test that valid receipts pass validation."""
    print("TEST: Valid receipt validation... ", end="")

    loader = PolicyLoader()
    loader.load_all()
    schema = loader.get_receipt_schema()

    receipt = Receipt()
    receipt.set_target(
        repo="https://github.com/test/repo",
        branch="main",
        commit_sha="c" * 40
    )
    receipt.set_test_result(
        command="echo test",
        exit_code=0,
        log_path="/tmp/test.log"
    )
    data = receipt.finalize()

    errors = validate_receipt(data, schema)

    if errors:
        print(f"FAILED: Unexpected validation errors: {errors}")
        return False

    print("PASSED")
    return True


def test_receipt_validation_invalid():
    """Test that invalid receipts fail validation."""
    print("TEST: Invalid receipt validation... ", end="")

    loader = PolicyLoader()
    loader.load_all()
    schema = loader.get_receipt_schema()

    # Create an invalid receipt (missing required fields)
    invalid_receipt = {
        "receipt_version": "v1",
        "timestamp": get_timestamp(),
        # Missing run_id, target_repo, etc.
    }

    errors = validate_receipt(invalid_receipt, schema)

    if not errors:
        print("FAILED: Expected validation errors but got none")
        return False

    # Should have errors for missing fields
    assert any("Missing required field" in e for e in errors)

    print("PASSED")
    return True


def test_receipt_writer():
    """Test that receipts can be written to disk."""
    print("TEST: Receipt writer... ", end="")

    with tempfile.TemporaryDirectory() as tmpdir:
        receipts_dir = Path(tmpdir) / "receipts"

        loader = PolicyLoader()
        loader.load_all()
        schema = loader.get_receipt_schema()

        writer = ReceiptWriter(receipts_dir, schema)

        receipt = Receipt()
        receipt.set_target(
            repo="https://github.com/test/repo",
            branch="main",
            commit_sha="d" * 40
        )
        receipt.set_test_result(
            command="echo test",
            exit_code=0,
            log_path="/tmp/test.log"
        )
        data = receipt.finalize()

        success, path = writer.write(data)

        if not success:
            print(f"FAILED: Write failed: {path}")
            return False

        # Verify file exists
        if not Path(path).exists():
            print(f"FAILED: File not created at {path}")
            return False

        # Verify content
        with open(path) as f:
            written_data = json.load(f)

        if written_data["run_id"] != data["run_id"]:
            print("FAILED: Written data doesn't match")
            return False

    print("PASSED")
    return True


def test_quarantine_invalid_receipt():
    """Test that invalid receipts are quarantined."""
    print("TEST: Quarantine invalid receipt... ", end="")

    with tempfile.TemporaryDirectory() as tmpdir:
        receipts_dir = Path(tmpdir) / "receipts"

        loader = PolicyLoader()
        loader.load_all()
        schema = loader.get_receipt_schema()

        writer = ReceiptWriter(receipts_dir, schema)

        # Create invalid receipt
        invalid_receipt = {
            "receipt_version": "v1",
            "timestamp": get_timestamp(),
            "run_id": generate_run_id(),
            # Missing required fields
        }

        success, path = writer.write(invalid_receipt)

        if success:
            print("FAILED: Expected write to fail for invalid receipt")
            return False

        # Should be quarantined
        if "quarantine" not in path:
            print(f"FAILED: Expected quarantine path, got: {path}")
            return False

        if not Path(path).exists():
            print(f"FAILED: Quarantine file not created at {path}")
            return False

    print("PASSED")
    return True


def test_policy_loading():
    """Test that all policy files can be loaded."""
    print("TEST: Policy loading... ", end="")

    loader = PolicyLoader()
    success = loader.load_all()

    if not success:
        print(f"FAILED: {loader.get_load_errors()}")
        return False

    loaded = loader.get_loaded_policy_names()
    expected = ["protected_paths", "escalation_rules", "receipt_schema"]

    for name in expected:
        if name not in loaded:
            print(f"FAILED: Missing policy: {name}")
            return False

    print("PASSED")
    return True


def test_protected_paths():
    """Test that protected paths can be read."""
    print("TEST: Protected paths... ", end="")

    loader = PolicyLoader()
    loader.load_all()

    globs = loader.get_protected_globs()

    if not globs:
        print("FAILED: No protected globs found")
        return False

    # Should include key protected paths
    if "runtime/**" not in globs:
        print("FAILED: runtime/** not in protected globs")
        return False

    print("PASSED")
    return True


def run_all_tests() -> bool:
    """Run all self-tests."""
    print("=" * 50)
    print("Openbot Self-Test Suite")
    print("=" * 50)
    print()

    tests = [
        test_receipt_creation,
        test_receipt_with_errors,
        test_schema_loading,
        test_receipt_validation_valid,
        test_receipt_validation_invalid,
        test_receipt_writer,
        test_quarantine_invalid_receipt,
        test_policy_loading,
        test_protected_paths,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            if test():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"FAILED: Exception: {e}")
            failed += 1

    print()
    print("=" * 50)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 50)

    return failed == 0


def main():
    """Main entry point."""
    success = run_all_tests()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
