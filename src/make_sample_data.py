"""Generate a reproducible, realistic marketing dataset for a fictional B2B SaaS company.

Writes raw CSVs to data/raw/:
  campaigns.csv   one row per campaign
  creatives.csv   one row per ad creative (2 per campaign)
  ad_daily.csv    date x creative x device x region: impressions, clicks, spend
  sessions.csv    one row per website visit (paid, owned and organic)
  leads.csv       one row per lead with MQL / SQL / won dates and plan
  orders.csv      monthly subscription invoices for won customers

The raw files deliberately contain a few data-quality problems (duplicates,
negative spend, clicks > impressions, inconsistent channel names, missing
devices) so the cleaning step has something to fix.

Usage:  python src/make_sample_data.py [--seed 42] [--out data/raw]
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

START = pd.Timestamp("2025-01-01")
END = pd.Timestamp("2025-12-31")

# Channel economics. cpm = cost per 1,000 impressions (sends for Email),
# ctr = click-through rate, land = share of clicks that load the site,
# lead = visit -> lead rate, mql / sql / win = stage pass rates,
# plan = (Starter, Pro, Business) mix, churn = monthly churn rate.
CHANNELS = {
    "Google Search":  dict(cpm=150.0, ctr=0.045, land=0.92, lead=0.055, mql=0.55, sql=0.50, win=0.26, plan=(0.45, 0.40, 0.15), churn=0.050),
    "Google Display": dict(cpm=3.2,  ctr=0.0045, land=0.80, lead=0.012, mql=0.35, sql=0.35, win=0.18, plan=(0.70, 0.25, 0.05), churn=0.090),
    "Meta Ads":       dict(cpm=15.0,  ctr=0.012, land=0.85, lead=0.028, mql=0.40, sql=0.38, win=0.20, plan=(0.60, 0.32, 0.08), churn=0.080),
    "LinkedIn Ads":   dict(cpm=34.0, ctr=0.006, land=0.90, lead=0.045, mql=0.65, sql=0.55, win=0.24, plan=(0.20, 0.45, 0.35), churn=0.035),
    "TikTok Ads":     dict(cpm=9.0,  ctr=0.009, land=0.78, lead=0.015, mql=0.30, sql=0.30, win=0.16, plan=(0.75, 0.22, 0.03), churn=0.110),
    "Email":          dict(cpm=14.0,  ctr=0.030, land=0.95, lead=0.060, mql=0.60, sql=0.50, win=0.28, plan=(0.40, 0.45, 0.15), churn=0.040),
    "Affiliate":      dict(cpm=12.0,  ctr=0.014, land=0.86, lead=0.030, mql=0.45, sql=0.42, win=0.22, plan=(0.50, 0.38, 0.12), churn=0.060),
}
# Unpaid channels: share of all paid visits, lead rate, stage rates, plan mix, churn.
ORGANIC = {
    "Organic Search": dict(share=0.22, lead=0.035, mql=0.50, sql=0.45, win=0.24, plan=(0.50, 0.38, 0.12), churn=0.050),
    "Direct":         dict(share=0.12, lead=0.050, mql=0.55, sql=0.50, win=0.26, plan=(0.45, 0.40, 0.15), churn=0.045),
    "Referral":       dict(share=0.05, lead=0.040, mql=0.50, sql=0.45, win=0.24, plan=(0.45, 0.40, 0.15), churn=0.050),
}
PLANS = np.array(["Starter", "Pro", "Business"])
PLAN_MRR = np.array([49.0, 149.0, 499.0])

# (channel, campaign name, objective, avg daily budget, start, end, quality)
CAMPAIGNS = [
    ("Google Search",  "Brand Keywords",            "Conversion",  70, None, None, 1.35),
    ("Google Search",  "Competitor Keywords",       "Conversion",  90, None, None, 0.85),
    ("Google Search",  "Generic - Analytics Tools", "Conversion", 140, None, None, 1.00),
    ("Google Display", "Prospecting - In-market",   "Awareness",   55, None, None, 0.80),
    ("Google Display", "Retargeting - Site Visitors", "Conversion", 35, None, None, 1.45),
    ("Meta Ads",       "Prospecting - Lookalike",   "Awareness",  110, None, None, 0.95),
    ("Meta Ads",       "Retargeting - Engaged",     "Conversion",  45, None, None, 1.40),
    ("Meta Ads",       "Spring Launch",             "Awareness",  150, "2025-03-01", "2025-04-30", 1.05),
    ("Meta Ads",       "Black Friday Offer",        "Conversion", 220, "2025-11-15", "2025-12-05", 1.25),
    ("LinkedIn Ads",   "Decision Makers - ABM",     "Conversion",  85, None, None, 1.20),
    ("LinkedIn Ads",   "Webinar Promotion",         "Lead Gen",    60, "2025-02-01", "2025-10-31", 0.95),
    ("LinkedIn Ads",   "Thought Leadership",        "Awareness",   40, None, None, 0.70),
    ("TikTok Ads",     "Gen Z Founders",            "Awareness",   45, "2025-04-01", None, 0.75),
    ("TikTok Ads",     "Product Demo Shorts",       "Awareness",   35, "2025-06-01", None, 0.90),
    ("Email",          "Monthly Newsletter",        "Retention",    6, None, None, 1.00),
    ("Email",          "Trial Nurture Sequence",    "Conversion",  10, None, None, 1.30),
    ("Email",          "Black Friday Email",        "Conversion",  25, "2025-11-20", "2025-12-02", 1.20),
    ("Affiliate",      "Partner Program",           "Conversion",  30, None, None, 1.00),
    ("Affiliate",      "Review Sites",              "Conversion",  25, None, None, 1.15),
]

CREATIVE_OPTIONS = {
    "offer": {"Free trial": 1.20, "Demo booking": 1.05, "Discount": 1.10, "Webinar": 0.95, "Ebook": 0.85},
    "tone": {"Data-driven": 1.08, "Urgent": 1.02, "Friendly": 1.00, "Bold": 0.97},
    "format": {"Video": 1.10, "Carousel": 1.03, "Image": 1.00, "Text": 0.95},
}
HEADLINES = {
    "Free trial": ["Try {p} free for 14 days", "See your funnel in minutes - start free"],
    "Demo booking": ["Book a 20-minute {p} demo", "Watch {p} find your best campaigns"],
    "Discount": ["Save 30% on {p} this month", "Get {p} Pro for less"],
    "Webinar": ["Live: fixing attribution with {p}", "Join our marketing analytics masterclass"],
    "Ebook": ["Free guide: the ROAS playbook", "Download the 2025 funnel benchmark report"],
}
CTAS = {"Free trial": "Start free trial", "Demo booking": "Book a demo", "Discount": "Claim offer",
        "Webinar": "Save my seat", "Ebook": "Download now"}
PRODUCT = "Lumora"

DEVICES = np.array(["mobile", "desktop", "tablet"])
DEVICE_SHARE = {"default": [0.55, 0.38, 0.07], "LinkedIn Ads": [0.35, 0.60, 0.05], "Email": [0.45, 0.48, 0.07],
                "TikTok Ads": [0.88, 0.08, 0.04], "Google Search": [0.48, 0.46, 0.06]}
DEVICE_LEAD = {"mobile": 0.75, "desktop": 1.30, "tablet": 0.90}
DEVICE_CTR = {"mobile": 1.05, "desktop": 0.95, "tablet": 0.90}
REGIONS = np.array(["North America", "Europe", "APAC", "LATAM"])
REGION_SHARE = [0.45, 0.30, 0.17, 0.08]
REGION_LEAD = {"North America": 1.10, "Europe": 1.00, "APAC": 0.85, "LATAM": 0.80}
REGION_CPM = {"North America": 1.25, "Europe": 1.00, "APAC": 0.70, "LATAM": 0.50}
COMPANY_SIZES = np.array(["1-10", "11-50", "51-200", "201-1000", "1000+"])
SIZE_WIN = np.array([0.80, 1.00, 1.15, 1.20, 1.05])
SIZE_PLAN_SHIFT = np.array([-0.15, -0.05, 0.05, 0.12, 0.18])
INDUSTRIES = np.array(["E-commerce", "SaaS", "Agency", "Retail", "Finance", "Education", "Healthcare"])

MONTH_SEASON = {1: 0.85, 2: 0.90, 3: 1.00, 4: 1.00, 5: 1.02, 6: 0.95, 7: 0.85, 8: 0.82, 9: 1.05, 10: 1.10, 11: 1.30, 12: 1.15}
HOUR_PROFILE = np.array([1, 0.6, 0.4, 0.3, 0.3, 0.5, 1, 2, 3.5, 4.5, 5, 5, 4.6, 4.8, 5, 4.8, 4.5, 4, 3.8, 4, 4, 3.5, 2.6, 1.6])
HOUR_PROFILE = HOUR_PROFILE / HOUR_PROFILE.sum()


def build_campaigns(rng: np.random.Generator) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows, creatives = [], []
    for i, (ch, name, obj, budget, start, end, q) in enumerate(CAMPAIGNS, start=1):
        cid = f"C{i:03d}"
        rows.append(dict(campaign_id=cid, campaign_name=f"{ch} | {name}", channel=ch, objective=obj,
                         start_date=start or START.date().isoformat(), end_date=end or END.date().isoformat(),
                         daily_budget=float(budget), quality=q))
        offers = rng.choice(list(CREATIVE_OPTIONS["offer"]), size=2, replace=False)
        for j, offer in enumerate(offers, start=1):
            tone = rng.choice(list(CREATIVE_OPTIONS["tone"]))
            fmt = "Text" if ch in ("Google Search", "Email") else rng.choice(["Video", "Carousel", "Image"])
            creatives.append(dict(
                creative_id=f"{cid}-{j}", campaign_id=cid, offer_type=offer, tone=tone, format=fmt,
                headline=HEADLINES[offer][j - 1].format(p=PRODUCT), cta=CTAS[offer],
                q=CREATIVE_OPTIONS["offer"][offer] * CREATIVE_OPTIONS["tone"][tone] * CREATIVE_OPTIONS["format"][fmt]
                  * rng.lognormal(0, 0.08),
                weight=0.6 if j == 1 else 0.4))
    return pd.DataFrame(rows), pd.DataFrame(creatives)


def build_ad_daily(rng, campaigns: pd.DataFrame, creatives: pd.DataFrame) -> pd.DataFrame:
    days = pd.date_range(START, END, freq="D")
    frames = []
    for c in campaigns.itertuples():
        p = CHANNELS[c.channel]
        d = days[(days >= pd.Timestamp(c.start_date)) & (days <= pd.Timestamp(c.end_date))]
        season = np.array([MONTH_SEASON[m] for m in d.month])
        weekday = np.where(d.day_of_week >= 5, 0.7 if c.channel in ("LinkedIn Ads", "Google Search") else 0.95, 1.0)
        spend_day = c.daily_budget * season * weekday * rng.lognormal(0, 0.15, len(d))
        # Diminishing returns: CTR falls as daily spend rises above the usual budget.
        sat = (1 + spend_day / c.daily_budget) ** -0.45 / (2 ** -0.45)
        cpm_trend = np.ones(len(d))
        if c.channel == "LinkedIn Ads":  # Q4 auction pressure
            cpm_trend = np.where(d.month >= 10, 1.35, 1.0)
        dev_share = DEVICE_SHARE.get(c.channel, DEVICE_SHARE["default"])
        for cr in creatives[creatives.campaign_id == c.campaign_id].itertuples():
            for di, dev in enumerate(DEVICES):
                for ri, reg in enumerate(REGIONS):
                    share = cr.weight * dev_share[di] * REGION_SHARE[ri]
                    spend = spend_day * share
                    cpm = p["cpm"] * REGION_CPM[reg] * cpm_trend
                    impr = rng.poisson(spend / cpm * 1000)
                    ctr = np.clip(p["ctr"] * c.quality ** 0.5 * cr.q * DEVICE_CTR[dev] * sat, 0, 0.5)
                    clicks = rng.binomial(impr, ctr)
                    frames.append(pd.DataFrame(dict(
                        date=d, campaign_id=c.campaign_id, creative_id=cr.creative_id, device=dev, region=reg,
                        impressions=impr, clicks=clicks, spend=np.round(spend, 2))))
    ad = pd.concat(frames, ignore_index=True)

    # Real-world anomalies the analysis should spot.
    meta = ad.campaign_id.isin(campaigns.loc[campaigns.channel == "Meta Ads", "campaign_id"])
    outage = meta & ad.date.between("2025-03-10", "2025-03-16")  # pixel/tracking issue: clicks under-reported
    ad.loc[outage, "clicks"] = (ad.loc[outage, "clicks"] * 0.3).round().astype(int)
    display = ad.campaign_id.isin(campaigns.loc[campaigns.channel == "Google Display", "campaign_id"])
    ad.loc[display & (ad.date == "2025-08-14"), ["impressions", "clicks"]] = 0  # reporting outage, spend still billed
    return ad


def build_sessions(rng, ad: pd.DataFrame, campaigns: pd.DataFrame) -> pd.DataFrame:
    chan = campaigns.set_index("campaign_id").channel
    ad = ad.assign(channel=ad.campaign_id.map(chan))
    land = ad.channel.map(lambda c: CHANNELS[c]["land"]).to_numpy()
    visits = rng.binomial(ad.clicks.to_numpy(), land)
    idx = np.repeat(np.arange(len(ad)), visits)
    paid = ad.iloc[idx][["date", "campaign_id", "creative_id", "device", "region", "channel"]].reset_index(drop=True)

    n_paid = len(paid)
    org_frames = []
    all_days = pd.date_range(START, END, freq="D")
    for ch, o in ORGANIC.items():
        n = int(n_paid * o["share"])
        season = np.array([MONTH_SEASON[m] for m in all_days.month])
        org_frames.append(pd.DataFrame(dict(
            date=rng.choice(all_days, size=n, p=season / season.sum()),
            campaign_id=None, creative_id=None,
            device=rng.choice(DEVICES, size=n, p=DEVICE_SHARE["default"]),
            region=rng.choice(REGIONS, size=n, p=REGION_SHARE), channel=ch)))
    s = pd.concat([paid, *org_frames], ignore_index=True)
    s["ts"] = (pd.to_datetime(s.date) + pd.to_timedelta(rng.choice(24, size=len(s), p=HOUR_PROFILE), unit="h")
               + pd.to_timedelta(rng.integers(0, 3600, size=len(s)), unit="s"))
    s = s.sort_values("ts", kind="stable").reset_index(drop=True)

    # Multi-touch journeys: ~38% of visits come from someone who visited in the previous ~2 weeks.
    n = len(s)
    returning = rng.random(n) < 0.38
    lag = rng.geometric(1 / (n / 365 * 10), size=n)
    users = np.empty(n, dtype=np.int64)
    next_id = 0
    for i in range(n):
        if returning[i] and i - lag[i] >= 0:
            users[i] = users[i - lag[i]]
        else:
            users[i] = next_id
            next_id += 1
    s["user_id"] = [f"U{u:07d}" for u in users]
    s["session_id"] = [f"S{i:08d}" for i in range(n)]

    lead_rate = s.channel.map(lambda c: (CHANNELS.get(c) or ORGANIC[c])["lead"]).to_numpy()
    s["pageviews"] = 1 + rng.poisson(1.2 + 3 * lead_rate / 0.05, size=n)
    s["bounced"] = (s.pageviews == 1) & (rng.random(n) < 0.85)
    s["duration_sec"] = np.where(s.bounced, rng.integers(3, 30, n), (s.pageviews * rng.gamma(2.0, 35, n)).astype(int))
    return s[["session_id", "user_id", "ts", "channel", "campaign_id", "creative_id", "device", "region",
              "pageviews", "duration_sec", "bounced"]]


def build_leads_orders(rng, s: pd.DataFrame, campaigns: pd.DataFrame, creatives: pd.DataFrame):
    params = {**CHANNELS, **ORGANIC}
    cq = campaigns.set_index("campaign_id").quality
    crq = creatives.set_index("creative_id").q
    prior = s.groupby("user_id").cumcount().to_numpy()
    p = (s.channel.map(lambda c: params[c]["lead"]).to_numpy()
         * s.campaign_id.map(cq).fillna(1.0).to_numpy()
         * s.creative_id.map(crq).fillna(1.0).to_numpy() ** 0.5
         * s.device.map(DEVICE_LEAD).to_numpy()
         * s.region.map(REGION_LEAD).to_numpy()
         * np.minimum(1 + 0.30 * prior, 2.2)
         * np.where(s.bounced, 0.1, 1.0))
    fired = s[rng.random(len(s)) < p]
    first = fired.drop_duplicates("user_id", keep="first")

    n = len(first)
    L = pd.DataFrame(dict(
        lead_id=[f"L{i:06d}" for i in range(n)], user_id=first.user_id.to_numpy(), created_at=first.ts.to_numpy(),
        channel=first.channel.to_numpy(), campaign_id=first.campaign_id.to_numpy(),
        session_id=first.session_id.to_numpy()))
    size_idx = rng.choice(len(COMPANY_SIZES), size=n, p=[0.28, 0.30, 0.22, 0.13, 0.07])
    L["company_size"] = COMPANY_SIZES[size_idx]
    L["industry"] = rng.choice(INDUSTRIES, size=n, p=[0.22, 0.20, 0.16, 0.14, 0.10, 0.09, 0.09])
    pv = first.pageviews.to_numpy()
    eng = np.clip(0.8 + 0.06 * pv, 0.8, 1.4)  # engaged leads progress more

    def ch_p(key):
        return L.channel.map(lambda c: params[c][key]).to_numpy()

    mql = rng.random(n) < np.clip(ch_p("mql") * eng, 0, 0.95)
    sql = mql & (rng.random(n) < np.clip(ch_p("sql") * SIZE_WIN[size_idx], 0, 0.95))
    won = sql & (rng.random(n) < np.clip(ch_p("win") * SIZE_WIN[size_idx] * eng, 0, 0.95))
    created = pd.to_datetime(L.created_at)
    mql_at = created + pd.to_timedelta(rng.exponential(3, n) * 24, unit="h")
    sql_at = mql_at + pd.to_timedelta(rng.exponential(7, n) * 24, unit="h")
    won_at = sql_at + pd.to_timedelta(rng.exponential(14, n) * 24, unit="h")
    cutoff = END + pd.Timedelta(days=1)
    L["mql_at"] = mql_at.where(mql & (mql_at < cutoff))
    L["sql_at"] = sql_at.where(L.mql_at.notna() & sql & (sql_at < cutoff))
    L["won_at"] = won_at.where(L.sql_at.notna() & won & (won_at < cutoff))

    # Plan choice: channel mix shifted towards bigger plans for bigger companies.
    plan_mix = np.array([params[c]["plan"] for c in L.channel])
    shift = SIZE_PLAN_SHIFT[size_idx]
    plan_mix = plan_mix + np.stack([-shift, shift * 0.4, shift * 0.6], axis=1)
    plan_mix = np.clip(plan_mix, 0.01, None)
    plan_mix = plan_mix / plan_mix.sum(axis=1, keepdims=True)
    plan_idx = (rng.random(n)[:, None] > np.cumsum(plan_mix, axis=1)).sum(axis=1).clip(0, 2)
    is_cust = L.won_at.notna()
    L["plan"] = np.where(is_cust, PLANS[plan_idx], None)
    L["mrr"] = np.where(is_cust, PLAN_MRR[plan_idx], np.nan)

    # Monthly invoices until churn or end of data window.
    orders = []
    churn = ch_p("churn")
    for i in np.flatnonzero(is_cust.to_numpy()):
        start = L.won_at.iat[i].normalize()
        lifetime = rng.geometric(churn[i])
        for m in range(lifetime):
            d = start + pd.DateOffset(months=m)
            if d > END:
                break
            orders.append((L.user_id.iat[i], d, L.mrr.iat[i], L.plan.iat[i], m == 0))
    orders_df = pd.DataFrame(orders, columns=["user_id", "order_date", "revenue", "plan", "is_first_order"])
    orders_df = orders_df.sort_values("order_date", kind="stable").reset_index(drop=True)
    orders_df.insert(0, "order_id", [f"O{i:07d}" for i in range(len(orders_df))])
    return L, orders_df


def inject_quality_issues(rng, ad: pd.DataFrame, s: pd.DataFrame, L: pd.DataFrame):
    ad = ad.copy()
    dup = ad.sample(frac=0.003, random_state=1)
    ad = pd.concat([ad, dup], ignore_index=True)
    neg = rng.choice(len(ad), 15, replace=False)
    ad.loc[neg, "spend"] = -ad.loc[neg, "spend"]
    bad = ad.index[ad.impressions > 50].to_numpy()
    bad = rng.choice(bad, 20, replace=False)
    ad.loc[bad, "clicks"] = ad.loc[bad, "impressions"] + rng.integers(1, 40, 20)
    ad = ad.sample(frac=1, random_state=2).reset_index(drop=True)

    s = s.copy()
    alias = {"Meta Ads": ["facebook", "FB Ads", "meta"], "Google Search": ["google_search", "Google - Search"],
             "Organic Search": ["organic", "google / organic"], "LinkedIn Ads": ["linkedin"]}
    for canon, names in alias.items():
        m = (s.channel == canon) & (rng.random(len(s)) < 0.02)
        s.loc[m, "channel"] = rng.choice(names, m.sum())
    s.loc[rng.random(len(s)) < 0.005, "device"] = None

    L = pd.concat([L, L.sample(30, random_state=3)], ignore_index=True)
    return ad, s, L


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parents[1] / "data" / "raw")
    args = ap.parse_args()
    rng = np.random.default_rng(args.seed)

    campaigns, creatives = build_campaigns(rng)
    ad = build_ad_daily(rng, campaigns, creatives)
    sessions = build_sessions(rng, ad, campaigns)
    leads, orders = build_leads_orders(rng, sessions, campaigns, creatives)
    ad_raw, sessions_raw, leads_raw = inject_quality_issues(rng, ad, sessions, leads)

    args.out.mkdir(parents=True, exist_ok=True)
    campaigns.drop(columns=["quality"]).to_csv(args.out / "campaigns.csv", index=False)
    creatives.drop(columns=["q", "weight"]).to_csv(args.out / "creatives.csv", index=False)
    ad_raw.to_csv(args.out / "ad_daily.csv", index=False)
    sessions_raw.to_csv(args.out / "sessions.csv", index=False)
    leads_raw.to_csv(args.out / "leads.csv", index=False)
    orders.to_csv(args.out / "orders.csv", index=False)

    print(f"campaigns {len(campaigns):>9,}\ncreatives {len(creatives):>9,}\nad_daily  {len(ad_raw):>9,}"
          f"\nsessions  {len(sessions_raw):>9,}\nleads     {len(leads_raw):>9,}\norders    {len(orders):>9,}")
    print(f"spend ${ad.spend.sum():,.0f}  revenue ${orders.revenue.sum():,.0f}  "
          f"customers {leads.won_at.notna().sum():,}  -> wrote {args.out}")


if __name__ == "__main__":
    main()
