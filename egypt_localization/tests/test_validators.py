"""Standalone tests for the National ID parser (run with pytest)."""
import pytest
from django.core.exceptions import ValidationError

from egypt_localization.validators import (
    parse_national_id, validate_egyptian_phone, normalize_egyptian_phone,
)


def test_valid_national_id_decodes():
    info = parse_national_id("29001011234567")  # 1990-01-01, Cairo-ish serial
    assert info["birth_date"].year == 1990
    assert info["governorate_code"] == "12"


def test_rejects_wrong_length():
    with pytest.raises(ValidationError):
        parse_national_id("12345")


def test_rejects_bad_century():
    with pytest.raises(ValidationError):
        parse_national_id("19001011234567")


def test_rejects_invalid_date():
    with pytest.raises(ValidationError):
        parse_national_id("29013991234567")


def test_gender_from_serial():
    assert parse_national_id("30001010112311")["gender"] == "M"
    assert parse_national_id("30001010112321")["gender"] == "F"


def test_phone_normalization():
    assert normalize_egyptian_phone("01012345678") == "+201012345678"
    assert normalize_egyptian_phone("0020 101 234 5678") == "+201012345678"


def test_mobile_validation():
    validate_egyptian_phone("+201012345678", mobile_only=True)
    with pytest.raises(ValidationError):
        validate_egyptian_phone("+15551234567", mobile_only=True)
