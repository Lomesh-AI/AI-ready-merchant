import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..ledger import append_entry
from ..models import Cart, Mandate
from ..security import (mandate_is_expired, require_agent, require_user,
                        sign_mandate)
from ..routers.carts import _load_items
from ..util import cart_hash

router = APIRouter()


class Scope(BaseModel):
    max_paise: int
    categories: list[str] = []
    ttl_minutes: int = 10


class MandateRequest(BaseModel):
    cart_id: uuid.UUID | None = None
    scope: Scope


class MandateOut(BaseModel):
    mandate_id: str
    status: str
    expires_at: datetime | None = None
    approval_url: str | None = None


@router.post("/v1/mandates/request")
def request_mandate(body: MandateRequest, db: Session = Depends(get_db),
                    _=Depends(require_agent)):
    m = Mandate(
        kind="INTENT", status="PENDING",
        max_paise=body.scope.max_paise,
        categories=body.scope.categories or None,
        cart_id=body.cart_id,
        nonce=secrets.token_hex(16),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=body.scope.ttl_minutes),
    )
    db.add(m)
    append_entry(db, actor="agent", action_type="MANDATE_REQUESTED",
                 mandate_id=m.id, payload={"max_paise": m.max_paise, "categories": m.categories})
    db.commit()
    from ..config import settings
    base = settings.PUBLIC_BASE_URL_TUNNEL or settings.PUBLIC_BASE_URL
    return {"mandate_id": str(m.id), "approval_url": f"{base}/v1/mandates/{m.id}/approve",
            "status": "PENDING"}


def _activate(db: Session, m: Mandate) -> Mandate:
    if m.status != "PENDING":
        raise HTTPException(409, f"mandate not PENDING (status={m.status})")
    if mandate_is_expired(m):
        m.status = "EXPIRED"
        append_entry(db, actor="merchant_system", action_type="MANDATE_EXPIRED",
                     mandate_id=m.id, decision="REJECT", reason="expired before approval")
        db.commit()
        raise HTTPException(410, "mandate expired")
    m.signature = sign_mandate(m)
    m.status = "ACTIVE"
    return m


@router.post("/v1/mandates/{mandate_id}/approve")
def approve(mandate_id: uuid.UUID, db: Session = Depends(get_db),
            _=Depends(require_user)):
    m = db.get(Mandate, mandate_id)
    if not m:
        raise HTTPException(404, "mandate not found")
    _activate(db, m)
    append_entry(db, actor="user", action_type="MANDATE_GRANTED", mandate_id=m.id,
                 decision="ALLOW", reason="user approved intent mandate",
                 payload={"max_paise": m.max_paise, "categories": m.categories})
    db.commit()
    return {"status": "ACTIVE", "mandate_id": str(m.id), "expires_at": m.expires_at}


@router.get("/v1/mandates/{mandate_id}")
def get_mandate(mandate_id: uuid.UUID, db: Session = Depends(get_db),
                _=Depends(require_agent)):
    m = db.get(Mandate, mandate_id)
    if not m:
        raise HTTPException(404, "mandate not found")
    if m.status == "ACTIVE" and mandate_is_expired(m):
        m.status = "EXPIRED"
        append_entry(db, actor="merchant_system", action_type="MANDATE_EXPIRED",
                     mandate_id=m.id, decision="REJECT", reason="expired")
        db.commit()
    return {"mandate_id": str(m.id), "status": m.status, "max_paise": m.max_paise,
            "categories": m.categories, "expires_at": m.expires_at,
            "signature": m.signature if m.status == "ACTIVE" else None}


@router.post("/v1/mandates/cart/{cart_id}/approve")
def approve_cart(cart_id: uuid.UUID, db: Session = Depends(get_db),
                 _=Depends(require_user)):
    """Step-up: issues CART mandate bound to cart_hash — §5."""
    cart = db.get(Cart, cart_id)
    if not cart:
        raise HTTPException(404, "cart not found")
    items = _load_items(db, cart_id)
    total = sum(i["qty"] * i["unit_price_paise"] for i in items)
    m = Mandate(
        kind="CART", status="ACTIVE", cart_id=cart_id,
        cart_hash=cart_hash(items), max_paise=total,
        categories=sorted({i["category"] for i in items}) or None,
        nonce=secrets.token_hex(16),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        signature="",
    )
    m.signature = sign_mandate(m)
    db.add(m)
    append_entry(db, actor="user", action_type="CART_MANDATE_GRANTED",
                 mandate_id=m.id, checkout_id=None,
                 decision="ALLOW", reason="user approved cart (step-up)",
                 payload={"cart_id": str(cart_id), "cart_hash": m.cart_hash, "total_paise": total})
    db.commit()
    return {"status": "ACTIVE", "mandate_id": str(m.id), "cart_hash": m.cart_hash,
            "expires_at": m.expires_at}
