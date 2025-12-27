#!/usr/bin/env python
"""Check for config model fields missing from schema."""

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

# Load schema
schema_path = Path("config/schemas/app_config.schema.yaml")
with schema_path.open() as f:
    schema = yaml.safe_load(f)

schema_props = set(schema.get("properties", {}).keys())

# Load SSO config code model to check if it has fields not in schema
import dataclasses

from src.core.auth.sso.config import (
    AuthorizationConfig,
    CaptchaConfig,
    ProviderConfig,
    SSOConfig,
)


# Get fields from dataclasses
def get_dataclass_fields(cls):
    return {f.name for f in dataclasses.fields(cls)}

sso_fields = get_dataclass_fields(SSOConfig)
provider_fields = get_dataclass_fields(ProviderConfig)
auth_fields = get_dataclass_fields(AuthorizationConfig)
captcha_fields = get_dataclass_fields(CaptchaConfig)

print("SSO config model fields:")
for f in sorted(sso_fields):
    print(f"  - {f}")

print("\nSSO schema properties:")
sso_schema_props = set(schema.get("properties", {}).get("sso", {}).get("properties", {}).keys())
for p in sorted(sso_schema_props):
    print(f"  - {p}")

print("\nComparing model vs schema for sso section:")
missing_in_schema = sso_fields - sso_schema_props
missing_in_model = sso_schema_props - sso_fields

if missing_in_schema:
    print(f"\n  Model fields missing from schema: {missing_in_schema}")
if missing_in_model:
    print(f"\n  Schema fields missing from model: {missing_in_model}")
if not missing_in_schema and not missing_in_model:
    print("\n  [OK] All fields match!")

# Check providers schema structure
print("\nChecking providers schema structure...")
providers_schema = schema.get("properties", {}).get("sso", {}).get("properties", {}).get("providers", {})
print(f"  Type: {providers_schema.get('type')}")
print(f"  AdditionalProperties: {providers_schema.get('additionalProperties')}")
if "properties" in providers_schema.get("additionalProperties", {}):
    provider_schema_props = set(providers_schema["additionalProperties"]["properties"].keys())
    print(f"\n  Provider schema properties: {sorted(provider_schema_props)}")
    print(f"\n  Provider model fields: {sorted(provider_fields)}")
    missing_prov_schema = provider_fields - provider_schema_props
    missing_prov_model = provider_schema_props - provider_fields
    if missing_prov_schema:
        print(f"\n  Provider model fields missing from schema: {missing_prov_schema}")
    if missing_prov_model:
        print(f"\n  Provider schema fields missing from model: {missing_prov_model}")
    if not missing_prov_schema and not missing_prov_model:
        print("\n  [OK] All provider fields match!")

# Check authorization schema structure
print("\nChecking authorization schema structure...")
auth_schema = schema.get("properties", {}).get("sso", {}).get("properties", {}).get("authorization", {})
if "properties" in auth_schema:
    auth_schema_props = set(auth_schema["properties"].keys())
    print(f"\n  Authorization schema properties: {sorted(auth_schema_props)}")
    print(f"\n  Authorization model fields: {sorted(auth_fields)}")
    missing_auth_schema = auth_fields - auth_schema_props
    missing_auth_model = auth_schema_props - auth_fields
    if missing_auth_schema:
        print(f"\n  Authorization model fields missing from schema: {missing_auth_schema}")
    if missing_auth_model:
        print(f"\n  Authorization schema fields missing from model: {missing_auth_model}")
    if not missing_auth_schema and not missing_auth_model:
        print("\n  [OK] All authorization fields match!")

# Check captcha schema structure
print("\nChecking captcha schema structure...")
captcha_schema = schema.get("properties", {}).get("sso", {}).get("properties", {}).get("captcha", {})
if "properties" in captcha_schema:
    captcha_schema_props = set(captcha_schema["properties"].keys())
    print(f"\n  Captcha schema properties: {sorted(captcha_schema_props)}")
    print(f"\n  Captcha model fields: {sorted(captcha_fields)}")
    missing_captcha_schema = captcha_fields - captcha_schema_props
    missing_captcha_model = captcha_schema_props - captcha_fields
    if missing_captcha_schema:
        print(f"\n  Captcha model fields missing from schema: {missing_captcha_schema}")
    if missing_captcha_model:
        print(f"\n  Captcha schema fields missing from model: {missing_captcha_model}")
    if not missing_captcha_schema and not missing_captcha_model:
        print("\n  [OK] All captcha fields match!")
