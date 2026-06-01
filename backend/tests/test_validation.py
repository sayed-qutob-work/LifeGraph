"""Tests for the validation helpers and domain error types."""

import pytest

from lifegraph.validation import (
    AttributeValidationError,
    DateValidationError,
    LabelValidationError,
    ValidationError,
    validate_attributes,
    validate_event_date,
    validate_manual_label,
    validate_storage_label,
)


# ---------------------------------------------------------------------------
# Error type hierarchy
# ---------------------------------------------------------------------------


class TestErrorTypes:
    def test_label_error_is_validation_error(self):
        assert issubclass(LabelValidationError, ValidationError)

    def test_date_error_is_validation_error(self):
        assert issubclass(DateValidationError, ValidationError)

    def test_attribute_error_is_validation_error(self):
        assert issubclass(AttributeValidationError, ValidationError)

    def test_validation_error_is_exception(self):
        assert issubclass(ValidationError, Exception)


# ---------------------------------------------------------------------------
# validate_storage_label
# ---------------------------------------------------------------------------


class TestValidateStorageLabel:
    def test_valid_single_char(self):
        assert validate_storage_label("A") == "A"

    def test_valid_200_chars(self):
        label = "x" * 200
        assert validate_storage_label(label) == label

    def test_valid_normal_label(self):
        assert validate_storage_label("Guitar Practice") == "Guitar Practice"

    def test_empty_string_raises(self):
        with pytest.raises(LabelValidationError, match="at least"):
            validate_storage_label("")

    def test_201_chars_raises(self):
        with pytest.raises(LabelValidationError, match="at most 200"):
            validate_storage_label("x" * 201)

    def test_very_long_label_raises(self):
        with pytest.raises(LabelValidationError):
            validate_storage_label("a" * 1000)


# ---------------------------------------------------------------------------
# validate_manual_label
# ---------------------------------------------------------------------------


class TestValidateManualLabel:
    def test_valid_single_char(self):
        assert validate_manual_label("A") == "A"

    def test_valid_100_chars(self):
        label = "y" * 100
        assert validate_manual_label(label) == label

    def test_trims_whitespace(self):
        assert validate_manual_label("  Hello World  ") == "Hello World"

    def test_empty_string_raises(self):
        with pytest.raises(LabelValidationError, match="required"):
            validate_manual_label("")

    def test_whitespace_only_raises(self):
        with pytest.raises(LabelValidationError, match="required"):
            validate_manual_label("   \t\n  ")

    def test_101_chars_after_trim_raises(self):
        with pytest.raises(LabelValidationError, match="at most 100"):
            validate_manual_label("z" * 101)

    def test_101_chars_with_surrounding_whitespace_raises(self):
        # 101 non-space chars + whitespace padding
        with pytest.raises(LabelValidationError, match="at most 100"):
            validate_manual_label("  " + "a" * 101 + "  ")

    def test_100_chars_with_whitespace_passes(self):
        # 100 non-space chars + whitespace padding should pass
        result = validate_manual_label("  " + "b" * 100 + "  ")
        assert result == "b" * 100


# ---------------------------------------------------------------------------
# validate_attributes
# ---------------------------------------------------------------------------


class TestValidateAttributes:
    def test_empty_attributes_valid(self):
        assert validate_attributes({}) == {}

    def test_single_entry_valid(self):
        attrs = {"date": "2025-06-15"}
        assert validate_attributes(attrs) == attrs

    def test_50_entries_valid(self):
        attrs = {f"key{i}": f"value{i}" for i in range(50)}
        assert validate_attributes(attrs) == attrs

    def test_51_entries_raises(self):
        attrs = {f"key{i}": f"value{i}" for i in range(51)}
        with pytest.raises(AttributeValidationError, match="at most 50"):
            validate_attributes(attrs)

    def test_key_255_chars_valid(self):
        attrs = {"k" * 255: "value"}
        assert validate_attributes(attrs) == attrs

    def test_key_256_chars_raises(self):
        with pytest.raises(AttributeValidationError, match="key must be at most 255"):
            validate_attributes({"k" * 256: "value"})

    def test_empty_key_raises(self):
        with pytest.raises(AttributeValidationError, match="key must be at least"):
            validate_attributes({"": "value"})

    def test_value_255_chars_valid(self):
        attrs = {"key": "v" * 255}
        assert validate_attributes(attrs) == attrs

    def test_value_256_chars_raises(self):
        with pytest.raises(AttributeValidationError, match="value must be at most 255"):
            validate_attributes({"key": "v" * 256})

    def test_empty_value_raises(self):
        with pytest.raises(AttributeValidationError, match="value must be at least"):
            validate_attributes({"key": ""})

    def test_multiple_valid_entries(self):
        attrs = {"name": "Alice", "role": "Developer", "level": "Senior"}
        assert validate_attributes(attrs) == attrs


# ---------------------------------------------------------------------------
# validate_event_date
# ---------------------------------------------------------------------------


class TestValidateEventDate:
    def test_valid_date(self):
        assert validate_event_date("2025-06-15") == "2025-06-15"

    def test_valid_leap_year_date(self):
        assert validate_event_date("2024-02-29") == "2024-02-29"

    def test_valid_jan_31(self):
        assert validate_event_date("2025-01-31") == "2025-01-31"

    def test_valid_dec_31(self):
        assert validate_event_date("2025-12-31") == "2025-12-31"

    def test_invalid_feb_30(self):
        with pytest.raises(DateValidationError, match="not a valid calendar date"):
            validate_event_date("2025-02-30")

    def test_invalid_feb_29_non_leap(self):
        with pytest.raises(DateValidationError, match="not a valid calendar date"):
            validate_event_date("2025-02-29")

    def test_invalid_month_13(self):
        with pytest.raises(DateValidationError, match="not a valid calendar date"):
            validate_event_date("2025-13-01")

    def test_invalid_month_00(self):
        with pytest.raises(DateValidationError, match="not a valid calendar date"):
            validate_event_date("2025-00-15")

    def test_invalid_day_00(self):
        with pytest.raises(DateValidationError, match="not a valid calendar date"):
            validate_event_date("2025-01-00")

    def test_invalid_day_32(self):
        with pytest.raises(DateValidationError, match="not a valid calendar date"):
            validate_event_date("2025-01-32")

    def test_wrong_format_slash(self):
        with pytest.raises(DateValidationError, match="YYYY-MM-DD format"):
            validate_event_date("2025/06/15")

    def test_wrong_format_no_separators(self):
        with pytest.raises(DateValidationError, match="YYYY-MM-DD format"):
            validate_event_date("20250615")

    def test_wrong_format_short_year(self):
        with pytest.raises(DateValidationError, match="YYYY-MM-DD format"):
            validate_event_date("25-06-15")

    def test_wrong_format_text(self):
        with pytest.raises(DateValidationError, match="YYYY-MM-DD format"):
            validate_event_date("June 15, 2025")

    def test_empty_string(self):
        with pytest.raises(DateValidationError, match="YYYY-MM-DD format"):
            validate_event_date("")

    def test_wrong_format_extra_chars(self):
        with pytest.raises(DateValidationError, match="YYYY-MM-DD format"):
            validate_event_date("2025-06-15T00:00:00")

    def test_apr_31_invalid(self):
        with pytest.raises(DateValidationError, match="not a valid calendar date"):
            validate_event_date("2025-04-31")

    def test_jun_30_valid(self):
        assert validate_event_date("2025-06-30") == "2025-06-30"

    def test_jun_31_invalid(self):
        with pytest.raises(DateValidationError, match="not a valid calendar date"):
            validate_event_date("2025-06-31")
