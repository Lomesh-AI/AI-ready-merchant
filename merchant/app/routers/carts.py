import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Cart, CartItem, Product
from ..security import require_agent
from ..util import cart_hash

router = APIRouter()


class ItemIn(BaseModel):
    sku: str
    qty: int  # §1: buyer may only send {sku, qty} — no amount/price/discount fields exist.


class ItemsIn(BaseModel):
    items: list[ItemIn]


def _load_items(db: Session, cart_id: uuid.UUID) -> list[dict]:
    rows = (db.query(CartItem, Product).join(Product, CartItem.sku == Product.sku)
            .filter(CartItem.cart_id == cart_id).all())
    return [{"sku": ci.sku, "qty": ci.qty, "unit_price_paise": ci.unit_price_paise,
             "name": p.name, "category": p.category} for ci, p in rows]


@router.post("/v1/carts")
def create_cart(db: Session = Depends(get_db), _=Depends(require_agent)):
    cart = Cart(status="DRAFT")
    db.add(cart)
    db.commit()
    return {"cart_id": str(cart.id)}


@router.post("/v1/carts/{cart_id}/items")
def add_items(cart_id: uuid.UUID, body: ItemsIn, db: Session = Depends(get_db),
              _=Depends(require_agent)):
    cart = db.get(Cart, cart_id)
    if not cart:
        raise HTTPException(404, "cart not found")
    for item in body.items:
        p = db.query(Product).filter_by(sku=item.sku).first()
        if not p:
            raise HTTPException(404, f"unknown sku {item.sku}")
        if item.qty < 1:
            raise HTTPException(422, "qty must be >= 1")
        assert isinstance(p.price_paise, int)  # §12: money is integer paise everywhere
        db.add(CartItem(cart_id=cart_id, sku=item.sku, qty=item.qty,
                        unit_price_paise=p.price_paise))  # copied at add-time from server
    cart.status = "DRAFT"
    db.commit()
    return {"cart_id": str(cart_id), "items": [
        {"sku": i["sku"], "qty": i["qty"], "unit_price_paise": i["unit_price_paise"]}
        for i in _load_items(db, cart_id)]}


@router.post("/v1/carts/{cart_id}/ready")
def ready(cart_id: uuid.UUID, db: Session = Depends(get_db), _=Depends(require_agent)):
    cart = db.get(Cart, cart_id)
    if not cart:
        raise HTTPException(404, "cart not found")
    items = _load_items(db, cart_id)
    if not items:
        raise HTTPException(422, "cart is empty")
    total = sum(i["qty"] * i["unit_price_paise"] for i in items)
    assert isinstance(total, int)  # §12 integer paise
    cart.status = "READY"
    db.commit()
    return {
        "cart_id": str(cart_id),
        "items": [{"sku": i["sku"], "qty": i["qty"], "unit_price_paise": i["unit_price_paise"]} for i in items],
        "total_paise": total,
        "cart_hash": cart_hash(items),
    }
