"""
Tests for OpenBot Bridge module.
"""

import json
import unittest
from unittest.mock import patch, MagicMock

from openbot.bridge.hooks import (
    sanitize_output,
    cap_size,
    check_allowlist,
    MAX_OUTPUT_SIZE,
    ALLOWLIST,
)
from openbot.bridge.triage import local_triage


class TestSanitization(unittest.TestCase):
    """Test output sanitization."""
    
    def test_sanitize_github_pat(self):
        """GitHub PAT tokens are redacted."""
        text = "token: ghp_1234567890abcdefghijklmnopqrstuvwxyz"
        result = sanitize_output(text)
        self.assertNotIn("ghp_", result)
        self.assertIn("[REDACTED]", result)
    
    def test_sanitize_github_pat_22(self):
        """GitHub fine-grained PAT tokens are redacted."""
        text = "Authorization: github_pat_11ABCDEF_abcdefghijklmnopqrstuvwxyz1234567890"
        result = sanitize_output(text)
        self.assertNotIn("github_pat_", result)
        self.assertIn("[REDACTED]", result)
    
    def test_sanitize_sk_key(self):
        """sk- prefixed keys are redacted."""
        text = "ANTHROPIC_API_KEY=sk-ant-api123456789abcdefghij"
        result = sanitize_output(text)
        self.assertNotIn("sk-ant", result)
        self.assertIn("[REDACTED]", result)
    
    def test_sanitize_preserves_normal_text(self):
        """Normal text is preserved."""
        text = "All tests passed: 838 passed, 0 failed"
        result = sanitize_output(text)
        self.assertEqual(text, result)
    
    def test_sanitize_empty(self):
        """Empty input returns empty string."""
        self.assertEqual(sanitize_output(""), "")
        self.assertEqual(sanitize_output(None), "")


class TestCapSize(unittest.TestCase):
    """Test output size capping."""
    
    def test_small_output_unchanged(self):
        """Small output is not truncated."""
        text = "Hello, world!"
        result, truncated = cap_size(text)
        self.assertEqual(result, text)
        self.assertFalse(truncated)
    
    def test_large_output_truncated(self):
        """Large output is truncated."""
        text = "x" * (MAX_OUTPUT_SIZE + 1000)
        result, truncated = cap_size(text)
        self.assertTrue(truncated)
        self.assertIn("[OUTPUT TRUNCATED]", result)
        self.assertLessEqual(len(result.encode("utf-8")), MAX_OUTPUT_SIZE + 50)
    
    def test_empty_input(self):
        """Empty input returns empty string."""
        result, truncated = cap_size("")
        self.assertEqual(result, "")
        self.assertFalse(truncated)


class TestAllowlist(unittest.TestCase):
    """Test allowlist enforcement."""
    
    def test_allowed_operations(self):
        """Known operations are allowed."""
        for op in ALLOWLIST.keys():
            if op == "service":
                result = check_allowlist(op, action="status")
            elif op == "logs":
                result = check_allowlist(op, lines=100)
            else:
                result = check_allowlist(op)
            self.assertIsNone(result, f"Operation {op} should be allowed")
    
    def test_forbidden_operation(self):
        """Unknown operations are blocked."""
        result = check_allowlist("shell")
        self.assertIsNotNone(result)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["type"], "forbidden")
    
    def test_forbidden_service_action(self):
        """Only status/restart are allowed for service."""
        # stop is not allowed
        result = check_allowlist("service", action="stop")
        self.assertIsNotNone(result)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["type"], "forbidden")
        
        # disable is not allowed
        result = check_allowlist("service", action="disable")
        self.assertIsNotNone(result)
        self.assertFalse(result["ok"])
    
    def test_forbidden_service_name(self):
        """Only openbot-run.service is allowed."""
        result = check_allowlist("service", action="status", service="sshd.service")
        self.assertIsNotNone(result)
        self.assertFalse(result["ok"])
        self.assertIn("sshd.service", result["error"]["message"])
    
    def test_logs_too_many_lines(self):
        """Too many log lines are rejected."""
        result = check_allowlist("logs", lines=5000)
        self.assertIsNotNone(result)
        self.assertFalse(result["ok"])


class TestTriage(unittest.TestCase):
    """Test local triage logic."""
    
    def test_success_triage(self):
        """Successful receipt produces OK severity."""
        receipt = {
            "overall_status": "SUCCESS",
            "test": {"exit_code": 0, "passed": 100, "failed": 0},
            "errors": [],
        }
        result = local_triage(receipt)
        self.assertEqual(result["severity"], "OK")
        self.assertFalse(result["notify"])
    
    def test_failure_triage(self):
        """Failed receipt produces FAIL severity."""
        receipt = {
            "overall_status": "FAILED",
            "test": {"exit_code": 1, "passed": 95, "failed": 5},
            "errors": [],
        }
        result = local_triage(receipt)
        self.assertEqual(result["severity"], "FAIL")
        self.assertTrue(result["notify"])
        self.assertIn("5", result["root_cause_guess"])
    
    def test_no_receipt_triage(self):
        """Missing receipt produces WARN severity."""
        result = local_triage(None)
        self.assertEqual(result["severity"], "WARN")
        self.assertTrue(result["notify"])


if __name__ == "__main__":
    unittest.main()

