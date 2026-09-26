"""Unit tests for priority queue scheduling logic."""

import pytest
from celerlite.scheduler.priority import (
    Priority,
    PRIORITY_SUFFIX,
    get_priority_queue_name,
    get_priority_dequeue_order,
)


class TestPriority:
    def test_priority_enum_values(self):
        assert Priority.LOW == 0
        assert Priority.NORMAL == 1
        assert Priority.HIGH == 2
        assert Priority.CRITICAL == 3

    def test_priority_ordering(self):
        assert Priority.CRITICAL > Priority.HIGH > Priority.NORMAL > Priority.LOW

    def test_queue_name_formatting(self):
        assert get_priority_queue_name("default", Priority.CRITICAL) == "celerlite:queue:default:critical"
        assert get_priority_queue_name("default", Priority.HIGH) == "celerlite:queue:default:high"
        assert get_priority_queue_name("default", Priority.NORMAL) == "celerlite:queue:default:normal"
        assert get_priority_queue_name("default", Priority.LOW) == "celerlite:queue:default:low"

    def test_custom_queue_name_formatting(self):
        assert get_priority_queue_name("emails", Priority.HIGH) == "celerlite:queue:emails:high"

    def test_strict_dequeue_order(self):
        order = get_priority_dequeue_order("default")
        assert len(order) == 4
        # Verify strict priority order: CRITICAL -> HIGH -> NORMAL -> LOW
        assert order[0] == "celerlite:queue:default:critical"
        assert order[1] == "celerlite:queue:default:high"
        assert order[2] == "celerlite:queue:default:normal"
        assert order[3] == "celerlite:queue:default:low"

    def test_all_priorities_have_suffixes(self):
        for p in Priority:
            assert p in PRIORITY_SUFFIX
            assert isinstance(PRIORITY_SUFFIX[p], str)
            assert len(PRIORITY_SUFFIX[p]) > 0
