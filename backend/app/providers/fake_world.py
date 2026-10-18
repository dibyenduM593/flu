"""Deterministic simulated Instagram / YouTube world.

Every handle maps to a persona (niche, reach, engagement, cadence, audience hours, fraud pattern)
seeded from the handle, so the same handle always produces the same history. Post metrics follow
views(t) = final_views * (1 - exp(-age/tau)) plus optional bought views (no engagement) that the
A6 anomaly filter is meant to catch.
"""
import hashlib
import math
import random
import string
from datetime import timedelta, timezone

from sqlalchemy.orm import Session

IST = timezone(timedelta(hours=5, minutes=30))

from ..clock import now
from ..models import FakeAccount, FakeMedia

CITIES = ["Mumbai", "Delhi", "Bengaluru", "Pune", "Hyderabad", "Chennai", "Kolkata", "Jaipur",
          "Lucknow", "Indore", "Kochi", "Ahmedabad", "Chandigarh", "Bhopal", "Nagpur", "Surat"]

CAPTIONS = {
    "skincare": ["3 steps for glass skin on a student budget", "I tried kumkumadi oil for 14 days",
                 "Sunscreen myths your aunty still believes", "Monsoon acne routine that finally worked",
                 "Rating every viral serum under ₹500", "Niacinamide vs vitamin C: which one first?"],
    "haircare": ["Oiling my hair the way my nani did", "Frizz fix for humid Mumbai days",
                 "Rice water rinse: 30 day result", "Hair fall routine that actually helped"],
    "makeup": ["Festive glam in 10 minutes", "Drugstore dupes for luxury lipsticks", "No-makeup makeup for college"],
    "fashion-women": ["5 ways to style one kurta", "Sarojini haul under ₹1000", "Office looks for the week"],
    "fashion-men": ["Kurta pajama styling for Diwali", "Capsule wardrobe for college guys", "Sneakers under ₹3000"],
    "fitness": ["20 minute home workout, no equipment", "What I eat in a day for fat loss", "Fixing my posture in 30 days"],
    "food-recipes": ["Hostel maggi but make it gourmet", "5 minute poha my mom swears by", "Protein dosa batter recipe"],
    "food-reviews": ["Rating every momo stall on this street", "₹100 vs ₹1000 biryani", "Hidden cafe in the old city"],
    "tech-gadgets": ["Best phone under ₹20k right now", "Earbuds I'd actually buy", "Desk setup on a budget"],
    "personal-finance": ["How I saved my first ₹1 lakh at 22", "SIP vs FD explained in 60 seconds", "Credit card mistakes to avoid"],
    "edtech": ["How I cracked my exam with 4 hours a day", "Study with me: pomodoro edition", "Free tools every student needs"],
    "sustainable-living": ["Zero-waste kitchen swaps", "Upcycled jar planters", "Plastic-free Diwali decor"],
    "home-decor": ["Rental-friendly room makeover", "Balcony garden glow up", "Decor finds under ₹500"],
    "travel": ["3 days in Rishikesh for ₹5000", "Hidden beaches in Gokarna", "Train journey hacks"],
    "comedy": ["When mom finds your report card", "Types of people in a Mumbai local", "Indian weddings be like"],
    "wellness": ["Morning routine for anxiety", "Ayurvedic habits that stuck", "Sleep better in 7 days"],
    "gaming": ["BGMI clutch moments", "Budget gaming PC build", "Ranking every mobile game this year"],
}
HASHTAGS = {
    "skincare": "#skincare #glowingskin #skincareroutine", "haircare": "#haircare #hairgrowth",
    "makeup": "#makeup #mua", "fashion-women": "#fashion #ootd", "fashion-men": "#mensfashion #ootd",
    "fitness": "#fitness #homeworkout", "food-recipes": "#recipe #indianfood", "food-reviews": "#foodie #streetfood",
    "tech-gadgets": "#tech #gadgets", "personal-finance": "#personalfinance #money", "edtech": "#studygram #exam",
    "sustainable-living": "#sustainableliving #zerowaste", "home-decor": "#homedecor #roommakeover",
    "travel": "#travel #incredibleindia", "comedy": "#comedy #relatable", "wellness": "#wellness #ayurveda",
    "gaming": "#gaming #bgmi",
}


def rng_for(seed: str) -> random.Random:
    return random.Random(int(hashlib.sha256(seed.encode()).hexdigest()[:16], 16))


def make_persona(handle: str, overrides: dict | None = None) -> dict:
    r = rng_for("persona:" + handle)
    niche = r.choice(list(CAPTIONS))
    second = r.choice([n for n in CAPTIONS if n != niche])
    followers = int(math.exp(r.uniform(math.log(800), math.log(60000))))
    p = {
        "niche": niche, "secondary_niche": second, "followers": followers,
        "median_ratio": round(r.uniform(0.6, 4.5), 2),     # median reel views / followers
        "view_sigma": round(r.uniform(0.35, 0.9), 2),
        "eng_rate": round(r.uniform(0.025, 0.11), 3),      # engagement / views
        "posts_per_week": round(r.uniform(1.0, 5.5), 1),
        "growth_30d": round(r.uniform(-0.01, 0.12), 3),
        "city": r.choice(CITIES),
        "peak_hours": sorted(r.sample([12, 13, 18, 19, 20, 21, 22], 3)),
        "best_length_s": r.choice([15, 22, 30, 45]),
        "hook_strength": round(r.uniform(0.3, 0.95), 2),
        "fraud": None,  # None | bought_views | follower_spike | comment_bots
    }
    p.update(overrides or {})
    return p


def _shortcode(r: random.Random) -> str:
    return "".join(r.choice(string.ascii_letters + string.digits) for _ in range(11))


def ensure_account(db: Session, platform: str, handle: str, account_type: str | None = None,
                   overrides: dict | None = None, history_posts: int = 36) -> FakeAccount:
    handle = handle.strip().lstrip("@").lower()
    acc = db.query(FakeAccount).filter_by(platform=platform, handle=handle).first()
    if acc:
        if account_type and acc.account_type != account_type:
            acc.account_type = account_type
        return acc
    persona = make_persona(handle, overrides)
    ext = ("17841" if platform == "instagram" else "UC") + hashlib.sha1(f"{platform}:{handle}".encode()).hexdigest()[:14]
    acc = FakeAccount(
        external_id=ext, platform=platform, handle=handle,
        account_type=account_type or ("MEDIA_CREATOR" if platform == "instagram" else "CHANNEL"),
        followers=persona["followers"], persona=persona,
    )
    db.add(acc)
    db.flush()
    _generate_history(db, acc, history_posts)
    return acc


def _generate_history(db: Session, acc: FakeAccount, n: int):
    p, r = acc.persona, rng_for("history:" + acc.handle)
    t = now()
    gap_h = 168 / max(p["posts_per_week"], 0.5)
    cursor = t - timedelta(hours=r.uniform(4, 30))
    for i in range(n):
        # peak_hours are IST; store UTC
        posted = (cursor.astimezone(IST).replace(hour=r.choice(p["peak_hours"] + [9, 15]), minute=r.randint(0, 59))
                  .astimezone(timezone.utc))
        if posted > t - timedelta(hours=2):
            posted = t - timedelta(hours=r.uniform(2, 20))
        create_post(db, acc, caption=None, posted_at=posted, seed=f"{acc.handle}:{i}")
        cursor -= timedelta(hours=gap_h * r.uniform(0.5, 1.6))


def create_post(db: Session, acc: FakeAccount, caption: str | None, posted_at=None, seed: str | None = None,
                quality_boost: float = 1.0, paid_partnership: bool = False) -> FakeMedia:
    p = acc.persona
    r = rng_for("post:" + (seed or f"{acc.handle}:{now().isoformat()}:{caption}"))
    niche = p["niche"] if r.random() < 0.75 else p["secondary_niche"]
    if caption is None:
        caption = f"{r.choice(CAPTIONS.get(niche, CAPTIONS['comedy']))} {HASHTAGS.get(niche, '')}"
    duration = int(max(7, r.gauss(p["best_length_s"], 12)))
    if acc.platform == "youtube" and r.random() < 0.25:
        duration = r.randint(240, 900)  # long-form upload, not a Short
    length_pen = math.exp(-abs(duration - p["best_length_s"]) / 60) if duration < 200 else 0.6
    hook = p["hook_strength"] * r.uniform(0.7, 1.25)
    factor = math.exp(r.gauss(0, p["view_sigma"])) * (0.6 + hook) * length_pen * quality_boost
    final = int(acc.followers * p["median_ratio"] * factor) + r.randint(20, 400)
    bot = 0
    if p.get("fraud") == "bought_views" and r.random() < 0.5:
        final = int(acc.followers * r.uniform(55, 90))
    sc = _shortcode(r)
    if acc.platform == "instagram":
        permalink, mpt = f"https://www.instagram.com/reel/{sc}/", "REELS"
    else:
        permalink = f"https://www.youtube.com/shorts/{sc}" if duration <= 180 else f"https://www.youtube.com/watch?v={sc}"
        mpt = "SHORTS" if duration <= 180 else "VIDEO"
    eng = p["eng_rate"] * r.uniform(0.7, 1.3)
    if p.get("fraud") == "bought_views":
        eng = min(eng, 0.003)
    m = FakeMedia(
        id=("18" if acc.platform == "instagram" else "yt") + hashlib.sha1(sc.encode()).hexdigest()[:15],
        account_external_id=acc.external_id, shortcode=sc, permalink=permalink, caption=caption,
        media_type="VIDEO", media_product_type=mpt, posted_at=posted_at or now(), duration_s=duration,
        final_views=final, tau_hours=r.uniform(14, 48), eng_rate=eng, reach_ratio=r.uniform(0.72, 0.9),
        bot_views=bot, paid_partnership=paid_partnership,
    )
    db.add(m)
    db.flush()
    return m


def metrics_at(m: FakeMedia, t) -> dict:
    age_h = max(0.0, (t - m.posted_at).total_seconds() / 3600)
    organic = m.final_views * (1 - math.exp(-age_h / m.tau_hours))
    # deterministic jitter so successive polls are not perfectly smooth
    jitter = 1 + (int(hashlib.md5(f"{m.id}:{int(age_h)}".encode()).hexdigest()[:4], 16) / 65535 - 0.5) * 0.01
    organic = organic * jitter
    bot = m.bot_views if (m.bot_at and t >= m.bot_at) else 0
    e = m.eng_rate
    likes = int(organic * e * 0.72)
    comments = int(organic * e * 0.05)
    saves = int(organic * e * 0.13)
    shares = int(organic * e * 0.10)
    views = int(organic + bot)
    return {
        "views": views, "reach": int(organic * m.reach_ratio + bot * 0.95), "likes": likes,
        "comments": comments, "saved": saves, "shares": shares,
        "total_interactions": likes + comments + saves + shares,
    }


def follower_history(acc: FakeAccount) -> int:
    """followers 30 days ago; follower_spike fraud shows a > 30% jump inside 7 days."""
    g = acc.persona.get("growth_30d", 0.03)
    if acc.persona.get("fraud") == "follower_spike":
        g = 0.55
    return int(acc.followers / (1 + g))
