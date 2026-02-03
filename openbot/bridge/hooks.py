"""
Bridge Hooks - Allowlist enforcement and output sanitization.

Security layer that:
- Enforces strict allowlist of permitted operations
- Sanitizes output to remove secrets/tokens
- Caps output size to prevent memory issues
"""

import re
from typing import Dict, Any, Optional

# Maximum output size in bytes (50KB)
MAX_OUTPUT_SIZE = 50 * 1024

# Allowed operations and their constraints
ALLOWLIST = {
    "doctor": {
        "description": "Run health check",
        "args": [],
    },
    "run": {
        "description": "Trigger test run",
        "args": [],
    },
    "service": {
        "description": "Control openbot-run.service",
        "allowed_actions": ["status", "restart"],
        "allowed_services": ["openbot-run.service"],
    },
    "logs": {
        "description": "Fetch journal logs",
        "allowed_services": ["openbot-run.service"],
        "max_lines": 1000,
        "default_lines": 120,
    },
    "latest_receipt": {
        "description": "Get most recent receipt",
        "args": [],
    },
}

# Patterns that indicate secrets - will be redacted
SECRET_PATTERNS = [
    re.compile(r"ghp_[a-zA-Z0-9]{36,}", re.IGNORECASE),
    re.compile(r"github_pat_[a-zA-Z0-9_]{22,}", re.IGNORECASE),
    re.compile(r"gho_[a-zA-Z0-9]{36,}", re.IGNORECASE),
    re.compile(r"ghu_[a-zA-Z0-9]{36,}", re.IGNORECASE),
    re.compile(r"ghs_[a-zA-Z0-9]{36,}", re.IGNORECASE),
    re.compile(r"ghr_[a-zA-Z0-9]{36,}", re.IGNORECASE),
    re.compile(r"sk-[a-zA-Z0-9]{20,}", re.IGNORECASE),
    re.compile(r"\"token\"\s*:\s*\"[^\"]+\"", re.IGNORECASE),
    re.compile(r"Authorization:\s*[^\n]+", re.IGNORECASE),
    re.compile(r"x-api-key:\s*[^\n]+", re.IGNORECASE),
    re.compile(r"ANTHROPIC_API_KEY[=:][^\s]+", re.IGNORECASE),
    re.compile(r"Bearer\s+[a-zA-Z0-9._-]{20,}", re.IGNORECASE),
    # Long base64 blobs (likely tokens/keys)
    re.compile(r"[A-Za-z0-9+/]{40,}={0,2}", re.IGNORECASE),
]

# Files that must NEVER be read or have contents printed
FORBIDDEN_PATHS = [
    "/etc/openbot/credentials.yaml",
    "/etc/openbot/credentials",
    "/etc/openbot/github_token",
]


def sanitize_output(text: str) -> str:
    """
    Remove any secrets/tokens from output text.
    
    Args:
        text: Raw output text
        
    Returns:
        Sanitized text with secrets replaced by [REDACTED]
    """
    if not text:
        return ""
    
    result = text
    for pattern in SECRET_PATTERNS:
        result = pattern.sub("[REDACTED]", result)
    
    return result


def cap_size(text: str, max_bytes: int = MAX_OUTPUT_SIZE) -> tuple[str, bool]:
    """
    Cap output size to prevent memory issues.
    
    Args:
        text: Input text
        max_bytes: Maximum size in bytes
        
    Returns:
        Tuple of (capped_text, was_truncated)
    """
    if not text:
        return "", False
    
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= max_bytes:
        return text, False
    
    # Truncate and decode back
    truncated = encoded[:max_bytes].decode("utf-8", errors="replace")
    return truncated + "\n[OUTPUT TRUNCATED]", True


def check_allowlist(operation: str, **kwargs) -> Optional[Dict[str, Any]]:
    """
    Check if an operation is allowed.
    
    Args:
        operation: The operation name
        **kwargs: Operation-specific arguments
        
    Returns:
        None if allowed, or error dict if forbidden
    """
    if operation not in ALLOWLIST:
        return {
            "ok": False,
            "error": {
                "type": "forbidden",
                "message": f"Operation not allowed: {operation}",
                "allowed_operations": list(ALLOWLIST.keys()),
            }
        }
    
    config = ALLOWLIST[operation]
    
    # Check service operations
    if operation == "service":
        action = kwargs.get("action")
        service = kwargs.get("service", "openbot-run.service")
        
        if action not in config["allowed_actions"]:
            return {
                "ok": False,
                "error": {
                    "type": "forbidden",
                    "message": f"Service action not allowed: {action}",
                    "allowed_actions": config["allowed_actions"],
                }
            }
        
        if service not in config["allowed_services"]:
            return {
                "ok": False,
                "error": {
                    "type": "forbidden",
                    "message": f"Service not allowed: {service}",
                    "allowed_services": config["allowed_services"],
                }
            }
    
    # Check logs operations
    if operation == "logs":
        service = kwargs.get("service", "openbot-run.service")
        lines = kwargs.get("lines", config["default_lines"])
        
        if service not in config["allowed_services"]:
            return {
                "ok": False,
                "error": {
                    "type": "forbidden",
                    "message": f"Service not allowed for logs: {service}",
                    "allowed_services": config["allowed_services"],
                }
            }
        
        if lines > config["max_lines"]:
            return {
                "ok": False,
                "error": {
                    "type": "forbidden",
                    "message": f"Too many lines requested: {lines} (max: {config["max_lines"]})",
                }
            }
    
    return None  # Allowed


def is_path_forbidden(path: str) -> bool:
    """Check if a path is in the forbidden list."""
    from pathlib import Path
    try:
        resolved = str(Path(path).resolve())
        for forbidden in FORBIDDEN_PATHS:
            if resolved == forbidden or resolved.startswith(forbidden):
                return True
        return False
    except Exception:
        return True  # If we cannot resolve, assume forbidden
