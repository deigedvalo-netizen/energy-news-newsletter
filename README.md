# Energy News Daily

A small, private daily newsletter covering **crude oil, natural gas, refined products and carbon credits**, built from reputable, mostly tier-1 sources.

- **Daily scan (GitHub Actions, free):** reads ~24 sources (EIA, DOE, FERC, IEA, OPEC, European Commission, ICAP, CARB, UNFCCC, Carbon Brief, Guardian, BBC, FT, CNBC, trade press). It tags commodities, topics and companies, groups same-story coverage, and publishes a digest. No AI calls, no API keys.
- **Trends:** an idea several companies are pushing. Evidence lives in an append-only ledger (`issues/trends.json`); code computes CONFIRMED/EMERGING and NEW/RISING/STEADY/FADING from verified company mentions.
- **Newsletter + analysis (Claude Code GitHub Action on your Claude subscription):** reads the digest and up to 15 linked articles, adds trend evidence, and writes the condensed newsletter plus "What this means for energy traders". It runs inside GitHub Actions, so no chat connector is needed.
- **Validator:** rejects links not in the digest, advice or forecasts, unconfirmed hot topics and ledger edits. It warns on figures it can't verify.
- **Site:** Newsletter · Analysis · Trends · All · Crude Oil · Natural Gas · Refined Products · Carbon Credits. Noindex, with a private-preview banner and optional custom domain.

Private preview. Unverified, informational only. Not investment advice. Requirements, architecture and ADRs are in [`docs/`](docs/).

## Schedule

| Piece | Where | When (America/Chicago) |
|---|---|---|
| `scan` workflow | GitHub Actions | daily 05:00 (`0 10 * * *` UTC in CDT; `0 11 * * *` from Nov 1) |
| `newsletter` workflow | GitHub Actions + `anthropics/claude-code-action`, prompt in [`tasks/newsletter-action-prompt.md`](tasks/newsletter-action-prompt.md) | daily 07:30 |
| `issue-gate` workflow | GitHub Actions | on every push to `issues/**` |

## One-time setup

1. Create the repo (public, so Actions and Pages are free) and push this code.
2. Run the **scan** workflow once from the Actions tab. Check the run summary to see which sources worked, then fix or disable any that failed in `config/sources.yaml`.
3. **Settings → Pages:** Deploy from branch `gh-pages` / root.
4. **Custom domain (optional):** set `site.custom_domain` in `config/settings.yaml`, add a DNS CNAME record pointing to `<user>.github.io`, then enable "Enforce HTTPS" in Pages.
5. **Claude subscription token:** install Claude Code, run `claude setup-token`, and save the printed token as the repository secret `CLAUDE_CODE_OAUTH_TOKEN` (Settings → Secrets and variables → Actions). Keep the Claude GitHub App installed on the repo.
6. Run the **newsletter** workflow once from the Actions tab to test it.

> Why not a Cowork scheduled task? The Claude chat/Cowork GitHub connector currently can read but not write repositories (403 "Resource not accessible by integration", anthropics/claude-code#80874). `tasks/daily-newsletter-task.md` is kept for when that's fixed.

## Local development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest -q                                              # acceptance criteria + two-day offline end-to-end run
python -m energynews.run --db data/energynews.db --site site          # live scan
python -m energynews.issues.gate --issues issues --site site          # validate ledger/newsletter/analysis locally
```

## Layout

```
config/     sources.yaml (tiers, types, terms) · organizations.yaml (company tagging) · settings.yaml
src/energynews/
  sources/  fetch/ (RSS + HTML_LIST)  extract/  tag/ (taxonomy, organizations, figures, summaries)
  cluster/  scoring/ (weights, relevance, ledger validation, trend engine)
  publish/  (digest JSON + Markdown, static site)  issues/ (validator, gate, scope guard)  run.py
  prices/   dormant until prices.enabled (deferred)
issues/     written by the scheduled task: YYYY-MM-DD.md, analysis/YYYY-MM-DD.md, trends.json, index.json
tasks/      scheduled task prompt
docs/       requirements (plan.md, handoff.json), architecture spec, ADR-001…ADR-019
```
