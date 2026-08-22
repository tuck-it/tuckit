"""Queue backend contract — shared assertions for all backends.

This module is NOT a test file. It is a contract body that the tuckit-cloud
test suite imports and runs against its Cloud Tasks backend. All backends
must pass these assertions.

Keep this module free of pytest-only constructs and importable from cloud.
"""
import time

from tuckit.integrations.slack.queue import JOBS, run_job


def assert_queue_backend_contract(backend, poll_timeout_seconds: float = 5.0) -> None:
    """Contract: a queue backend must call the job handler with the payload.

    This assertion is shared by all backends (in-process, Cloud Tasks, etc.)
    and must pass for both core and cloud.

    Args:
        backend: A callable(job_name: str, payload: dict) backend to test
        poll_timeout_seconds: How long to wait for the job to complete

    Raises:
        AssertionError: If the job handler was not called
    """
    # Set up a test job that marks itself as run
    test_state = {"was_called": False, "received_payload": None}

    def test_job_handler(payload: dict) -> None:
        test_state["was_called"] = True
        test_state["received_payload"] = payload

    JOBS["__contract_test_job__"] = test_job_handler
    test_payload = {"key": "value", "number": 42}

    # Enqueue the job via the backend
    backend("__contract_test_job__", test_payload)

    # Wait for the job to complete (poll with timeout)
    start_time = time.time()
    while time.time() - start_time < poll_timeout_seconds:
        if test_state["was_called"]:
            break
        time.sleep(0.05)

    # Clean up the registry
    del JOBS["__contract_test_job__"]

    # Assert the job was called
    assert test_state["was_called"], (
        "Job handler was not called within the timeout. "
        "Either the backend did not execute the job, or execution took too long."
    )

    # Assert the payload was passed correctly
    assert test_state["received_payload"] == test_payload, (
        f"Payload mismatch. Expected {test_payload}, got {test_state['received_payload']}"
    )
