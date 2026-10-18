"""One adapter per external provider (PRD § External API integrations).

`PROVIDER_MODE=fake` (default) wires the simulators in fake_*.py, which keep their own world in
fake_* tables so the whole loop runs locally. `live` wires the real HTTP adapters.
"""
from sqlalchemy.orm import Session

from ..config import settings


def social_mode(platform: str) -> str:
    """INSTAGRAM_MODE / YOUTUBE_MODE override PROVIDER_MODE, so a real Instagram account can be connected while
    payments, KYC and OTP stay simulated."""
    return settings.instagram_mode if platform == "instagram" else settings.youtube_mode


def social(platform: str, db: Session, force_live: bool = False, force_fake: bool = False):
    if not force_fake and (force_live or social_mode(platform) == "live"):
        if platform == "instagram":
            from .instagram_live import InstagramLive
            return InstagramLive()
        from .youtube_live import YouTubeLive
        return YouTubeLive()
    from .fake_social import FakeInstagram, FakeYouTube
    return FakeInstagram(db) if platform == "instagram" else FakeYouTube(db)


def social_for(acc, db: Session):
    """The provider for an already-connected account. Accounts created by the simulator (seeded demo creators,
    /dev/connect) keep using it even when the platform runs live, so real and demo accounts can coexist."""
    from ..models import FakeAccount
    if db.get(FakeAccount, acc.external_id) is not None:
        from .fake_social import FakeInstagram, FakeYouTube
        return FakeInstagram(db) if acc.platform == "instagram" else FakeYouTube(db)
    return social(acc.platform, db, force_live=True)


def razorpay(db: Session):
    if settings.provider_mode == "live":
        from .razorpay_live import RazorpayLive
        return RazorpayLive()
    from .fake_razorpay import FakeRazorpay
    return FakeRazorpay(db)


def kyc():
    if settings.provider_mode == "live":
        from .kyc_live import CashfreeKyc
        return CashfreeKyc()
    from .fake_kyc import FakeKyc
    return FakeKyc()


def otp():
    if settings.provider_mode == "live":
        from .otp_live import Msg91Otp
        return Msg91Otp()
    from .fake_otp import FakeOtp
    return FakeOtp()
