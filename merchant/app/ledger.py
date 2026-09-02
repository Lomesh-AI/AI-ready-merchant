import threading

from sqlalchemy.orm import Session

from .models import LedgerEntry
from .util import canonical_json, sha256_hex

GENESIS_PREV = "0" * 64  # §1: genesis prev_entry_hash

_chain_lock = threading.Lock()


def append_entry(
    db: Session,
    actor: str,
    action_type: str,
    payload: dict,
    decision: str | None = None,
    reason: str | None = None,
    checkout_id=None,
    mandate_id=None,
) -> LedgerEntry:
    """Append-only, hash-chained audit ledger — §1.
    entry_hash = sha256(prev_entry_hash + '|' + sha256(canonical_json(payload_without_hashes)))
    """
    with _chain_lock:
        prev = db.query(LedgerEntry).order_by(LedgerEntry.seq.desc()).first()
        prev_hash = prev.entry_hash if prev else GENESIS_PREV
        body = {
            "actor": actor,
            "action_type": action_type,
            "checkout_id": str(checkout_id) if checkout_id else None,
            "mandate_id": str(mandate_id) if mandate_id else None,
            "decision": decision,
            "reason": reason,
            "payload": payload,
        }
        entry_hash = sha256_hex(prev_hash + "|" + sha256_hex(canonical_json(body)))
        e = LedgerEntry(
            actor=actor, action_type=action_type, decision=decision, reason=reason,
            checkout_id=checkout_id, mandate_id=mandate_id,
            payload_json=body, prev_entry_hash=prev_hash, entry_hash=entry_hash,
        )
        db.add(e)
        db.flush()
        return e


def verify_chain(db: Session) -> dict:
    entries = db.query(LedgerEntry).order_by(LedgerEntry.seq).all()
    prev_hash = GENESIS_PREV
    for e in entries:
        expected = sha256_hex(prev_hash + "|" + sha256_hex(canonical_json(e.payload_json)))
        if e.prev_entry_hash != prev_hash or e.entry_hash != expected:
            return {"valid": False, "broken_at_seq": e.seq}
        prev_hash = e.entry_hash
    return {"valid": True}
