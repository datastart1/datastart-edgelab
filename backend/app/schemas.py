from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)


class UserOut(BaseModel):
    email: EmailStr
    name: str | None = None


class LoginResponse(BaseModel):
    ok: bool
    auth_token: str
    user: UserOut


class CheckoutSessionRequest(BaseModel):
    email: EmailStr
    plan_code: Literal['strategy_builder_monthly', 'strategy_builder_yearly']
    success_url: str | None = None
    cancel_url: str | None = None


class CheckoutSessionResponse(BaseModel):
    checkout_url: str


class BillingPortalRequest(BaseModel):
    email: EmailStr
    return_url: str | None = None


class BillingPortalResponse(BaseModel):
    portal_url: str


class ActivateLicenseRequest(BaseModel):
    email: EmailStr
    auth_token: str
    device_id: str
    device_name: str | None = None
    app_version: str


class ValidateLicenseRequest(BaseModel):
    email: EmailStr
    auth_token: str
    device_id: str
    license_token: str
    app_version: str


class DeactivateLicenseRequest(BaseModel):
    email: EmailStr
    auth_token: str
    device_id: str


class SubscriptionOut(BaseModel):
    plan_code: str
    status: str
    current_period_end: datetime | None = None


class LicenseResponse(BaseModel):
    allowed: bool
    reason: str | None = None
    license_token: str | None = None
    license_expires_at: datetime | None = None
    offline_valid_until: datetime | None = None
    subscription: SubscriptionOut | None = None


class SimpleOK(BaseModel):
    ok: bool
