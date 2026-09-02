from fastapi import Header
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import IdempotencyKey


class ReplayResponse(Exception):
    """Raised when an Idempotency-Key is replayed; carries the original result — §1."""

    def __init__(self, response: dict):
        self.response = response


def require_idempotency_key(idempotency_key: str | None = Header(None)) -> str:
    if not idempotency_key:
        raise ValueError("Idempotency-Key header required for money mutations — §1")
    return idempotency_key


def begin(db: Session, key: str) -> IdempotencyKey | None:
    """Reserve the key; raises ReplayResponse if already used."""
    existing = db.get(IdempotencyKey, key)
    if existing:
        raise ReplayResponse(existing.response_json)
    db.add(IdempotencyKey(key=key, response_json={}))
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = db.get(IdempotencyKey, key)
        raise ReplayResponse(existing.response_json if existing else {})
    return None


def complete(db: Session, key: str, response: dict):
    row = db.get(IdempotencyKey, key)
    if row:
        row.response_json = response
