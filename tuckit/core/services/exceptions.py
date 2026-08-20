class NotFound(Exception):
    """Raised when an id does not exist or is not visible to the given org."""


class InvalidValue(Exception):
    """Raised when a caller supplies a value outside the allowed set (e.g. a bad status)."""


class LimitReached(Exception):
    """Raised when an org-level plan limit (e.g. a seat cap) would be exceeded."""


class WritesBlocked(Exception):
    """Raised when an org may still read everything but may not write right now.

    Deliberately separate from LimitReached: that one means "you exceeded a
    number", this one means "writing is closed for you at the moment", and the
    two need different words in front of a person. Nothing is hidden or deleted
    when this is raised — reads, exports and the whole history stay available.

    The message IS the product here. It travels out to whoever tried to write,
    including a coding agent over MCP that will relay it to its human, so it has
    to say what happened and what to do about it. A bare status code is the
    failure mode this exception exists to prevent.
    """
