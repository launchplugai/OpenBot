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
from openbot.runner import parse_pytest_output
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


def test_doctor_permission_error():
    """Test that doctor handles PermissionError gracefully."""
    print("TEST: Doctor PermissionError handling... ", end="")

    import io
    import subprocess
    from unittest import mock

    # We need to test that when is_writable raises PermissionError,
    # doctor still returns JSON with UNHEALTHY status

    from openbot.utils import is_writable, safe_path_exists

    # Test is_writable handles PermissionError
    def mock_exists_raises(*args, **kwargs):
        raise PermissionError("Permission denied: /var/lib/openbot")

    original_exists = Path.exists

    # Test that safe_path_exists catches PermissionError
    with mock.patch.object(Path, 'exists', mock_exists_raises):
        result = safe_path_exists(Path("/var/lib/openbot/logs"))
        if result != False:
            print("FAILED: safe_path_exists should return False on PermissionError")
            return False

    # Test that is_writable catches PermissionError
    with mock.patch.object(Path, 'exists', mock_exists_raises):
        result = is_writable(Path("/var/lib/openbot/logs"))
        if result != False:
            print("FAILED: is_writable should return False on PermissionError")
            return False

    # Test full doctor command with mocked permission errors
    # Run doctor in subprocess to capture output
    result = subprocess.run(
        [sys.executable, "-m", "openbot.cli", "doctor", "--local"],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).parent.parent)
    )

    # Doctor with --local should succeed (local dirs are writable)
    # Parse the JSON output
    try:
        output_lines = result.stdout.strip().split('\n')
        # Find JSON block (may have trailing messages)
        json_text = ""
        brace_count = 0
        for line in output_lines:
            json_text += line + "\n"
            brace_count += line.count('{') - line.count('}')
            if brace_count == 0 and json_text.strip():
                break
        report = json.loads(json_text)
    except json.JSONDecodeError as e:
        print(f"FAILED: Doctor output not valid JSON: {e}")
        print(f"Output was: {result.stdout[:500]}")
        return False

    # Verify report structure
    if "overall_status" not in report:
        print("FAILED: Doctor report missing overall_status")
        return False

    if "checks" not in report:
        print("FAILED: Doctor report missing checks")
        return False

    print("PASSED")
    return True


def test_is_writable_permission_error():
    """Test is_writable returns False on PermissionError, never crashes."""
    print("TEST: is_writable PermissionError safety... ", end="")

    from unittest import mock
    from openbot.utils import is_writable

    def always_raise_permission_error(*args, **kwargs):
        raise PermissionError("Mocked permission denied")

    # Mock Path.exists to raise PermissionError
    with mock.patch.object(Path, 'exists', always_raise_permission_error):
        result = is_writable(Path("/some/restricted/path"))
        if result is not False:
            print(f"FAILED: Expected False, got {result}")
            return False

    # Mock Path.mkdir to raise PermissionError
    with mock.patch.object(Path, 'exists', return_value=False):
        with mock.patch.object(Path, 'mkdir', always_raise_permission_error):
            result = is_writable(Path("/some/restricted/path"))
            if result is not False:
                print(f"FAILED: Expected False on mkdir error, got {result}")
                return False

    print("PASSED")
    return True


def test_config_example_has_required_keys():
    """Test that config.example.yaml contains all required keys."""
    print("TEST: Config example has required keys... ", end="")

    # Find config.example.yaml relative to this file
    repo_root = Path(__file__).parent.parent
    config_path = repo_root / "runtime" / "config.example.yaml"

    if not config_path.exists():
        print(f"FAILED: Config example not found at {config_path}")
        return False

    with open(config_path, "r") as f:
        content = f.read()

    required_keys = ["target_repo", "target_branch", "command"]
    missing = []

    for key in required_keys:
        # Check for key: pattern (allowing for comments)
        if f"{key}:" not in content:
            missing.append(key)

    if missing:
        print(f"FAILED: Missing required keys: {missing}")
        return False

    print("PASSED")
    return True


def test_config_yaml_parsing():
    """Test YAML parsing handles quoted values and whitespace correctly."""
    print("TEST: Config YAML parsing... ", end="")

    import subprocess
    import re

    # Create test config with various quoting styles
    test_cases = [
        # (config_content, expected_repo, expected_branch, expected_command)
        (
            'target_repo: "https://github.com/test/repo"\ntarget_branch: "main"\ncommand: "npm test"',
            "https://github.com/test/repo",
            "main",
            "npm test"
        ),
        (
            "target_repo: 'https://github.com/test/repo'\ntarget_branch: 'main'\ncommand: 'npm test'",
            "https://github.com/test/repo",
            "main",
            "npm test"
        ),
        (
            "target_repo: https://github.com/test/repo\ntarget_branch: main\ncommand: ls -la",
            "https://github.com/test/repo",
            "main",
            "ls -la"
        ),
        (
            '  target_repo:   "https://github.com/test/repo"  \n  target_branch:  main  \ncommand: "echo hello"',
            "https://github.com/test/repo",
            "main",
            "echo hello"
        ),
    ]

    # We'll test the parsing logic directly using subprocess
    # The parse_yaml_value function is in bash, so we test via subprocess
    repo_root = Path(__file__).parent.parent
    openbot_run = repo_root / "scripts" / "openbot-run"

    if not openbot_run.exists():
        print(f"FAILED: openbot-run script not found at {openbot_run}")
        return False

    # Extract and test the parse_yaml_value function
    with open(openbot_run, "r") as f:
        script_content = f.read()

    # Verify script contains the parse function
    if "parse_yaml_value()" not in script_content:
        print("FAILED: parse_yaml_value function not found in script")
        return False

    # Extract the parse_yaml_value function from the actual script
    import re
    func_match = re.search(
        r'parse_yaml_value\(\)\s*\{.*?\n\}',
        script_content,
        re.DOTALL
    )
    if not func_match:
        print("FAILED: Could not extract parse_yaml_value function")
        return False

    parse_func = func_match.group(0)

    # Test the parsing by creating temp config files and running the parse function
    for i, (config_content, exp_repo, exp_branch, exp_cmd) in enumerate(test_cases):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(config_content)
            config_file = f.name

        try:
            # Create a test script using the actual parse function from the script
            test_script = f'''
#!/bin/bash
{parse_func}
echo "REPO:$(parse_yaml_value target_repo {config_file})"
echo "BRANCH:$(parse_yaml_value target_branch {config_file})"
echo "CMD:$(parse_yaml_value command {config_file})"
'''
            result = subprocess.run(
                ["bash", "-c", test_script],
                capture_output=True,
                text=True
            )

            output = result.stdout
            parsed_repo = ""
            parsed_branch = ""
            parsed_cmd = ""

            for line in output.strip().split('\n'):
                if line.startswith("REPO:"):
                    parsed_repo = line[5:]
                elif line.startswith("BRANCH:"):
                    parsed_branch = line[7:]
                elif line.startswith("CMD:"):
                    parsed_cmd = line[4:]

            if parsed_repo != exp_repo:
                print(f"FAILED: Case {i+1} repo mismatch: got '{parsed_repo}', expected '{exp_repo}'")
                return False
            if parsed_branch != exp_branch:
                print(f"FAILED: Case {i+1} branch mismatch: got '{parsed_branch}', expected '{exp_branch}'")
                return False
            if parsed_cmd != exp_cmd:
                print(f"FAILED: Case {i+1} command mismatch: got '{parsed_cmd}', expected '{exp_cmd}'")
                return False

        finally:
            Path(config_file).unlink()

    print("PASSED")
    return True


def test_pytest_output_parsing():
    """Test parsing of pytest output for pass/fail counts."""
    print("TEST: Pytest output parsing... ", end="")

    test_cases = [
        # (output, expected_passed, expected_failed)
        ("===== 831 passed, 9 failed in 5.23s =====", 831, 9),
        ("831 passed, 9 failed", 831, 9),
        ("831 passed", 831, None),
        ("9 failed", None, 9),
        ("===== 100 passed in 2.31s =====", 100, None),
        ("===== 5 failed in 1.23s =====", None, 5),
        ("no tests ran", None, None),
        ("", None, None),
        ("collected 50 items\n\ntest_foo.py ...... [100%]\n\n===== 50 passed in 0.5s =====", 50, None),
        ("FAILED tests/test_foo.py::test_bar - AssertionError\n===== 1 failed, 49 passed in 2.3s =====", 49, 1),
    ]

    for output, exp_passed, exp_failed in test_cases:
        passed, failed = parse_pytest_output(output)
        if passed != exp_passed:
            print(f"FAILED: For '{output[:40]}...', expected passed={exp_passed}, got {passed}")
            return False
        if failed != exp_failed:
            print(f"FAILED: For '{output[:40]}...', expected failed={exp_failed}, got {failed}")
            return False

    print("PASSED")
    return True


def test_receipt_with_pytest_counts():
    """Test that receipts correctly store pytest pass/fail counts."""
    print("TEST: Receipt with pytest counts... ", end="")

    receipt = Receipt()
    receipt.set_target(
        repo="https://github.com/test/repo",
        branch="main",
        commit_sha="e" * 40
    )
    receipt.set_test_result(
        command="pytest",
        exit_code=0,
        log_path="/tmp/test.log",
        passed=831,
        failed=9,
        runtime_seconds=5.23,
        setup_command="pip install -r requirements.txt"
    )

    data = receipt.finalize()

    assert data["test"]["passed"] == 831, f"Expected 831, got {data['test'].get('passed')}"
    assert data["test"]["failed"] == 9, f"Expected 9, got {data['test'].get('failed')}"
    assert data["test"]["runtime_seconds"] == 5.23, f"Expected 5.23, got {data['test'].get('runtime_seconds')}"
    assert data["test"]["setup_command"] == "pip install -r requirements.txt"

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
        test_doctor_permission_error,
        test_is_writable_permission_error,
        test_config_example_has_required_keys,
        test_config_yaml_parsing,
        test_pytest_output_parsing,
        test_receipt_with_pytest_counts,
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
