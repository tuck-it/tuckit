from tuckit.core.services.exceptions import InvalidValue


def validate_choice(value: str, choices, field: str) -> None:
    """Raise InvalidValue if `value` is not among the keys of a Django `choices` list."""
    valid = {key for key, _label in choices}
    if value not in valid:
        raise InvalidValue(f"invalid {field}: {value!r} (allowed: {sorted(valid)})")
