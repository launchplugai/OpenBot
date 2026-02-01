"""
Policy loading and parsing for Openbot.

Phase 1: Policies are loaded and included in receipts but not enforced.
"""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

# Avoid external dependency - use simple YAML parsing for our known formats
# If the YAML is more complex, we document that PyYAML would be needed


def _parse_simple_yaml(content: str) -> Dict[str, Any]:
    """
    Parse simple YAML structure without external dependency.
    Handles our specific policy file formats only.
    """
    result: Dict[str, Any] = {}
    current_key = None
    current_list: List[str] = []
    in_list = False
    indent_stack: List[tuple] = []

    lines = content.split("\n")
    for line in lines:
        # Skip comments and empty lines
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        # Count leading spaces
        spaces = len(line) - len(line.lstrip())

        # Check if it's a list item
        if stripped.startswith("- "):
            item = stripped[2:].strip()
            # Remove quotes if present
            if (item.startswith('"') and item.endswith('"')) or \
               (item.startswith("'") and item.endswith("'")):
                item = item[1:-1]

            if current_key:
                if current_key not in result:
                    result[current_key] = []
                if isinstance(result[current_key], list):
                    # Check if it's a nested object (has 'id:' or similar)
                    if ": " in item or item.endswith(":"):
                        # It's a complex list item, just store as string for now
                        result[current_key].append(item)
                    else:
                        result[current_key].append(item)
            continue

        # Key-value pair
        if ":" in stripped:
            parts = stripped.split(":", 1)
            key = parts[0].strip()
            value = parts[1].strip() if len(parts) > 1 else ""

            if not value:
                # This is a section header
                current_key = key
                if current_key not in result:
                    result[current_key] = []
            else:
                # Remove quotes from value
                if (value.startswith('"') and value.endswith('"')) or \
                   (value.startswith("'") and value.endswith("'")):
                    value = value[1:-1]
                result[key] = value
                current_key = None

    return result


class PolicyLoader:
    """Loads and provides access to policy files."""

    def __init__(self, policies_dir: Optional[Path] = None):
        if policies_dir is None:
            # Default to policies/ relative to this file's package
            pkg_root = Path(__file__).parent.parent
            policies_dir = pkg_root / "policies"
        self.policies_dir = Path(policies_dir)
        self._loaded: Dict[str, Dict[str, Any]] = {}
        self._load_errors: List[str] = []

    def load_all(self) -> bool:
        """Load all policy files. Returns True if all loaded successfully."""
        success = True
        policy_files = [
            ("protected_paths", "protected_paths.yaml"),
            ("escalation_rules", "escalation_rules.yaml"),
            ("receipt_schema", "receipt_schema_v1.json"),
        ]

        for name, filename in policy_files:
            path = self.policies_dir / filename
            if not path.exists():
                self._load_errors.append(f"Policy file not found: {path}")
                success = False
                continue

            try:
                with open(path, "r") as f:
                    content = f.read()

                if filename.endswith(".json"):
                    import json
                    self._loaded[name] = json.loads(content)
                elif filename.endswith(".yaml"):
                    self._loaded[name] = _parse_simple_yaml(content)
                else:
                    self._load_errors.append(f"Unknown policy format: {filename}")
                    success = False
            except Exception as e:
                self._load_errors.append(f"Error loading {filename}: {e}")
                success = False

        return success

    def get_policy(self, name: str) -> Optional[Dict[str, Any]]:
        """Get a loaded policy by name."""
        return self._loaded.get(name)

    def get_protected_globs(self) -> List[str]:
        """Get list of protected path globs."""
        policy = self._loaded.get("protected_paths", {})
        return policy.get("protected_globs", [])

    def get_allowed_write_paths(self) -> List[str]:
        """Get list of allowed write path globs."""
        policy = self._loaded.get("allowed_write_paths", {})
        return policy.get("allowed_write_paths", [])

    def get_escalation_rules(self) -> List[Dict[str, Any]]:
        """Get escalation rules."""
        policy = self._loaded.get("escalation_rules", {})
        return policy.get("rules", [])

    def get_receipt_schema(self) -> Optional[Dict[str, Any]]:
        """Get receipt JSON schema."""
        return self._loaded.get("receipt_schema")

    def get_loaded_policy_names(self) -> List[str]:
        """Get list of successfully loaded policy names."""
        return list(self._loaded.keys())

    def get_load_errors(self) -> List[str]:
        """Get list of errors from loading policies."""
        return self._load_errors.copy()
