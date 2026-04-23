from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr

app = FastAPI(title="Datastart EdgeLab API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten this later
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Temporary in-memory user store
DEMO_USER = {
    "email": "demo@datastartedgelab.com",
    "password": "edgelab123",
    "full_name": "Demo User",
    "plan": "Monthly",
    "subscription_active": True,
}

TOKENS: dict[str, dict] = {}


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


def _issue_token(email: str) -> str:
    expires = datetime.now(timezone.utc) + timedelta(days=7)
    token = f"token-{email}-{int(expires.timestamp())}"
    TOKENS[token] = {"email": email, "expires": expires}
    return token


def _get_user_from_token(token: str) -> Optional[dict]:
    record = TOKENS.get(token)
    if not record:
        return None
    if record["expires"] < datetime.now(timezone.utc):
        TOKENS.pop(token, None)
        return None
    if record["email"] == DEMO_USER["email"]:
        return DEMO_USER
    return None


@app.get("/health")
def health():
    return {"status": "ok", "app": "Datastart EdgeLab API"}


@app.post("/auth/login", response_model=LoginResponse)
def login(payload: LoginRequest):
    if (
        payload.email.lower() != DEMO_USER["email"].lower()
        or payload.password != DEMO_USER["password"]
    ):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = _issue_token(DEMO_USER["email"])
    return LoginResponse(
        success=True,
        token=token,
        email=DEMO_USER["email"],
        full_name=DEMO_USER["full_name"],
        plan=DEMO_USER["plan"],
    )


@app.get("/auth/me", response_model=MeResponse)
def me(authorization: Optional[str] = Header(default=None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")

    token = authorization.replace("Bearer ", "", 1).strip()
    user = _get_user_from_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return MeResponse(
        authenticated=True,
        email=user["email"],
        full_name=user["full_name"],
        plan=user["plan"],
        subscription_active=user["subscription_active"],
    )