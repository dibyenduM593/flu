"""Seed a demo marketplace by driving the real services end to end.

    python -m app.seed

Runs the clock 120 simulated hours in the past, onboards creators through the fake OAuth flow,
funds brand wallets through the fake Razorpay checkout + webhook, publishes briefs, hires, posts,
tracks views, auto-approves and pays out, then advances the clock back to the present.

Demo logins (OTP is shown on screen in dev mode):
  creator  +91 90000 00001  Riya Kulkarni (new creator, not yet hired)
  brand    +91 90000 00002  Arjun @ Kesari Naturals
  brand    +91 90000 00004  Meera @ Loop Bottles
  ops      +91 90000 00003
"""
from datetime import timedelta

from . import clock
from .db import Base, SessionLocal, engine
from .errors import ApiError
from .models import Application, CreatorProfile, Deliverable, Hire, Org, OrgMember, User
from .providers.fake_razorpay import FakeRazorpay
from .providers.fake_social import _FakeBase
from .providers.fake_world import ensure_account
from .security import sign_state
from .services import briefs, connections, jobs, kyc, money
from .services import ai, audit, scoring, tracking  # noqa: F401  (register job handlers)

CREATORS = [
    # name, phone, platform handles, persona overrides
    ("Riya Kulkarni", "+919000000001", {"instagram": "riya.skin"},
     {"niche": "skincare", "secondary_niche": "makeup", "followers": 4200, "median_ratio": 1.3, "eng_rate": 0.055,
      "hook_strength": 0.45, "posts_per_week": 2.6, "city": "Pune", "growth_30d": 0.04}),
    ("Kavya Menon", "+919100000001", {"instagram": "kavyamenon"},
     {"niche": "skincare", "followers": 23000, "median_ratio": 2.6, "eng_rate": 0.08, "hook_strength": 0.85,
      "posts_per_week": 4.5, "city": "Bengaluru", "growth_30d": 0.07}),
    ("Meher Kapoor", "+919100000002", {"instagram": "meherglows"},
     {"niche": "skincare", "followers": 42000, "median_ratio": 1.9, "eng_rate": 0.068, "hook_strength": 0.7,
      "posts_per_week": 3.8, "city": "Mumbai"}),
    ("Divya Nair", "+919100000003", {"instagram": "divya.dewy", "youtube": "divyadewy"},
     {"niche": "skincare", "followers": 58000, "median_ratio": 1.2, "eng_rate": 0.047, "hook_strength": 0.55,
      "posts_per_week": 2.5, "city": "Bengaluru"}),
    ("Harleen Gill", "+919100000004", {"instagram": "harleen.gram"},
     {"niche": "makeup", "secondary_niche": "skincare", "followers": 39000, "median_ratio": 2.4, "eng_rate": 0.062,
      "hook_strength": 0.8, "posts_per_week": 4.0, "city": "Delhi"}),
    ("Tanvi Iyer", "+919100000005", {"instagram": "tanvi.skin"},
     {"niche": "skincare", "followers": 18000, "median_ratio": 0.9, "eng_rate": 0.051, "hook_strength": 0.4,
      "posts_per_week": 1.6, "city": "Chennai"}),
    ("Farhan Ali", "+919100000006", {"youtube": "desidermnotes"},
     {"niche": "skincare", "followers": 34000, "median_ratio": 1.6, "eng_rate": 0.072, "hook_strength": 0.75,
      "posts_per_week": 2.2, "city": "Hyderabad"}),
    ("Ananya Rao", "+919100000007", {"instagram": "ananya.at.home"},
     {"niche": "sustainable-living", "secondary_niche": "home-decor", "followers": 48200, "median_ratio": 0.8,
      "eng_rate": 0.054, "hook_strength": 0.6, "posts_per_week": 3.0, "city": "Bengaluru"}),
    ("Ishaan Verma", "+919100000008", {"instagram": "ishaan.zerowaste"},
     {"niche": "sustainable-living", "followers": 9000, "median_ratio": 3.1, "eng_rate": 0.09, "hook_strength": 0.9,
      "posts_per_week": 5.0, "city": "Pune"}),
    ("Sneha Pillai", "+919100000009", {"instagram": "sneha.makes.home"},
     {"niche": "home-decor", "secondary_niche": "sustainable-living", "followers": 15500, "median_ratio": 1.4,
      "eng_rate": 0.06, "hook_strength": 0.5, "posts_per_week": 2.8, "city": "Kochi"}),
    ("Zoya Khan", "+919100000010", {"instagram": "zoyafits"},
     {"niche": "fitness", "followers": 72000, "median_ratio": 0.7, "eng_rate": 0.044, "hook_strength": 0.45,
      "posts_per_week": 3.5, "city": "Hyderabad"}),
    ("Aditya Rao", "+919100000011", {"instagram": "aditya.eats"},
     {"niche": "food-reviews", "followers": 26000, "median_ratio": 2.8, "eng_rate": 0.075, "hook_strength": 0.8,
      "posts_per_week": 4.2, "city": "Indore"}),
    ("Pooja Shah", "+919100000012", {"instagram": "pooja.paise"},
     {"niche": "personal-finance", "followers": 31000, "median_ratio": 1.8, "eng_rate": 0.058, "hook_strength": 0.7,
      "posts_per_week": 3.0, "city": "Ahmedabad"}),
    ("Rohan Das", "+919100000013", {"youtube": "rohan.tech"},
     {"niche": "tech-gadgets", "followers": 54000, "median_ratio": 1.1, "eng_rate": 0.04, "hook_strength": 0.5,
      "posts_per_week": 2.0, "city": "Kolkata"}),
    ("Nikhil Das", "+919100000014", {"instagram": "nikhil.groomed"},
     {"niche": "fashion-men", "followers": 47000, "median_ratio": 0.9, "eng_rate": 0.053, "hook_strength": 0.5,
      "posts_per_week": 2.6, "city": "Pune"}),
    ("Lakshmi Raman", "+919100000015", {"instagram": "lakshmi.glow"},
     {"niche": "skincare", "secondary_niche": "wellness", "followers": 12000, "median_ratio": 2.0, "eng_rate": 0.066,
      "hook_strength": 0.66, "posts_per_week": 3.2, "city": "Chennai"}),
    # Accounts the fraud screen should catch (CR-4).
    ("Vikram Bose", "+919100000016", {"instagram": "vikram.viral"},
     {"niche": "skincare", "followers": 6000, "fraud": "bought_views", "city": "Jaipur"}),
    ("Simran Arora", "+919100000017", {"instagram": "simranstyles"},
     {"niche": "fashion-women", "followers": 21000, "fraud": "comment_bots", "city": "Chandigarh"}),
]


def connect(db, uid: str, platform: str, handle: str, overrides: dict):
    ensure_account(db, platform, handle, overrides=overrides)
    db.commit()
    from .models import FakeAccount
    acc = db.query(FakeAccount).filter_by(platform=platform, handle=handle).first()
    connections.callback(db, platform, _FakeBase.issue_code(acc.external_id),
                         sign_state({"uid": uid, "platform": platform}))


def topup(db, org: Org, rupees: int, actor: str):
    out = money.create_topup(db, org, rupees * 100, actor)
    rzp = FakeRazorpay(db)
    resp = rzp.simulate_checkout(out["order_id"])
    db.commit()
    raw, sig = rzp.webhook_for("payment.captured", "payment", rzp.get_payment(resp["razorpay_payment_id"]))
    money.handle_webhook(db, raw, sig)


def post_and_submit(db, hire: Hire, caption: str, quality: float = 1.0):
    from .models import FakeAccount, PlatformAccount
    from .providers.fake_world import create_post
    brief = db.get(briefs.Brief, hire.brief_id)
    platform = brief.platforms[0]
    acc = db.query(PlatformAccount).filter_by(creator_id=hire.creator_id, platform=platform).first()
    fa = db.get(FakeAccount, acc.external_id)
    m = create_post(db, fa, caption, posted_at=clock.now() - timedelta(minutes=20),
                    seed=f"seed:{hire.id}", quality_boost=quality)
    db.commit()
    briefs.accept_contract(db, hire, hire.creator_id)
    return briefs.submit(db, hire, hire.creator_id, m.permalink)


def main():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    clock.set_offset(-120)
    db = SessionLocal()
    clock.persist(db)
    db.commit()
    jobs.ensure_recurring(db)

    ops_user = User(phone="+919000000003", role="ops")
    arjun = User(phone="+919000000002", role="brand_member")
    meera = User(phone="+919000000004", role="brand_member")
    db.add_all([ops_user, arjun, meera])
    db.flush()
    kesari = Org(name="Kesari Naturals", gstin="29ABCDE1234F1Z5", gst_verified=True, category="Beauty & personal care",
                 city="Bengaluru", website="kesarinaturals.in", instagram_handle="kesarinaturals", created_by=arjun.id,
                 description="Ayurvedic skincare: face oils, lip balms and serums made in small batches.", plan="growth")
    loop = Org(name="Loop Bottles", gstin="27AAKCL9876M1Z2", gst_verified=True, category="Home & kitchen", city="Pune",
               website="loopbottles.in", instagram_handle="loopbottles", created_by=meera.id,
               description="Refillable glass bottles and plastic-free kitchen refills.")
    db.add_all([kesari, loop])
    db.flush()
    db.add_all([OrgMember(org_id=kesari.id, user_id=arjun.id, role="owner"),
                OrgMember(org_id=loop.id, user_id=meera.id, role="owner")])
    db.commit()

    uids = {}
    for name, phone, handles, persona in CREATORS:
        u = User(phone=phone, role="creator")
        db.add(u)
        db.flush()
        db.add(CreatorProfile(user_id=u.id, display_name=name, city=persona.get("city")))
        db.commit()
        uids[name] = u.id
        for platform, handle in handles.items():
            connect(db, u.id, platform, handle, persona)
    jobs.run_due(limit=500)
    db.expire_all()
    for cp in db.query(CreatorProfile).all():
        scoring.run_score(db, cp.user_id, trigger="seed")
    db.commit()

    topup(db, kesari, 3_00_000, arjun.id)
    topup(db, loop, 1_00_000, meera.id)

    t = clock.now()
    angles = lambda *hooks: [{"title": h[0], "hook": h[1], "format": h[2], "length_s": 25, "source": "ai",
                              "why_now": h[3], "trend_ref": h[4]} for h in hooks]
    night_oil = briefs.upsert(db, kesari, {
        "title": "Kumkumadi Night Oil launch", "product": "Kumkumadi night face oil, ₹649, ships pan-India",
        "goal": "awareness", "platforms": ["instagram"], "pay_model": "cpm", "cpm_paise": 6000, "cap_paise": 9_000_00,
        "min_tier": "bronze", "niches": ["skincare", "makeup"], "max_creators": 4, "tracking_days": 30,
        "deadline": t + timedelta(days=10), "usage_rights": "organic_paid_90d",
        "dos": ["Show the oil on skin in the first 3 seconds", "Mention it's for night use"],
        "donts": ["No medical or cure claims", "No filters on skin results"],
        "required_elements": {"mention": "@kesarinaturals", "hashtags": ["#ad", "#kumkumadi"], "disclosure": True},
        "angles": angles(("Ingredient explainer", "What is kumkumadi, and why is everyone using it?", "question",
                          "Ingredient explainers are up 41% on saves.", "yt:IN:mostPopular:howto:ingredient-explainers"),
                         ("Day 1 vs day 14", "Day 1 vs day 14 of kumkumadi at night", "before/after",
                          "Before/after drives saves.", "ig:hashtag:#empties")),
    }, arjun.id)
    briefs.publish(db, night_oil, kesari, arjun.id)
    lip = briefs.upsert(db, kesari, {
        "title": "Winter Lip Care", "product": "Saffron lip balm, ₹299, ships pan-India",
        "goal": "orders", "platforms": ["instagram"], "pay_model": "hybrid", "flat_paise": 1_500_00, "cpm_paise": 5000,
        "cap_paise": 6_000_00, "min_tier": "bronze", "niches": ["skincare", "makeup"], "max_creators": 6,
        "deadline": t + timedelta(days=21), "usage_rights": "organic",
        "dos": ["Use it on camera", "Mention the code KESARI10"], "donts": ["No medical claims"],
        "required_elements": {"mention": "@kesarinaturals", "hashtags": ["#ad"], "disclosure": True,
                              "discount_code": "KESARI10"},
        "angles": angles(("Dupe or dud", "₹299 vs ₹2,999 lip balm: can you tell?", "contrarian",
                          "Dupe-or-dud is up 33% on shares.", "ig:audio:dupe-or-dud"),
                         ("POV winter", "POV: Delhi winter and your lips are cracking", "POV",
                          "Seasonal window opens now.", "evergreen")),
    }, arjun.id)
    briefs.publish(db, lip, kesari, arjun.id)
    serum = briefs.upsert(db, kesari, {
        "title": "Glow Serum: creator seeding", "product": "Vitamin C + saffron serum, ₹799", "goal": "awareness",
        "platforms": ["instagram", "youtube"], "pay_model": "cpm", "cpm_paise": 9000, "cap_paise": 18_000_00,
        "min_tier": "gold", "niches": ["skincare"], "max_creators": 3, "deadline": t + timedelta(days=30),
        "required_elements": {"mention": "@kesarinaturals", "hashtags": ["#ad"], "disclosure": True},
    }, arjun.id)
    briefs.publish(db, serum, kesari, arjun.id)
    briefs.upsert(db, kesari, {"title": "Monsoon Repair Serum", "product": "Lightweight gel serum for humid weather",
                               "pay_model": "cpm", "cpm_paise": 5000, "cap_paise": 5_000_00, "niches": ["skincare"],
                               "max_creators": 5}, arjun.id)
    diwali = briefs.upsert(db, loop, {
        "title": "Plastic-free Diwali", "product": "Refillable glass bottle kit, ₹1,199", "goal": "orders",
        "platforms": ["instagram"], "pay_model": "flat", "flat_paise": 6_000_00, "min_tier": "bronze",
        "niches": ["sustainable-living", "home-decor"], "max_creators": 4, "deadline": t + timedelta(days=12),
        "required_elements": {"mention": "@loopbottles", "hashtags": ["#ad"], "disclosure": True},
        "dos": ["Show the refill in action"], "donts": ["Don't compare with named brands"],
    }, meera.id)
    briefs.publish(db, diwali, loop, meera.id)
    db.commit()

    def apply(name, brief, pitch):
        try:
            return briefs.apply(db, db.get(CreatorProfile, uids[name]), brief, pitch, None)
        except ApiError as e:
            print(f"  skip apply {name} -> {brief.title}: {e.code} {e.details}")

    for n, pitch in [("Kavya Menon", "My kumkumadi explainer did 60K views last month; I'll do a day 1 vs 14."),
                     ("Meher Kapoor", "Night routine Reels are my best format: 2x my median views."),
                     ("Harleen Gill", "I'll pair it with a GRWM-to-bed transition, my top hook pattern."),
                     ("Lakshmi Raman", "Tamil voiceover version for South India reach."),
                     ("Tanvi Iyer", "Honest review format, my audience trusts my ingredient breakdowns.")]:
        apply(n, night_oil, pitch)
    for n, pitch in [("Meher Kapoor", "Lip care is evergreen on my page; dupe-or-dud is my best format."),
                     ("Divya Nair", "Winter skincare series starts next week; happy to include it."),
                     ("Lakshmi Raman", "Short POV with the KESARI10 code pinned.")]:
        apply(n, lip, pitch)
    for n, pitch in [("Ananya Rao", "I did a plastic-free Diwali series last year: 6.9% engagement."),
                     ("Ishaan Verma", "Zero-waste refills are my whole niche. Reel + story set.")]:
        apply(n, diwali, pitch)
    db.commit()

    # Hire top 3 on the launch brief and get them posting.
    for n in ["Kavya Menon", "Meher Kapoor", "Harleen Gill"]:
        kyc.submit(db, db.get(CreatorProfile, uids[n]), {"Kavya Menon": "AKVPM4821K", "Meher Kapoor": "BMKPK7712L",
                                                        "Harleen Gill": "CHGPG3390M"}[n], n, "HDFC0001234",
                   "50100234567812", None, None)
    hires = []
    for n in ["Kavya Menon", "Meher Kapoor", "Harleen Gill"]:
        app = db.query(Application).filter_by(brief_id=night_oil.id, creator_id=uids[n]).first()
        hires.append(briefs.accept(db, app, kesari, arjun.id))
    for h, q in zip(hires, [1.5, 1.1, 1.3]):
        post_and_submit(db, h, "Kumkumadi at night, 14 days in. @kesarinaturals #ad #kumkumadi #skincare", q)

    jobs.advance(24)
    db.expire_all()
    d1 = db.query(Deliverable).filter_by(hire_id=hires[0].id).first()
    briefs.approve(db, d1.id, kesari.id, arjun.id, {"brief_adherence": 5, "content_quality": 5, "would_book_again": True})
    # Bought views on the second creator's post: the A6 filter should hold them.
    from .models import FakeMedia, MediaItem
    d2 = db.query(Deliverable).filter_by(hire_id=hires[1].id).first()
    fm = db.get(FakeMedia, db.get(MediaItem, d2.media_item_id).external_media_id)
    fm.bot_views, fm.bot_at = 1_500_000, clock.now()
    db.commit()

    jobs.advance(60)  # -> -36 h: the 72 h window has closed for the others, auto-approve fires
    db.expire_all()
    kyc.submit(db, db.get(CreatorProfile, uids["Ananya Rao"]), "DARPR5521Q", "Ananya Rao", None, None,
               "ananya@okicici", None)
    app = db.query(Application).filter_by(brief_id=diwali.id, creator_id=uids["Ananya Rao"]).first()
    h = briefs.accept(db, app, loop, meera.id)
    d = post_and_submit(db, h, "Diwali, minus the plastic. Refill kit from @loopbottles #ad #plasticfreediwali")
    jobs.advance(12)
    db.expire_all()
    briefs.dispute(db, d.id, loop.id, meera.id,
                   "The bottle is only visible for 2 seconds at the end; the brief asked to show the refill in action.",
                   [])
    jobs.advance(24)  # back to the present
    db.close()
    print("Seeded. Clock offset now", clock.offset_hours(), "h")


if __name__ == "__main__":
    main()
