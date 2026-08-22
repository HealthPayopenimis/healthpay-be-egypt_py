"""
Egyptian National ID (الرقم القومي) and phone validation.

National ID format: 14 digits — C YYMMDD GG SSSS X
  C    : century digit (2 = 1900-1999, 3 = 2000-2099)
  YYMMDD: date of birth
  GG   : governorate code at birth (01-35, or 88 = born abroad)
  SSS  : birth serial (odd final serial digit = male, even = female)
  X    : check digit (algorithm not officially published; structural
         validation only unless E-KYC verification is enabled)
"""
import re
from datetime import date

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

GOVERNORATE_CODES = {
    "01": "Cairo", "02": "Alexandria", "03": "Port Said", "04": "Suez",
    "11": "Damietta", "12": "Dakahlia", "13": "Sharqia", "14": "Qalyubia",
    "15": "Kafr El Sheikh", "16": "Gharbia", "17": "Monufia", "18": "Beheira",
    "19": "Ismailia", "21": "Giza", "22": "Beni Suef", "23": "Faiyum",
    "24": "Minya", "25": "Assiut", "26": "Sohag", "27": "Qena",
    "28": "Aswan", "29": "Luxor", "31": "Red Sea", "32": "New Valley",
    "33": "Matrouh", "34": "North Sinai", "35": "South Sinai",
    "88": "Born Abroad",
}

NATIONAL_ID_RE = re.compile(r"^[23]\d{13}$")


def parse_national_id(value: str) -> dict:
    """Validate and decode a 14-digit Egyptian National ID.

    Returns dict with birth_date, governorate_code, governorate, gender.
    Raises ValidationError on structural problems.
    """
    value = (value or "").strip()
    if not re.fullmatch(r"\d{14}", value):
        raise ValidationError(_("National ID must be exactly 14 digits."))
    if not NATIONAL_ID_RE.fullmatch(value):
        raise ValidationError(_("National ID must start with 2 or 3 (century digit)."))

    century = 1900 if value[0] == "2" else 2000
    yy, mm, dd = int(value[1:3]), int(value[3:5]), int(value[5:7])
    try:
        birth_date = date(century + yy, mm, dd)
    except ValueError:
        raise ValidationError(_("National ID contains an invalid birth date."))
    if birth_date > date.today():
        raise ValidationError(_("National ID birth date is in the future."))

    gov = value[7:9]
    if gov not in GOVERNORATE_CODES:
        raise ValidationError(_("National ID contains an invalid governorate code."))

    gender = "M" if int(value[12]) % 2 == 1 else "F"
    return {
        "birth_date": birth_date,
        "governorate_code": gov,
        "governorate": GOVERNORATE_CODES[gov],
        "gender": gender,
    }


def validate_national_id(value: str):
    """Django validator wrapper (attach to the insuree identifier field)."""
    parse_national_id(value)


EG_PHONE_RE = re.compile(r"^(\+20|0020|0)?(1[0125]\d{8}|[23]\d{7,8}|\d{8,9})$")
EG_MOBILE_RE = re.compile(r"^(\+20|0020|0)?1[0125]\d{8}$")


def validate_egyptian_phone(value: str, mobile_only: bool = False):
    value = re.sub(r"[\s\-]", "", value or "")
    pattern = EG_MOBILE_RE if mobile_only else EG_PHONE_RE
    if not pattern.fullmatch(value):
        raise ValidationError(_("Enter a valid Egyptian phone number (+20…)."))


def normalize_egyptian_phone(value: str) -> str:
    """Normalize to E.164 (+20XXXXXXXXXX)."""
    v = re.sub(r"[\s\-]", "", value or "")
    if v.startswith("0020"):
        v = "+20" + v[4:]
    elif v.startswith("0"):
        v = "+20" + v[1:]
    elif not v.startswith("+20"):
        v = "+20" + v
    return v


# --- openIMIS insuree-number validator hook ---------------------------------
# Wired via the `insuree` module config key `insuree_number_validator`
# (be-insuree services.custom_insuree_number_validation imports this by dotted
# path). Returning [] means valid; otherwise a list of
# {"errorCode": int, "message": str}. This is the SERVER-BACKED validation the
# insuree form calls through the insureeNumberValidity GraphQL query, so the
# messages below are what the operator sees next to the field.
#
# Error codes are namespaced in the 9xx range to avoid colliding with
# InsureeConfig's own validation_code_* values.
EG_ERR_LENGTH = 901
EG_ERR_CENTURY = 902
EG_ERR_DATE = 903
EG_ERR_GOVERNORATE = 904
EG_ERR_EMPTY = 905

_AR_MESSAGES = {
    EG_ERR_EMPTY: "الرقم القومي مطلوب.",
    EG_ERR_LENGTH: "الرقم القومي يجب أن يتكون من 14 رقمًا بالضبط.",
    EG_ERR_CENTURY: "الرقم القومي يجب أن يبدأ برقم 2 أو 3 (خانة القرن).",
    EG_ERR_DATE: "تاريخ الميلاد داخل الرقم القومي غير صحيح.",
    EG_ERR_GOVERNORATE: "كود المحافظة داخل الرقم القومي غير صحيح.",
}


def validate_egyptian_national_id_for_insuree(insuree_number):
    """openIMIS-compatible validator: returns [] when valid."""
    value = (insuree_number or "").strip()
    if not value:
        return [{"errorCode": EG_ERR_EMPTY, "message": _AR_MESSAGES[EG_ERR_EMPTY]}]
    if not re.fullmatch(r"\d{14}", value):
        return [{"errorCode": EG_ERR_LENGTH, "message": _AR_MESSAGES[EG_ERR_LENGTH]}]
    if value[0] not in ("2", "3"):
        return [{"errorCode": EG_ERR_CENTURY, "message": _AR_MESSAGES[EG_ERR_CENTURY]}]

    century = 1900 if value[0] == "2" else 2000
    try:
        birth = date(century + int(value[1:3]), int(value[3:5]), int(value[5:7]))
    except ValueError:
        return [{"errorCode": EG_ERR_DATE, "message": _AR_MESSAGES[EG_ERR_DATE]}]
    if birth > date.today():
        return [{"errorCode": EG_ERR_DATE, "message": _AR_MESSAGES[EG_ERR_DATE]}]
    if value[7:9] not in GOVERNORATE_CODES:
        return [{"errorCode": EG_ERR_GOVERNORATE, "message": _AR_MESSAGES[EG_ERR_GOVERNORATE]}]
    return []
