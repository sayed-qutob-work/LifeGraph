"""Validation helpers and domain error types for LifeGraph.

Provides validators for:
- Storage labels (1–200 characters, parser-produced)
- Manual labels (trimmed 1–100 characters, user-entered via Graph_Editor)
- Attribute sets (≤50 entries, keys 1–255 chars, values 1–255 chars)
- Event date (YYYY-MM-DD format AND real calendar date)

Requirements: 5.2, 6.1, 6.3, 8.1, 8.4, 8.5
"""

from __future__ import annotations

import datetime
import re


# ---------------------------------------------------------------------------
# Domain error types
# ---------------------------------------------------------------------------


class ValidationError(Exception):
    """Base class for all validation errors in LifeGraph."""

    pass


class LabelValidationError(ValidationError):
    """Raised when a node label fails validation.

    Covers both storage labels (1–200 chars) and manual labels (trimmed 1–100 chars).
    """

    pass


class DateValidationError(ValidationError):
    """Raised when an Event date attribute is not a valid YYYY-MM-DD calendar date."""

    pass


class AttributeValidationError(ValidationError):
    """Raised when a node's attribute set violates bounds.

    Covers: too many entries (>50), key too short/long, value too short/long.
    """

    pass


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

STORAGE_LABEL_MIN = 1
STORAGE_LABEL_MAX = 200

MANUAL_LABEL_MIN = 1
MANUAL_LABEL_MAX = 100

ATTRIBUTE_MAX_ENTRIES = 50
ATTRIBUTE_KEY_MIN = 1
ATTRIBUTE_KEY_MAX = 255
ATTRIBUTE_VALUE_MIN = 1
ATTRIBUTE_VALUE_MAX = 255

# Strict YYYY-MM-DD format pattern
_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------


def validate_storage_label(label: str) -> str:
    """Validate a storage label (parser-produced): must be 1–200 characters.

    Args:
        label: The label string to validate.

    Returns:
        The label unchanged if valid.

    Raises:
        LabelValidationError: If the label is empty or exceeds 200 characters.
    """
    length = len(label)
    if length < STORAGE_LABEL_MIN:
        raise LabelValidationError(
            f"Storage label must be at least {STORAGE_LABEL_MIN} character(s); "
            f"got empty string."
        )
    if length > STORAGE_LABEL_MAX:
        raise LabelValidationError(
            f"Storage label must be at most {STORAGE_LABEL_MAX} characters; "
            f"got {length}."
        )
    return label


def validate_manual_label(label: str) -> str:
    """Validate a manual label (user-entered via Graph_Editor).

    The label is trimmed of leading/trailing whitespace first, then checked
    for 1–100 characters.

    Args:
        label: The raw label string from user input.

    Returns:
        The trimmed label if valid.

    Raises:
        LabelValidationError: If the trimmed label is empty or exceeds 100 characters.
    """
    trimmed = label.strip()
    length = len(trimmed)
    if length < MANUAL_LABEL_MIN:
        raise LabelValidationError(
            "A label is required; the submitted label is empty or contains only whitespace."
        )
    if length > MANUAL_LABEL_MAX:
        raise LabelValidationError(
            f"Manual label must be at most {MANUAL_LABEL_MAX} characters after trimming; "
            f"got {length}."
        )
    return trimmed


def validate_attributes(attributes: dict[str, str]) -> dict[str, str]:
    """Validate a node's attribute set.

    Rules:
    - At most 50 entries
    - Each key: 1–255 characters
    - Each value: 1–255 characters

    Args:
        attributes: The attribute dictionary to validate.

    Returns:
        The attributes unchanged if valid.

    Raises:
        AttributeValidationError: If any bound is violated.
    """
    if len(attributes) > ATTRIBUTE_MAX_ENTRIES:
        raise AttributeValidationError(
            f"Attribute set must have at most {ATTRIBUTE_MAX_ENTRIES} entries; "
            f"got {len(attributes)}."
        )

    for key, value in attributes.items():
        key_len = len(key)
        if key_len < ATTRIBUTE_KEY_MIN:
            raise AttributeValidationError(
                f"Attribute key must be at least {ATTRIBUTE_KEY_MIN} character(s); "
                f"got empty key."
            )
        if key_len > ATTRIBUTE_KEY_MAX:
            raise AttributeValidationError(
                f"Attribute key must be at most {ATTRIBUTE_KEY_MAX} characters; "
                f"got {key_len} for key '{key[:50]}...'."
            )

        val_len = len(value)
        if val_len < ATTRIBUTE_VALUE_MIN:
            raise AttributeValidationError(
                f"Attribute value must be at least {ATTRIBUTE_VALUE_MIN} character(s); "
                f"got empty value for key '{key}'."
            )
        if val_len > ATTRIBUTE_VALUE_MAX:
            raise AttributeValidationError(
                f"Attribute value must be at most {ATTRIBUTE_VALUE_MAX} characters; "
                f"got {val_len} for key '{key}'."
            )

    return attributes


def validate_event_date(date_str: str) -> str:
    """Validate an Event node's date attribute.

    The value must be in YYYY-MM-DD format AND represent a real calendar date.
    For example, '2025-02-30' is rejected because February 30 does not exist.

    Args:
        date_str: The date string to validate.

    Returns:
        The date string unchanged if valid.

    Raises:
        DateValidationError: If the format is wrong or the date is not a real
            calendar date.
    """
    if not _DATE_PATTERN.match(date_str):
        raise DateValidationError(
            f"Event date must be in YYYY-MM-DD format; got '{date_str}'."
        )

    # Parse to verify it's a real calendar date
    try:
        datetime.date.fromisoformat(date_str)
    except ValueError:
        raise DateValidationError(
            f"Event date '{date_str}' is not a valid calendar date."
        )

    return date_str
