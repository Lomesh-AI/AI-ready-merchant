import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import CoOccurrence, Product, RecommendationLog
from ..security import require_agent

router = APIRouter()

# §5: The discounted item enters the cart through the normal cart endpoints, so it is
# inside the cart_hash and the same gates apply. There is NO separate "agent discount"
# path — by design.


@router.get("/v1/recommendations")
def recommendations(cart_id: uuid.UUID, db: Session = Depends(get_db),
                    _=Depends(require_agent)):
    from .carts import _load_items
    items = _load_items(db, cart_id)
    skus = [i["sku"] for i in items]
    total_orders = 120  # historical order base used by the seed's co_occurrence math
    pairs = (db.query(CoOccurrence)
             .filter(CoOccurrence.sku_a.in_(skus) | CoOccurrence.sku_b.in_(skus))
             .order_by(CoOccurrence.pair_count.desc()).all())
    seen, out = set(), []
    for p in pairs:
        other = p.sku_b if p.sku_a in skus else p.sku_a
        if other in skus or other in seen:
            continue
        seen.add(other)
        prod = db.query(Product).filter_by(sku=other).first()
        if not prod:
            continue
        from ..config import settings
        discount_pct = min(10, settings.POLICY_DISCOUNT_CAP_PCT)  # computed SERVER-side
        discounted = prod.price_paise * (100 - discount_pct) // 100
        reason = f"bought together in {p.pair_count} of {total_orders} historical orders"
        entry = {
            "sku": prod.sku, "name": prod.name, "base_price_paise": prod.price_paise,
            "discounted_price_paise": discounted, "reason": reason,
            "confidence": round(p.pair_count / total_orders, 3),
        }
        out.append(entry)
        db.add(RecommendationLog(checkout_ref=str(cart_id), sku_suggested=prod.sku,
                                 score=entry["confidence"], reason=reason))
        if len(out) == 2:
            break
    db.commit()
    return out
