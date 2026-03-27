"""
Openbot - Automation Platform Runtime

A minimal automation runtime for running tests, capturing logs,
and producing machine-readable receipt JSON files.

Phase 2: Constitutional enforcement layer active.
"""

__version__ = "0.2.0"
__author__ = "Openbot Team"

from openbot.receipts import Receipt, ReceiptWriter
from openbot.runner import Runner
from openbot.policy import PolicyLoader
from openbot.enforce import Enforcer, PathProtector, QualityGate, WorkerReceipt

__all__ = [
    "Receipt", "ReceiptWriter", "Runner", "PolicyLoader",
    "Enforcer", "PathProtector", "QualityGate", "WorkerReceipt",
    "__version__",
]
