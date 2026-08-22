"""Job queue seam for the Slack integration.

Handlers enqueue work as (name: str, payload: dict) — never a callable.
Cloud Tasks on the wire requires JSON-serializable data, so a backend that
accepted closures would work in core and be unbuildable in cloud.

The queue backend is pluggable: self-hosts run in-process by default, cloud
uses Google Cloud Tasks. Backends are swapped via TUCKIT_SLACK_QUEUE_BACKEND
(full import path to a callable that returns a QueueBackend instance).
"""
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
import logging
from typing import Any, Callable

from django.utils.module_loading import import_string
from django.conf import settings

logger = logging.getLogger(__name__)

# Module-level job registry: maps job_name -> callable(payload: dict)
_JOB_REGISTRY: dict[str, Callable[[dict], None]] = {}


def register_job(name: str) -> Callable:
    """Decorator to register a job handler.

    Usage:
        @register_job("some_job_name")
        def handle_some_job(payload: dict) -> None:
            pass
    """
    def decorator(func: Callable) -> Callable:
        _JOB_REGISTRY[name] = func
        return func
    return decorator


def get_job_handler(job_name: str) -> Callable:
    """Retrieve a registered job handler by name.

    Raises KeyError if the job is not registered.
    """
    if job_name not in _JOB_REGISTRY:
        raise KeyError(f"No handler registered for job '{job_name}'")
    return _JOB_REGISTRY[job_name]


class QueueBackend(ABC):
    """Abstract base class for queue backends.

    A backend accepts a job name and a JSON-serializable payload,
    and arranges for that job to be executed (either immediately,
    deferred, or on a task queue). Implementations are free to:
    - Run synchronously or asynchronously
    - Run in-process or out-of-process
    - Retry or fail silently

    The contract is: the backend must call the job handler with the
    payload, at some point. The handler function is looked up by name.
    """

    @abstractmethod
    def enqueue(self, job_name: str, payload: dict) -> None:
        """Enqueue a job for execution.

        Args:
            job_name: The name of the job (must be registered via @register_job)
            payload: A JSON-serializable dict to pass to the job handler
        """
        pass


class InProcessQueueBackend(QueueBackend):
    """Runs jobs on a thread pool in the current process.

    Jobs are executed asynchronously on background threads, so enqueue()
    returns immediately. Useful for development and self-hosted deployments.
    """

    def __init__(self):
        """Initialize the in-process backend with a thread pool."""
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="slack_job_")

    def enqueue(self, job_name: str, payload: dict) -> None:
        """Enqueue a job to run on a background thread.

        The job handler is looked up by name in the job registry and
        submitted to the thread pool for execution.
        """
        try:
            handler = get_job_handler(job_name)
        except KeyError as e:
            logger.error("Job enqueue failed: %s", e)
            raise

        def run_job() -> None:
            try:
                handler(payload)
            except Exception as e:
                logger.exception("Job %s failed with exception", job_name, exc_info=e)

        self._executor.submit(run_job)


def get_backend() -> QueueBackend:
    """Load and instantiate the configured queue backend.

    The backend class is specified by TUCKIT_SLACK_QUEUE_BACKEND setting
    (a full import path). If not set, defaults to InProcessQueueBackend.

    Returns:
        An instance of the configured QueueBackend
    """
    backend_path = getattr(
        settings,
        "TUCKIT_SLACK_QUEUE_BACKEND",
        "tuckit.integrations.slack.queue.InProcessQueueBackend",
    )
    backend_class = import_string(backend_path)
    return backend_class()


# Module-level backend instance (lazy-loaded on first use)
_backend: QueueBackend | None = None


def enqueue(job_name: str, payload: dict) -> None:
    """Enqueue a job for async execution.

    This is the public API for queueing work. The job_name identifies
    a registered handler, and payload is passed to it.

    Args:
        job_name: Name of the registered job handler
        payload: JSON-serializable dict to pass to the handler

    Raises:
        KeyError: If job_name is not registered
    """
    global _backend
    if _backend is None:
        _backend = get_backend()
    _backend.enqueue(job_name, payload)
