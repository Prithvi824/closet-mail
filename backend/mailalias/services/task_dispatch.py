"""Hand background work to Celery by task name (swappable so tests can capture calls)."""

# 1st party imports
from collections.abc import Callable

Dispatcher = Callable[[str, str], None]


def _celery_dispatch(task_name: str, object_id: str) -> None:
    """Enqueue a task by name (no import of the tasks modules, avoiding a cycle).

    Args:
        task_name: Registered Celery task name.
        object_id: Id argument for the task.
    Returns:
        None.
    """
    from mailalias.tasks.celery_app import celery_app  # deferred: celery app imports settings

    celery_app.send_task(task_name, args=[object_id])


_dispatcher: Dispatcher = _celery_dispatch


def dispatch(task_name: str, object_id: str) -> None:
    """Enqueue one task through the current dispatcher.

    Args:
        task_name: Registered Celery task name.
        object_id: Id argument for the task.
    Returns:
        None.
    """
    _dispatcher(task_name, object_id)


def set_dispatcher(dispatcher: Dispatcher) -> Dispatcher:
    """Replace the dispatcher (tests); returns the previous one.

    Args:
        dispatcher: Callable(task_name, object_id).
    Returns:
        The previous dispatcher.
    """
    global _dispatcher
    previous, _dispatcher = _dispatcher, dispatcher
    return previous
