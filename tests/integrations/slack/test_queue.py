"""Tests for the Slack integration queue system."""
import pytest

from tuckit.integrations.slack.queue import (
    enqueue,
    register_job,
    get_job_handler,
    InProcessQueueBackend,
    _JOB_REGISTRY,
)
from tuckit.integrations.slack.queue_contract import (
    contract_enqueue_calls_the_job_handler,
)


def test_register_job_decorator():
    """Test that @register_job registers a handler in the global registry."""

    @register_job("test_job")
    def handler(payload):
        pass

    assert "test_job" in _JOB_REGISTRY
    assert _JOB_REGISTRY["test_job"] is handler

    # Clean up
    del _JOB_REGISTRY["test_job"]


def test_get_job_handler_returns_registered_handler():
    """Test that get_job_handler returns a registered handler."""

    @register_job("my_job")
    def my_handler(payload):
        return "result"

    handler = get_job_handler("my_job")
    assert handler is my_handler

    # Clean up
    del _JOB_REGISTRY["my_job"]


def test_get_job_handler_raises_on_missing_job():
    """Test that get_job_handler raises KeyError for unregistered jobs."""
    with pytest.raises(KeyError, match="No handler registered for job 'nonexistent'"):
        get_job_handler("nonexistent")


def test_enqueue_raises_on_missing_job():
    """Test that enqueue() raises KeyError if the job is not registered."""
    with pytest.raises(KeyError, match="No handler registered for job 'missing_job'"):
        enqueue("missing_job", {"key": "value"})


def test_in_process_backend_satisfies_the_contract():
    """Test that the in-process backend passes the queue contract.

    This test verifies that the backend actually executes the job on a thread
    and passes the payload correctly. If the backend did nothing, the contract
    test would hang until timeout and fail.
    """
    backend = InProcessQueueBackend()
    contract_enqueue_calls_the_job_handler(backend)


def test_enqueue_returns_immediately():
    """Test that enqueue() returns without waiting for job completion.

    The job runs on a background thread, so enqueue() should return
    immediately even though the job has not finished yet.
    """
    job_started = False
    job_completed = False

    @register_job("slow_job")
    def slow_handler(payload):
        nonlocal job_completed
        import time
        time.sleep(0.5)  # Simulate a slow job
        job_completed = True

    backend = InProcessQueueBackend()
    backend.enqueue("slow_job", {})

    # If enqueue() waited for the job, job_completed would be True here.
    # But it returns immediately, so job_completed is still False.
    assert not job_completed, "enqueue() should return immediately, not wait for the job"

    # Wait for the job to actually complete
    import time
    start_time = time.time()
    while not job_completed and time.time() - start_time < 5:
        time.sleep(0.01)

    assert job_completed, "Job never completed"

    # Clean up
    del _JOB_REGISTRY["slow_job"]


def test_enqueue_dispatches_to_backend():
    """Test that the global enqueue() function dispatches to the backend."""
    calls = []

    @register_job("test_dispatch")
    def handler(payload):
        calls.append(payload)

    payload = {"test": "data"}
    enqueue("test_dispatch", payload)

    # Wait for the background job to complete
    import time
    start_time = time.time()
    while len(calls) == 0 and time.time() - start_time < 5:
        time.sleep(0.01)

    assert len(calls) == 1
    assert calls[0] == payload

    # Clean up
    del _JOB_REGISTRY["test_dispatch"]
