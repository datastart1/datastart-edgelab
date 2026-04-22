from datetime import datetime, timedelta, timezone

from jose import jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import User
from .settings import settings

pwd_context = CryptContext(schemes=['bcrypt'], deprecated='auto')


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def issue_auth_token(user: User) -> str:
    payload = {
        'sub': user.id,
        'email': user.email,
        'exp': datetime.now(timezone.utc) + timedelta(days=7),
        'type': 'auth',
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_auth_token(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == email.lower().strip()))


def require_user_from_token(db: Session, email: str, token: str) -> User:
    payload = decode_auth_token(token)
    if payload.get('email') != email.lower().strip():
        raise ValueError('Email does not match token.')
    user = get_user_by_email(db, email)
    if not user:
        raise ValueError('User not found.')
    return user
