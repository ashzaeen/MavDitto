# MavDitto

Migration content QA. Given an old subsite and its replacement, MavDitto pairs
up the pages, compares them structurally and semantically, and ranks them by how
likely it is that content was **lost** rather than merely reworded.

A plain text-diff cannot tell "we rewrote this paragraph for tone" from "we
rewrote this paragraph and dropped the tuition figure." That distinction is the
whole point of this tool.

See `MavDitto — Build Plan.md` for the full design.

## Disclaimer

MavDitto is an independent, unofficial, open-source project. It is not affiliated
with, endorsed by, or supported by The University of Texas at Arlington. The
repository ships no university data, brand material, or credentials: crawl
output, caches, and the brand-voice, knowledge-base, and component-catalog
configs are generated locally and git-ignored. Bring your own configuration and
only point it at sites you are authorized to scan.

## Status

| Phase | Scope | State |
| --- | --- | --- |
| 0 | Discovery: crawl + pair two sites | **done** |
| 1 | Fetch + extract | **done** |
| 1.5 | Page pairs, both-live or archived | **done** |
| 2 | Structural diff | **done** |
| 3 | Semantic diff | **done** |
| 4 | Risk scoring | **done** |
| 5 | Dashboard v1 | **done** |
| 6 | LLM judge | **done** |
| 7 | Dashboard v2 polish | **done** |
| 8 | React dashboard, wired to real data | **done** |
| 9 | Run a comparison from the dashboard | **done** |

## Setup

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt   # Windows
.venv/Scripts/python.exe -m playwright install chromium
```

Phase 3 pulls torch (~2.5 GB on disk). The embedding model itself is a 90 MB
download on first use and is cached afterwards; loading it costs about twenty
seconds per process, and it is loaded lazily, so `--no-semantic` never pays for
it. The `anthropic` package is installed but only used by the LLM judge, which
is opt-in; nothing else in the pipeline needs credentials.

## Start here: two root URLs

```bash
cd dashboard-react && npm install && npm run build && cd ..
python -m src.server                    # http://127.0.0.1:8000
```

Open it, paste the two site roots into **Compare two sites**, press Run. That
is the whole workflow — no terminal needed after the first build. The run
happens on the server's thread and reports progress as it goes, so the page
stays usable, and the results appear when it finishes.

The same run is available headless, which is what you want in CI or over SSH:

```bash
python -m src.run_pipeline --old https://old.example.edu --new https://example.edu --out data/run
```

Either way it enumerates every page under each root, works out which old page
became which new page, compares the pairs, and writes everything the dashboard
reads.

Its headline answer arrives **before** any content is compared: **which old
pages have no counterpart at all.** A page that no longer exists anywhere is
the worst migration failure there is, and a pairwise content diff structurally
cannot find it — you cannot compare a page against a replacement it does not
have. Only enumerating both sides finds those.

Four outputs land in `--out`:

| file | what it is |
| --- | --- |
| `url_pairs.csv` | the old→new map, and step 2's input |
| `unmatched_pages.csv` | **pages needing a decision** — redirect, rebuild, or accept |
| `inventory_old.csv` / `inventory_new.csv` | every page found on each side |
| `discovery.json` | the same, for the dashboard to read |

`url_pairs.csv` doubles as a redirect map, which is the standalone artifact the
build plan asks for.

### How pages get paired

Four passes, most confident first, each claiming what it is sure of before the
looser ones run:

1. **exact** — identical site-relative path; the page did not move.
2. **slug** — same final path segment; it moved but kept its name.
3. **fuzzy-path** — best path similarity above a floor, blending character
   overlap with shared path words so `/portfolio-coding` → `/projects/coding`
   beats a coincidental string match.
4. **name** (`--match-titles`) — for pages whose URLs have nothing in common.

Two refusals matter as much as the matches. When an old page's two best
candidates score within a hair of each other, it is left **unmatched**: picking
one is a coin flip presented as a finding, and a wrong pair sends a reviewer to
compare two unrelated pages. And CMS extensions are stripped, so Sitecore's
`/About.aspx` lines up with WordPress's `/about/`.

### What names a page

`--match-titles` does not blindly trust `<title>`. It first checks whether
titles are *distinctive on that site*: single-page apps and site builders
routinely serve one static title for every route, and matching on a shared
title would pair every old page with whichever new page was compared first.
When titles repeat, it falls back to each page's first `<h1>`, which is the
per-page text such sites do send. When neither is distinctive it declines to
match and says so. The run reports which signal it used on each side.

### Sites that do not answer

Pages are fetched concurrently, with a deliberately tighter budget than a
single considered fetch: in bulk, a page that will not answer promptly *is* the
finding. It is recorded as unreachable and the run moves on.

This is not hypothetical. Sequential fetching with three long retries turns one
unresponsive page into ninety seconds of nothing, and a site with thirty of them
into a quarter-hour of silence before any result appears. Overlapped, the same
twenty-page case with half the pages dead finishes in **ten seconds** instead of
roughly fifteen minutes.

`--check-live` goes further and confirms every listed page actually responds. A
sitemap is a claim, not a guarantee — sites list pages that time out, 404, or
were never built. Those are named on both sides and kept out of the content
comparison, which would otherwise score an unfetchable page as total loss.

Politeness is unchanged by any of this: every worker passes through the same
per-host rate limiter, so concurrency overlaps *waiting*, not requests.

### Enumeration

`sitemap.xml` first — including sitemap indexes and any `Sitemap:` line in
`robots.txt` — because a site that publishes one is telling you what it thinks
its pages are, and it costs a single request instead of hundreds. Sites without
a usable sitemap get a bounded same-host crawl, fetched a depth level at a time,
capped by `--max-pages` and `--max-depth`. An unbounded crawl of someone's site
is a denial of service with good intentions.

### Deep crawl

`--deep` (or the "Deep, exhaustive crawl" checkbox in the dashboard) trades
speed for thoroughness, for the sites where the ordinary pass leaves pages out:

* **Sitemap and crawl are merged, not chosen between.** Normally a usable
  sitemap is trusted on its own. In deep mode both run, and a page found either
  way is kept — a sitemap can list a page nobody links to anymore, and a crawl
  can only find what is actually linked, so neither is complete alone.
* **More sitemap paths are tried**, and nested sitemap indexes are followed
  further (`/wp-sitemap.xml`, `/page-sitemap.xml`, `/post-sitemap.xml`, and
  others alongside the default guesses).
* **Every link is followed, not just `<a href>`**: `<link rel="next">`
  pagination, `<link rel="alternate">` translations, `<area href>` image-map
  targets, `<iframe src>` embeds, a meta-refresh redirect target, and JSON-LD
  `@id`/`url` fields — the places a real site hides a navigable page outside
  its menu.
* **A page whose static HTML looks like an empty JS shell is re-fetched with a
  real browser**, so a client-rendered nav menu gets read at all instead of
  silently contributing zero links.
* **A page that fails once gets a second try** after the crawl finishes,
  rather than being written off on the spot — a slow server that recovers
  mid-crawl should not cost a page its reachability.
* **The effective page and depth caps are raised** to at least 1,000 pages and
  depth 10 (never lowered below whatever was already asked for), because the
  dashboard has no depth field of its own and "thorough" implied by the
  checkbox should not be capped by the quick-run defaults.

It is slower — every page can cost a browser launch, and the sitemap is read
in full rather than trusted at face value — so it stays opt-in rather than the
default.

## Dashboard

```bash
python -m src.server --results data/run --port 8000
```

`src/server.py` serves the built React app and exposes five endpoints:
`GET /api/data`, `POST /api/run`, `GET /api/run`, `POST /api/run/cancel`, and
`POST /api/judge`.
Standard library only — this is a single-user tool on localhost, and a web
framework would be a dependency earning nothing. It binds to `127.0.0.1` and
should stay there: the run endpoint fetches arbitrary URLs on request.

Opened as a static bundle with no server behind it, the dashboard still works —
it falls back to `public/data.json` from `python -m src.export_web` and the run
form says it needs the server. Everything else is computed by the pipeline, so
the dashboard never fetches a page or loads a model itself.

It is written for a reviewer or a manager rather than the tool's author, which
sets the priorities:

* **Compare two sites** — two fields and a Run button, at the top of the page
  and open by default when there is nothing to show yet. Progress reports the
  stage and the counts as they become known; Stop is checked between pages, not
  only between stages, because a stop button that waits out a crawl is not a
  stop button.

* **Review screen** — verdict first, then the concrete losses, then the two
  pages rendered as documents, side by side: real headings, paragraphs, lists
  and tables, each in its own page's own order, each block coloured by what
  happened to it. A page-wide word diff was the original design and it fails
  exactly where it matters: on a page that really changed it marks every
  word, so both columns come out solid red and solid green and say nothing.
  A flat list of word-budget passage cards was the second design, and it
  fails differently: a section with twenty paragraphs slices into a handful
  of ~80-word blobs that all carry the same heading label, which reads as
  repetition rather than as the section it is. Rendering the actual document
  structure fixes both — a list that dropped one bullet shows as that list
  with one bullet struck through, not as an unlabeled card among many.
* **Did every page make it across?** — the discovery result, shown first and
  above everything else: old pages found, how many matched, and **how many have
  no counterpart at all**, each listed with a link. This cannot come out of a
  content diff — a page that does not exist has nothing to compare — so without
  it the worst outcome in a migration would be missing from the report a
  reviewer actually reads. Pages that were listed but would not load are shown
  separately, and net-new pages are shown apart from losses.
* **Summary header** — pages checked, how many need a human, how many came
  through clean, and a single bar showing the shape of the batch. Pages that
  could not be fetched are counted apart: a page nobody could read is not a
  page that lost content.
* **Ranked table** — worst first, colour-coded by tier, filterable by tier,
  by search, and by whether a page has caveats. Both URLs are clickable, so a
  reviewer can open the old Wayback capture beside the live page.
* **Detail view** — the verdict with its reasons and caveats, then four tabs:
  **what changed** (the judge's explanation), the structural counts, the
  findings, and **old vs new text side by side**.

That last tab is the one that matters. A reviewer can only judge whether a
rewrite dropped something by reading both versions, and no score substitutes
for that — so dropped passages are listed first, with the old text beside an
explicit "no counterpart on the new page" where the new text should be.

Caveats are shown expanded rather than tucked away. They are the reasons not to
take a tier at face value, and burying them would defeat the point of having
them.

**Export**: the sidebar offers the filtered pages as a review checklist CSV —
the plan's "fix it checklist" — with a `done` column, the tier, what to check,
and both links, so a content editor can work through it in Excel.

### Word-level highlighting

In the side-by-side, removed words are struck through in red and added words
are green, toggleable. Reading two blocks of prose and spotting the difference
by eye is exactly the manual work this tool exists to remove.

Figures the rewrite dropped are called out on the passage header — `amount $75
missing`, `date February 15 missing` — because "a number is missing" is only
actionable next to the sentence it went missing from.

### The one chart

Coverage against similarity, one dot per comparable page. It is the only chart
here because it is the only thing the table cannot say: the two measures
disagree, and the pages that matter are where they disagree most. A page far
right and low down reads as "barely changed" by similarity while most of its
text is gone — the shaded region is that trap.

On the demo set, `academics 2024` sits at **86% similarity, 41% coverage**.

Pages that could not be compared are absent rather than plotted at zero; they
have no coordinates and inventing some would be a lie.

The dot colour was checked with the dataviz validator against both the light
and dark chart surfaces rather than chosen by eye. That check also caught a
real bug in the v1 palette: the amber swatch carried white text at 2.69:1,
below the 4.5:1 floor, so it was darkened to 5.14:1. Tier identity is carried
by the label inside every chip, never by colour alone.

## React dashboard

```bash
cd dashboard-react && npm install && npm run dev    # against a running src.server
```

Built from a design brief and mockups. See `dashboard-react/README.md` for its
own notes.

There was briefly a second dashboard in Streamlit, written before this one
existed. It is gone: two front ends over one pipeline meant every feature had
to be built twice, and the run form would have been the second time. Nothing
was lost in the move except the coverage-vs-similarity scatter, which has not
been ported yet.

**What the wiring added.** The brief predates several of the pipeline's
findings, so this was not only a matter of swapping in real numbers: coverage
now sits beside similarity, the structural panel lists *which* headings went
rather than only how many, caveats appear on the rows that are not clean, and
a `/missing` screen exists at all. Two things from the brief changed on purpose
— the copy panels named Sitecore and WordPress and now name the hosts actually
loaded, and the
loading state's progress bar went, because the load is a JSON fetch and a
progress bar that cannot progress is a lie.

**On verifying it.** `npm run smoke` loads every route headlessly, fails on any
console error, and asserts something specific rendered. That last part was
added after a length-only check passed a main table showing "Showing 0 of 3" —
a `useMemo` was missing its data dependency, so it kept the empty first-render
result forever. A build that compiles says nothing about whether the app runs.

## Phase 1 usage

`inspect_page` fetches a URL and prints the normalized shape every later stage
consumes: clean body text, heading outline, images (flagging missing alt), and
links (flagging documents and externals).

```bash
# a live page
python -m src.inspect_page https://www.uta.edu/academics

# the most recent archived capture of a retired page
python -m src.inspect_page http://www.uta.edu/academics/ --source wayback

# a capture from around a given date
python -m src.inspect_page http://www.uta.edu/old-dept/ --source wayback --timestamp 20150601

# live if it resolves, otherwise Wayback
python -m src.inspect_page https://www.uta.edu/about --source auto

# a batch, saving one JSON per page
python -m src.inspect_page --urls data/test_urls.txt --out data/out
```

Useful flags: `--render js` forces a browser, `--no-js` forbids one, `--json`
prints machine-readable output, `--no-cache` bypasses the fetch cache, `--delay`
sets the per-host politeness gap.

## Comparing a pair

Both sides are fetched independently, so the source is a property of each
**side**, not of the run. Three shapes, all ordinary:

```bash
# Pre-launch check: old site still serving users, new site being built.
# This is the common case, so it needs no flags.
python -m src.compare --old https://www.uta.edu/dept --new https://new.uta.edu/dept

# Post-hoc audit: the old site is already gone.
python -m src.compare --old http://www.uta.edu/dept/ --old-source wayback --new https://www.uta.edu/dept

# A batch, from the build plan's url_pairs.csv.
python -m src.compare --pairs data/url_pairs.csv
```

`url_pairs.csv` needs only `old_url` and `new_url`; `old_source`, `new_source`,
`timestamp` and `label` are optional, `#` comment lines are allowed, and the
plan's original single `source` column still works (it describes the old side).

### Staging sites

A pre-launch new site usually lives on a staging host, and staging hosts
routinely serve `Disallow: /` to stay out of search results. That is not a
statement about whether their owner may QA them, but MavDitto honors robots by
default and would otherwise fetch nothing and report nothing:

```bash
python -m src.compare --old https://www.uta.edu/dept --new https://staging.uta.edu/dept --trust-new-site --new-auth qa
```

`--trust-new-site` applies to the new side only, so it cannot quietly become a
licence to ignore robots on the live internet. `--new-auth USER:PASS` handles
basic auth; giving just `USER` reads the password from `MAVDITTO_PASSWORD` so it
stays out of shell history.

### What it prints

A count table, then the structural findings ranked worst first. `--out DIR`
writes one JSON per pair carrying the full findings and both normalized pages —
the results store phases 3 to 5 read from.

## Structural diff

`diff_structural.py` compares heading, image and link structure and returns
findings, each with a severity for phase 4 to weigh:

| Severity | Meaning | Examples |
| --- | --- | --- |
| `high` | content is probably gone | dropped heading, dropped document link |
| `medium` | a reviewer should look | dropped image or link, lost alt text, retargeted link, missing h1 |
| `low` | cosmetic or likely intentional | reworded heading, changed level, skipped level |
| `info` | worth showing, not worth worrying about | anything *added* |

Additions are always `info`. New content is not a migration defect, and ranking
it beside losses would bury them.

Three decisions here came from real pages rather than the plan, and each one
was a false-positive source before it was fixed:

**Links compare site-relative, not absolute.** A migration moves the whole
site, so the old page links to `old.edu/apply` where the new one links to
`new.edu/apply`. Those are the same link. Comparing absolute URLs reports every
internal link on every page as dropped — a flood that buries the real findings.
`SiteContext` reduces internal links to their site-relative path and leaves
external links whole. Roots default to each page's scheme+host; pass
`--old-root`/`--new-root` for a subsite move under one host. CMS page
extensions are stripped too, so Sitecore's `/About/Apply.aspx` matches
WordPress's `/about/apply/`.

**Headings compare by content, not by count.** The 2019 `uta.edu/academics`
page and its rebuild both carry ten headings, of which nine are different. A
count-based diff calls that page clean. Headings are aligned as a sequence,
with exact matches anchoring the alignment.

**Heading rewording needs token evidence, not character similarity.**
`Graduate Studies` and `Undergraduate Studies` are 0.86 similar on characters
and are *separate sections of the same real page* — matching them would merge
two sections and hide the dropped one. `Youth Programs` and `Explore Programs`
score 0.67 on the shared word "Programs" alone. So multi-word headings must
share at least half their words, or one must expand the other
(`Requirements` → `Admission Requirements`). Single-word headings have no
tokens to share, so there spelling is all there is (`Deadline` → `Deadlines`).

Images are matched across a rehost by filename stem and alt text as well as
URL, since Sitecore's `/-/media/<guid>.jpg` becomes WordPress's
`/wp-content/uploads/<year>/<name>.jpg` and the URL is not an identity.

One finding exists purely because the real pair surfaced it:
`image.became_background`. Missing-alt counts can *improve* while accessibility
gets worse, because an `<img>` that became a CSS background is no longer an
element that can carry alt text at all.

### Validation

* `uta.edu/academics` vs `www.uta.edu/academics` — same content, different host
  — produces **zero findings**. An unchanged page generates no noise.
* The 2019 archive vs today's rebuild produces nine dropped headings at `high`,
  with the additions kept separately at `info`.

## Semantic diff

Runs by default; `--no-semantic` skips it, `--embedder lexical` swaps the model
for a word-overlap stand-in useful only for smoke tests. The model is
`all-MiniLM-L6-v2`, local, free, and nothing leaves the machine.

**Coverage is the headline number, not similarity.** A whole-page cosine is
symmetric and dominated by bulk, so a page that kept most of its text and
dropped one load-bearing paragraph still scores as "minor rewording". Each old
passage is instead matched to its best counterpart on the new page, and the
passages with no match *are* the finding.

The real pair proves the point: the 2019 `/academics/` page against today's
rebuild scores **0.83 similarity but 0.33 coverage**. Reported as similarity
alone it reads as light rewording. Coverage says two-thirds of the old page is
unaccounted for — 594 words across eight passages.

Matching is best-first across the whole similarity matrix, not in document
order, because migrations reorder sections freely and positional matching would
call a moved section one drop plus one addition.

### What the thresholds can and cannot do

`python -m src.tune_semantic` prints the scores the thresholds are set from, so
they can be re-derived rather than trusted. Its headline result is negative:

| case | truth | score |
| --- | --- | --- |
| reordered sentences | same | 0.956 |
| tone rewrite | same | 0.880 |
| **fact dropped: GPA requirement** | **loss** | **0.764** |
| expanded, same facts | same | 0.744 |
| heavy paraphrase | same | 0.734 |
| fact dropped: fee | loss | 0.426 |

**The classes overlap.** A faithful heavy paraphrase (0.734) scores *lower*
than a rewrite that silently dropped a GPA requirement (0.764). Cosine
similarity measures topical overlap, not factual completeness, so no threshold
separates "reworded" from "reworded and lost a fact."

So `MATCH_STRONG` is set at 0.85 — above the ambiguous region rather than
inside it — and everything between 0.55 and 0.85 is "substantially rewritten,
someone must read this." The two errors are not symmetric: a dropped fact
scored as *kept* is silent and never reaches a reviewer, while a faithful
paraphrase sent for review costs one LLM judge call. The threshold makes the
first kind impossible on the calibration set and accepts the second.

That band is exactly the queue phase 6 consumes, and the JSON output carries
per-passage scores and verdicts for it. This is the concrete argument for the
LLM judge: it is not an explanation layer bolted on for polish, it is the only
component that can make a distinction embeddings provably cannot.

### Validation

* Unchanged control: similarity 1.000, coverage 1.000, no findings.
* Synthetic sabotaged pair: coverage drops, dropped passages reported at `high`.
* On the calibration set, no content loss is scored as kept, and no faithful
  rewrite is scored as dropped.

## Risk scoring

Every pair gets one tier, and the run ends with the pages ranked worst first.

| Tier | Meaning |
| --- | --- |
| `Missing content` | specific content is gone |
| `Major rewording` | heavily rewritten, or a small but real loss |
| `Minor rewording` | light rewording, cosmetic structural change |
| `Clean` | nothing meaningful changed |
| `Unknown` | the pair could not be compared; listed apart, never ranked |

The plan's four tiers are not four points on one scale. "Missing" is a
different *kind* of evidence from "rewritten", not more of it — a page can be
rewritten end to end and still say everything it used to. So two axes are
scored separately:

* **loss** — passages with no counterpart, dropped headings, documents, images
  and links.
* **change** — passages substantially rewritten, headings reworded, similarity
  down.

The tier comes from rules over those two, so it is always explainable; the
0-100 score only orders pages *within* a tier. Every verdict carries its
reasons, including `Clean` ones — the plan asks for that explicitly, and a
reviewer will not trust a green row unless the tool says what it checked.

### Confidence and caveats

Each verdict also carries caveats that could make it wrong in either
direction, and confidence falls as they accumulate:

* the old page is a Wayback capture years older than the new one, so some
  differences are the old site's own drift rather than the migration's doing
* passages were rewritten, which embeddings cannot vouch for (see above)
* a page was extracted without a content landmark, so boilerplate may have
  leaked in
* the new page came back nearly empty — scored as loss, but possibly a
  rendering failure

### Structural signals are proxies, and get weighted down

`diff_structural` reports dropped headings, images and links. When the semantic
stage says the old page's text is fully accounted for, those drops mean the
page was **restructured**, not that content is gone — the words are still
there under a different shape.

The real `uta.edu/about` pair proved it: coverage 1.00, text *grown* from 113
to 285 words, and it still scored `Missing content` purely on dropped headings.
Adding structural drops to a coverage figure that already says nothing is
missing double-counts a redesign as a deletion. Their weight now ramps with how
much text is genuinely unaccounted for — a ramp, not a cliff, so a page
slipping from 0.90 to 0.89 coverage cannot jump two tiers on a rounding error.

Document links are exempt from the discount. A PDF is not part of a page's
text, so no coverage figure can vouch for it; its loss is independent evidence.

### Validating the tiers

Real pairs are a poor calibration set for the middle tiers: a page against its
own latest capture is identical, and against a capture from years ago is a
wholesale rewrite. Almost nothing lands in between.

So `python -m src.tune_score` damages one page by degrees in two series and
asserts the tiers behave:

```
REWORDING -- facts kept; must never reach Missing content
identical                    coverage 1.00  Clean
light rewording              coverage 1.00  Clean
moderate rewording           coverage 1.00  Minor rewording
heavy rewording + padding    coverage 1.00  Minor rewording

REMOVAL -- content deleted; must climb and never fall
one image removed            coverage 1.00  Minor rewording
PDF link removed             coverage 1.00  Major rewording
one sixth of text removed    coverage 0.78  Missing content    29.5
a third of text removed      coverage 0.62  Missing content    54.9
half the text removed        coverage 0.48  Missing content    77.7
all but the first section    coverage 0.18  Missing content   100.0
```

On real pairs, `about` against its 2024 capture is the one that lands in the
middle — coverage 1.00, similarity 0.68, `Major rewording`.

## LLM judge

Off by default; `--judge` turns it on. It costs money, so everything about it
is built around spending as little as possible.

```bash
python -m src.compare --pairs data/url_pairs.csv --out data/out \
    --judge --judge-budget 0.50
```

### Why it exists

Not as polish. Phase 3's calibration proved the limit: a faithful heavy
paraphrase scores **0.734** while a rewrite that silently dropped a GPA
requirement scores **0.764**. Cosine similarity measures topical overlap, not
factual completeness, so no threshold separates "reworded" from "reworded and
lost a fact". The judge is the only component that can make that call, and the
semantic stage deliberately routes that ambiguous band to it rather than
guessing.

So the judge does not re-read whole pages. It reads the passages the semantic
stage could not vouch for — the ones between `MATCH_WEAK` and `MATCH_STRONG` —
plus the passages that vanished outright, and answers one question: did this
rewrite keep the facts? It returns a page summary, a severity, and a per-passage
verdict naming the specific figure, date or requirement that is gone.

### Cost control

The build plan asks for an explicit cap, so there is one:

* **Only flagged pages.** `Clean` and `Unknown` pages are never judged, and
  neither is a flagged page with nothing ambiguous on it.
* **Only flagged passages**, reworded ones first, capped per page. Settled
  passages are not paid for.
* **One request per page**, not per passage.
* **A hard budget, checked before each call** using the API's own free token
  counter, estimating output at the full ceiling. A budget that only holds on
  average is not a budget. When the next call would breach it, that page is
  skipped and the run continues.
* **Disk cache keyed by content and rubric**, so re-running over unchanged
  pages costs nothing, while changed text or a changed rubric is judged again.

Every run prints what it spent: `3 judge call(s), 24,910 in / 1,802 out,
$0.0912 of $0.50`.

Flags: `--judge-model` (default `claude-opus-5`), `--judge-budget USD`,
`--judge-max-calls`, `--judge-effort`, `--no-judge-cache`. The model is a flag
rather than a quietly cheaper default because downgrading for cost is a
spending decision, not one the tool should make silently — `claude-haiku-4-5`
is a defensible choice here and costs about a fifth as much.

### Without credentials

Nothing else in the pipeline needs an API key, and `--judge` degrades rather
than failing: the page is marked skipped with an actionable reason, the budget
is untouched, and the run finishes normally. The SDK reports missing
credentials as a plain `TypeError` on the first request — not at client
construction, and not as `AuthenticationError` — so that case is translated
into an instruction instead of reaching a reviewer as a traceback.

### What the tests do and do not cover

The 26 judge tests run against a stub client: no network, no credentials. They
cover passage selection, budget enforcement, caching, verdict-to-passage
matching, refusals, and error translation. **They do not cover whether the real
model returns good verdicts** — that needs credentials and a live run against
real pages, which has not been done.

## What phase 1 handles

Four things were not obvious from the plan and are worth knowing, because each
one would have quietly corrupted the diff stages downstream:

**Sitecore puts its images in CSS, not `<img>`.** Real `uta.edu` pages carry
zero `<img>` tags inside `<main>`; the hero and section artwork are
`background-image` declarations. An `<img>`-only count would report phantom
image loss on every page whose artwork moved into a real `<img>` tag during the
rebuild. Both forms are extracted, tagged by `kind`, and background images are
excluded from the missing-alt count since they cannot carry alt text.

**Archived pages need a different base URL than live ones.** Fetched with
Wayback's `id_` modifier, an archived page's HTML is the *original,
unrewritten* bytes, so a root-relative `/academics/programs` belongs to the old
site and must resolve against the old site's URL. Resolving it against the
snapshot URL instead produces `web.archive.org/academics/programs` — the path is
silently replaced, and every root-relative link on the page compares as changed.
`make_resolver` picks the correct base per link, handling both `id_` snapshots
and the rewritten framed viewer.

**The Wayback APIs go down.** Both the availability API and CDX returned 429 and
503 during development. The primary route asks Wayback for a timestamp it cannot
have and lets its own redirect land on the nearest capture — one ordinary,
rate-limited fetch, no API involved. The APIs are consulted only if that fails.

**Dropping a paragraph is the expensive mistake.** Text extraction runs
trafilatura in `favor_recall` mode: a stray extra sentence costs a rounding
error on a similarity score, while a wrongly dropped paragraph shows up
downstream as content loss that never happened, and burns a reviewer's trust in
the tool.

Fetching is polite by default: robots.txt honored, one-second minimum gap per
host with jitter, exponential backoff on 429/5xx, and an on-disk cache in
`data/cache/` so development re-runs do not re-hammer anyone.

## Layout

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
  discover_cli.py     crawl-and-pair CLI
dashboard-react/
  src/                the dashboard (see its own README)
  smoke.mjs           headless render check for every route
  run-e2e.mjs         drives the form and waits for a real run to finish
tests/                274 tests, no network required
data/
  run/                results: per-pair JSON + discovery.json
  cache/              fetch cache (gitignored)
```

## Tests

```bash
.venv/Scripts/python.exe -m pytest tests/ -q
```

All tests run offline against fixtures in `tests/fixtures.py`, including the
synthetic worst-case pair from the build plan: a page and a version of it that
drops a fee, a GPA requirement, a whole section, an image's alt text and a PDF
link, while still reading as fluent prose.
