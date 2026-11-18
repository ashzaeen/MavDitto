# Code map

```
src/
  models.py        normalized PageContent / FetchResult, JSON round-trippable
  urls.py          normalization, Wayback unwrapping, per-page link resolver
  fetch.py         polite fetcher: httpx, Playwright fallback, Wayback, caching
  extract.py       boilerplate stripping -> text, headings, images, links,
                   structural blocks (heading/paragraph/list/table, in order)
  pair.py          PagePair, per-side sourcing, url_pairs.csv
  diff_structural.py  heading/image/link comparison -> ranked findings
  embed.py            one chunk per block (word-budget grouping as a fallback)
                      + the local embedding model
  diff_semantic.py    passage matching, coverage, meaning-loss findings
  textdiff.py         word-level diff + item-level diff for lists/tables
  tune_semantic.py    prints the scores the semantic thresholds are set from
  score.py            loss/change axes -> one risk tier per page
  tune_score.py       checks the tiers discriminate on graded damage
  store.py            the results store: one JSON record per pair
  llm_cost.py          budget cap, disk-cached spend, and Claude error translation
                      shared by llm_judge.py and alt_text.py
  llm_judge.py        Claude API judge for the passages embeddings cannot settle
  alt_text.py          alt text for one image, or every real image on a page
  discover.py         enumerate a site, pair two sites' pages
  discover_cli.py     the two-root-URLs entry point
  export_web.py       results store -> one JSON for the dashboard
  run_pipeline.py     two URLs -> a finished results folder, with progress
  server.py           serves the dashboard and runs comparisons for it
  inspect_page.py     single-page CLI
  compare.py          old-vs-new pair CLI
  llm_provider.py     one entry point for every LLM call (Claude, OpenAI, Gemini)
  llm_config.py       provider and API-key settings, kept in data/llm_config.json
  link_checker/       Broken Link Inspector: extract, categorize, check, crawl a site
  content_writer/     rewrite / generate / refine / review / export, brand voice, templates
  web_builder/        match sections to components, populate fields, validate
  setup_engine/       freeform material -> draft brand-voice and component configs
dashboard-react/
  src/                the dashboard (see its own README)
  smoke.mjs           headless render check for every route
  run-e2e.mjs         drives the form and waits for a real run to finish
docs/
  ARCHITECTURE.md     diagrams of every pipeline
  design/             build plan, design system, per-tool design guides
config/               your own brand voice, knowledge base and component catalog
                      (generated locally, git-ignored; see config/README.md)
  seed/uta/           optional starter profile, installed by scripts/seed_config.py
scripts/              seed_config.py, plus one-off catalog migration helpers
LICENSE, NOTICE       Apache-2.0, and attribution for vendored and seeded material
vendor/               the brand-voice writing method, vendored under Apache-2.0
tests/                see the README
data/
  run/                results: per-pair JSON + discovery.json
  cache/              fetch cache (gitignored)
```
