"""Runtime configuration. Every value can be overridden with an environment variable."""
import base64
import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    """Read backend/.env (KEY=VALUE lines) into the environment. Real environment variables win."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key.strip(), value)


if not os.environ.get("FLU_SKIP_DOTENV"):
    _load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _bool(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    database_url: str = _env("DATABASE_URL", "sqlite:///" + str(Path(__file__).resolve().parent.parent / "flu.db").replace("\\", "/"))
    web_origin: str = _env("WEB_ORIGIN", "http://localhost:3000")
    api_origin: str = _env("API_ORIGIN", "http://127.0.0.1:8000")
    dev_mode: bool = _bool("FLU_DEV_MODE", True)

    # PRD: 3 OTPs per 10 minutes. Dev mode allows more so demo accounts can be switched freely.
    otp_per_10min: int = int(_env("OTP_PER_10MIN", "10" if _bool("FLU_DEV_MODE", True) else "3"))

    jwt_secret: str = _env("JWT_SECRET", "dev-only-jwt-secret-change-me-before-production")
    access_ttl_min: int = int(_env("ACCESS_TTL_MIN", "15"))
    refresh_ttl_days: int = int(_env("REFRESH_TTL_DAYS", "30"))

    # 32-byte AES-256-GCM key for platform OAuth tokens (base64). Production: a KMS-wrapped data key.
    token_enc_key_b64: str = _env(
        "TOKEN_ENC_KEY",
        base64.b64encode(hashlib.sha256(b"flu-dev-token-key").digest()).decode(),
    )
    pan_pepper: str = _env("PAN_PEPPER", "dev-only-pan-pepper")

    # Provider mode: "fake" runs the bundled simulators; "live" uses the real adapters.
    provider_mode: str = _env("PROVIDER_MODE", "fake")

    razorpay_key_id: str = _env("RAZORPAY_KEY_ID", "rzp_test_flu")
    razorpay_key_secret: str = _env("RAZORPAY_KEY_SECRET", "rzp_test_secret_flu")
    razorpay_webhook_secret: str = _env("RAZORPAY_WEBHOOK_SECRET", "whsec_test_flu")
    razorpay_base_url: str = _env("RAZORPAY_BASE_URL", "https://api.razorpay.com")
    # Route can only release a held transfer whole, so each hire's escrow is split into slices (live mode).
    razorpay_escrow_max_slices: int = int(_env("RAZORPAY_ESCROW_MAX_SLICES", "20"))
    razorpay_escrow_min_slice_paise: int = int(_env("RAZORPAY_ESCROW_MIN_SLICE_PAISE", "10000"))  # ₹100
    # Business profile for creators' Route linked accounts. Razorpay has no creator category; confirm this pair
    # (alternative: services / ad_and_marketing) with Razorpay before going live.
    razorpay_route_category: str = _env("RAZORPAY_ROUTE_CATEGORY", "media_and_entertainment")
    razorpay_route_subcategory: str = _env("RAZORPAY_ROUTE_SUBCATEGORY", "content_and_publishing")

    # Cashfree Verification Suite (PAN, bank account, UPI). Sandbox: https://sandbox.cashfree.com/verification
    cashfree_base_url: str = _env("CASHFREE_BASE_URL", "https://api.cashfree.com/verification")
    cashfree_client_id: str = _env("CASHFREE_CLIENT_ID", "")
    cashfree_client_secret: str = _env("CASHFREE_CLIENT_SECRET", "")
    # PEM public key from the Cashfree dashboard; signs each call (x-cf-signature) when the server IP isn't whitelisted.
    cashfree_public_key: str = _env("CASHFREE_PUBLIC_KEY", "")

    # MSG91 OTP. The send call takes MSG91's template id; the DLT template id and sender id live on that template
    # (Msg91Otp.register_dlt_template sets them once).
    msg91_base_url: str = _env("MSG91_BASE_URL", "https://control.msg91.com")
    msg91_auth_key: str = _env("MSG91_AUTH_KEY", "")
    msg91_template_id: str = _env("MSG91_TEMPLATE_ID", "")
    msg91_dlt_te_id: str = _env("MSG91_DLT_TE_ID", "")
    msg91_sender_id: str = _env("MSG91_SENDER_ID", "")
    # flu: Flu generates the code, MSG91 delivers it, Flu checks its own hash. msg91: MSG91 generates and verifies.
    msg91_otp_verify: str = _env("MSG91_OTP_VERIFY", "flu")

    # Per-platform override of provider_mode: INSTAGRAM_MODE=live connects real accounts through Business Login
    # for Instagram while everything else stays simulated. Demo accounts keep using the simulator either way.
    instagram_mode: str = _env("INSTAGRAM_MODE", _env("PROVIDER_MODE", "fake"))
    youtube_mode: str = _env("YOUTUBE_MODE", _env("PROVIDER_MODE", "fake"))
    instagram_client_id: str = _env("INSTAGRAM_CLIENT_ID", "")      # "Instagram app ID" in the Meta App Dashboard
    instagram_client_secret: str = _env("INSTAGRAM_CLIENT_SECRET", "")
    # Must match a "Valid OAuth Redirect URI" in the dashboard exactly. Defaults to the API's own callback.
    instagram_redirect_uri: str = _env("INSTAGRAM_REDIRECT_URI", "")
    instagram_graph_version: str = _env("INSTAGRAM_GRAPH_VERSION", "v25.0")
    google_client_id: str = _env("GOOGLE_CLIENT_ID", "")
    google_client_secret: str = _env("GOOGLE_CLIENT_SECRET", "")
    youtube_api_key: str = _env("YOUTUBE_API_KEY", "")

    # AI. With no Anthropic credentials the AI services fall back to deterministic heuristics.
    ai_mode: str = _env("FLU_AI_MODE", "auto")  # auto | live | heuristic
    model_main: str = _env("FLU_MODEL_MAIN", "claude-sonnet-5-5")   # briefs, diagnosis, hooks
    model_fast: str = _env("FLU_MODEL_FAST", "claude-haiku-5-5")    # classification, policy pre-check
    ai_cap_paise_per_creator_month: int = int(_env("AI_CAP_PAISE", "1500"))  # ₹15

    # Matching weights (MT-2); config, revisited monthly.
    rank_weights: dict = field(default_factory=lambda: {
        "score": 0.45, "niche": 0.25, "cpm": 0.15, "responsiveness": 0.15,
    })

    worker_enabled: bool = _bool("FLU_WORKER", True)

    @property
    def token_enc_key(self) -> bytes:
        return base64.b64decode(self.token_enc_key_b64)


settings = Settings()

# Business constants from the PRD.
TIERS = [("platinum", 80), ("gold", 60), ("silver", 40), ("bronze", 0)]
TIER_ORDER = {"bronze": 0, "silver": 1, "gold": 2, "platinum": 3}
TAKE_RATE = {"starter": 0.15, "growth": 0.10, "scale": 0.0}
PLAN_LIVE_CREATORS = {"starter": 5, "growth": 50, "scale": 10_000}
GST_RATE = 0.18
TDS_194O_RATE = 0.001
TDS_NO_PAN_RATE = 0.05
TDS_194O_EXEMPT_PAISE = 5_00_000_00  # ₹5 lakh per FY
APPROVAL_WINDOW_H = 72
DISPUTE_RESPONSE_H = 48
MIN_TOPUP_PAISE = 5_000_00
MIN_WITHDRAW_PAISE = 500_00
MAX_OPEN_APPLICATIONS = 20
GST_REQUIRED_TOPUP_PAISE = 50_000_00
DISCLOSURE_TAGS = ["#ad", "#collab", "#sponsored", "#paidpartnership"]

NICHES = [
    "skincare", "haircare", "makeup", "fashion-women", "fashion-men", "fitness", "food-recipes",
    "food-reviews", "tech-gadgets", "personal-finance", "edtech", "parenting", "travel", "comedy",
    "gaming", "home-decor", "sustainable-living", "wellness", "pets", "books", "music", "dance",
    "automobiles", "cricket", "photography", "art-craft", "career", "productivity", "spirituality",
    "regional-cinema",
]
