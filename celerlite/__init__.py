"""CelerLite — Distributed Task Queue Engine."""

__version__ = "1.0.0"
__author__ = "Mudit Rungta"

from celerlite.sdk.decorators import task
from celerlite.scheduler.priority import Priority

__all__ = ["task", "Priority"]
