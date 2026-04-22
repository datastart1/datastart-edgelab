import stripe
from fastapi import HTTPException
from sqlalchemy.orm import Session

from .auth import get_user_by_email
from .models import Subscription, User
from .settings import settings

stripe.api_key = settings.stripe_secret_key


PLAN_TO_PRICE = {
    'strategy_builder_monthly': settings.stripe_price_monthly,
    'strategy_builder_yearly': settings.stripe_price_yearly,
}


def ensure_user(db: Session, email: str) -> User:
    user = get_user_by_email(db, email)
    if user:
        return user
    user = User(email=email.lower().strip())
    db.add(user)
    db.flush()
    return user


def create_checkout_session(email: str, plan_code: str, success_url: str | None, cancel_url: str | None) -> str:
    price_id = PLAN_TO_PRICE.get(plan_code)
    if not price_id:
        raise HTTPException(status_code=400, detail='Unknown plan_code.')

    session = stripe.checkout.Session.create(
        mode='subscription',
        customer_email=email,
        line_items=[{'price': price_id, 'quantity': 1}],
        success_url=success_url or settings.app_success_url,
        cancel_url=cancel_url or settings.app_cancel_url,
        allow_promotion_codes=True,
    )
    return session.url


def create_billing_portal(customer_id: str, return_url: str | None) -> str:
    session = stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=return_url or settings.billing_return_url,
    )
    return session.url


def upsert_subscription_from_stripe(db: Session, stripe_customer_id: str, stripe_subscription_id: str, plan_code: str, status: str, current_period_end, cancel_at_period_end: bool) -> None:
    sub = db.query(Subscription).filter(Subscription.stripe_subscription_id == stripe_subscription_id).one_or_none()
    if sub:
        sub.plan_code = plan_code
        sub.status = status
        sub.current_period_end = current_period_end
        sub.cancel_at_period_end = cancel_at_period_end
        return

    user = db.query(User).filter(User.email == db.info.get('stripe_customer_email')).one_or_none()
    if not user:
        return
    db.add(
        Subscription(
            user_id=user.id,
            stripe_customer_id=stripe_customer_id,
            stripe_subscription_id=stripe_subscription_id,
            plan_code=plan_code,
            status=status,
            current_period_end=current_period_end,
            cancel_at_period_end=cancel_at_period_end,
        )
    )
