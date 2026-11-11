"""Deterministic grading with explicit answer semantics."""

import re
from decimal import Decimal, InvalidOperation


def grade_select_all_answer(
    answer: str, reference: str, options: dict[str, str] | None,
) -> bool:
    """Compare complete label sets; reject empty, duplicate and unknown labels.

    Clients submit comma-separated option keys. Reference answers may also use
    slash, semicolon or pipe separators, as accepted by question validation.
    """
    if not options:
        return False
    valid = {key.strip().casefold() for key in options}

    def labels(value: str) -> set[str] | None:
        parts = [part.strip().casefold() for part in re.split(r"[,/;|]", value)]
        unique = set(parts)
        if not all(parts) or len(unique) != len(parts) or not unique <= valid:
            return None
        return unique

    expected = labels(reference)
    submitted = labels(answer)
    return expected is not None and submitted is not None and submitted == expected


_NUMBER_PATTERN = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")


def parse_numeric_answer(value: str) -> Decimal | None:
    """Parse a finite decimal/scientific scalar, without evaluating expressions."""
    value = value.strip()
    if not value or len(value) > 200 or not _NUMBER_PATTERN.fullmatch(value):
        return None
    try:
        number = Decimal(value)
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def grade_text_answer(answer: str, reference: str, *, numeric: bool = False) -> bool:
    """Use exact numeric equality only when the author explicitly opted in."""
    if numeric:
        submitted = parse_numeric_answer(answer)
        expected = parse_numeric_answer(reference)
        return submitted is not None and expected is not None and submitted == expected
    return answer.strip().lower() == reference.strip().lower()
