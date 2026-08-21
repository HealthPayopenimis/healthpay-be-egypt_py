# HealthPay Payer System — Egypt Localization (`healthpay-be-egypt`)

Backend Django module providing Egypt-specific localization for the HealthPay
Payer System (built on openIMIS, AGPL-3.0).

## Provides

- **National ID (الرقم القومي)** — 14-digit structural validator and decoder
  (century, birth date, governorate code 01–35/88, gender from serial). Attach
  `validate_national_id` to the insuree identifier field. The official check-digit
  algorithm is unpublished; production identity assurance should use the
  Digital Egypt E-KYC verification hook (async task stub in `services.py`, TODO).
- **Governorate seed data** — 27 governorates (Arabic + English + capital),
  mapped onto the openIMIS 4-level hierarchy:
  `Region→Governorate (المحافظة)`, `District→Markaz (المركز)`,
  `Ward→City/Qism (المدينة/القسم)`, `Village→Sheyakha (الشياخة)`.
  Markaz/city/sheyakha levels: load from CAPMAS datasets (follow-up).
- **Arabic language registration** — inserts `ar` with RTL flag into the core
  `Language` register; default new users to `ar`.
- **EGP currency** (`ج.م`), Egyptian fiscal calendar (July–June) for batch runs.
- **Phone validation** — `+20` normalization to E.164, mobile prefixes 010/011/012/015.

## Install (assembly `openimis-be_py` / `healthpay-be_py`)

Add to the module list in `openimis.json`:

```json
{ "name": "egypt_localization", "pip": "healthpay-be-egypt" }
```

Then `python manage.py migrate egypt_localization`.

## Tests

```
pytest egypt_localization/tests
```
