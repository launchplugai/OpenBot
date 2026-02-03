"""
Bridge Triage - Local heuristic for failure analysis.

Provides a simple rule-based triage without calling external models.
Returns structured output compatible with future Haiku integration.
"""

from typing import Dict, Any, Optional


def local_triage(receipt: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Analyze a receipt and produce triage output.
    
    Args:
        receipt: The receipt data dict (from latest_receipt)
        
    Returns:
        Triage dict with:
        - severity: "OK" | "WARN" | "FAIL"
        - root_cause_guess: str
        - next_action: str
        - notify: bool
        - confidence: float 0-1
    """
    if not receipt:
        return {
            "severity": "WARN",
            "root_cause_guess": "No receipt available",
            "next_action": "Check if run completed or if receipts directory is accessible",
            "notify": True,
            "confidence": 0.3,
        }
    
    overall_status = receipt.get("overall_status", "UNKNOWN")
    test_data = receipt.get("test", {})
    errors = receipt.get("errors", [])
    
    exit_code = test_data.get("exit_code")
    passed = test_data.get("passed", 0)
    failed = test_data.get("failed", 0)
    summary = test_data.get("summary", "")
    
    # Success case
    if overall_status == "SUCCESS" and exit_code == 0:
        return {
            "severity": "OK",
            "root_cause_guess": "All tests passed",
            "next_action": "No action needed",
            "notify": False,
            "confidence": 0.95,
        }
    
    # Failure cases
    if overall_status == "FAILED" or exit_code != 0:
        # Determine root cause hint
        root_cause = "Tests failed"
        next_action = "Review failing tests in logs"
        confidence = 0.7
        
        if failed > 0:
            root_cause = f"{failed} test(s) failed"
            next_action = f"Check logs for the {failed} failing test(s)"
            confidence = 0.85
        elif errors:
            root_cause = f"Errors during run: {errors[0] if errors else unknown}"
            next_action = "Check run errors and logs"
            confidence = 0.6
        elif exit_code and exit_code != 0:
            root_cause = f"Test command exited with code {exit_code}"
            next_action = "Review test output and check for setup issues"
            confidence = 0.5
        
        return {
            "severity": "FAIL",
            "root_cause_guess": root_cause,
            "next_action": next_action,
            "notify": True,
            "confidence": confidence,
        }
    
    # Unknown/degraded states
    if overall_status in ("DEGRADED", "UNHEALTHY"):
        return {
            "severity": "WARN",
            "root_cause_guess": f"System in {overall_status} state",
            "next_action": "Run openbot doctor to diagnose issues",
            "notify": True,
            "confidence": 0.6,
        }
    
    # Fallback
    return {
        "severity": "WARN",
        "root_cause_guess": f"Unknown status: {overall_status}",
        "next_action": "Manual investigation required",
        "notify": True,
        "confidence": 0.3,
    }
