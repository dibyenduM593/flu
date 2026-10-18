"""One adapter per external provider (PRD § External API integrations).

`PROVIDER_MODE=fake` (default) wires the simulators in fake_*.py, which keep their own world in
fake_* tables so the whole loop runs locally. `live` wires the real HTTP adapters.
"""
from sqlalchemy.orm import Session

from ..config import settings


def social(platform: str, db: Session):
    if settings.provider_mode == "live":
        if platform == "instagram":
            from .instagram_live import InstagramLive
            return InstagramLive()
        from .youtube_live import YouTubeLive
        return YouTubeLive()
    from .fake_social import FakeInstagram, FakeYouTube
    return FakeInstagram(db) if platform == "instagram" else FakeYouTube(db)


def razorpay(db: Session):
    from .fake_razorpay import FakeRazorpay
    return FakeRazorpay(db)


def kyc():
    from .fake_kyc import FakeKyc
    return FakeKyc()


def otp():
    from .fake_otp import FakeOtp
    return FakeOtp()
