from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from jose import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Device, LicenseToken, Subscription, User
from .settings import settings

ALLOWED_SUBSCRIPTION_STATUSES = {'active', 'trialing'}
MAX_DEVICES = 1


def get_active_subscription(db: Session, user_id: str) -> Subscription | None:
    stmt = (
        select(Subscription)
        .where(Subscription.user_id == user_id)
        .order_by(Subscription.updated_at.desc())
    )
    rows = db.scalars(stmt).all()
    now = datetime.now(timezone.utc)
    for sub in rows:
        if sub.status in ALLOWED_SUBSCRIPTION_STATUSES:
            return sub
        if sub.status == 'canceled' and sub.current_period_end and sub.current_period_end.replace(tzinfo=timezone.utc) > now:
            return sub
    return None


def get_or_create_device(db: Session, user: User, device_id: str, device_name: str | None) -> Device:
    device = db.scalar(
        select(Device).where(Device.user_id == user.id, Device.device_id == device_id)
    )
    if device:
        device.last_seen_at = datetime.utcnow()
        if device_name:
            device.device_name = device_name
        return device

    active_devices = db.scalars(
        select(Device).where(Device.user_id == user.id, Device.status == 'active')
    ).all()
    if len(active_devices) >= MAX_DEVICES:
        raise ValueError('Device limit reached.')

    device = Device(user_id=user.id, device_id=device_id, device_name=device_name, status='active')
    db.add(device)
    return device


def issue_license_token(user: User, device_id: str, subscription: Subscription) -> tuple[str, datetime, datetime]:
    issued_at = datetime.now(timezone.utc)
    expires_at = issued_at + timedelta(hours=settings.license_token_ttl_hours)
    offline_valid_until = issued_at + timedelta(days=settings.offline_grace_days)
    jti = str(uuid.uuid4())

    payload = {
        'sub': user.id,
        'email': user.email,
        'device_id': device_id,
        'plan_code': subscription.plan_code,
        'subscription_status': subscription.status,
        'exp': expires_at,
        'iat': issued_at,
        'jti': jti,
        'type': 'license',
    }
    token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return token, expires_at, offline_valid_until


def persist_license_token(db: Session, user: User, device_id: str, expires_at: datetime, token: str) -> None:
    payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    record = LicenseToken(
        user_id=user.id,
        device_id=device_id,
        jti=payload['jti'],
        issued_at=datetime.fromtimestamp(payload['iat'], tz=timezone.utc) if isinstance(payload['iat'], (int, float)) else payload['iat'],
        expires_at=expires_at,
        revoked=False,
    )
    db.add(record)


def validate_license_token(token: str, device_id: str) -> dict:
    payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    if payload.get('device_id') != device_id:
        raise ValueError('License token does not match this device.')
    return payload
