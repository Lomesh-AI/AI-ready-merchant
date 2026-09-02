import hashlib
import hmac
from datetime import datetime, timezone

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import Mandate
from .util import canonical_json

# Constants for token names (§12).
TOKEN_USER = "DEMO_USER_TOKEN"
TOKEN_AGENT = "AGENT_SERVICE_TOKEN"


def _bearer(authorization: str | None) -> str | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    return authorization[len("Bearer "):]


def require_user(authorization: str | None = Header(None)):
    token = _bearer(authorization)
    if token != settings.DEMO_USER_TOKEN:
        raise HTTPException(status_code=401, detail="invalid user token")
    return "demo-user"


def require_agent(authorization: str | None = Header(None)):
    token = _bearer(authorization)
    if token != settings.AGENT_SERVICE_TOKEN:
        raise HTTPException(status_code=401, detail="invalid agent token")
    return "agent"


def require_user_or_agent(authorization: str | None = Header(None)):
    token = _bearer(authorization)
    if token == settings.DEMO_USER_TOKEN:
        return "demo-user"
    if token == settings.AGENT_SERVICE_TOKEN:
        return "agent"
    raise HTTPException(status_code=401, detail="invalid token")


def verify_webhook_signature(raw_body: bytes, signature: str | None) -> bool:
    """§1: HMAC-SHA256 of RAW body with RAZORPAY_WEBHOOK_SECRET, verified BEFORE parsing."""
    if not signature or not settings.RAZORPAY_WEBHOOK_SECRET:
        return False
    expected = hmac.new(settings.RAZORPAY_WEBHOOK_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def sign_mandate(m: Mandate) -> str:
    """HMAC-SHA256 over canonical mandate fields — §1."""
    payload = canonical_json({
        "mandate_id": str(m.id),
        "user_id": m.user_id,
        "kind": m.kind,
        "max_paise": m.max_paise,
        "categories": m.categories,
        "nonce": m.nonce,
        "expires_at": m.expires_at.astimezone(timezone.utc).isoformat(),
    })
    return hmac.new(settings.MANDATE_SIGNING_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()


def mandate_is_expired(m: Mandate) -> bool:
    return m.expires_at.astimezone(timezone.utc) <= datetime.now(timezone.utc)
