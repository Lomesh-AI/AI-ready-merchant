from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import Product
from ..security import require_agent

router = APIRouter()

AGENTS_JSON = {
    "version": "1.0",
    "merchant": {"name": "Acme Outdoors", "description": "AI-ready outdoor gear store (demo)"},
    "capabilities": [
        {"name": "catalog.search", "method": "POST", "path": "/v1/catalog/search"},
        {"name": "cart.create", "method": "POST", "path": "/v1/carts"},
        {"name": "cart.add_item", "method": "POST", "path": "/v1/carts/{cart_id}/items"},
        {"name": "cart.ready", "method": "POST", "path": "/v1/carts/{cart_id}/ready"},
        {"name": "checkout.propose", "method": "POST", "path": "/v1/checkout/propose"},
        {"name": "checkout.status", "method": "GET", "path": "/v1/checkout/{checkout_id}"},
        {"name": "mandates.request", "method": "POST", "path": "/v1/mandates/request"},
    ],
    "payment": {"currency": "INR", "provider": "razorpay", "mode": "test"},
    # informational; enforcement is server-side.
    "policies": {
        "max_agent_purchase_paise": 500000,
        "agent_session_minutes": 10,
        "allowed_categories": ["shoes", "accessories"],
    },
}


class SearchRequest(BaseModel):
    query: str = ""
    category: str | None = None
    max_paise: int | None = None


def _product_out(p: Product) -> dict:
    return {
        "sku": p.sku, "name": p.name, "description": p.description,
        "price_paise": p.price_paise, "category": p.category, "tags": p.tags,
        "rating": p.rating, "stock": p.stock, "image_url": p.image_url,
    }


@router.get("/.well-known/agents.json", tags=["public"])
@router.get("/agents.json", tags=["public"])
def agents_manifest():
    return AGENTS_JSON


@router.post("/v1/catalog/search")
def search(req: SearchRequest, db: Session = Depends(get_db), _=Depends(require_agent)):
    q = db.query(Product)
    if req.category:
        q = q.filter(Product.category == req.category)
    if req.max_paise is not None:
        q = q.filter(Product.price_paise <= req.max_paise)
    if req.query:
        like = f"%{req.query.lower()}%"
        q = q.filter((Product.name.ilike(like)) | (Product.description.ilike(like))
                     | (Product.category.ilike(like)))
    return [_product_out(p) for p in q.all()]


@router.get("/v1/catalog/products")
def list_products(db: Session = Depends(get_db), _=Depends(require_agent)):
    return [_product_out(p) for p in db.query(Product).order_by(Product.id).all()]
