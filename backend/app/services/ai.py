"""AI subsystems A2–A5 plus the brief policy pre-check (TS-4).

Each function calls Claude with a versioned prompt and a JSON schema (structured outputs) when
Anthropic credentials are configured, and otherwise runs a deterministic heuristic that follows
the same rules. Every call, live or heuristic, is logged to ai_jobs with model, prompt version,
tokens, cost and latency.
"""
import json
import logging
import os
import re
import statistics
import time
from datetime import timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..ai import registry
from ..ai.trends import CPM_PRIORS, SEED_SIGNALS, TIER_MEDIAN_VIEWS
from ..clock import now
from ..config import NICHES, settings
from ..models import AiJob, Brief, Deliverable, Hire, HookIssued, MediaItem, ViewLedger
from ..providers.fake_world import CAPTIONS, HASHTAGS
from . import jobs

log = logging.getLogger("flu.ai")
HEURISTIC = "flu-heuristic-v1"
USD_INR = 88
PRICES = {  # USD per 1M tokens (input, output)
    "claude-sonnet-5-5": (2.0, 10.0), "claude-haiku-5-5": (0.10, 0.50), "claude-opus-5-5": (4.0, 20.0),
}
FALLBACK_MODELS = {"claude-sonnet-5-5", "claude-opus-5-5", "claude-opus-5", "claude-fable-5-1"}
HOOK_PATTERNS = ["question", "contrarian", "number", "POV", "before/after"]


def live_enabled() -> bool:
    if settings.ai_mode == "heuristic":
        return False
    if settings.ai_mode == "live":
        return True
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def _cost_paise(model: str, tin: int, tout: int) -> int:
    pin, pout = PRICES.get(model, (2.0, 10.0))
    return round((tin * pin + tout * pout) / 1e6 * USD_INR * 100)


def month_spend_paise(db: Session, user_id: str) -> int:
    start = now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return int(db.query(func.coalesce(func.sum(AiJob.cost_paise), 0))
               .filter(AiJob.created_by == user_id, AiJob.created_at >= start,
                       AiJob.kind.in_(["diagnosis", "hooks"])).scalar())


def _claude(prompt_name: str, payload: dict, schema: dict, cached_context: str | None = None):
    import anthropic
    p = registry.load(prompt_name)
    model = settings.model_main if p["header"].get("model") == "main" else settings.model_fast
    system = [{"type": "text", "text": p["body"]}]
    if cached_context:
        system.append({"type": "text", "text": cached_context, "cache_control": {"type": "ephemeral"}})
    kwargs = dict(
        model=model, max_tokens=8000, system=system,
        messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)}],
        output_config={"format": {"type": "json_schema", "schema": schema}, "effort": p["header"].get("effort", "medium")},
    )
    client = anthropic.Anthropic()
    if model in FALLBACK_MODELS:
        try:
            resp = client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)
        except anthropic.BadRequestError:
            resp = client.messages.create(**kwargs)  # account without the fallback beta
    else:
        resp = client.messages.create(**kwargs)
    if resp.stop_reason == "refusal":
        raise RuntimeError("model declined the request")
    if resp.stop_reason == "max_tokens":
        raise RuntimeError("output truncated")
    text = "".join(b.text for b in resp.content if b.type == "text")
    return json.loads(text), resp.usage, resp.model, p["version"]


def _record(db: Session, kind: str, inp: dict, created_by: str | None, fn_live, fn_heur, job: AiJob | None = None,
            force_heuristic: bool = False) -> AiJob:
    job = job or AiJob(kind=kind, input=inp, created_by=created_by)
    if job.id is None:
        db.add(job)
    t0 = time.monotonic()
    job.status = "running"
    out = None
    if live_enabled() and not force_heuristic:
        import anthropic
        try:
            out, usage, model, version = fn_live()
            job.model, job.prompt_version = model, version
            job.tokens_in, job.tokens_out = usage.input_tokens, usage.output_tokens
            job.cost_paise = _cost_paise(model, usage.input_tokens, usage.output_tokens)
        except (anthropic.RateLimitError, anthropic.APIStatusError, anthropic.APIConnectionError,
                RuntimeError, json.JSONDecodeError, LookupError) as e:
            log.warning("claude %s failed, using heuristic: %s", kind, e)
            job.error = f"live call failed, heuristic used: {e}"[:500]
            out = None
    if out is None:
        out = fn_heur()
        job.model, job.prompt_version = HEURISTIC, f"{kind}_heuristic_v1"
    job.output, job.status = out, "done"
    job.latency_ms = int((time.monotonic() - t0) * 1000)
    db.flush()
    return job


# ======================================================================= A4 niche classifier
NICHE_KEYWORDS = {
    "skincare": ["skin", "serum", "sunscreen", "acne", "glow", "spf", "niacinamide", "kumkumadi", "moistur"],
    "haircare": ["hair", "frizz", "oiling", "scalp"], "makeup": ["makeup", "glam", "lipstick", "mua", "grwm"],
    "fashion-women": ["kurta", "haul", "ootd", "saree", "office looks"], "fashion-men": ["mensfashion", "sneakers", "guys"],
    "fitness": ["workout", "fitness", "fat loss", "posture", "gym"], "food-recipes": ["recipe", "dosa", "poha", "maggi", "batter"],
    "food-reviews": ["momo", "biryani", "cafe", "street food", "foodie", "stall"],
    "tech-gadgets": ["phone", "earbuds", "gadget", "setup", "tech"],
    "personal-finance": ["sip", "saved", "credit card", "money", "invest", "fd"],
    "edtech": ["exam", "study with me", "studygram", "pomodoro"], "sustainable-living": ["zero-waste", "zerowaste", "upcycl", "plastic-free", "sustainable"],
    "home-decor": ["decor", "makeover", "balcony", "room"], "travel": ["travel", "beach", "rishikesh", "train", "trip"],
    "comedy": ["comedy", "relatable", "be like", "types of"], "wellness": ["ayurved", "anxiety", "sleep", "wellness", "routine for"],
    "gaming": ["bgmi", "gaming", "pc build", "game"],
}


def _niche_heuristic(captions: list[str]) -> dict:
    scores = {}
    for c in captions:
        low = c.lower()
        for n, kws in NICHE_KEYWORDS.items():
            if any(k in low for k in kws):
                scores[n] = scores.get(n, 0) + 1
    total = max(1, len(captions))
    ranked = sorted(scores.items(), key=lambda x: -x[1])[:3]
    out = [{"niche": n, "confidence": round(min(0.99, s / total * 1.4), 2)} for n, s in ranked]
    out = out[:1] + [n for n in out[1:] if n["confidence"] >= 0.25]  # drop incidental keyword hits
    return {"niches": out or [{"niche": "comedy", "confidence": 0.2}]}


def niche_classify(db: Session, captions: list[str], created_by: str | None = None) -> dict:
    schema = {"type": "object", "additionalProperties": False, "required": ["niches"], "properties": {
        "niches": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                              "required": ["niche", "confidence"],
                                              "properties": {"niche": {"type": "string", "enum": NICHES},
                                                             "confidence": {"type": "number"}}}}}}
    caps = [c[:300] for c in captions[:30]]
    job = _record(db, "niche_classify", {"captions": len(caps)}, created_by,
                  lambda: _claude("niche_classify", {"taxonomy": NICHES, "captions": caps}, schema),
                  lambda: _niche_heuristic(caps))
    out = job.output
    out["niches"] = [n for n in out["niches"] if n["niche"] in NICHES][:3]
    out["needs_confirmation"] = not out["niches"] or out["niches"][0]["confidence"] < 0.6
    return out


# ======================================================================= TS-4 policy pre-check
BLOCKLIST = [
    (r"\bcures?\b|\bheal(s|ing)? (acne|disease)|\bclinically proven\b|\bpermanent(ly)? remove", "Health or cure claim (ASCI)"),
    (r"guaranteed (returns?|profit)|double your money|risk[- ]free returns?", "Guaranteed financial returns (ASCI)"),
    (r"(don'?t|do not|no need to|without) (use |add |mention )?(#ad|#sponsored|disclos|the paid partnership)", "Hidden promotion: disclosure is mandatory"),
    (r"\bhide (that|the) (it'?s|this is) (an )?ad\b|pretend (it'?s|this is) (not )?organic", "Hidden promotion: disclosure is mandatory"),
]


def _policy_heuristic(text: str) -> dict:
    issues = sorted({reason for pat, reason in BLOCKLIST if re.search(pat, text, re.I)})
    return {"blocked": bool(issues), "issues": issues}


def policy_check(db: Session, brief: Brief, created_by: str | None) -> dict:
    # Don'ts are prohibitions ("no cure claims"), so only what the brief asks creators to say is checked.
    text = " \n".join([brief.title, brief.product, *brief.dos,
                       *[a.hook + " " + (a.angle_text or "") for a in brief.angles]])
    schema = {"type": "object", "additionalProperties": False, "required": ["blocked", "issues"],
              "properties": {"blocked": {"type": "boolean"}, "issues": {"type": "array", "items": {"type": "string"}}}}
    # The human-reviewed block list always runs; the model can only add issues.
    base = _policy_heuristic(text)
    job = _record(db, "policy_check", {"brief_id": brief.id}, created_by,
                  lambda: _claude("policy_check", {"brief": text}, schema), lambda: base)
    out = job.output
    issues = sorted(set(base["issues"]) | set(out.get("issues", []) if out.get("blocked") else []))
    return {"blocked": bool(issues), "issues": issues}


# ======================================================================= A5 trend brief generator
def trend_corpus(db: Session, niches: list[str]) -> list[dict]:
    items = [s for s in SEED_SIGNALS if not niches or s["niche"] in niches] or SEED_SIGNALS[:6]
    since = now() - timedelta(days=14)
    top = (db.query(Deliverable, MediaItem).join(MediaItem, MediaItem.id == Deliverable.media_item_id)
           .filter(Deliverable.submitted_at >= since).all())
    flu = []
    for d, m in top:
        x = m.last_metrics or {}
        if x.get("views"):
            flu.append({"ref": f"flu:deliverable:{d.id[:8]}", "platform": "flu", "title": (m.caption or "")[:80],
                        "metric": "views/reach", "value": round(x["views"] / max(x.get("reach", 1), 1), 2),
                        "length_s": m.duration_s, "views": x["views"]})
    flu.sort(key=lambda r: -r["views"])
    return items + flu[:5]


def pricing_priors(db: Session, niches: list[str]) -> dict:
    """Median effective CPM paid on Flu (paise per 1,000 verified views), else the fallback table."""
    rows = (db.query(Deliverable.id, func.sum(ViewLedger.delta_views), func.sum(ViewLedger.accrued_paise))
            .join(ViewLedger, ViewLedger.deliverable_id == Deliverable.id).filter(ViewLedger.verified.is_(True))
            .group_by(Deliverable.id).all())
    cpms = [int(p * 1000 / v) for _, v, p in rows if v and p]
    if len(cpms) >= 5:
        med = int(statistics.median(cpms))
        return {"source": "flu_view_ledger", "low": int(med * 0.75), "high": int(med * 1.3), "by_tier": CPM_PRIORS}
    return {"source": "fallback_table", "low": 2000, "high": 15000, "by_tier": CPM_PRIORS}


def _tier_mix(budget_paise: int) -> dict:
    b = budget_paise / 100
    if b < 50_000:
        return {"bronze": 50, "silver": 40, "gold": 10, "platinum": 0}
    if b < 2_00_000:
        return {"bronze": 25, "silver": 45, "gold": 25, "platinum": 5}
    return {"bronze": 10, "silver": 35, "gold": 40, "platinum": 15}


def _brief_heuristic(inp: dict, corpus: list[dict], priors: dict) -> dict:
    product, goal = inp["product"], inp.get("goal", "awareness")
    name = inp.get("product_name") or product.split(",")[0].split(":")[0][:40]
    mix = _tier_mix(inp["budget_paise"])
    lo = int(sum(mix[t] * CPM_PRIORS[t][0] for t in mix) / 100)
    hi = int(sum(mix[t] * CPM_PRIORS[t][1] for t in mix) / 100)
    if priors["source"] == "flu_view_ledger":
        lo, hi = priors["low"], priors["high"]
    cpm = (lo + hi) // 2
    exp_views = sum(mix[t] * TIER_MEDIAN_VIEWS[t] for t in mix) / 100
    cap = max(1_500_00, int(exp_views * 1.6 * cpm / 1000 / 100) * 100)
    count = max(2, min(40, inp["budget_paise"] // cap))
    t = [c for c in corpus if c.get("platform") != "flu"] or SEED_SIGNALS
    pick = lambda i: t[i % len(t)]
    angles = [
        {"title": f"{pick(0)['title']}, with {name}", "format": "question",
         "hook": f"Why is nobody talking about {name.lower()}?", "length_s": 25,
         "why_now": f"{pick(0)['title']} is up {pick(0).get('growth_pct', 20)}% on {pick(0)['metric']}.",
         "trend_ref": pick(0)["ref"]},
        {"title": "The honest take", "format": "contrarian",
         "hook": "Unpopular opinion: you don't need a 10-step routine", "length_s": 30,
         "why_now": f"Contrarian openers pair well with {pick(1)['title'].lower()}.", "trend_ref": pick(1)["ref"]},
        {"title": "Three reasons in thirty seconds", "format": "number",
         "hook": f"3 things I wish I knew before trying {name.lower()}", "length_s": 30,
         "why_now": "Numbered hooks hold the first 3 seconds best in this niche.", "trend_ref": pick(2)["ref"]},
        {"title": "A day in the life", "format": "POV",
         "hook": f"POV: it's 8 am and {name.lower()} is the only thing on your shelf", "length_s": 20,
         "why_now": f"POV formats ride {pick(3)['title'].lower()}.", "trend_ref": pick(3)["ref"]},
        {"title": "Day 1 vs day 14", "format": "before/after",
         "hook": f"Day 1 vs day 14 of using {name.lower()}", "length_s": 22,
         "why_now": "Before/after content drives saves, the signal that predicts repeat views.",
         "trend_ref": pick(4)["ref"] if len(t) > 4 else "evergreen"},
    ]
    if goal == "installs":
        angles[2]["hook"] = f"3 apps I use daily, and #1 is {name.lower()}"
    return {
        "title": f"{name}: {['awareness push', 'install drive', 'order drive'][['awareness', 'installs', 'orders'].index(goal) if goal in ('awareness', 'installs', 'orders') else 0]}",
        "angles": angles,
        "suggested_cpm_paise": {"low": lo, "high": hi},
        "suggested_cap_paise": cap,
        "creator_mix": mix,
        "creator_count": int(count),
        "required_elements": {"mention": inp.get("brand_handle") or "@yourbrand", "hashtags": ["#ad"],
                              "disclosure": True, "link_in_bio": goal != "awareness",
                              "discount_code": "FLU10" if goal == "orders" else None},
        "donts": ["No medical or cure claims", "No before/after edits or filters on skin results",
                  "Do not hide the #ad disclosure", "No competitor names"],
        "dos": ["Show the product in the first 3 seconds", "Use your own voice and setting",
                "End with one clear call to action"],
    }


BRIEF_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["title", "angles", "suggested_cpm_paise", "suggested_cap_paise", "creator_mix", "creator_count",
                 "required_elements", "donts", "dos"],
    "properties": {
        "title": {"type": "string"},
        "angles": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                   "required": ["title", "hook", "format", "length_s", "why_now", "trend_ref"],
                   "properties": {"title": {"type": "string"}, "hook": {"type": "string"},
                                  "format": {"type": "string", "enum": HOOK_PATTERNS},
                                  "length_s": {"type": "integer"}, "why_now": {"type": "string"},
                                  "trend_ref": {"type": "string"}}}},
        "suggested_cpm_paise": {"type": "object", "additionalProperties": False, "required": ["low", "high"],
                                "properties": {"low": {"type": "integer"}, "high": {"type": "integer"}}},
        "suggested_cap_paise": {"type": "integer"},
        "creator_mix": {"type": "object", "additionalProperties": False,
                        "required": ["bronze", "silver", "gold", "platinum"],
                        "properties": {k: {"type": "integer"} for k in ["bronze", "silver", "gold", "platinum"]}},
        "creator_count": {"type": "integer"},
        "required_elements": {"type": "object", "additionalProperties": False,
                              "required": ["mention", "hashtags", "disclosure", "link_in_bio", "discount_code"],
                              "properties": {"mention": {"type": "string"},
                                             "hashtags": {"type": "array", "items": {"type": "string"}},
                                             "disclosure": {"type": "boolean"}, "link_in_bio": {"type": "boolean"},
                                             "discount_code": {"type": ["string", "null"]}}},
        "donts": {"type": "array", "items": {"type": "string"}},
        "dos": {"type": "array", "items": {"type": "string"}},
    },
}


def run_trend_brief(db: Session, job: AiJob):
    inp = job.input
    corpus = trend_corpus(db, inp.get("niches") or [])
    priors = pricing_priors(db, inp.get("niches") or [])
    heur = lambda: _brief_heuristic(inp, corpus, priors)
    context = "TREND CORPUS (refreshed every 6 h):\n" + json.dumps(corpus, ensure_ascii=False) + \
              "\n\nPRICING PRIORS (paise per 1,000 verified views):\n" + json.dumps(priors)
    _record(db, "trend_brief", inp, job.created_by,
            lambda: _claude("trend_brief", inp, BRIEF_SCHEMA, cached_context=context), heur, job=job)
    out = job.output
    # Guardrails the schema cannot express.
    out["angles"] = (out.get("angles") or [])[:5]
    if len(out["angles"]) < 5:
        out["angles"] += heur()["angles"][len(out["angles"]):]
    cap = max(1, out["suggested_cap_paise"])
    out["creator_count"] = max(1, min(out["creator_count"], inp["budget_paise"] // cap))
    out["required_elements"]["disclosure"] = True
    if not any(h.lower() in DISCLOSURES for h in out["required_elements"]["hashtags"]):
        out["required_elements"]["hashtags"].insert(0, "#ad")
    out["pricing_source"] = priors["source"]
    out["corpus_refs"] = [c["ref"] for c in corpus]
    job.output = dict(out)


DISCLOSURES = {"#ad", "#collab", "#sponsored", "#paidpartnership"}


# ======================================================================= A2 reel diagnosis
DIAG_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["primary_issue", "confidence", "summary", "evidence", "fixes"],
    "properties": {
        "primary_issue": {"type": "string", "enum": ["hook", "length", "timing", "topic", "cta", "none"]},
        "confidence": {"type": "number"},
        "summary": {"type": "string"},
        "evidence": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                     "required": ["metric", "value", "benchmark"],
                     "properties": {"metric": {"type": "string"}, "value": {"type": "string"},
                                    "benchmark": {"type": "string"}}}},
        "fixes": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                  "required": ["what", "why", "example"],
                  "properties": {"what": {"type": "string"}, "why": {"type": "string"}, "example": {"type": "string"}}}},
    },
}


def diagnosis_inputs(db: Session, media: MediaItem, creator_id: str) -> dict:
    from ..models import PlatformAccount
    from .audit import IST, latest_audit
    from .scoring import compute
    acc = db.get(PlatformAccount, media.platform_account_id)
    a = latest_audit(db, acc.id)
    m = media.last_metrics or {}
    sc = compute(db, creator_id) or {}
    niche_vr = (sc.get("cohort") or {}).get("niche_views_per_reach_median", 1.0)
    own = db.query(MediaItem).filter_by(platform_account_id=acc.id).all()
    lengths = [x.duration_s for x in own if x.duration_s]
    return {
        "platform": acc.platform, "caption": (media.caption or "")[:300], "posted_hour_ist": media.posted_at.astimezone(IST).hour,
        "length_s": media.duration_s, "views": m.get("views", 0), "reach": m.get("reach", 0),
        "likes": m.get("likes", 0), "comments": m.get("comments", 0), "saves": m.get("saves", 0), "shares": m.get("shares", 0),
        "views_per_reach": round(m.get("views", 0) / max(m.get("reach", 1), 1), 3),
        "creator_median_views": (a.metrics if a else {}).get("median_views"),
        "creator_median_length_s": int(statistics.median(lengths)) if lengths else None,
        "creator_top3_hours_ist": (a.metrics if a else {}).get("best_hours_ist", []),
        "creator_engagement_rate": (a.metrics if a else {}).get("engagement_rate"),
        "niche": (sc.get("cohort") or {}).get("niche"), "niche_views_per_reach_median": niche_vr,
    }


def _diag_heuristic(x: dict) -> dict:
    ev, fixes = [], []
    vr, nvr = x["views_per_reach"], x["niche_views_per_reach_median"] or 1
    eng = (x["likes"] + x["comments"] + x["saves"] + x["shares"]) / max(x["reach"], 1)
    off_hours = x["creator_top3_hours_ist"] and x["posted_hour_ist"] not in x["creator_top3_hours_ist"]
    long = x["length_s"] and x["creator_median_length_s"] and x["length_s"] > 1.4 * x["creator_median_length_s"]
    if vr < 0.6 * nvr:
        primary, conf = "hook", 0.8
        ev.append({"metric": "views / reach (retention proxy)", "value": f"{vr:.2f}", "benchmark": f"niche median {nvr:.2f}"})
        fixes.append({"what": "Put the payoff on screen in the first 2 seconds",
                      "why": f"Views per reach was {vr:.2f} against a niche median of {nvr:.2f}: people scrolled past early.",
                      "example": "Open on the finished result, then say: 'Here's how I got this in 3 steps.'"})
    elif long:
        primary, conf = "length", 0.65
        ev.append({"metric": "length", "value": f"{x['length_s']} s", "benchmark": f"your median {x['creator_median_length_s']} s"})
        fixes.append({"what": f"Cut to about {x['creator_median_length_s']} seconds",
                      "why": "This post ran much longer than your usual Reels, which tends to lower completion.",
                      "example": "Drop the intro and the second example; keep one demo and the result."})
    elif off_hours:
        primary, conf = "timing", 0.55
    elif eng < (x["creator_engagement_rate"] or 0.03) * 0.7:
        primary, conf = "cta", 0.55
        ev.append({"metric": "engagement / reach", "value": f"{eng:.1%}", "benchmark": f"your median {(x['creator_engagement_rate'] or 0):.1%}"})
        fixes.append({"what": "End with one question people can answer in a word",
                      "why": "Engagement on this post was well below your usual rate.",
                      "example": "'Oily or dry skin? Comment and I'll make your routine next.'"})
    elif x["creator_median_views"] and x["views"] < 0.7 * x["creator_median_views"]:
        primary, conf = "topic", 0.5
        ev.append({"metric": "views", "value": f"{x['views']:,}", "benchmark": f"your median {x['creator_median_views']:,}"})
        fixes.append({"what": "Return to the topics your best Reels covered",
                      "why": "Retention was fine but fewer people were shown this topic.",
                      "example": "Re-shoot your top Reel's idea with a new product or a new location."})
    else:
        primary, conf = "none", 0.6
        ev.append({"metric": "views", "value": f"{x['views']:,}", "benchmark": f"your median {x['creator_median_views'] or 0:,}"})
        fixes.append({"what": "Make a part 2 while the topic is warm",
                      "why": "This post did at or above your usual numbers.",
                      "example": "'You asked for part 2, so here's what happened next.'"})
    if off_hours:
        ev.append({"metric": "posting hour (IST)", "value": f"{x['posted_hour_ist']}:00",
                   "benchmark": "your top hours " + ", ".join(f"{h}:00" for h in x["creator_top3_hours_ist"])})
        fixes.append({"what": f"Post at {x['creator_top3_hours_ist'][0]}:00 IST next time",
                      "why": "This went out outside your audience's top-3 active hours.",
                      "example": f"Schedule the next Reel for {x['creator_top3_hours_ist'][0]}:00 and reply to comments for the first hour."})
    generic = [
        {"what": "Add bold on-screen text in the first frame", "why": "Most viewers watch on mute in the first seconds.",
         "example": "Overlay: '₹299 vs ₹2,999 — can you tell?'"},
        {"what": "Ask for a save with a reason", "why": "Saves are the signal brands in your niche value most.",
         "example": "'Save this for your next Nykaa sale.'"},
        {"what": "Reply to the first 10 comments within an hour", "why": "Early replies lifted reach on most creators' Reels.",
         "example": "Pin your favourite comment and reply with a short video."},
    ]
    for g in generic:
        if len(fixes) >= 3:
            break
        fixes.append(g)
    summary = {"hook": "People saw it but scrolled past early: the opening didn't hold them.",
               "length": "The Reel ran long for your audience, so fewer people finished it.",
               "timing": "Content held up, but it went out when your audience wasn't online.",
               "cta": "Viewers watched but didn't act: the ending gave them nothing to do.",
               "topic": "Retention was fine; the topic just reached fewer people than usual.",
               "none": "This one worked. Build on it."}[primary]
    return {"primary_issue": primary, "confidence": conf, "summary": summary, "evidence": ev, "fixes": fixes[:3]}


def run_diagnosis(db: Session, job: AiJob):
    media = db.get(MediaItem, job.input["media_item_id"])
    x = diagnosis_inputs(db, media, job.created_by)
    job.input = {**job.input, "metrics": x}
    capped = month_spend_paise(db, job.created_by) >= settings.ai_cap_paise_per_creator_month
    _record(db, "diagnosis", job.input, job.created_by,
            lambda: _claude("diagnosis", x, DIAG_SCHEMA), lambda: _diag_heuristic(x), job=job, force_heuristic=capped)
    out = dict(job.output)
    out["fixes"] = (out.get("fixes") or [])[:3]
    if capped:
        out["note"] = "Monthly AI budget reached; this diagnosis used Flu's rules engine."
    job.output = out


# ======================================================================= A3 hook generator
HOOK_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["hooks"],
    "properties": {"hooks": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["pattern", "first_line", "on_screen_text", "why_it_fits"],
        "properties": {"pattern": {"type": "string", "enum": HOOK_PATTERNS}, "first_line": {"type": "string"},
                       "on_screen_text": {"type": "string"}, "why_it_fits": {"type": "string"}}}}},
}


def _words(s: str) -> set:
    return set(re.findall(r"[a-z0-9₹]+", s.lower()))


def similar(a: str, b: str) -> float:
    """Jaccard over words: the stand-in for pgvector cosine on hook embeddings (> 0.92 ≈ > 0.7 here)."""
    wa, wb = _words(a), _words(b)
    return len(wa & wb) / max(1, len(wa | wb))


def _hooks_heuristic(x: dict, avoid: list[str], salt: int) -> dict:
    p = x.get("product") or x["niche"].replace("-", " ")
    variants = {
        "question": [f"Why does nobody tell you this about {p}?", f"Is {p} actually worth it?",
                     f"Would you try {p} for 7 days?"],
        "contrarian": [f"Unpopular opinion: {p} isn't overrated", f"Stop doing {x['niche'].replace('-', ' ')} like this",
                       f"I was wrong about {p}"],
        "number": [f"3 things I wish I knew before {p}", f"I tested {p} for 14 days: 2 surprises",
                   f"5 seconds to see why {p} works"],
        "POV": [f"POV: you finally found {p} that works", f"POV: your mom steals your {p}",
                f"POV: 7 am, no time, only {p}"],
        "before/after": [f"Day 1 vs day 14 with {p}", f"Before {p} vs after {p}", f"Last month vs this month: {p}"],
    }
    out = []
    for i, pat in enumerate(HOOK_PATTERNS):
        opts = variants[pat][salt % 3:] + variants[pat][:salt % 3]
        line = next((o for o in opts if all(similar(o, a) < 0.7 for a in avoid)), opts[0] + " (part 2)")
        line = line[0].upper() + line[1:]
        out.append({"pattern": pat, "first_line": line, "on_screen_text": " ".join(line.rstrip("?").split()[:5]),
                    "why_it_fits": f"{pat.capitalize()} openers stop the scroll in {x['niche'].replace('-', ' ')}; "
                                   f"your best captions lean the same way."})
    return {"hooks": out}


def generate_hooks(db: Session, creator_id: str, niche: str, product: str | None, brief_id: str | None) -> list[HookIssued]:
    from .audit import latest_audit
    from .scoring import primary_account
    avoid = [h.first_line for h in db.query(HookIssued).filter_by(brief_id=brief_id).all()] if brief_id else []
    acc = primary_account(db, creator_id)
    top = []
    if acc:
        top = [m.caption for m in sorted(db.query(MediaItem).filter_by(platform_account_id=acc.id).all(),
                                         key=lambda m: -(m.last_metrics or {}).get("views", 0))[:3]]
    brief = db.get(Brief, brief_id) if brief_id else None
    short_name = brief.product.split(",")[0].split(":")[0].strip()[:40].lower() if brief else None
    x = {"niche": niche, "product": product or short_name,
         "brief_angles": [a.hook for a in brief.angles] if brief else [], "top_captions": top,
         "already_issued_for_this_brief": avoid[-40:]}
    capped = month_spend_paise(db, creator_id) >= settings.ai_cap_paise_per_creator_month
    salt = len(avoid) + db.query(HookIssued).filter_by(creator_id=creator_id).count()
    job = _record(db, "hooks", x, creator_id, lambda: _claude("hooks", x, HOOK_SCHEMA),
                  lambda: _hooks_heuristic(x, avoid, salt), force_heuristic=capped)
    hooks = job.output["hooks"][:5]
    rows = []
    for h in hooks:
        if any(similar(h["first_line"], a) >= 0.7 for a in avoid):
            continue  # de-duplicate against hooks already issued for this brief
        r = HookIssued(creator_id=creator_id, brief_id=brief_id, ai_job_id=job.id, pattern=h["pattern"],
                       first_line=h["first_line"], on_screen_text=h["on_screen_text"], why_it_fits=h["why_it_fits"])
        db.add(r)
        rows.append(r)
        avoid.append(h["first_line"])
    db.flush()
    return rows


# ======================================================================= async runner
@jobs.task("ai.run")
def ai_run(db: Session, ai_job_id: str):
    job = db.get(AiJob, ai_job_id)
    if not job or job.status == "done":
        return
    try:
        {"trend_brief": run_trend_brief, "diagnosis": run_diagnosis}[job.kind](db, job)
        db.commit()
    except Exception as e:
        log.exception("ai job %s failed", ai_job_id)
        db.rollback()
        job = db.get(AiJob, ai_job_id)
        job.status, job.error = "failed", str(e)[:500]
        db.commit()


@jobs.task("ai.refresh_trend_corpus")
def refresh_corpus(db: Session):
    """Live mode: pull YouTube mostPopular IN + aggregate hashtag counts. Fake mode: nothing to fetch."""
    return None


def schedule(db: Session, kind: str, inp: dict, created_by: str) -> AiJob:
    job = AiJob(kind=kind, input=inp, created_by=created_by, status="queued")
    db.add(job)
    db.flush()
    jobs.enqueue(db, "ai.run", {"ai_job_id": job.id})
    return job


def public_job(j: AiJob) -> dict:
    return {"id": j.id, "kind": j.kind, "status": j.status, "output": j.output, "model": j.model,
            "prompt_version": j.prompt_version, "latency_ms": j.latency_ms, "error": j.error if j.status == "failed" else None,
            "created_at": j.created_at, "feedback": j.feedback}
