"""Retry decorator for transient failures."""

from __future__ import annotations

import time
from functools import wraps
from typing import Any, Callable, TypeVar

from app.utils.logging import get_logger

logger = get_logger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


def with_retry(
    attempts: int = 3,
    delay: float = 2.0,
    exceptions: tuple[type[Exception], ...] = (Exception,),
) -> Callable[[F], F]:
    """Retry a function on failure with exponential backoff."""

    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exc: Exception | None = None
            for attempt in range(1, attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    if attempt < attempts:
                        wait = delay * (2 ** (attempt - 1))
                        logger.warning(
                            "%s failed (attempt %d/%d): %s. Retrying in %.1fs...",
                            func.__name__,
                            attempt,
                            attempts,
                            exc,
                            wait,
                        )
                        time.sleep(wait)
                    else:
                        logger.error(
                            "%s failed after %d attempts: %s",
                            func.__name__,
                            attempts,
                            exc,
                        )
            raise last_exc  # type: ignore[misc]

        return wrapper  # type: ignore[return-value]

    return decorator
