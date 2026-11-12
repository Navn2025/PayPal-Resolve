"""Shared pure input validation; no storage or provider access."""

import re

EMAIL = re.compile(
    r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+"
)


def normalize_email(value):
    if (
        not isinstance(value, str)
        or len(value) > 254
        or not EMAIL.fullmatch(value.strip())
    ):
        raise ValueError("Enter a valid email address")
    return value.strip().lower()
