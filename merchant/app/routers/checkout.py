import asyncio
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..gates import evaluate
from ..idempotency import ReplayResponse, begin, complete, require_idempotency_key
from ..ledger import append_entry
from ..models import (Cart, CartItem, Checkout, Mandate, PaymentAttempt, Product,
                      DemoSession)
from ..razorpay_client import client as rp_client
from ..security import require_agent, require_user, require_user_or_agent
from ..util import cart_hash
from .carts import _load_items

from .webhooks import verify_on_timeout

router = APIRouter()


class ProposeIn(BaseModel):
    cart_id: uuid.UUID
    mandate_id: uuid.UUID
    rationale: str  # §5: REQUIRED


def _create_order(db: Session, co: Checkout, attempt_no: int, idem_key: str | None = None):
    key = idem_key or f"order-{co.id}-{attempt_no}"
    order = rp_client().order.create(
        data={"amount": co.total_paise, "currency": "INR", "receipt": str(co.id)},
        # razorpay SDK has no per-call idempotency; our payment_attempts UNIQUE key enforces §1.
    )
    db.add(PaymentAttempt(checkout_id=co.id, razorpay_order_id=order["id"],
                          idempotency_key=key, attempt_no=attempt_no))
    co.razorpay_order_id = order["id"]
    co.status = "AWAITING_PAYMENT"
    append_entry(db, actor="merchant_system", action_type="ORDER_CREATED",
                 checkout_id=co.id, decision="ALLOW",
                 payload={"razorpay_order_id": order["id"], "amount_paise": co.total_paise,
                          "attempt_no": attempt_no})
    return order


def _user_action(co: Checkout) -> dict | None:
    if co.status == "AWAITING_PAYMENT" and co.razorpay_order_id:
        return {"type": "razorpay_checkout", "order_id": co.razorpay_order_id,
                "key_id": settings.RAZORPAY_KEY_ID, "amount_paise": co.total_paise}
    if co.status == "FALLBACK_LINK_ISSUED" and co.razorpay_payment_link_id:
        return {"type": "payment_link", "url": co.user_action_url or ""}
    return None


@router.post("/v1/checkout/propose")
async def propose(body: ProposeIn, db: Session = Depends(get_db),
            idempotency_key: str = Depends(require_idempotency_key),
            _=Depends(require_agent)):
    if not body.rationale.strip():
        raise HTTPException(422, "rationale is required — §5")
    try:
        begin(db, idempotency_key)
    except ReplayResponse as r:
        return r.response  # §1: replay returns the original result

    mandate = db.get(Mandate, body.mandate_id)
    cart = db.get(Cart, body.cart_id)
    if not mandate or not cart:
        db.commit()
        raise HTTPException(404, "mandate or cart not found")
    items = _load_items(db, body.cart_id)
    if not items:
        db.commit()
        raise HTTPException(422, "cart empty")
    total = sum(i["qty"] * i["unit_price_paise"] for i in items)
    assert isinstance(total, int)
    ch = cart_hash(items)
    categories = sorted({i["category"] for i in items})

    co = Checkout(cart_id=body.cart_id, mandate_id=body.mandate_id, total_paise=total,
                  cart_hash=ch, status="PROPOSED", rationale=body.rationale)
    db.add(co)
    append_entry(db, actor="agent", action_type="CHECKOUT_PROPOSED", checkout_id=co.id,
                 mandate_id=mandate.id,
                 payload={"cart_hash": ch, "total_paise": total, "rationale": body.rationale})

    # cart_modified_after_proposal: cart hash differs from any prior proposal on this cart
    modified = bool(db.query(Checkout)
                    .filter(Checkout.cart_id == body.cart_id, Checkout.id != co.id,
                            Checkout.cart_hash != ch).first())
    # For a CART mandate the cart_hash must match (step-up binding).
    if mandate.kind == "CART" and mandate.cart_hash and mandate.cart_hash != ch:
        co.status = "GATE_REJECTED"
        co.rejection_reason = "cart changed since cart-mandate approval (hash mismatch)"
        append_entry(db, actor="merchant_system", action_type="GATE_CART_HASH_MISMATCH",
                     checkout_id=co.id, decision="REJECT", reason=co.rejection_reason)
        db.commit()
        resp = {"checkout_id": str(co.id), "status": "GATE_REJECTED",
                "rejection_reason": co.rejection_reason}
        complete(db, idempotency_key, resp)
        db.commit()
        return resp

    g = evaluate(db, co, mandate, categories, modified_after_proposal=modified)
    if not g.allowed:
        co.status = g.status
        co.rejection_reason = g.reason
        db.commit()
        resp = {"checkout_id": str(co.id), "status": g.status}
        if g.step_up:
            base = settings.PUBLIC_BASE_URL_TUNNEL or settings.PUBLIC_BASE_URL
            resp["cart_approval_url"] = f"{base}/v1/checkout/{co.id}/approve-cart"
            resp["rejection_reason"] = g.reason
        else:
            resp["rejection_reason"] = g.reason
        complete(db, idempotency_key, resp)
        db.commit()
        return resp

    co.status = "ORDER_CREATED"
    _create_order(db, co, attempt_no=1, idem_key=f"order-{co.id}-1")
    db.commit()
    resp = {"checkout_id": str(co.id), "status": co.status,
            "user_action": _user_action(co)}
    complete(db, idempotency_key, resp)
    db.commit()
    asyncio.create_task(verify_on_timeout(str(co.id)))  # §1 verify-on-timeout
    return resp


@router.get("/v1/checkout/{checkout_id}")
def status(checkout_id: uuid.UUID, db: Session = Depends(get_db),
           _=Depends(require_user_or_agent)):
    co = db.get(Checkout, checkout_id)
    if not co:
        raise HTTPException(404, "checkout not found")
    out = {"checkout_id": str(co.id), "status": co.status, "total_paise": co.total_paise,
           "cart_id": str(co.cart_id), "mandate_id": str(co.mandate_id),
           "razorpay_order_id": co.razorpay_order_id, "retries_used": co.retries_used,
           "user_action": _user_action(co)}
    if co.status in ("FAILED", "GATE_REJECTED", "FALLBACK_LINK_ISSUED"):
        out["rejection_reason"] = co.rejection_reason
        out["retries_allowed"] = 1
        out["next_action"] = ("retry via server" if co.retries_used == 0 and co.status == "FAILED"
                              else "payment link" if co.status == "FALLBACK_LINK_ISSUED" else "none")
    return out


@router.post("/v1/checkout/{checkout_id}/approve-cart")
async def approve_cart(checkout_id: uuid.UUID, db: Session = Depends(get_db),
                 _=Depends(require_user)):
    co = db.get(Checkout, checkout_id)
    if not co:
        raise HTTPException(404, "checkout not found")
    if co.status != "AWAITING_CART_APPROVAL":
        raise HTTPException(409, f"checkout not AWAITING_CART_APPROVAL (status={co.status})")
    items = _load_items(db, co.cart_id)
    ch = cart_hash(items)
    if ch != co.cart_hash:
        co.status = "GATE_REJECTED"
        co.rejection_reason = "cart modified after step-up approval request"
        append_entry(db, actor="merchant_system", action_type="GATE_CART_HASH_MISMATCH",
                     checkout_id=co.id, decision="REJECT", reason=co.rejection_reason)
        db.commit()
        raise HTTPException(409, co.rejection_reason)

    # issue CART mandate bound to cart_hash
    m = Mandate(kind="CART", status="ACTIVE", cart_id=co.cart_id, cart_hash=ch,
                max_paise=co.total_paise, nonce=uuid.uuid4().hex,
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=10))
    from ..security import sign_mandate
    m.signature = sign_mandate(m)
    db.add(m)
    append_entry(db, actor="user", action_type="CART_MANDATE_GRANTED",
                 checkout_id=co.id, mandate_id=m.id, decision="ALLOW",
                 reason="user approved cart (step-up)", payload={"cart_hash": ch})
    co.mandate_id = m.id
    co.status = "CART_APPROVED"
    _create_order(db, co, attempt_no=1, idem_key=f"order-{co.id}-1")
    db.commit()
    asyncio.create_task(verify_on_timeout(str(co.id)))  # §1 verify-on-timeout
    return {"checkout_id": str(co.id), "status": co.status, "user_action": _user_action(co)}


@router.post("/v1/checkout/{checkout_id}/complete-session")
def complete_session(checkout_id: uuid.UUID, db: Session = Depends(get_db),
                     _=Depends(require_user)):
    co = db.get(Checkout, checkout_id)
    if not co:
        raise HTTPException(404, "checkout not found")
    db.add(DemoSession(with_ai=True, total_paise=co.total_paise, is_simulated=False))
    db.commit()
    return {"ok": True, "total_paise": co.total_paise}


@router.post("/v1/payments/refund")
def refund(body: dict, db: Session = Depends(get_db), _=Depends(require_user)):
    co = db.get(Checkout, uuid.UUID(body["checkout_id"]))
    if not co or not co.razorpay_order_id:
        raise HTTPException(404, "checkout/order not found")
    # find the payment id via order
    order = rp_client().order.fetch(co.razorpay_order_id)
    payments = rp_client().order.payments(co.razorpay_order_id)
    paid = next((p for p in payments.get("items", []) if p["status"] == "captured"), None)
    if not paid:
        raise HTTPException(409, "no captured payment to refund")
    r = rp_client().payment.refund(paid["id"], {"amount": co.total_paise, "speed": "normal"})
    append_entry(db, actor="user", action_type="REFUND", checkout_id=co.id,
                 payload={"refund_id": r.get("id"), "payment_id": paid["id"],
                          "amount_paise": co.total_paise})
    db.commit()
    return {"refund_id": r.get("id"), "status": r.get("status")}
