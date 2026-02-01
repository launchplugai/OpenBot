"""
Openbot - Automation Platform Runtime

A minimal automation runtime for running tests, capturing logs,
and producing machine-readable receipt JSON files.
"""

__version__ = "0.1.0"
__author__ = "Openbot Team"

from openbot.receipts import Receipt, ReceiptWriter
from openbot.runner import Runner
from openbot.policy import PolicyLoader

__all__ = ["Receipt", "ReceiptWriter", "Runner", "PolicyLoader", "__version__"]
