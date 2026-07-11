class NotFound(Exception):
    """Raised when an id does not exist or is not visible to the given workspace."""


class InvalidValue(Exception):
    """Raised when a caller supplies a value outside the allowed set (e.g. a bad status)."""
