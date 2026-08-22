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
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

logger = logging.getLogger(__name__)

# Module-level job registry: maps job_name -> callable(payload: dict)
JOBS: dict[str, Callable[[dict], None]] = {}


def job(name: str) -> Callable:
    """Decorator to register a job handler.

    Usage:
        @job("some_job_name")
        def handle_some_job(payload: dict) -> None:
            pass
    """
    def decorator(func: Callable) -> Callable:
        JOBS[name] = func
        return func
    return decorator


def run_job(job_name: str, payload: dict) -> None:
    """Execute a registered job handler with the given payload.

    This is called by backends (in-process, Cloud Tasks, etc.) to run the
    actual job. The handler is looked up by name in the job registry.

    Args:
        job_name: The name of the registered job handler
        payload: The JSON-serializable dict to pass to the handler

    Raises:
        KeyError: If job_name is not registered
    """
    if job_name not in JOBS:
        raise KeyError(f"No handler registered for job '{job_name}'")
    handler = JOBS[job_name]
    try:
        handler(payload)
    except Exception as e:
        logger.exception("Job %s failed with exception", job_name, exc_info=e)
        raise


def in_process_backend(job_name: str, payload: dict) -> None:
    """In-process queue backend — runs jobs on a thread pool.

    Jobs are executed asynchronously on background threads, so this function
    returns immediately. Useful for development and self-hosted deployments.

    Args:
        job_name: The name of the registered job handler
        payload: The JSON-serializable dict to pass to the handler
    """
    executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="slack_job_")
    executor.submit(run_job, job_name, payload)


def enqueue(job_name: str, payload: dict) -> None:
    """Enqueue a job for async execution.

    This is the public API for queueing work. The payload is validated as
    JSON-serializable at this call site to ensure early failure in core,
    not silent failure across the repo boundary in cloud.

    Args:
        job_name: Name of the registered job handler
        payload: JSON-serializable dict to pass to the handler

    Raises:
        TypeError: If payload is not JSON-serializable
        KeyError: If job_name is not registered
    """
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
