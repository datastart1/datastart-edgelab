from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr

APP_DIR = Path(__file__).resolve().parent
DB_PATH = APP_DIR / "edgelab.db"

app = FastAPI(title="Datastart EdgeLab API", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten later
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

TOKENS: dict[str, dict] = {}
LEMON_SQUEEZY_WEBHOOK_SECRET = os.getenv("LEMON_SQUEEZY_WEBHOOK_SECRET", "").strip()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with closing(_connect()) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                full_name TEXT NOT NULL DEFAULT '',
                subscription_active INTEGER NOT NULL DEFAULT 0,
                plan_name TEXT NOT NULL DEFAULT '',
                lemonsqueezy_customer_id TEXT DEFAULT '',
                lemonsqueezy_subscription_id TEXT DEFAULT '',
                lemonsqueezy_order_id TEXT DEFAULT '',
                lemonsqueezy_license_key TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.commit()

    upsert_user(
        email="demo@datastartedgelab.com",
        password="edgelab123",
        full_name="Demo User",
        subscription_active=True,
        plan_name="Monthly",
    )


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        200_000,
    ).hex()
    return f"{salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, expected = stored.split("$", 1)
    except ValueError:
        return False

    actual = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        200_000,
    ).hex()
    return hmac.compare_digest(actual, expected)


def get_user_by_email(email: str) -> Optional[dict]:
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE lower(email) = lower(?)",
            (email.strip(),),
        ).fetchone()
        return dict(row) if row else None


def upsert_user(
    *,
    email: str,
    password: Optional[str] = None,
    full_name: str = "",
    subscription_active: bool = False,
    plan_name: str = "",
    lemonsqueezy_customer_id: str = "",
    lemonsqueezy_subscription_id: str = "",
    lemonsqueezy_order_id: str = "",
    lemonsqueezy_license_key: str = "",
) -> dict:
    email = email.strip().lower()
    if not email:
        raise ValueError("email is required")

    now = utc_now().isoformat()
    existing = get_user_by_email(email)

    with closing(_connect()) as conn:
        if existing:
            password_hash = existing["password_hash"]
            if password:
                password_hash = hash_password(password)

            conn.execute(
                """
                UPDATE users
                SET password_hash = ?,
                    full_name = ?,
                    subscription_active = ?,
                    plan_name = ?,
                    lemonsqueezy_customer_id = ?,
                    lemonsqueezy_subscription_id = ?,
                    lemonsqueezy_order_id = ?,
                    lemonsqueezy_license_key = ?,
                    updated_at = ?
                WHERE lower(email) = lower(?)
                """,
                (
                    password_hash,
                    full_name or existing.get("full_name", ""),
                    1 if subscription_active else 0,
                    plan_name or existing.get("plan_name", ""),
                    lemonsqueezy_customer_id or existing.get("lemonsqueezy_customer_id", ""),
                    lemonsqueezy_subscription_id or existing.get("lemonsqueezy_subscription_id", ""),
                    lemonsqueezy_order_id or existing.get("lemonsqueezy_order_id", ""),
                    lemonsqueezy_license_key or existing.get("lemonsqueezy_license_key", ""),
                    now,
                    email,
                ),
            )
        else:
            password_hash = hash_password(password or "changeme123")
            conn.execute(
                """
                INSERT INTO users (
                    email, password_hash, full_name, subscription_active, plan_name,
                    lemonsqueezy_customer_id, lemonsqueezy_subscription_id,
                    lemonsqueezy_order_id, lemonsqueezy_license_key,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    email,
                    password_hash,
                    full_name,
                    1 if subscription_active else 0,
                    plan_name,
                    lemonsqueezy_customer_id,
                    lemonsqueezy_subscription_id,
                    lemonsqueezy_order_id,
                    lemonsqueezy_license_key,
                    now,
                    now,
                ),
            )
        conn.commit()

    user = get_user_by_email(email)
    if not user:
        raise RuntimeError("Failed to load saved user")
    return user


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    success: bool
    token: str
    email: EmailStr
    full_name: str
    plan: str


class MeResponse(BaseModel):
    authenticated: bool
    email: EmailStr
    full_name: str
    plan: str
    subscription_active: bool


class SetPasswordRequest(BaseModel):
    email: EmailStr
    password: str


def issue_token(email: str) -> str:
    expires = utc_now() + timedelta(days=7)
    token = f"token-{secrets.token_urlsafe(24)}"
    TOKENS[token] = {"email": email.lower(), "expires": expires}
    return token


def get_user_from_token(token: str) -> Optional[dict]:
    record = TOKENS.get(token)
    if not record:
        return None
    if record["expires"] < utc_now():
        TOKENS.pop(token, None)
        return None
    return get_user_by_email(record["email"])


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/")
def root():
    return {
        "app": "Datastart EdgeLab API",
        "status": "ok",
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health")
def health():
    return {"status": "ok", "app": "Datastart EdgeLab API"}


@app.post("/auth/login", response_model=LoginResponse)
def login(payload: LoginRequest):
    user = get_user_by_email(payload.email)
    if not user or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not bool(user["subscription_active"]):
        raise HTTPException(status_code=403, detail="Subscription is not active")

    token = issue_token(user["email"])
    return LoginResponse(
        success=True,
        token=token,
        email=user["email"],
        full_name=user["full_name"] or user["email"],
        plan=user["plan_name"] or "Unknown",
    )


@app.get("/auth/me", response_model=MeResponse)
def me(authorization: Optional[str] = Header(default=None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")

    token = authorization.replace("Bearer ", "", 1).strip()
    user = get_user_from_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return MeResponse(
        authenticated=True,
        email=user["email"],
        full_name=user["full_name"] or user["email"],
        plan=user["plan_name"] or "Unknown",
        subscription_active=bool(user["subscription_active"]),
    )


@app.post("/auth/set-password")
def set_password(payload: SetPasswordRequest):
    user = get_user_by_email(payload.email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if len(payload.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    updated = upsert_user(
        email=user["email"],
        password=payload.password,
        full_name=user["full_name"],
        subscription_active=bool(user["subscription_active"]),
        plan_name=user["plan_name"],
        lemonsqueezy_customer_id=user["lemonsqueezy_customer_id"],
        lemonsqueezy_subscription_id=user["lemonsqueezy_subscription_id"],
        lemonsqueezy_order_id=user["lemonsqueezy_order_id"],
        lemonsqueezy_license_key=user["lemonsqueezy_license_key"],
    )

    return {"success": True, "email": updated["email"]}


@app.post("/webhooks/lemonsqueezy")
async def lemonsqueezy_webhook(request: Request):
    body = await request.body()

    if LEMON_SQUEEZY_WEBHOOK_SECRET:
        signature = request.headers.get("X-Signature", "")
        digest = hmac.new(
            LEMON_SQUEEZY_WEBHOOK_SECRET.encode("utf-8"),
            body,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(signature, digest):
            raise HTTPException(status_code=401, detail="Invalid webhook signature")

    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON payload: {exc}") from exc

    meta = payload.get("meta", {})
    event_name = meta.get("event_name", "")
    data = payload.get("data", {})
    attributes = data.get("attributes", {}) or {}
    relationships = data.get("relationships", {}) or {}

    custom_data = attributes.get("custom_data", {}) or {}
    email = (
        attributes.get("user_email")
        or attributes.get("customer_email")
        or custom_data.get("email")
        or ""
    ).strip().lower()

    if not email:
        return {"received": True, "ignored": True, "reason": "No email found", "event": event_name}

    full_name = attributes.get("user_name") or attributes.get("customer_name") or ""
    status = (attributes.get("status") or "").lower()

    active_statuses = {"active", "on_trial", "trialing", "paid"}
    inactive_statuses = {"cancelled", "canceled", "expired", "unpaid", "past_due", "paused"}

    subscription_active = True
    if status in inactive_statuses:
        subscription_active = False
    elif status in active_statuses:
        subscription_active = True

    variant_name = attributes.get("variant_name") or attributes.get("product_name") or ""
    customer_id = ""
    subscription_id = ""
    order_id = ""
    license_key = attributes.get("license_key") or ""

    if isinstance(data.get("id"), str):
        if "subscription" in event_name:
            subscription_id = data["id"]
        elif "order" in event_name:
            order_id = data["id"]

    customer_rel = relationships.get("customer", {}).get("data")
    if isinstance(customer_rel, dict):
        customer_id = customer_rel.get("id", "") or ""

    user = upsert_user(
        email=email,
        full_name=full_name,
        subscription_active=subscription_active,
        plan_name=variant_name,
        lemonsqueezy_customer_id=customer_id,
        lemonsqueezy_subscription_id=subscription_id,
        lemonsqueezy_order_id=order_id,
        lemonsqueezy_license_key=license_key,
    )

    return {
        "received": True,
        "event": event_name,
        "email": user["email"],
        "subscription_active": bool(user["subscription_active"]),
    }
