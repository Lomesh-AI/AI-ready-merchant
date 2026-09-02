import os


class Settings:
    DATABASE_URL = os.environ["DATABASE_URL"]
    PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8000")
    PUBLIC_BASE_URL_TUNNEL = os.environ.get("PUBLIC_BASE_URL_TUNNEL", "")
    RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "")
    RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "")
    RAZORPAY_WEBHOOK_SECRET = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "")
    MANDATE_SIGNING_KEY = os.environ.get("MANDATE_SIGNING_KEY", "0" * 64)
    # Constants for token names (§12): tokens are never inlined.
    DEMO_USER_TOKEN = os.environ.get("DEMO_USER_TOKEN", "demo-user-token-1")
    AGENT_SERVICE_TOKEN = os.environ.get("AGENT_SERVICE_TOKEN", "agent-service-token-1")
    POLICY_PER_TXN_CAP_PAISE = int(os.environ.get("POLICY_PER_TXN_CAP_PAISE", "1000000"))
    POLICY_DAILY_CAP_PAISE = int(os.environ.get("POLICY_DAILY_CAP_PAISE", "2000000"))
    POLICY_MAX_TXNS_PER_HOUR = int(os.environ.get("POLICY_MAX_TXNS_PER_HOUR", "5"))
    POLICY_DISCOUNT_CAP_PCT = int(os.environ.get("POLICY_DISCOUNT_CAP_PCT", "10"))
    # §5 verify-on-timeout: poll the Orders API once after this many seconds.
    WEBHOOK_TIMEOUT_SECONDS = 20


settings = Settings()
