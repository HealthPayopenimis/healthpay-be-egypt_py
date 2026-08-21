"""
URL contract stub.

The openIMIS assembly (openimisurls.py) auto-registers
`path('<SITE_ROOT><module>/', include('<module>.urls'))` for EVERY module in
openimis.json, with no try/except and no opt-out — so a urls submodule is
mandatory even for modules that expose no endpoints. This module provides
validators, seed migrations, and configuration only.
"""
urlpatterns = []
