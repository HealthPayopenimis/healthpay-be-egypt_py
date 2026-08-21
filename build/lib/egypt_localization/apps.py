from django.apps import AppConfig

MODULE_NAME = "egypt_localization"

DEFAULT_CFG = {
    "currency": "EGP",
    "currency_symbol": "\u062c.\u0645",  # ج.م
    "default_language": "ar",
    "phone_country_code": "+20",
    "fiscal_year_start_month": 7,  # Egyptian fiscal year: 1 July – 30 June
}


class EgyptLocalizationConfig(AppConfig):
    name = MODULE_NAME
    verbose_name = "HealthPay Egypt Localization"

    currency = DEFAULT_CFG["currency"]
    currency_symbol = DEFAULT_CFG["currency_symbol"]
    default_language = DEFAULT_CFG["default_language"]
    phone_country_code = DEFAULT_CFG["phone_country_code"]
    fiscal_year_start_month = DEFAULT_CFG["fiscal_year_start_month"]

    def ready(self):
        from core.models import ModuleConfiguration  # openIMIS core
        cfg = ModuleConfiguration.get_or_default(MODULE_NAME, DEFAULT_CFG)
        for k, v in cfg.items():
            setattr(EgyptLocalizationConfig, k, v)
