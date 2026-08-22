"""Tests for the Slack integration queue system."""
import pytest

from tuckit.integrations.slack.queue import (
    enqueue,
    job,
    run_job,
    in_process_backend,
    JOBS,
)
from tuckit.integrations.slack.queue_contract import (
    assert_queue_backend_contract,
)


def test_payload_must_be_json_serialisable():
    """Test that enqueue() validates payload JSON-serialisability at call time.

    This guard is critical: unserialisable payloads fail at the call site in
    core, not silently in cloud where the traceback no longer belongs to the
    caller.
    """
    class NonSerializable:
        pass

    # Register a dummy job
    @job("test_job")
    def handler(payload):
        pass

    # Try to enqueue with a non-serialisable payload
    with pytest.raises(TypeError, match="not JSON-serializable"):
        enqueue("test_job", {"obj": NonSerializable()})

    # Clean up
    del JOBS["test_job"]


def test_in_process_backend_satisfies_the_contract():
    """Test that the in-process backend passes the queue contract.

    This test verifies that the backend actually executes the job on a thread
    and passes the payload correctly. If the backend did nothing, the contract
    test would hang until timeout and fail.
    """
    assert_queue_backend_contract(in_process_backend)


def test_run_job_calls_the_registered_handler():
    """Test that run_job() executes the registered handler with the payload."""
    calls = []

    @job("tracked_job")
    def handler(payload):
        calls.append(payload)

    test_payload = {"key": "value"}
    run_job("tracked_job", test_payload)

    assert len(calls) == 1
    assert calls[0] == test_payload

    # Clean up
    del JOBS["tracked_job"]


def test_enqueue_returns_immediately():
    """Test that enqueue() returns without waiting for job completion.

    The job runs on a background thread (or is deferred to a queue), so
    enqueue() should return immediately even though the job has not
    finished yet.
    """
    job_completed = False

    @job("slow_job")
    def slow_handler(payload):
        nonlocal job_completed
        import time
        time.sleep(0.5)  # Simulate a slow job
        job_completed = True

    enqueue("slow_job", {})

    # If enqueue() waited for the job, job_completed would be True here.
    # But it returns immediately, so job_completed is still False.
    assert not job_completed, "enqueue() should return immediately, not wait for the job"

    # Clean up
    del JOBS["slow_job"]
