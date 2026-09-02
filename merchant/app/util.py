import hashlib
import json
from typing import Any


def canonical_json(obj: Any) -> str:
    """Canonical JSON: sorted keys, no whitespace, ensure ASCII."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def cart_hash(items: list[dict]) -> str:
    """cart_hash = sha256(canonical json of [{sku,qty,unit_price_paise}]) — §5 cart.ready."""
    return sha256_hex(canonical_json(
        [{"sku": i["sku"], "qty": i["qty"], "unit_price_paise": i["unit_price_paise"]} for i in items]
    ))
