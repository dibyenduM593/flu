"""Trend corpus for the Trend Brief Generator (A5).

Live mode refreshes this every 6 h from YouTube mostPopular (regionCode=IN), the top Flu
deliverables of the last 14 days, and aggregate hashtag counts. The seed list below stands in
for the external feeds in fake mode; Flu's own deliverables are always read from the database."""
SEED_SIGNALS = [
    {"ref": "yt:IN:mostPopular:howto:ingredient-explainers", "platform": "youtube", "niche": "skincare",
     "title": "Ingredient explainers (one ingredient, shown on skin)", "metric": "saves", "growth_pct": 41},
    {"ref": "ig:hashtag:#grwmdiwali", "platform": "instagram", "niche": "makeup",
     "title": "Festive get-ready-with-me", "metric": "reach", "growth_pct": 38},
    {"ref": "yt:IN:mostPopular:people:monsoon-skin", "platform": "youtube", "niche": "skincare",
     "title": "Monsoon skin fixes", "metric": "watch time", "growth_pct": 22},
    {"ref": "ig:hashtag:#regionalreview", "platform": "instagram", "niche": "skincare",
     "title": "Regional-language honest reviews (Tamil, Hindi, Kannada)", "metric": "views", "growth_pct": 29},
    {"ref": "ig:hashtag:#empties", "platform": "instagram", "niche": "skincare",
     "title": "Shelfies and empties: products I actually finished", "metric": "comments", "growth_pct": 17},
    {"ref": "ig:hashtag:#plasticfreediwali", "platform": "instagram", "niche": "sustainable-living",
     "title": "Plastic-free festive swaps", "metric": "shares", "growth_pct": 26},
    {"ref": "ig:audio:dupe-or-dud", "platform": "instagram", "niche": "makeup",
     "title": "Dupe or dud: ₹300 vs ₹3,000 side by side", "metric": "shares", "growth_pct": 33},
    {"ref": "yt:IN:mostPopular:food:hostel-recipes", "platform": "youtube", "niche": "food-recipes",
     "title": "Hostel and PG kitchen recipes", "metric": "views", "growth_pct": 31},
    {"ref": "ig:hashtag:#streetfoodrating", "platform": "instagram", "niche": "food-reviews",
     "title": "Rating every stall on one street", "metric": "reach", "growth_pct": 27},
    {"ref": "ig:hashtag:#sipexplained", "platform": "instagram", "niche": "personal-finance",
     "title": "60-second money explainers for first salaries", "metric": "saves", "growth_pct": 35},
    {"ref": "yt:IN:mostPopular:tech:under20k", "platform": "youtube", "niche": "tech-gadgets",
     "title": "Best under ₹20k comparisons", "metric": "views", "growth_pct": 24},
    {"ref": "ig:hashtag:#studywithme", "platform": "instagram", "niche": "edtech",
     "title": "Study-with-me timelapses before exams", "metric": "saves", "growth_pct": 30},
    {"ref": "ig:hashtag:#homeworkoutindia", "platform": "instagram", "niche": "fitness",
     "title": "No-equipment 20-minute routines", "metric": "saves", "growth_pct": 19},
    {"ref": "ig:hashtag:#officelooks", "platform": "instagram", "niche": "fashion-women",
     "title": "One kurta, five looks", "metric": "shares", "growth_pct": 28},
    {"ref": "ig:hashtag:#ayurvedichabits", "platform": "instagram", "niche": "wellness",
     "title": "Ayurvedic routines that stuck", "metric": "saves", "growth_pct": 21},
    {"ref": "ig:audio:mom-reacts", "platform": "instagram", "niche": "comedy",
     "title": "Mom reacts to my purchase", "metric": "shares", "growth_pct": 44},
]

# Fallback CPM bands (paise per 1,000 verified views) until view_ledger has data. [Guessing] in the PRD.
CPM_PRIORS = {"bronze": (2000, 6000), "silver": (2000, 6000), "gold": (5000, 15000), "platinum": (5000, 15000)}
TIER_MEDIAN_VIEWS = {"bronze": 2500, "silver": 8000, "gold": 22000, "platinum": 60000}
