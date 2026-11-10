"""Deterministic grading for select-all answers using the existing label format."""

import re


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
