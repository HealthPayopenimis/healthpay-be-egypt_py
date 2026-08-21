from setuptools import setup, find_packages

setup(
    name="healthpay-be-egypt",
    version="1.0.0",
    description="HealthPay Payer System - Egypt localization: National ID, governorates, EGP, phone validation",
    license="AGPL-3.0-only",
    packages=find_packages(),
    include_package_data=True,
    package_data={"egypt_localization": ["fixtures/*.json"]},
    install_requires=["django"],
)
