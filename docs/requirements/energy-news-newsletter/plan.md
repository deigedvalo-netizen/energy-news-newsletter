# Requirements & Plan — Energy News Newsletter (v2)

**feature_id:** `energy-news-newsletter` · **Revised:** 2026-09-16 with the owner's decisions
**Machine artifacts:** `requirements/energy-news-newsletter/handoff.json` · `architecture/energy-news-newsletter/architecture_spec.json` + ADR-001…ADR-019 (both validate against `pipeline/handoff.schema.json`)

**What it is:** a small, private, daily newsletter that reads reputable energy and carbon sources, finds the hottest topics (ideas several companies are pushing, and whether they're gaining or losing steam), and condenses them into a short read with a "what this means for energy traders" analysis. v1 is news only, with no price data.

```
 05:00 CT  GitHub Actions (free)                      07:30 CT  Claude scheduled task (your subscription)
 ┌──────────────────────────────────┐                ┌───────────────────────────────────────────┐
 │ read ~30 reputable sources        │   digest.md    │ read digest + open ≤15 linked articles     │
 │ tag commodity · topic · companies │ ─────────────► │ append trend evidence → issues/trends.json │
 │ group same-story coverage         │  (≤60 KB)      │ write newsletter + trader analysis         │
 │ compute trend status/trajectory   │                └──────────────────────┬────────────────────┘
 └───────────────┬──────────────────┘                                       │ one "issue:" commit
                 ▼                                                           ▼
        web page (your domain) ◄──────────── CI validator: links from digest? hot topics confirmed?
        noindex · private preview                          no advice? → publish (warn on unverified figures)
```

## 1. Decisions log (2026-09-16)

| # | Question | Decision |
|---|---|---|
| Q1 | Commodities | Crude Oil, Natural Gas, Refined Products **and Carbon Credits** in v1 (FR-4, FR-18) |
| Q2 | Price data | **Deferred.** v1 reads and condenses news only; price code stays dormant behind `prices.enabled: false` (FR-8 WONT, NFR-9, ADR-016) |
| Q3 | Sources | **As many tier-1 sources as possible**: official agencies and regulators plus outlets with a public editorial and corrections policy. Wire services that need licenses stay out (FR-1, ADR-018, §5) |
| Q4 | Audience | Small and basically private (you and a friend), labelled as unverified, informational only. May grow (FR-20, NFR-4, A4) |
| Q5 | Cadence | **Daily**: scan at 05:00, newsletter at 07:30 Central, instead of every 3 hours (NFR-1, ADR-001) |
| Q6 | AI | **Your Claude subscription only**: no API keys, and the pipeline makes no AI calls (NFR-3, ADR-014) |
| Q7 | What a trend is | **An idea multiple companies are pushing, tracked as a trajectory** (FR-7, FR-19, ADR-015; see §2) |
| Q8 | Delivery | **Web page on your own domain** (FR-20, ADR-019) |
| Q9 | Who writes | **The Claude scheduled task writes the newsletter** (FR-14) |
| Q10 | Trader analysis | Yes: a daily "What this means for energy traders" (FR-17) |
| Q11 | Carbon | Yes, news only (FR-18) |
| — | CDR.fyi (recommended by your friend's company) | **Link-only reference** in the Carbon Credits tab. Its Terms of Service §5.3 ban scraping and using AI to summarize its data without a commercial license. If the project grows, ask partners@cdr.fyi about a partner or commercial license (ADR-006) |

### New open questions

- **N1. Company press releases:** should wire releases alone be enough to make a trend a hot topic? *Recommendation:* yes, since they are the best evidence of what companies push. The analysis must say when a trend rests only on company releases (A3).
- **N2. Real privacy:** GitHub Pages is public to anyone who has the URL, even with noindex. *Recommendation:* noindex is fine for now. Add Cloudflare Access (free for small teams) if you share it wider.
- **N3. Which feeds work from GitHub's runner:** Guardian, BBC, FT, CNBC, OPEC and UNFCCC couldn't be checked from here. The first run report will show which ones work (AC-1.4).
- **N4. Your domain:** when you buy one, set `site.custom_domain` and add a DNS CNAME pointing to `deigedvalo-netizen.github.io`.

## 2. How trends work

A **trend** is an idea, initiative or direction pushed by several companies, for example *"long-term LNG supply deals with Asian buyers"* or *"corporate purchases of durable carbon removal"*.

1. **Evidence:** each day the scheduled task records a dated *mention* in `issues/trends.json` for every relevant story: which company did what, plus a link to the story. The ledger only grows; mentions are never deleted.
2. **Checks:** the validator accepts a mention only if its link is in a digest from the last 30 days. It marks the company *verified* when that company is actually named in the story's digest text or tags.
3. **Status:** CONFIRMED = 2 or more verified companies in 30 days · EMERGING = only 1 company.
4. **Trajectory:** compares the last 7 days with the 7 days before that.

| Trajectory | Rule |
|---|---|
| NEW | first seen within the last 7 days |
| RISING | more companies than the previous week, or the same number of companies with more mentions |
| FADING | fewer companies, or the same number with fewer mentions |
| STEADY | no change |
| DORMANT | nothing in 30 days (hidden) |

5. **Hotness** = 3 × companies this week + the tier-weighted, age-discounted stories linked this week. The newsletter's **Hottest topics** are the top 5 CONFIRMED trends.

*Illustrative only:* "Company A, Company B and Company C announced offtake deals this week versus one company last week" gives CONFIRMED · RISING · hotness 3×3 + story weights.

## 3. Page layout

```
┌──────────────────────────────────────────────────────────────────────┐
│ ⚠ Private preview for a small readership. Unverified, informational  │
│   only. Not investment advice.                                        │
│ Energy News Daily                            data as of 09-16 05:10 CT│
│ [Newsletter] [Analysis] [Trends] [All] [Crude] [Gas] [Refined] [Carbon]│
├──────────────────────────────────────────────────────────────────────┤
│ NEWSLETTER — Wed Sep 16                                     FR-14     │
│  Hottest topics                                                       │
│   1. <trend>   CONFIRMED · RISING · 4 companies  (A, B, C, D)         │
│      2–3 sentences · links                                            │
│  Crude Oil · Natural Gas · Refined Products · Carbon Credits          │
│   ≤4 notable stories each, linked                                     │
│  ⓘ contains figures not machine-verified (if warned)        FR-15     │
├──────────────────────────────────────────────────────────────────────┤
│ TRENDS tab: every trend · trajectory badge · companies · timeline     │
│ COMMODITY tabs: pinned analysis section · trends · 7-day feed         │
│ CARBON tab adds: Further reading → CDR.fyi (link only)                │
└──────────────────────────────────────────────────────────────────────┘
```

## 4. Requirements


### 4.1 Functional

#### FR-1 [MUST]
Maintain a source registry (config file). Every source declares id, name, url, tier, source_type, commodities, access_method (RSS | HTML_LIST), tos_status (ALLOWED | HEADLINE_ONLY | REFERENCE_ONLY | BLOCKED | UNVERIFIED), terms_note and enabled. Tier 1 = official or primary publishers (government agencies, regulators, intergovernmental bodies) and news organizations with a public editorial and corrections policy; tier 2 = specialist trade press and company press-release wires; tier 3 = aggregators and commentary, disabled by default. source_type is OFFICIAL | PRESS | TRADE | NEWSROOM | AGGREGATOR.

*Why:* Reputable, well-checked sources are the product. Tier and type drive weighting, and terms status decides what the scanner may touch.

- **AC-1.1** — *Given* a source whose tos_status is BLOCKED, UNVERIFIED or REFERENCE_ONLY, *when* the daily scan runs, *then* no HTTP request is made to it and the run report lists it as SKIPPED with its tos_status.
- **AC-1.2** — *Given* a registry entry with a duplicate id, a tier outside 1-3, or an unknown source_type, *when* the registry is loaded, *then* loading fails with a validation error naming the entry and no scan starts.
- **AC-1.3** — *Given* a tier-3 AGGREGATOR entry with enabled omitted, *when* the registry is loaded, *then* it is treated as disabled.
- **AC-1.4** — *Given* the first successful daily run, *when* the run report is written, *then* it lists every enabled source with OK, NOT_MODIFIED, FAILED or ROBOTS_DISALLOWED so the owner can confirm which reputable feeds work from the runner.

#### FR-2 [MUST]
Once per day, scan enabled sources in tier order, honouring robots.txt and conditional GET, and store only items not already seen after URL canonicalisation. RSS sources are parsed as feeds; official sources without RSS use an HTML_LIST adapter configured with CSS selectors for item link, title and date.

*Depends on:* FR-1

- **AC-2.1** — *Given* an item whose URL differs from a stored item only by utm_* parameters or a trailing slash, *when* it is scanned, *then* it is recognised as a duplicate and not stored again.
- **AC-2.2** — *Given* one source times out or returns HTTP 5xx, *when* the scan runs, *then* that source is recorded FAILED with the reason, every other source is still scanned, and the run completes.
- **AC-2.3** — *Given* a source has FAILED on 3 consecutive daily runs, *when* the run report is produced, *then* the source carries a STALE_SOURCE flag.
- **AC-2.4** — *Given* robots.txt disallows the listing or article path, *when* it would be fetched, *then* it is not fetched and is recorded ROBOTS_DISALLOWED.
- **AC-2.5** — *Given* an HTML_LIST source (e.g. ICAP news) whose page yields items with title, link and date via the configured selectors, *when* it is scanned, *then* each item becomes a stored article exactly as an RSS item would; if the selectors match nothing the source is FAILED with reason SELECTOR_NO_MATCH.

#### FR-3 [MUST]
Read each new item: title, canonical url, outlet, published_at (UTC) and a persisted excerpt of at most 300 characters. HEADLINE_ONLY sources use only the listing or feed title and summary; ALLOWED sources may fetch the article body transiently for tagging and figure extraction.

*Depends on:* FR-2

- **AC-3.1** — *Given* an article with no parseable publish timestamp, *when* it is extracted, *then* it is marked UNDATED and excluded from the digest, trends and newsletter candidates.
- **AC-3.2** — *Given* a HEADLINE_ONLY source, *when* one of its items is read, *then* the article page is never requested by the pipeline.
- **AC-3.3** — *Given* an article published '2026-09-09 10:35 EDT', *when* it is extracted, *then* published_at is stored as 2026-09-09T14:35:00Z.

#### FR-4 [MUST]
Tag every article deterministically (no LLM API): one or more commodities from CRUDE_OIL, NATURAL_GAS, REFINED_PRODUCTS, CARBON_CREDITS; one topic from the closed topic list; and the organizations it names, matched against a maintained organizations file (name, aliases, org_type COMPANY | GOVERNMENT | AGENCY | INTERGOVERNMENTAL).

*Depends on:* FR-3

- **AC-4.1** — *Given* the headline 'Venture Global and Cheniere expand US LNG export capacity', *when* it is tagged, *then* commodities include NATURAL_GAS and organizations include Venture Global and Cheniere Energy (via alias 'Cheniere'), both COMPANY.
- **AC-4.2** — *Given* an article with no commodity keyword matches, *when* it is tagged, *then* it is marked NOT_RELEVANT and excluded from all outputs.
- **AC-4.3** — *Given* the headline 'EU carbon allowances slide after Commission proposes changes to EU ETS auctions', *when* it is tagged, *then* its commodities are exactly CARBON_CREDITS and organizations include European Commission as GOVERNMENT.

#### FR-5 [MUST]
Group articles from different outlets that report the same event into a story cluster with distinct_source_count, best source tier, organizations (union) and first_published_at.

*Depends on:* FR-4

- **AC-5.1** — *Given* 4 articles from 4 sources about the same EIA Weekly Petroleum Status Report within 24 h, *when* clustering runs, *then* exactly one cluster is formed with distinct_source_count = 4.
- **AC-5.2** — *Given* 3 articles from one source about one event, *when* clustering runs, *then* they share one cluster and the source counts once.
- **AC-5.3** — *Given* two OPEC+ meeting articles more than 72 h apart, *when* clustering runs, *then* they form two clusters.
- **AC-5.4** — *Given* identical inputs and configuration, *when* clustering runs twice, *then* membership is identical.

#### FR-6 [SHOULD]
Extract key reported figures verbatim (exact quoted span, unit as written, source url) from text the pipeline is allowed to read; never compute, convert or average them.

*Depends on:* FR-5

- **AC-6.1** — *Given* a proposed figure whose span is not an exact substring of the source text, *when* figures are validated, *then* it is dropped and logged.
- **AC-6.2** — *Given* two sources in a cluster report different values for the same quantity, *when* the cluster is rendered, *then* both are shown with sources and the cluster carries CONFLICTING_FIGURES.

#### FR-7 [MUST]
Trends are ideas, initiatives or directions that multiple companies are pushing, tracked as a trajectory over time. A trend is CONFIRMED when at least 2 distinct verified COMPANY organizations have mentions in the last 30 days, and EMERGING with 1. Trajectory is computed deterministically from the trend ledger (FR-19) using the 7 days before the run (current) and the 7 days before that (previous): NEW if first_seen is within the current window; otherwise RISING if distinct companies increased, or stayed equal while mentions increased; FADING if distinct companies decreased, or stayed equal while mentions decreased; STEADY otherwise; DORMANT if no mentions in 30 days (hidden). hotness = 3 x distinct companies (current) + sum over distinct linked stories in the current window of w(tier) x 0.5^(age_h / 72), with w = 3 / 2 / 1 for tiers 1 / 2 / 3. Hottest topics are the top 5 CONFIRMED trends by hotness, ties broken by latest mention then trend_id.

*Why:* Owner definition (2026-09-16): 'a trend is an idea multiple companies are pushing, essentially trajectory'.

*Depends on:* FR-19, FR-4

- **AC-7.1** — *Given* a trend whose verified mentions in 30 days all come from Shell, *when* trends are computed, *then* its status is EMERGING and it is not eligible for hottest topics.
- **AC-7.2** — *Given* a trend first seen 20 days ago with 3 distinct companies in the current window and 1 in the previous, *when* trajectory is computed, *then* it is RISING.
- **AC-7.3** — *Given* a trend first seen 3 days ago, *when* trajectory is computed, *then* it is NEW.
- **AC-7.4** — *Given* a trend with 0 mentions in the current window and 2 companies in the previous, *when* trajectory is computed, *then* it is FADING.
- **AC-7.5** — *Given* 2 companies in the current window and one linked tier-1 story aged 72 h, *when* hotness is computed, *then* it equals 3x2 + 3x0.5 = 7.5.
- **AC-7.6** — *Given* identical ledger, digest and run time, *when* trends are computed twice, *then* statuses, trajectories, hotness and ranking are identical.

#### FR-8 [WONT]
Price effects (benchmark moves beside stories) are deferred. v1 is news-only. The price module stays in the codebase disabled behind a settings flag (see NFR-9).

*Why:* Owner decision 2026-09-16: price data is not important yet; reading and condensing reputable news is.

- **AC-8.1** — *Given* v1 settings, *when* any page, digest or newsletter is produced, *then* no price, benchmark move or price-effect badge appears.

#### FR-9 [MUST]
Render a scrollable feed of story clusters first published in the last 7 days with relevance >= threshold (default 30), newest first. relevance = round(100 x (0.6 x min(cluster_weight / 10, 1) + 0.4 x tier_score)), cluster_weight = sum over distinct sources of w(tier) x 0.5^(age_h / 72), tier_score = 1.0 / 0.66 / 0.33. Each item shows local time, title, 1-sentence extractive summary, source count and best tier, commodity chips, organizations, linked trend names, and links to every source.

*Depends on:* FR-5

- **AC-9.1** — *Given* a cluster first published 7 days and 1 hour ago, *when* the feed is built, *then* it is excluded.
- **AC-9.2** — *Given* 120 eligible clusters, *when* the page loads, *then* 25 items render and 25 more append each time the reader nears the end.
- **AC-9.3** — *Given* one tier-1 source 0 h old, *when* relevance is computed, *then* it is round(100 x (0.6 x 0.3 + 0.4 x 1.0)) = 58.
- **AC-9.4** — *Given* a cluster with relevance 29 and threshold 30, *when* the feed is built, *then* it is excluded.

#### FR-10 [MUST]
Tabs: Newsletter (default), Analysis, Trends, All, and one per commodity (Crude Oil, Natural Gas, Refined Products, Carbon Credits). Commodity tabs show that commodity's pinned analysis section, its hottest trends with trajectory badges and companies, and the filtered feed. The Trends tab lists all CONFIRMED and EMERGING trends with trajectory, companies and dated mention timeline.

*Depends on:* FR-9, FR-7

- **AC-10.1** — *Given* a cluster tagged CRUDE_OIL and REFINED_PRODUCTS, *when* tabs render, *then* it appears in both commodity tabs.
- **AC-10.2** — *Given* a commodity with no qualifying stories, *when* its tab opens, *then* it shows 'No qualifying news in the last 7 days' and is not hidden.
- **AC-10.3** — *Given* the URL /#carbon-credits, *when* the page opens, *then* the Carbon Credits tab is selected.
- **AC-10.4** — *Given* a trend RISING with companies Shell, TotalEnergies and Equinor, *when* the Trends tab renders it, *then* it shows a RISING badge, the three company names, and each dated mention linking to its story.

#### FR-11 [MUST]
Feed and cluster summaries are extractive in v1: the first sentence of the best-tier source's feed summary or excerpt, never generated by an LLM API.

*Depends on:* FR-5

- **AC-11.1** — *Given* a cluster whose best-tier excerpt is 'U.S. crude inventories fell 4.1 million barrels. Stocks at Cushing rose.', *when* its summary is built, *then* it is 'U.S. crude inventories fell 4.1 million barrels.'.

#### FR-12 [COULD]
Freeze a weekly archive of the digest and that week's newsletters every Monday 07:00 America/Chicago; archives are immutable.

*Depends on:* FR-10

- **AC-12.1** — *Given* the archive for 2026-W38 exists, *when* later runs execute, *then* its content hash does not change.

#### FR-13 [SHOULD]
Write a daily run report: sources scanned / skipped / failed with reasons, new articles, clusters, organizations tagged, digest size, flags.

- **AC-13.1** — *Given* a completed run, *when* the report is written, *then* its totals reconcile with stored records.

#### FR-14 [MUST]
A Claude scheduled task on the owner's Claude subscription runs daily at 07:30 America/Chicago. It reads the latest digest snapshot, may open up to 15 article links that appear in the digest to understand the stories, updates the trend ledger (FR-19), and writes a condensed newsletter issues/YYYY-MM-DD.md: title, an 'unverified, informational only' line, Hottest topics (top 5 trends: name, trajectory, companies pushing it, 2-3 sentences, links), one short section per commodity (Crude Oil, Natural Gas, Refined Products, Carbon Credits) with up to 4 notable stories, Sources and Disclaimer. Target 600-900 words.

*Why:* Owner decisions 2026-09-16: the scheduled Claude task writes the newsletter; use the Claude subscription, no API.

*Depends on:* FR-16, FR-19

- **AC-14.1** — *Given* the digest's data_as_of is more than 30 hours before the task starts, *when* the task runs, *then* no newsletter is written and a SKIPPED_STALE entry is appended to issues/index.json.
- **AC-14.2** — *Given* issues/2026-09-16.md already exists, *when* the task runs again that day, *then* nothing is overwritten and the task ends ALREADY_PUBLISHED.
- **AC-14.3** — *Given* a commodity with no qualifying stories in the digest, *when* the newsletter is written, *then* its section says 'No qualifying news in the last 24 hours.'.
- **AC-14.4** — *Given* a written newsletter, *when* it is uploaded, *then* frontmatter records date, digest feed_sha256, data_as_of, prompt_version and articles_opened (list of URLs, at most 15).

#### FR-15 [MUST]
Before publishing, a deterministic validator checks newsletters and analyses. REJECT when: a URL is not in the referenced digest; the disclaimer or 'unverified' line is missing; advisory or forecast language appears; a Hottest topic names a trend that is not CONFIRMED in the validated ledger; required sections are missing. WARN (publish with a visible 'contains figures not machine-verified' note) when a number does not appear in the digest, because the author may cite figures from linked articles it opened.

*Depends on:* FR-14, FR-19

- **AC-15.1** — *Given* a newsletter linking https://evil.example/a, *when* validation runs, *then* it is REJECTED with UNSOURCED_URL and not published.
- **AC-15.2** — *Given* a newsletter citing '3.8 million barrels' where the digest has no 3.8, *when* validation runs, *then* it is PUBLISHED_WITH_WARNINGS listing UNVERIFIED_NUMBER 3.8 and the page shows the warning note.
- **AC-15.3** — *Given* a newsletter containing 'traders should buy', *when* validation runs, *then* it is REJECTED with ADVISORY_LANGUAGE.
- **AC-15.4** — *Given* a Hottest topic for a trend whose ledger status is EMERGING, *when* validation runs, *then* it is REJECTED with TREND_NOT_CONFIRMED.
- **AC-15.5** — *Given* a rejected newsletter, *when* the site builds, *then* the Newsletter tab keeps the previous published issue and the run report shows the reasons.

#### FR-16 [MUST]
Every scan builds a digest for the author: a JSON snapshot (validator's source of truth) and a compact Markdown digest (<= 60 KB) listing, per commodity, qualifying clusters with title, extractive summary, outlets and tiers, links, organizations and verbatim figures; candidate trend groups (topic x commodity clusters with 2+ companies); the current trend ledger with computed status, trajectory and hotness; the most active companies of the last 7 days; and the next recurring scheduled releases (EIA WPSR, EIA storage, Baker Hughes, CFTC COT). It also contains a data-only synopsis in template sentences.

*Depends on:* FR-5, FR-7, FR-9

- **AC-16.1** — *Given* a day with 400 qualifying clusters, *when* the Markdown digest is built, *then* it is at most 60 KB, keeping the highest-relevance clusters per commodity and stating how many were omitted.
- **AC-16.2** — *Given* the run time Tuesday 2026-09-15 12:00 CT, *when* the calendar is built, *then* its first entry is EIA Weekly Petroleum Status Report at Wed 2026-09-16 09:30 CT.
- **AC-16.3** — *Given* identical stored data and run time, *when* the digest is built twice, *then* both JSON snapshots are byte-identical.

#### FR-17 [MUST]
Publish a daily analysis, 'What this means for energy traders', written by the same scheduled task from the same digest (issues/analysis/YYYY-MM-DD.md): The big picture, one section per commodity, Trend trajectories, What to watch, Data notes, Disclaimer. It explains what the collected news and trend trajectories add up to, may describe in general conditional terms how such developments are usually read, and may not forecast prices, suggest trades, or add links absent from the digest. It is shown in an Analysis tab and pinned to All and each commodity tab; if none based on data from the last 36 hours exists, pinned cards show the data-only synopsis.

*Depends on:* FR-14, FR-15, FR-16

- **AC-17.1** — *Given* a submitted analysis whose links are all in its digest, *when* the gate runs, *then* it is PUBLISHED and its sections are available to each tab.
- **AC-17.2** — *Given* an analysis containing 'LNG prices are likely to rise', *when* validation runs, *then* it is REJECTED with ADVISORY_LANGUAGE.
- **AC-17.3** — *Given* the latest published analysis is based on data over 36 hours old, *when* a commodity tab opens, *then* the pinned card shows the data-only synopsis.

#### FR-18 [MUST]
Carbon Credits is a v1 commodity with its own tab and reputable sources: official (European Commission Climate Action, ICAP, California Air Resources Board, UNFCCC) and specialist press (Carbon Brief tier 1; Carbon Herald tier 2). CDR.fyi is REFERENCE_ONLY: its terms forbid scraping and AI summarization without a commercial license, so it is shown as a static 'further reading' link in the Carbon Credits tab and never collected or summarized.

*Depends on:* FR-1, FR-4, FR-10

- **AC-18.1** — *Given* the registry entry for cdr.fyi with tos_status REFERENCE_ONLY, *when* the daily scan runs, *then* no request is made to cdr.fyi and the Carbon Credits tab shows the reference link with attribution.
- **AC-18.2** — *Given* a scan with at least one qualifying carbon story, *when* the Carbon Credits tab opens, *then* it shows the pinned analysis or synopsis, carbon trends and carbon stories.

#### FR-19 [MUST]
The scheduled task maintains a trend ledger issues/trends.json: trends (trend_id slug, name, one-sentence thesis, commodities, first_seen) with dated mentions (date, company, story_url, action in 20 words or fewer). The ledger is append-only for mentions. The validator accepts a ledger update only if every new mention's story_url exists in a retained digest snapshot (30 days) and no existing mention was removed or changed; a mention's company is 'verified' when its name or a known alias appears in that story's digest title, excerpt or organizations. Unverified mentions are kept but excluded from trend status and trajectory.

*Depends on:* FR-16

- **AC-19.1** — *Given* a new mention whose story_url is not in any retained digest, *when* the ledger is validated, *then* the update is REJECTED with UNSOURCED_MENTION and the previous ledger stays live.
- **AC-19.2** — *Given* an update that deletes an existing mention, *when* the ledger is validated, *then* it is REJECTED with LEDGER_NOT_APPEND_ONLY.
- **AC-19.3** — *Given* a mention naming 'BP' for a story whose digest organizations include BP, *when* it is validated, *then* the mention is verified.
- **AC-19.4** — *Given* a mention naming 'Aramco' where the story's digest text does not mention Aramco, *when* it is validated, *then* the update is accepted, the mention is marked UNVERIFIED_COMPANY and it does not count toward status or trajectory.

#### FR-20 [MUST]
Host the web page on GitHub Pages with an optional custom domain from settings (CNAME, HTTPS enforced). Because the readership is small and private, every page carries <meta name="robots" content="noindex, nofollow">, robots.txt disallows all crawlers, and a banner states 'Private preview for a small readership. Unverified, informational only. Not investment advice.'

- **AC-20.1** — *Given* settings site.custom_domain = 'news.example.com', *when* the site builds, *then* a CNAME file containing news.example.com is published.
- **AC-20.2** — *Given* any rendered page, *when* it is inspected, *then* the noindex meta tag and the banner are present and robots.txt contains 'Disallow: /'.

### 4.2 Non-Functional

#### NFR-1 [MUST]
Cadence: the scan runs once daily at 05:00 America/Chicago; the task runs at 07:30. The page shows data-as-of and a stale banner when the last successful scan is older than 30 hours.

*Why:* Owner decision 2026-09-16: daily updates are enough.

- **AC-N1.1** — *Given* the last successful scan finished 31 hours ago, *when* the page is viewed, *then* the stale banner is visible.

#### NFR-2 [MUST]
Determinism: the pipeline has no LLM calls; identical inputs, ledger and run time produce byte-identical digests and trend computations.

- **AC-N2.1** — *Given* the same stored data, ledger and run time, *when* the pipeline runs twice, *then* digest JSON and trends output are byte-identical.

#### NFR-3 [MUST]
Cost: no API keys or per-token spend. Infrastructure is free (GitHub Actions on a public repo, GitHub Pages); the only paid items are the owner's existing Claude subscription and an optional domain. Subscription usage is bounded to one task run per day reading one compact digest (<= 60 KB) and at most 15 linked articles.

- **AC-N3.1** — *Given* the repository and workflows, *when* they are inspected, *then* no Anthropic or other LLM API key, SDK call or secret is referenced.
- **AC-N3.2** — *Given* a newsletter frontmatter listing 16 articles_opened, *when* validation runs, *then* it is REJECTED with READING_BUDGET_EXCEEDED.

#### NFR-4 [MUST]
Compliance and reputation: honour robots.txt and source terms; persist at most 300-character excerpts; always link to originals; never collect REFERENCE_ONLY or BLOCKED sources; the author quotes at most one short sentence per linked article; every page and newsletter carries the private-preview, unverified, not-investment-advice disclaimer.

- **AC-N4.1** — *Given* a stored article, *when* the database is inspected, *then* its persisted text is 300 characters or fewer.
- **AC-N4.2** — *Given* any rendered page or published newsletter, *when* it is inspected, *then* the disclaimer is present.

#### NFR-5 [MUST]
Traceability: every story links to its sources, every trend mention links to its story, every figure shows its source, and every trend status and trajectory can be expanded to show the mention counts behind it.

- **AC-N5.1** — *Given* a trend marked RISING, *when* the reader expands it, *then* the current and previous window company counts and mention lists are shown.

#### NFR-6 [MUST]
Bounded storage: raw article records kept 30 days, digests kept 30 days, the ledger kept indefinitely; no committed file over 50 MiB; data and site branches are single-commit force-pushed.

- **AC-N6.1** — *Given* a file would exceed 50 MiB, *when* publish runs, *then* the push aborts, the live site stays intact and STORAGE_LIMIT is raised.

#### NFR-7 [MUST]
Resilience: a failed scan or rejected newsletter never replaces the last good published page.

- **AC-N7.1** — *Given* the scan fails during clustering, *when* the workflow ends, *then* the live site still serves the previous build.

#### NFR-8 [MUST]
Least privilege: the task may only create or modify files under issues/ (newsletter, analysis, index.json, trends.json); a CI scope guard reverts task commits touching anything else.

- **AC-N8.1** — *Given* a task commit modifying config/sources.yaml, *when* CI runs, *then* it is reverted and ISSUE_SCOPE_VIOLATION is raised.

#### NFR-9 [COULD]
Growth path: price tracking, email delivery and access control can be added without restructuring. Prices sit behind settings prices.enabled (default false); access control can later move hosting behind Cloudflare Access or a private host without changing the pipeline.

- **AC-N9.1** — *Given* prices.enabled is false, *when* the scan runs, *then* no request is made to any price API.

## 5. Source registry (v2)

Checked from the planning environment on 2026-09-15/16. ✅ = a live feed or listing was confirmed. ⏳ = confirm from the GitHub runner on the first run (AC-1.4).

| Source | Tier | Type | Commodities | Access | Terms status | Check |
|---|---|---|---|---|---|---|
| EIA Today in Energy | 1 | OFFICIAL | all | RSS | ALLOWED (US gov) | ✅ |
| EIA Press Releases | 1 | OFFICIAL | all | RSS | ALLOWED | ✅ listed on EIA feeds page |
| EIA Gasoline & Diesel Fuel Update | 1 | OFFICIAL | Refined | RSS | ALLOWED | ✅ listed |
| EIA Heating Oil & Propane Update | 1 | OFFICIAL | Refined | RSS | ALLOWED | ✅ listed |
| US DOE Newsroom | 1 | OFFICIAL | all | HTML_LIST | ALLOWED (US gov) | ✅ page |
| FERC News Releases | 1 | OFFICIAL | Gas | HTML_LIST | ALLOWED (US gov) | ✅ page |
| IEA News | 1 | OFFICIAL | all | HTML_LIST | HEADLINE_ONLY | ✅ page, no RSS |
| OPEC Press Releases | 1 | OFFICIAL | Crude | HTML_LIST | HEADLINE_ONLY | ⏳ (HTTP 402 to checker) |
| European Commission — Climate Action news | 1 | OFFICIAL | Carbon | HTML_LIST | HEADLINE_ONLY | ✅ page |
| ICAP (International Carbon Action Partnership) news | 1 | OFFICIAL | Carbon | HTML_LIST | HEADLINE_ONLY | ✅ consistent listing |
| California Air Resources Board — Cap-and-Invest news | 1 | OFFICIAL | Carbon | HTML_LIST | HEADLINE_ONLY | ✅ page |
| UNFCCC News | 1 | OFFICIAL | Carbon | HTML_LIST | HEADLINE_ONLY | ⏳ (timed out) |
| Carbon Brief | 1 | PRESS | Carbon, Gas | RSS | HEADLINE_ONLY | ✅ |
| The Guardian — Energy | 1 | PRESS | all | RSS | HEADLINE_ONLY | ⏳ (blocked from checker) |
| BBC News — Business | 1 | PRESS | all (tagger filters) | RSS | HEADLINE_ONLY | ⏳ |
| Financial Times — Energy | 1 | PRESS | all | RSS | HEADLINE_ONLY; paywalled, author does not open | ⏳ |
| CNBC — Energy | 1 | PRESS | all | RSS | HEADLINE_ONLY | ⏳ (403 to bots; may fail) |
| Utility Dive | 2 | TRADE | Gas, Carbon | RSS | HEADLINE_ONLY | ✅ |
| Canary Media | 2 | TRADE | Gas, Carbon | RSS | HEADLINE_ONLY | ✅ |
| LNG Prime | 2 | TRADE | Gas | RSS | HEADLINE_ONLY | ✅ |
| Offshore Energy | 2 | TRADE | Crude, Gas | RSS | HEADLINE_ONLY | ✅ |
| Rigzone | 2 | TRADE | Crude, Gas, Refined | RSS | HEADLINE_ONLY | ⏳ |
| Carbon Herald | 2 | TRADE | Carbon | RSS | HEADLINE_ONLY | ✅ |
| PR Newswire — Energy | 2 | NEWSROOM | all | RSS | HEADLINE_ONLY (company claims) | ✅ |
| OilPrice.com | 3 | AGGREGATOR | Crude | RSS | disabled (commentary-heavy) | — |
| Reuters · Bloomberg · AP · S&P Global Platts · Argus | — | PRESS | all | — | BLOCKED (license needed) | — |
| **CDR.fyi** | — | reference | Carbon | link only | **REFERENCE_ONLY** (ToS §5.3: no scraping or AI summarization) | ✅ terms read |

## 6. Newsletter format (written by the scheduled task)

```markdown
# Energy News Daily — Wednesday, September 16, 2026
_Private preview · unverified, informational only · not investment advice_

## Hottest topics
### <trend name> — CONFIRMED · RISING · <companies>
<2–3 sentences on what the companies are doing and why it matters> [source](link)

## Crude Oil
- **<headline>** — <one line>. [Outlet](link)
## Natural Gas
## Refined Products
## Carbon Credits
## Sources
## Disclaimer
```
Plus `issues/analysis/YYYY-MM-DD.md` ("What this means for energy traders") and ledger updates in `issues/trends.json`, all in one commit.

## 7. What changes in the code already built

| Area | Change |
|---|---|
| Schedule | `scan.yml` cron `0 */3 * * *` → `0 10 * * *` (05:00 CDT); stale banner at 30 h |
| AI | remove `llm/live.py`, the anthropic dependency and LLM settings; keep deterministic tagging |
| Prices | remove price stages from the run path and UI; keep `prices/` dormant behind `prices.enabled: false` |
| Sources | registry v2 (§5) with `source_type`, `terms_note`, `REFERENCE_ONLY`; new `HTML_LIST` adapter (beautifulsoup4) |
| Tagging | new `config/organizations.yaml` + organization tagger |
| Trends | replace topic×commodity scoring with the ledger validator + TrendEngine (status, trajectory, hotness) and candidate groups |
| Digest | JSON snapshot + compact Markdown digest (≤60 KB) for the author |
| Validator | reject/warn split (ADR-017), `TREND_NOT_CONFIRMED`, `READING_BUDGET_EXCEEDED`, ledger append-only checks |
| Page | tabs Newsletter · Analysis · Trends · All · 4 commodities; noindex, robots.txt, banner, CNAME; CDR.fyi link |
| Task prompt | v2: newsletter + analysis + ledger, ≤15 opened links, no paywalled opens |

## 8. Delivery phases

1. **P1 — Collection:** FR-1, FR-2 (RSS + HTML_LIST), FR-3, FR-13, NFR-1, NFR-4, NFR-6. Done when the first run report confirms the source list (AC-1.4).
2. **P2 — Understanding:** FR-4 (including organizations), FR-5, FR-6, FR-11, FR-16 digest.
3. **P3 — Trends:** FR-19 ledger + validator, FR-7 TrendEngine, Trends tab.
4. **P4 — Page:** FR-9, FR-10, FR-18, FR-20, NFR-7. Point your domain at the site.
5. **P5 — Author:** FR-14, FR-15, FR-17, NFR-3, NFR-8. Create the scheduled task and review its output for 5 days before trusting it unattended.
6. **P6 — Growth (later):** FR-12 archive, NFR-9 (prices, email, access control), a CDR.fyi license if wanted.

## 9. Glossary

- **Tier 1** — Official or primary publishers (agencies, regulators, intergovernmental bodies) and news organizations with a public editorial and corrections policy.
- **Tier 2** — Specialist trade press and company press-release wires.
- **Tier 3** — Aggregators and commentary; disabled by default.
- **Trend** — An idea, initiative or direction that multiple companies are pushing, tracked as a trajectory over time.
- **Trajectory** — NEW, RISING, STEADY, FADING or DORMANT, computed from verified company mentions in the current vs previous 7-day window.
- **Hotness** — 3 x distinct companies in the current window plus tier-weighted, recency-decayed linked stories; ranks the hottest topics.
- **Trend ledger** — issues/trends.json, an append-only record of trends and their dated company mentions maintained by the scheduled task.
- **Digest** — The daily JSON snapshot (source of truth) and compact Markdown version the author reads.
- **REFERENCE_ONLY** — A source shown only as a link for further reading; never fetched or summarized (e.g. CDR.fyi).

## 10. Constraints and assumptions

- **scale:** About 25-35 enabled sources, roughly 150-400 new articles per day, one private web page for a handful of readers, with room to grow.
- **latency:** Daily scan completes in under 15 minutes; the newsletter is live by about 08:00 America/Chicago; the page is interactive in under 2 s.
- **cost:** No API spend; free CI and hosting; existing Claude subscription; optional domain (roughly the price of a domain registration per year).
- **team_size:** One developer plus the scheduled Claude task.
- **existing_stack:** Python 3.12, SQLite, GitHub Actions, GitHub Pages, Claude scheduled tasks with the GitHub connector.
- **compliance:** Reputable sources only; honour robots.txt and terms; excerpts and links only; no scraping or AI use of CDR.fyi data without a license; unverified, not-investment-advice disclaimer; noindex.

- **A1** — v1 commodities are Crude Oil, Natural Gas, Refined Products and Carbon Credits. (FR-4, FR-10, FR-18)
- **A2** — Reuters, Bloomberg, AP, S&P Global Platts and Argus require licenses and stay BLOCKED; tier-1 coverage comes from official publishers and outlets with public feeds. (FR-1)
- **A3** — Company press-release wires (e.g. PR Newswire Energy) are tier-2 NEWSROOM sources: good evidence of what a company is pushing, not independent confirmation. A CONFIRMED trend needs 2+ companies but not an independent source; the analysis must say when a trend rests only on company releases. (FR-7, FR-17)
- **A4** — The readership is the owner and a friend; the page is public-but-unlisted (noindex), prefaced as unverified. If it grows, add access control and review each source's terms for wider distribution. (FR-20, NFR-4, NFR-9)
- **A5** — Claude scheduled tasks count against the owner's plan usage; one bounded run per day is expected to fit. If a run fails on usage limits, the site shows the data-only synopsis and the previous newsletter. (FR-14, NFR-3)
- **A6** — Several reputable feeds (The Guardian, BBC, Financial Times, CNBC, OPEC, UNFCCC) could not be verified from the planning environment; they ship enabled or pending per the registry and the first run report (AC-1.4) confirms them from the GitHub runner. (FR-1, FR-2)
- **A7** — The existing stack is reused: Python 3.12, SQLite, GitHub Actions and GitHub Pages; the owner buys a domain and points it at Pages. (FR-20, NFR-3)

**Out of scope:** Price data, benchmark moves and price effects (deferred, FR-8); Price forecasts, trade ideas or investment advice; Any LLM API usage or API keys; Automated collection or AI summarization of CDR.fyi or other REFERENCE_ONLY sources; Paywall bypass or full-text republication; Email delivery and user accounts (growth path); True access control in v1 (GitHub Pages is public; noindex only).
