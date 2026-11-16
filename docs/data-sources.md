# Getting real data

Notes from looking into what real data I could use instead of, or alongside, the generated set.

## Ad platforms

Google Ads, Meta, LinkedIn and TikTok all have APIs, but they only return real numbers for an ad account that's actually spending. Their test and sandbox accounts come back empty. So without a budget, real campaign performance data isn't available. If I ever run a small campaign, dlt has connectors for Google Ads and Facebook Ads that load straight into DuckDB.

## Public datasets worth using

- **GA4 sample on BigQuery** (`bigquery-public-data.ga4_obfuscated_sample_ecommerce`): real Google Merchandise Store traffic and purchases from Nov 2020 to Jan 2021. It has source, medium, campaign, device and country. Free with the BigQuery sandbox. It would replace the sessions and orders tables.
- **Criteo attribution dataset**: 16.5M real display ad impressions with clicks, cost and conversions. Good for testing attribution. The licence is non-commercial and share-alike.
- **Meridian and Robyn demo data**: simulated weekly spend by channel, the usual benchmark for marketing mix models.
- **UCI Bank Marketing**: 45k campaign contacts with outcomes, fine for lead scoring practice.

## CRM

A free HubSpot developer test account would let me push the generated leads in and pull them back out with dlt on a schedule. That gives a real API-to-DuckDB pipeline even though the leads themselves are made up. The test account expires after 90 days without API calls, so a weekly job keeps it alive.

## Public ad and market data

These have official APIs, so no scraping is needed:

- Microsoft Ad Library: competitor ad text, dates and reach, no login needed
- Meta Ad Library: needs a developer app and ID check
- Google Ads Transparency Center: EU ads only, through BigQuery
- Wikipedia pageviews: a decent stand-in for category demand, useful as a control in the MMM
- Hacker News, YouTube and Product Hunt APIs for community chatter

pytrends (unofficial Google Trends) stopped working in 2025. The official Trends API is in alpha and you have to apply for it.

Competitor pricing pages are fine to fetch occasionally if robots.txt allows it. Review sites (Trustpilot, G2, Capterra) and LinkedIn forbid scraping in their terms, so I'm leaving them out. I'd only publish aggregates on the site, not copied ad creatives or review text.

## What I'll probably do

Keep the generated data as the main set, since it's the only option with ads, visits, CRM stages and revenue all linked. Then add the GA4 sample as a real-data comparison, a HubSpot pipeline, and competitor ads from the ad library APIs.
