demo:
	docker compose exec merchant python -m app.seed
	@echo ""
	@echo "=== DEMO CHECKLIST ==="
	@echo "1. Open http://localhost:3000 (buyer UI) and http://localhost:3000/merchant (merchant UI)"
	@echo "2. Buyer: goal 'Buy beginner running shoes under 5,000 INR. You may purchase if you find a good option.'"
	@echo "3. Approve the intent mandate ONCE via the consent card."
	@echo "4. Watch: discovery -> selection rationale -> silent gates -> Razorpay checkout."
	@echo "5. Pay with test SUCCESS card 4111 1111 1111 1111 (any future expiry, any CVV)."
	@echo "6. Failure demo: card 4000 0000 0000 0002 -> server retry -> fallback link."
	@echo "7. Attack demo: ask agent for the 'TrailBlazer Pro Bundle' -> HARD CAP REJECT."
	@echo "8. Merchant UI: Audit tab -> Why? modal + chain badge; Policies tab; Growth tab (AOV)."
