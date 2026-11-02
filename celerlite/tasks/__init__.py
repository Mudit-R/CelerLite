"""Built-in CelerLite workflows that demonstrate useful background jobs."""

from celerlite.tasks.crm import register_crm_tasks

__all__ = ["register_crm_tasks"]
