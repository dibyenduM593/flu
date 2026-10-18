# Flu

A performance-paid UGC marketplace for India. Brands post briefs and fund them into escrow, creators post Reels and
Shorts from their own accounts, views are verified, and money is released from escrow on approval. Every post feeds a
Creator Score that ranks creators for the next brief and tells them what to fix.

This repo implements the MVP from *Flu — Technical PRD v1 (Flu × SideShift combined)* as a runnable web app:

- **`backend/`**: FastAPI + SQLAlchemy (SQLite locally, Postgres-ready), a job queue with an in-process worker, and
  one adapter per external provider with a simulator behind each.
- **`web/`**: Next.js 15 (App Router, TypeScript). One app with three role-based consoles: creator (mobile-first),
  brand and ops.

## Run it

You need Python 3.12+ and Node 20+.

```bash
cd backend
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt     # macOS/Linux: .venv/bin/pip
.venv/Scripts/python -m app.seed                  # builds a demo marketplace (about 30 s)
.venv/Scripts/python -m uvicorn app.main:app --port 8000
```

```bash
cd web
npm install
npm run dev                                       # http://localhost:3000
```

Sign in with a demo account. In dev mode the OTP is shown on screen.

| Phone | Who |
| --- | --- |
| 90000 00001 | Riya Kulkarni, creator in Pune: Silver tier, not yet hired |
| 90000 00002 | Arjun at Kesari Naturals, skincare brand, Growth plan |
| 90000 00004 | Meera at Loop Bottles, home and kitchen brand |
| 90000 00003 | Flu ops: trust queue and simulator |

The seed drives the real services: it onboards 18 creators through the OAuth flow, funds wallets through Checkout plus
the signed webhook, publishes briefs, hires, posts, polls views for five simulated days, auto-approves, pays out, injects
bought views (held by the anomaly filter) and opens a dispute.

### The full loop in five minutes

1. **Riya**: Briefs → *Winter Lip Care* → apply. Locked briefs show what's missing (usually tier).
2. **Arjun**: Briefs → *Winter Lip Care* → Applicants (ranked 45% score / 25% niche / 15% expected views / 15%
   responsiveness) → Hire. The reserve moves into escrow.
3. **Riya**: My work → accept the contract → *Post a test Reel (simulator)* → Submit. Flu verifies the post is on her
   connected account and that the caption has the mention, #ad and the discount code.
4. **Ops**: Simulator → advance 3 days. Polls run at +1 h, +6 h, +24 h and then every 6 h; the 72-hour auto-approve fires.
5. **Riya**: Earnings. The payout waits for KYC; add a PAN and UPI ID and it moves to *Settling*, then *Paid*
   (with a UTR) once you advance the clock another two days.

Also try the Trend Brief Generator (Brands → New brief), Studio (post diagnosis, hooks, posting times), Creator Score,
and the trust queue (clear or reject held views, decide disputes, clear fraud flags).

## What's implemented (by PRD module)

| Module | In this build |
| --- | --- |
| M1 Creator onboarding and audit | Phone OTP + JWT with rotating refresh; Instagram/YouTube OAuth (Personal IG accounts refused); audit of the last 30 posts; fraud screen (views without engagement, follower spike, duplicate comments) to the ops queue; niche classifier; KYC (PAN hashed + last 4, bank penny-drop or UPI, Route linked account) |
| M2 Creator app | Home with tier, score, streak and qualifying briefs; feed ranked by expected earnings; apply; contract; deliverable submission with ownership and required-element checks; reel diagnosis; hook generator with de-duplication per brief; posting schedule; earnings ledger with TDS |
| M3 Brand console | Workspace (GSTIN gate above ₹50k top-ups); Trend Brief Generator; brief editor and publish gate (wallet ≥ every creator's reserve); ranked applicants, bulk hire top-N; 72 h approve/dispute; performance per creator and per day; directory and invites; plans; CSV payout export for the brand's CA |
| M4 Matching | MT-1 eligibility, MT-2 weighted ranking with breakdown, MT-3 expected earnings |
| M5 Tracking | TR-1 poll schedule, append-only snapshots, A6 anomaly holds, TR-4 freeze on deleted posts, stats-only daily polls to 90 days |
| M6 AI | Creator Score phase 1 (percentiles within niche cohort, tiers, "fastest lever"); diagnosis, hooks, trend brief, niche classification, ASCI policy pre-check, each with a versioned prompt and JSON schema, logged to `ai_jobs` with cost |
| M7 Money | Append-only double-entry ledger with derived balances; Razorpay Orders → signed webhook credit; Route transfers on hold per hire; daily release batches; 15/10/0% take rate; 18% GST on the fee; Section 194-O TDS with the ₹5 lakh exemption; invoices; settlement; daily reconciliation |
| M8 Trust and ops | Queue with reason codes; dispute flow (48 h creator response, ops decision); audit log on every money movement; idempotency keys on money-moving POSTs; OTP rate limit |

**AI:** with `ANTHROPIC_API_KEY` set, diagnosis, hooks and trend briefs call Claude Sonnet 5.5 (server-side refusal
fallbacks on), and classification and policy checks call Claude Haiku 5.5, all with structured outputs. Without a key, every AI feature uses
Flu's deterministic rules engine, which follows the same rules as the prompts in `backend/app/ai/prompts/`.

**Simulated in dev mode:** Instagram and YouTube (deterministic per-handle histories and view curves), Razorpay (orders,
checkout signature, webhooks, Route transfers, settlement), PAN/bank verification and OTP SMS. The consent screen and
checkout are pages under `/dev/*`. `PROVIDER_MODE=live` switches Instagram and YouTube to the real adapters in
`backend/app/providers/*_live.py`; these are written against the documented endpoints but are **untested** until Meta App
Review and Google OAuth verification are granted. Live Razorpay, KYC and MSG91 adapters are not written yet.

## Not done yet

- Creator Score phase 2 (LightGBM on verified 7-day views) and Gemini video features; `score_runs` already logs the
  feature vectors it will train on.
- Labelled eval sets for the prompts: every prompt is marked `eval_status: not_run`, and outside dev mode the registry
  refuses to serve them until an eval passes.
- pgvector embeddings (hook de-duplication uses word overlap for now), WhatsApp/FCM delivery (notifications are in-app
  only), streak freezes, the MCP server, agency workspaces, Form 16A generation and GST e-invoicing.
- The React Native creator app; the creator console here is a mobile-first web app.

## Tests

```bash
cd backend && .venv/Scripts/python -m pytest -q
```

16 tests: the ledger invariants (balances never negative, releases never exceed the reserve, idempotent and sign-checked
posting), a property test on CPM accrual against the cap, TDS 194-O, the A6 anomaly rules, the fraud screen, score bounds
and tiers, and an HTTP walk-through of apply → hire with an idempotency key → contract → submission checks.

## Layout

```
backend/app
  models.py            all tables (money in paise, UTC, UUIDv7)
  services/            identity, connections, audit, scoring, matching, briefs, tracking, money, kyc, ai, ops, jobs
  routers/             /v1 creator, brand, ops; /webhooks; /v1/dev simulator
  providers/           base interfaces, fake_* simulators, *_live adapters
  ai/prompts/          versioned prompts with model, effort and eval set
  seed.py              demo marketplace
web/
  app/creator/(app)    home, briefs, work, studio, score, earnings, accounts
  app/brand/(app)      overview, briefs (+ generator and detail), creators, wallet, settings
  app/ops              trust queue, simulator, AI and evals, audit log
  app/dev              simulated OAuth consent and Razorpay checkout
```
