"""Unit tests for retry policy logic."""

import pytest
from celerlite.broker.serializer import TaskMessage
from celerlite.scheduler.retry_policy import FatalError, RetryPolicy, RetryableError


def make_msg(retry_count=0, max_retries=3):
    return TaskMessage(
        task_name="test.task",
        args=[], kwargs={},
        queue="default", priority=1,
        retry_count=retry_count,
        max_retries=max_retries,
        timeout=30,
    )


@pytest.fixture
def policy(test_config):
    # Override for deterministic tests
    test_config.RETRY_JITTER = False
    return RetryPolicy(test_config)


class TestRetryPolicy:
    def test_should_retry_under_max(self, policy):
        msg = make_msg(retry_count=0, max_retries=3)
        assert policy.should_retry(msg, ValueError("oops")) is True

    def test_should_retry_at_max_minus_one(self, policy):
        msg = make_msg(retry_count=2, max_retries=3)
        assert policy.should_retry(msg, ValueError("oops")) is True

    def test_should_not_retry_at_max(self, policy):
        msg = make_msg(retry_count=3, max_retries=3)
        assert policy.should_retry(msg, ValueError("oops")) is False

    def test_fatal_error_no_retry(self, policy):
        msg = make_msg(retry_count=0, max_retries=3)
        assert policy.should_retry(msg, FatalError("fatal")) is False

    def test_retryable_error_retries(self, policy):
        msg = make_msg(retry_count=0)
        assert policy.should_retry(msg, RetryableError("retry me")) is True

    def test_backoff_exponential(self, policy):
        """Backoff increases exponentially: 2^0=1, 2^1=2, 2^2=4, 2^3=8"""
        delays = [policy.get_backoff_delay(i) for i in range(4)]
        for i in range(1, len(delays)):
            assert delays[i] > delays[i - 1], f"delay[{i}]={delays[i]} not > delay[{i-1}]={delays[i-1]}"

    def test_backoff_capped(self, policy):
        very_high_retry = 100
        delay = policy.get_backoff_delay(very_high_retry)
        assert delay <= policy.config.RETRY_BACKOFF_MAX

    def test_prepare_retry_increments_count(self, policy):
        msg = make_msg(retry_count=1)
        retried = policy.prepare_retry(msg)
        assert retried.retry_count == 2
        assert retried.eta is not None

    def test_build_dlq_entry(self, policy):
        msg = make_msg(retry_count=3)
        error = ValueError("permanent failure")
        entry = policy.build_dlq_entry(msg, error)
        assert entry.error_message == "permanent failure"
        assert entry.retry_count == 3
        assert entry.task_name == "test.task"
