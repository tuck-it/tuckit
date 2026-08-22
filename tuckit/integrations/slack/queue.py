"""Job queue seam for the Slack integration.

Handlers enqueue work as (name: str, payload: dict) — never a callable.
Cloud Tasks must put the payload on the wire, so a backend accepting closures
would work in core and be unbuildable in cloud. Validation happens at enqueue()
time via json.dumps(): unserialisable payloads fail at the call site in core,
not silently in cloud.

The queue backend is pluggable: self-hosts run in-process by default, cloud
uses Google Cloud Tasks. Each backend is a plain callable (name, payload) -> None.
"""
import json
import logging
import threading
from typing import Callable

logger = logging.getLogger(__name__)

# Module-level job registry: maps job_name -> callable(**payload_dict)
JOBS: dict[str, Callable[..., None]] = {}


def job(name: str) -> Callable:
    """Decorator to register a job handler.

    Handlers are called with keyword arguments: JOBS[name](**payload).

    Usage:
        @job("some_job_name")
        def handle_some_job(*, team_id: str, event: dict) -> None:
            pass
    """
    def decorator(func: Callable) -> Callable:
        JOBS[name] = func
        return func
    return decorator


def run_job(job_name: str, payload: dict) -> None:
    """Execute a registered job handler with the given payload.

    This is called by backends (in-process, Cloud Tasks, etc.) to run the
    actual job. The handler is looked up by name in the job registry and
    called with keyword arguments unpacked from the payload dict.

    Args:
        job_name: The name of the registered job handler
        payload: The JSON-serializable dict to unpack and pass as kwargs

    Raises:
        KeyError: If job_name is not registered
    """
    if job_name not in JOBS:
        raise KeyError(f"No handler registered for job '{job_name}'")
    handler = JOBS[job_name]
    try:
        handler(**payload)
    except Exception as e:
        logger.exception("Job %s failed with exception", job_name, exc_info=e)
        raise


def in_process_backend(job_name: str, payload: dict) -> None:
    """In-process queue backend — runs jobs on daemon threads.

    Jobs are executed asynchronously on background daemon threads, so this
    function returns immediately. Useful for development and self-hosted
    deployments. Each job runs on its own daemon thread (no shared pool).

    Args:
        job_name: The name of the registered job handler
        payload: The JSON-serializable dict to pass to the handler
    """
    thread = threading.Thread(target=run_job, args=(job_name, payload), daemon=True)
    thread.start()


def enqueue(job_name: str, payload: dict) -> None:
    """Enqueue a job for async execution.

    This is the public API for queueing work. Job name and payload are both
    validated at the call site: unknown jobs and non-serializable payloads
    raise immediately, ensuring early failure in core, not silent failure
    across the repo boundary in cloud.

    Args:
        job_name: Name of the registered job handler
        payload: JSON-serializable dict to pass to the handler

    Raises:
        KeyError: If job_name is not registered
        TypeError: If payload is not JSON-serializable
    """
    # Check that the job is registered. Failure here lands at the call site.
    if job_name not in JOBS:
        raise KeyError(f"No handler registered for job '{job_name}'")

    # Validate that the payload is JSON-serializable. This guard is critical:
    # it ensures unserialisable payloads fail at the call site in core,
    # not silently in cloud where the traceback no longer belongs to the caller.
    try:
        json.dumps(payload)
    except TypeError as e:
        raise TypeError(f"Payload for job '{job_name}' is not JSON-serializable") from e

    # Load and use the configured backend (default: in-process)
    from django.conf import settings
    from django.utils.module_loading import import_string

    backend_path = getattr(
        settings,
        "TUCKIT_SLACK_QUEUE_BACKEND",
        "tuckit.integrations.slack.queue.in_process_backend",
    )
    backend = import_string(backend_path)
    backend(job_name, payload)
