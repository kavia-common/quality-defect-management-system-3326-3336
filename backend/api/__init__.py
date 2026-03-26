"""
API app package.

This module ensures Django uses ApiConfig so that app startup hooks (like auto-seeding
demo data when the DB is empty) run reliably.
"""

default_app_config = "api.apps.ApiConfig"
