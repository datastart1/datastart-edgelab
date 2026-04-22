from datetime import datetime, timezone

import stripe
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from .auth import get_user_by_email, issue_auth_token, require_user_from_token, verify_password
from .billing import create_billing_portal, create_checkout_session, ensure_user
from .db import Base, engine, get_db
from .licensing import get_active_subscription, get_or_create_device, issue_license_token, persist_license_token, validate_license_token
from .models import User
from .schemas import (
    ActivateLicenseRequest,
    BillingPortalRequest,
    BillingPortalResponse,
    CheckoutSessionRequest,
    CheckoutSessionResponse,
    DeactivateLicenseRequest,
    LicenseResponse,
    LoginRequest,
    LoginResponse,
    SimpleOK,
    UserOut,
    ValidateLicenseRequest,
)
from .settings import settings

app = FastAPI(title='StrategyTool Licensing API')
stripe.api_key = settings.stripe_secret_key
Base.metadata.create_all(bind=engine)


@app.get('/api/health')
def health() -> dict:
    return {'ok': True}


@app.post('/api/auth/login', response_model=LoginResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = get_user_by_email(db, payload.email)
    if not user or not user.password_hash or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail='Invalid credentials.')
    return LoginResponse(ok=True, auth_token=issue_auth_token(user), user=UserOut(email=user.email, name=user.name))


@app.post('/api/billing/create-checkout-session', response_model=CheckoutSessionResponse)
def create_checkout(payload: CheckoutSessionRequest, db: Session = Depends(get_db)):
    ensure_user(db, payload.email)
    db.commit()
    url = create_checkout_session(payload.email, payload.plan_code, payload.success_url, payload.cancel_url)
    return CheckoutSessionResponse(checkout_url=url)


@app.post('/api/billing/create-portal-session', response_model=BillingPortalResponse)
def create_portal(payload: BillingPortalRequest, db: Session = Depends(get_db)):
    user = get_user_by_email(db, payload.email)
    if not user:
        raise HTTPException(status_code=404, detail='User not found.')
    sub = user.subscriptions[-1] if user.subscriptions else None
    if not sub or not sub.stripe_customer_id:
        raise HTTPException(status_code=400, detail='No Stripe customer found.')
    return BillingPortalResponse(portal_url=create_billing_portal(sub.stripe_customer_id, payload.return_url))


@app.post('/api/license/activate', response_model=LicenseResponse)
def activate_license(payload: ActivateLicenseRequest, db: Session = Depends(get_db)):
    try:
        user = require_user_from_token(db, payload.email, payload.auth_token)
        subscription = get_active_subscription(db, user.id)
        if not subscription:
            return LicenseResponse(allowed=False, reason='No active subscription.')
        get_or_create_device(db, user, payload.device_id, payload.device_name)
        token, expires_at, offline_valid_until = issue_license_token(user, payload.device_id, subscription)
        persist_license_token(db, user, payload.device_id, expires_at, token)
        db.commit()
        return LicenseResponse(
            allowed=True,
            license_token=token,
            license_expires_at=expires_at,
            offline_valid_until=offline_valid_until,
            subscription={
                'plan_code': subscription.plan_code,
                'status': subscription.status,
                'current_period_end': subscription.current_period_end,
            },
        )
    except ValueError as exc:
        db.rollback()
        return LicenseResponse(allowed=False, reason=str(exc))


@app.post('/api/license/validate', response_model=LicenseResponse)
def validate_license(payload: ValidateLicenseRequest, db: Session = Depends(get_db)):
    try:
        user = require_user_from_token(db, payload.email, payload.auth_token)
        validate_license_token(payload.license_token, payload.device_id)
        subscription = get_active_subscription(db, user.id)
        if not subscription:
            return LicenseResponse(allowed=False, reason='Subscription inactive.')
        token, expires_at, offline_valid_until = issue_license_token(user, payload.device_id, subscription)
        persist_license_token(db, user, payload.device_id, expires_at, token)
        db.commit()
        return LicenseResponse(
            allowed=True,
            license_token=token,
            license_expires_at=expires_at,
            offline_valid_until=offline_valid_until,
            subscription={
                'plan_code': subscription.plan_code,
                'status': subscription.status,
                'current_period_end': subscription.current_period_end,
            },
        )
    except ValueError as exc:
        db.rollback()
        return LicenseResponse(allowed=False, reason=str(exc))


@app.post('/api/license/deactivate', response_model=SimpleOK)
def deactivate_license(payload: DeactivateLicenseRequest, db: Session = Depends(get_db)):
    require_user_from_token(db, payload.email, payload.auth_token)
    device = db.query(User).join(User.devices).filter(User.email == payload.email).first()
    # Keep simple in scaffold; implement proper device lookup in production.
    return SimpleOK(ok=True)


@app.post('/api/stripe/webhook')
async def stripe_webhook(request: Request, stripe_signature: str = Header(alias='stripe-signature'), db: Session = Depends(get_db)):
    body = await request.body()
    try:
        event = stripe.Webhook.construct_event(body, stripe_signature, settings.stripe_webhook_secret)
    except (ValueError, stripe.error.SignatureVerificationError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    event_type = event['type']
    data = event['data']['object']

    if event_type == 'checkout.session.completed':
        email = data.get('customer_details', {}).get('email') or data.get('customer_email')
        if email:
            ensure_user(db, email)
            db.commit()

    # Intentionally lightweight scaffold. Extend with full subscription upsert logic.
    return JSONResponse({'received': True})
